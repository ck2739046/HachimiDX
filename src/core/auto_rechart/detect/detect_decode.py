from __future__ import annotations

import sys
import time
from queue import Empty

import cv2
import i18n
import torch.multiprocessing as tmp

from ...schemas.op_result import OpResult, err, ok
from .shared_frame_buffer import SharedFrameBuffer

_DECODE_STALL_TIMEOUT = 60.0
_DECODE_PUBLISH_WAIT_TIMEOUT = 0.1
_DECODE_BACKPRESSURE_TIMEOUT = 60.0
_DECODE_PHASE_FINISHED = 0
_DECODE_PHASE_READING = 1
_DECODE_PHASE_PUBLISHING = 2


class Decoder:
    """控制直接向共享帧缓冲写入数据的解码进程。"""

    def __init__(
        self,
        std_video_path: str,
        imgsz: int,
        total_frames: int,
        *,
        frame_buffer: SharedFrameBuffer,
        stop_event,
    ):
        if imgsz <= 0:
            raise ValueError(f"decoder image size must be positive: {imgsz}")

        self._frame_buffer = frame_buffer
        self._stop_event = stop_event
        self._control_queue = tmp.Queue()
        self._progress_frame = tmp.Value("q", 0)
        self._decode_phase = tmp.Value("b", _DECODE_PHASE_READING)
        self._decode_phase_started = tmp.Value("d", time.monotonic())
        self._status: OpResult | None = None
        self._force_closed = False

        self._process = tmp.Process(
            target=decode_worker_main,
            args=(
                std_video_path,
                imgsz,
                total_frames,
                frame_buffer.spec,
                self._control_queue,
                self._progress_frame,
                self._decode_phase,
                self._decode_phase_started,
                stop_event,
            ),
            daemon=True,
        )
        try:
            self._process.start()
        except BaseException:
            self._control_queue.close()
            raise

    @property
    def is_done(self) -> bool:
        return self._status is not None

    @property
    def progress_frame(self) -> int:
        return int(self._progress_frame.value)

    def check(self) -> OpResult:
        """检查解码状态，并执行 60 秒无解码进度 watchdog。"""

        if self._force_closed:
            return err("[decoder] check: decoder already force closed.")
        if self._status is not None:
            return self._status

        for item in _drain_queue(self._control_queue):
            if not isinstance(item, OpResult):
                self._status = err("[decoder] invalid decoder worker status")
                self._request_stop()
                break
            self._status = item
            if not item.is_ok:
                self._request_stop()
            break

        if self._status is None and not self._process.is_alive():
            self._process.join(timeout=0)
            if self._process.exitcode == 0:
                self._status = err(
                    "[decoder] decoder worker exited without publishing completion"
                )
            else:
                self._status = err(_format_exit_line(self._process))
            self._request_stop()

        if self._status is None and self._decode_phase.value == _DECODE_PHASE_READING:
            stalled_for = time.monotonic() - self._decode_phase_started.value
            if stalled_for > _DECODE_STALL_TIMEOUT:
                self._status = err(
                    "[decoder] decode stalled for "
                    f"{_DECODE_STALL_TIMEOUT:.0f}s at frame {self.progress_frame}"
                )
                self._request_stop()

        return self._status if self._status is not None else ok()

    def close(self) -> None:
        if self._force_closed:
            return
        self._force_closed = True
        self._request_stop()
        if self._process.is_alive():
            self._process.terminate()
        self._process.join(timeout=10.0)
        if self._process.is_alive():
            from src.services import kill_process_tree

            kill_process_tree(self._process.pid)
        try:
            self._control_queue.close()
        except (AttributeError, OSError, ValueError):
            pass

    def _request_stop(self) -> None:
        self._stop_event.set()
        self._frame_buffer.wake_all()


def decode_worker_main(
    std_video_path,
    imgsz,
    total_frames,
    frame_buffer_spec,
    control_queue,
    progress_frame,
    decode_phase,
    decode_phase_started,
    stop_event,
):
    """在独立进程中解码，并直接向共享帧缓冲发布每一帧。"""

    frame_buffer = None
    cap = None
    frame_idx = 0
    try:
        frame_buffer = SharedFrameBuffer.attach(frame_buffer_spec)
        cap = cv2.VideoCapture(std_video_path)
        if not cap.isOpened():
            raise RuntimeError(
                i18n.t(
                    "detect_decode.error_open_video_failed",
                    path=str(std_video_path),
                )
            )

        while not stop_event.is_set():
            decode_phase.value = _DECODE_PHASE_READING
            decode_phase_started.value = time.monotonic()
            ret, frame = cap.read()
            if not ret:
                if frame_idx >= total_frames * 0.98:
                    decode_phase.value = _DECODE_PHASE_FINISHED
                    frame_buffer.finish_input()
                    control_queue.put(ok())
                    return
                raise RuntimeError(
                    i18n.t(
                        "detect_decode.error_decode_stopped_early",
                        frame=frame_idx,
                        expected=f"{total_frames * 0.98:.2f}",
                    )
                )

            frame = cv2.resize(frame, (imgsz, imgsz), interpolation=cv2.INTER_LINEAR)
            decode_phase.value = _DECODE_PHASE_PUBLISHING
            decode_phase_started.value = time.monotonic()

            deadline = time.monotonic() + _DECODE_BACKPRESSURE_TIMEOUT
            while True:
                if stop_event.is_set():
                    return
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(
                        "decoder shared frame buffer remained full for "
                        f"{_DECODE_BACKPRESSURE_TIMEOUT:.0f}s"
                    )
                if frame_buffer.publish(
                    frame_idx,
                    frame,
                    timeout=min(_DECODE_PUBLISH_WAIT_TIMEOUT, remaining),
                    stop_event=stop_event,
                ):
                    break

            frame_idx += 1
            progress_frame.value = frame_idx

    except BaseException as e:
        if stop_event.is_set():
            return
        try:
            control_queue.put(
                err(
                    f"[decoder] decoder worker failed at frame {frame_idx}",
                    error_raw=e,
                )
            )
        except Exception:
            pass
        sys.exit(1)
    finally:
        if cap is not None:
            cap.release()
        if frame_buffer is not None:
            frame_buffer.close()


def _drain_queue(queue):
    items = []
    while True:
        try:
            items.append(queue.get_nowait())
        except Empty:
            return items


def _format_exit_line(process):
    exitcode = process.exitcode
    win_code = (
        (exitcode & 0xFFFFFFFF) if exitcode is not None and exitcode < 0 else None
    )
    win_str = f"0x{win_code:08X}" if win_code is not None else "N/A"
    return f"decoder worker died, exitcode={exitcode} win_code={win_str}"
