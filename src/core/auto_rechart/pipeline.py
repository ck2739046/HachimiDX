"""轻量线程级生产者-消费者框架"""

from __future__ import annotations

import queue
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any

from ..schemas.op_result import OpResult, err, ok


_PUT_TIMEOUT = 0.5          # _put_or_stop 单次 put 超时(周期检查 stop)
_POLL_INTERVAL = 0.5        # 主线程 poll-join 间隔
_ERROR_GRACE_TIMEOUT = 5.0  # 异常后给存活 worker 的退出宽限(秒)


class WorkerStatus(Enum):
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class _MessageKind(Enum):
    ITEM = "item"
    DONE = "done"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class _Message:
    kind: _MessageKind
    value: Any = None


class _RunState:
    """单次运行的共享状态。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._status = {
            "producer": WorkerStatus.RUNNING,
            "consumer": WorkerStatus.RUNNING,
        }
        self._failures: list[OpResult[Any]] = []
        self._cleanup_started: set[str] = set()

    def set_status(self, role: str, status: WorkerStatus) -> None:
        with self._lock:
            if self._status[role] == WorkerStatus.RUNNING:
                self._status[role] = status

    def add_failure(self, role: str, failure: OpResult[Any]) -> None:
        with self._lock:
            self._failures.append(failure)
            if role in self._status and self._status[role] == WorkerStatus.RUNNING:
                self._status[role] = WorkerStatus.FAILED

    def has_failure(self) -> bool:
        with self._lock:
            return bool(self._failures)

    def first_failure(self) -> OpResult[Any] | None:
        with self._lock:
            return self._failures[0] if self._failures else None

    def failures(self) -> list[OpResult[Any]]:
        with self._lock:
            return list(self._failures)

    def statuses(self) -> dict[str, WorkerStatus]:
        with self._lock:
            return dict(self._status)

    def begin_cleanup(self, role: str) -> bool:
        with self._lock:
            if role in self._cleanup_started:
                return False
            self._cleanup_started.add(role)
            return True


class Producer(ABC):
    """生产者基类。produce() 正常返回后，框架自动通知 consumer 结束。"""

    @abstractmethod
    def produce(self, q: "queue.Queue[Any]", stop: threading.Event, ctx: Any) -> None:
        """生产业务数据；正常返回即可。"""

    def on_start(self, ctx: Any) -> None:
        """线程启动前调用一次(默认空)。打开 cap、加载模型可放此处或 __init__"""

    def on_cleanup(self, ctx: Any, error: OpResult[Any] | None) -> None:
        """退出前调用一次；error=None 表示当前已知路径正常。"""

    @staticmethod
    def _put_or_stop(
        q: "queue.Queue[Any]",
        item: Any,
        stop: threading.Event,
        timeout: float = _PUT_TIMEOUT,
    ) -> bool:
        """
        带超时的 put:队列满则周期重试并检查 stop_event。
        返回 True 表示已入队; 返回 False 表示 stop 已触发, 业务方应即刻 return。
        """
        while True:
            if stop.is_set():
                return False
            try:
                q.put(_Message(_MessageKind.ITEM, item), block=True, timeout=timeout)
                return True
            except queue.Full:
                continue


class Consumer(ABC):
    """消费者基类。框架只会把业务 item 传给 consume()。"""

    @abstractmethod
    def consume(self, item: Any, stop: threading.Event, ctx: Any) -> None:
        """处理单个 item。sentinel 不会传入,框架自动终止"""

    def on_start(self, ctx: Any) -> None:
        """线程启动前调用一次(默认空)"""

    def on_cleanup(self, ctx: Any, error: OpResult[Any] | None) -> None:
        """无论正常/异常都恰好调用一次"""


class Pipeline:
    """编排一个 producer 线程和一个 consumer 线程。"""

    def __init__(
        self,
        producer: Producer,
        consumer: Consumer,
        *,
        queue_size: int = 2,
        ctx: Any = None,
        poll_interval: float = _POLL_INTERVAL,
        error_grace_timeout: float = _ERROR_GRACE_TIMEOUT,
    ) -> None:
        self.producer = producer
        self.consumer = consumer
        self.queue_size = queue_size
        self.ctx = ctx
        self.poll_interval = poll_interval
        self.error_grace_timeout = error_grace_timeout
        self._worker_status = {
            "producer": WorkerStatus.RUNNING,
            "consumer": WorkerStatus.RUNNING,
        }

    @property
    def worker_status(self) -> dict[str, WorkerStatus]:
        """最近一次 run 的 worker 状态快照。"""
        return dict(self._worker_status)

    def run(self) -> OpResult[None]:
        """启动并等待两个 worker；成功或错误链均通过 OpResult 返回。"""
        validation_error = self._validate_config()
        if validation_error is not None:
            self._worker_status = {
                "producer": WorkerStatus.FAILED,
                "consumer": WorkerStatus.FAILED,
            }
            return validation_error

        q: "queue.Queue[Any]" = queue.Queue(maxsize=self.queue_size)
        stop = threading.Event()
        state = _RunState()
        started_roles: set[str] = set()

        producer_t = threading.Thread(
            target=self._run_producer,
            args=(q, stop, state),
            name="pipeline-producer",
            daemon=True,
        )
        consumer_t = threading.Thread(
            target=self._run_consumer,
            args=(q, stop, state),
            name="pipeline-consumer",
            daemon=True,
        )

        try:
            consumer_t.start()
            started_roles.add("consumer")
            producer_t.start()
            started_roles.add("producer")

            while producer_t.is_alive() or consumer_t.is_alive():
                producer_t.join(timeout=self.poll_interval)
                consumer_t.join(timeout=self.poll_interval)
                if state.has_failure():
                    stop.set()
                    self._replace_with_terminal(
                        q,
                        _Message(_MessageKind.FAILED, state.first_failure()),
                    )
                    break
        except BaseException as exc:
            failure = err("[pipeline] coordinator failed", error_raw=exc)
            state.add_failure("pipeline", failure)
            stop.set()
            self._replace_with_terminal(q, _Message(_MessageKind.FAILED, failure))
        finally:
            if state.has_failure():
                stop.set()
                self._replace_with_terminal(
                    q,
                    _Message(_MessageKind.FAILED, state.first_failure()),
                )

            self._join_workers(producer_t, consumer_t, state)

            for role, worker in (
                ("producer", self.producer),
                ("consumer", self.consumer),
            ):
                if role not in started_roles:
                    self._safe_cleanup(role, worker, state, state.first_failure())
                    state.set_status(role, WorkerStatus.FAILED)

            self._worker_status = state.statuses()

        failures = state.failures()
        statuses = state.statuses()
        if not failures and all(status == WorkerStatus.DONE for status in statuses.values()):
            return ok()

        if not failures:
            failures.append(err(f"[pipeline] invalid final worker status: {statuses}"))
        return err("[pipeline] failed", inner=_chain_op_results(failures))

    def _run_producer(
        self,
        q: "queue.Queue[Any]",
        stop: threading.Event,
        state: _RunState,
    ) -> None:
        failure: OpResult[Any] | None = None
        try:
            if stop.is_set():
                failure = state.first_failure()
            else:
                self.producer.on_start(self.ctx)
                self.producer.produce(q, stop, self.ctx)
                if stop.is_set():
                    failure = state.first_failure()
        except BaseException as exc:
            failure = err("[pipeline.producer] worker failed", error_raw=exc)
            state.add_failure("producer", failure)
            stop.set()

        cleanup_failure = self._safe_cleanup(
            "producer", self.producer, state, failure or state.first_failure()
        )
        failure = failure or cleanup_failure or state.first_failure()

        if failure is not None or stop.is_set():
            state.set_status("producer", WorkerStatus.FAILED)
            self._replace_with_terminal(q, _Message(_MessageKind.FAILED, failure))
            return

        if self._put_message_or_stop(q, _Message(_MessageKind.DONE), stop):
            state.set_status("producer", WorkerStatus.DONE)
        else:
            state.set_status("producer", WorkerStatus.FAILED)

    def _run_consumer(
        self,
        q: "queue.Queue[Any]",
        stop: threading.Event,
        state: _RunState,
    ) -> None:
        failure: OpResult[Any] | None = None
        try:
            if stop.is_set():
                failure = state.first_failure()
            else:
                self.consumer.on_start(self.ctx)
                while True:
                    if stop.is_set() and state.has_failure():
                        failure = state.first_failure()
                        break
                    try:
                        message = q.get(timeout=self.poll_interval)
                    except queue.Empty:
                        continue

                    if not isinstance(message, _Message):
                        raise RuntimeError("pipeline queue received an invalid message")
                    if message.kind == _MessageKind.ITEM:
                        self.consumer.consume(message.value, stop, self.ctx)
                    elif message.kind == _MessageKind.DONE:
                        break
                    elif message.kind == _MessageKind.FAILED:
                        failure = message.value or state.first_failure()
                        stop.set()
                        break
        except BaseException as exc:
            failure = err("[pipeline.consumer] worker failed", error_raw=exc)
            state.add_failure("consumer", failure)
            stop.set()

        cleanup_failure = self._safe_cleanup(
            "consumer", self.consumer, state, failure or state.first_failure()
        )
        failure = failure or cleanup_failure or state.first_failure()

        if failure is not None or stop.is_set():
            state.set_status("consumer", WorkerStatus.FAILED)
        else:
            state.set_status("consumer", WorkerStatus.DONE)

    def _safe_cleanup(
        self,
        role: str,
        worker: "Producer | Consumer",
        state: _RunState,
        error: OpResult[Any] | None,
    ) -> OpResult[Any] | None:
        if not state.begin_cleanup(role):
            return None
        try:
            worker.on_cleanup(self.ctx, error)
            return None
        except BaseException as exc:
            failure = err(f"[pipeline.{role}] cleanup failed", error_raw=exc)
            state.add_failure(role, failure)
            return failure

    def _join_workers(
        self,
        producer_t: threading.Thread,
        consumer_t: threading.Thread,
        state: _RunState,
    ) -> None:
        if not state.has_failure():
            producer_t.join()
            consumer_t.join()
            return

        deadline = time.monotonic() + self.error_grace_timeout
        for thread in (producer_t, consumer_t):
            if thread.ident is None:
                continue
            remaining = max(0.0, deadline - time.monotonic())
            thread.join(timeout=remaining)

        alive = [
            role
            for role, thread in (("producer", producer_t), ("consumer", consumer_t))
            if thread.ident is not None and thread.is_alive()
        ]
        if alive:
            failure = err(
                "[pipeline] worker stop timeout; daemon thread still alive: "
                + ", ".join(alive)
            )
            state.add_failure("pipeline", failure)
            for role in alive:
                state.set_status(role, WorkerStatus.FAILED)

    def _validate_config(self) -> OpResult[None] | None:
        if not isinstance(self.queue_size, int) or self.queue_size <= 0:
            return err(f"[pipeline] queue_size must be a positive integer: {self.queue_size!r}")
        if not isinstance(self.poll_interval, (int, float)) or self.poll_interval <= 0:
            return err(f"[pipeline] poll_interval must be positive: {self.poll_interval!r}")
        if (
            not isinstance(self.error_grace_timeout, (int, float))
            or self.error_grace_timeout <= 0
        ):
            return err(
                "[pipeline] error_grace_timeout must be positive: "
                f"{self.error_grace_timeout!r}"
            )
        return None

    @staticmethod
    def _put_message_or_stop(
        q: "queue.Queue[Any]",
        message: _Message,
        stop: threading.Event,
    ) -> bool:
        while not stop.is_set():
            try:
                q.put(message, block=True, timeout=_PUT_TIMEOUT)
                return True
            except queue.Full:
                continue
        return False

    @staticmethod
    def _replace_with_terminal(q: "queue.Queue[Any]", message: _Message) -> None:
        """异常路径丢弃待处理 item，并尽力放入终止消息解除 consumer。"""
        while True:
            try:
                q.get_nowait()
            except queue.Empty:
                break
        try:
            q.put_nowait(message)
        except queue.Full:
            pass


def _clone_op_result(result: OpResult[Any]) -> OpResult[Any]:
    return OpResult(
        is_ok=result.is_ok,
        source=result.source,
        value=result.value,
        error_msg=result.error_msg,
        error_raw=result.error_raw,
        inner=_clone_op_result(result.inner) if result.inner is not None else None,
    )


def _chain_op_results(results: list[OpResult[Any]]) -> OpResult[Any]:
    if not results:
        return err("[pipeline] no failure details")

    root = _clone_op_result(results[0])
    tail = root
    while tail.inner is not None:
        tail = tail.inner
    for result in results[1:]:
        tail.inner = _clone_op_result(result)
        while tail.inner is not None:
            tail = tail.inner
    return root
