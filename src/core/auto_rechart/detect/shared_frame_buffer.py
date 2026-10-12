from __future__ import annotations

import multiprocessing.shared_memory as multiprocessing_shared_memory
import time
from dataclasses import dataclass
from typing import Any

import numpy as np
import torch.multiprocessing as tmp


@dataclass
class SharedFrameBufferSpec:
    """进程间传递共享帧缓冲所需的句柄和同步对象。"""

    name: str
    capacity: int
    frame_shape: tuple[int, int, int]
    dtype: str
    write_sequence: Any
    detect_sequence: Any
    obb_sequence: Any
    frame_indices: Any
    eof_sequence: Any
    condition: Any


@dataclass
class SharedFrameBatch:
    """worker 当前持有的一批共享帧。"""

    start_sequence: int
    end_sequence: int
    frame_indices: list[int]
    frames: list[np.ndarray]


class SharedFrameBuffer:
    """固定容量的单生产者、双消费者共享帧环形缓冲。"""

    def __init__(self, spec: SharedFrameBufferSpec, shared_memory):
        self.spec = spec
        self._shared_memory = shared_memory
        self._frames = np.ndarray(
            (spec.capacity, *spec.frame_shape),
            dtype=np.dtype(spec.dtype),
            buffer=shared_memory.buf,
        )
        self._closed = False

    @classmethod
    def create(
        cls,
        frame_shape: tuple[int, int, int],
        capacity: int,
        dtype=np.uint8,
    ) -> SharedFrameBuffer:
        if capacity <= 0:
            raise ValueError(
                f"shared frame buffer capacity must be positive: {capacity}"
            )
        normalized_shape = tuple(int(v) for v in frame_shape)
        if len(normalized_shape) != 3 or any(v <= 0 for v in normalized_shape):
            raise ValueError(
                f"shared frame buffer shape must be 3D and positive: {frame_shape}"
            )
        normalized_dtype = np.dtype(dtype)
        size = capacity * int(np.prod(normalized_shape)) * normalized_dtype.itemsize
        shared_memory = multiprocessing_shared_memory.SharedMemory(
            create=True, size=size
        )
        try:
            spec = SharedFrameBufferSpec(
                name=shared_memory.name,
                capacity=capacity,
                frame_shape=normalized_shape,
                dtype=normalized_dtype.str,
                write_sequence=tmp.Value("q", 0),
                detect_sequence=tmp.Value("q", 0),
                obb_sequence=tmp.Value("q", 0),
                frame_indices=tmp.Array("q", capacity, lock=False),
                eof_sequence=tmp.Value("q", -1),
                condition=tmp.Condition(),
            )
            return cls(spec, shared_memory)
        except BaseException:
            shared_memory.close()
            shared_memory.unlink()
            raise

    @classmethod
    def attach(cls, spec: SharedFrameBufferSpec) -> SharedFrameBuffer:
        shared_memory = multiprocessing_shared_memory.SharedMemory(name=spec.name)
        return cls(spec, shared_memory)

    @property
    def capacity(self) -> int:
        return self.spec.capacity

    def publish(
        self,
        frame_index: int,
        frame: np.ndarray,
        *,
        timeout: float,
        stop_event=None,
    ) -> bool:
        """写入一帧；超时、停止或缓冲关闭时返回 False。"""

        if self._closed:
            raise RuntimeError("shared frame buffer is closed")
        if not isinstance(frame, np.ndarray):
            raise TypeError(f"shared frame must be numpy.ndarray, got {type(frame)!r}")
        if frame.shape != self.spec.frame_shape:
            raise ValueError(
                f"shared frame shape mismatch: expected {self.spec.frame_shape}, "
                f"got {frame.shape}"
            )
        if frame.dtype != np.dtype(self.spec.dtype):
            raise ValueError(
                f"shared frame dtype mismatch: expected {self.spec.dtype}, "
                f"got {frame.dtype}"
            )
        if timeout < 0:
            raise ValueError(
                f"shared frame publish timeout must be non-negative: {timeout}"
            )

        deadline = time.monotonic() + timeout
        with self.spec.condition:
            if self.spec.eof_sequence.value >= 0:
                raise RuntimeError("shared frame buffer input is already finished")
            while self._is_full_locked():
                if stop_event is not None and stop_event.is_set():
                    return False
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self.spec.condition.wait(timeout=remaining)

            if stop_event is not None and stop_event.is_set():
                return False
            sequence = int(self.spec.write_sequence.value)
            slot = sequence % self.spec.capacity
            np.copyto(self._frames[slot], frame)
            self.spec.frame_indices[slot] = int(frame_index)
            self.spec.write_sequence.value = sequence + 1
            self.spec.condition.notify_all()
            return True

    def read_batch(
        self,
        worker_name: str,
        batch_size: int,
        stop_event=None,
    ) -> SharedFrameBatch | None:
        """等待并返回一批帧；返回 None 表示 EOF 或停止。"""

        if worker_name not in ("detect", "obb"):
            raise ValueError(f"unknown shared frame buffer worker: {worker_name!r}")
        if batch_size <= 0:
            raise ValueError(f"shared frame batch size must be positive: {batch_size}")
        sequence_ref = self._sequence_ref(worker_name)
        minimum_batch = min(batch_size, self.spec.capacity)

        with self.spec.condition:
            while True:
                if stop_event is not None and stop_event.is_set():
                    return None

                start_sequence = int(sequence_ref.value)
                write_sequence = int(self.spec.write_sequence.value)
                available = write_sequence - start_sequence
                eof_sequence = int(self.spec.eof_sequence.value)

                if available > 0:
                    if eof_sequence >= 0:
                        count = min(batch_size, available)
                    elif available >= minimum_batch:
                        count = minimum_batch
                    else:
                        self.spec.condition.wait()
                        continue

                    frame_indices = []
                    frames = []
                    for offset in range(count):
                        slot = (start_sequence + offset) % self.spec.capacity
                        frame_indices.append(int(self.spec.frame_indices[slot]))
                        frames.append(self._frames[slot])
                    return SharedFrameBatch(
                        start_sequence=start_sequence,
                        end_sequence=start_sequence + count,
                        frame_indices=frame_indices,
                        frames=frames,
                    )

                if eof_sequence >= 0:
                    return None
                self.spec.condition.wait()

    def release(self, worker_name: str, end_sequence: int) -> None:
        """释放 worker 已完成推理的帧槽位。"""

        sequence_ref = self._sequence_ref(worker_name)
        with self.spec.condition:
            current = int(sequence_ref.value)
            write_sequence = int(self.spec.write_sequence.value)
            if end_sequence <= current or end_sequence > write_sequence:
                raise RuntimeError(
                    f"invalid {worker_name} release sequence: "
                    f"current={current}, end={end_sequence}, write={write_sequence}"
                )
            sequence_ref.value = int(end_sequence)
            self.spec.condition.notify_all()

    def finish_input(self) -> None:
        """发布 EOF；已写入的帧仍会被两个 worker 消费。"""

        with self.spec.condition:
            if self.spec.eof_sequence.value < 0:
                self.spec.eof_sequence.value = int(self.spec.write_sequence.value)
            self.spec.condition.notify_all()

    def wake_all(self) -> None:
        """唤醒等待中的生产者和消费者。"""

        with self.spec.condition:
            self.spec.condition.notify_all()

    def _is_full_locked(self) -> bool:
        write_sequence = int(self.spec.write_sequence.value)
        oldest_sequence = min(
            int(self.spec.detect_sequence.value), int(self.spec.obb_sequence.value)
        )
        return write_sequence - oldest_sequence >= self.spec.capacity

    def _sequence_ref(self, worker_name: str):
        if worker_name == "detect":
            return self.spec.detect_sequence
        if worker_name == "obb":
            return self.spec.obb_sequence
        raise ValueError(f"unknown shared frame buffer worker: {worker_name!r}")

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._shared_memory.close()

    def unlink(self) -> None:
        try:
            self._shared_memory.unlink()
        except FileNotFoundError:
            pass
