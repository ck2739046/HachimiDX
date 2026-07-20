"""
轻量线程级生产者-消费者框架

专注非业务代码:
    线程拉起 / sentinel 协议 / 异常传播 / 资源清理钩子

业务方继承 Producer / Consumer 实现 produce() / consume(),
可选重写 on_start / on_cleanup; Pipeline.run() 编排一切

设计要点:
- producer 和 consumer 都是独立 daemon 线程, 主线程只编排不消费
- sentinel 协议:
      producer 结束必须 q.put(self.sentinel), 框架检测到后自动停 consumer
- 异常策略 = stop_event 合作式 + 主线程排空兜底:
    * 任一方崩溃 → error_box 记录 → stop.set()
    * 主线程 poll 检测到 error → drain queue + 补投 sentinel,解除存活方阻塞
    * 业务方应使用 _put_or_stop 才能在满队列上享受合作式中断
- on_cleanup 无论正常/异常都恰好调用一次 (error=None 表示正常退出)
"""

from __future__ import annotations

import queue
import threading
from abc import ABC, abstractmethod
from typing import Any, Optional


# Pipeline 内部默认哨兵:用模块级单例对象,避免与 None 这类合法业务 item 冲突
_DEFAULT_SENTINEL = object()

_PUT_TIMEOUT = 0.5          # _put_or_stop 单次 put 超时(周期检查 stop)
_POLL_INTERVAL = 0.5        # 主线程 poll-join 间隔
_ERROR_GRACE_TIMEOUT = 5.0  # 异常后给存活 worker 的退出宽限(秒)


class Producer(ABC):
    """
    生产者基类。

    子类实现 produce(), 在其中用 q.put 推数据,
    结束前必须 q.put(self.sentinel) 通知 consumer 终止。
    满队列场景下应使用 self._put_or_stop(q, item, stop) 而非裸 q.put,
    以保证 stop_event 触发时能及时脱困。
    """

    # 由 Pipeline.run() 启动前注入; 业务方在 produce() 末尾 q.put(self.sentinel)
    sentinel: Any = _DEFAULT_SENTINEL

    @abstractmethod
    def produce(self, q: "queue.Queue[Any]", stop: threading.Event, ctx: Any) -> None:
        """业务循环。结束时必须 q.put(self.sentinel)"""

    def on_start(self, ctx: Any) -> None:
        """线程启动前调用一次(默认空)。打开 cap、加载模型可放此处或 __init__"""

    def on_cleanup(self, ctx: Any, error: Optional[BaseException]) -> None:
        """
        无论正常/异常都恰好调用一次; error=None 表示正常退出。
        典型用途: cap.release()、atexit.unregister、kill 子进程。
        """

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
                q.put(item, block=True, timeout=timeout)
                return True
            except queue.Full:
                continue


class Consumer(ABC):
    """
    消费者基类

    子类实现 consume(item, ...) 处理单个 item; sentinel 由框架拦截,
    不会传入 consume。可选重写 on_start / on_cleanup 管理资源句柄
    (如 export 的 ffmpeg 子进程)。
    """

    #: 由 Pipeline.run() 启动前注入(仅用于身份比较,框架侧使用)
    sentinel: Any = _DEFAULT_SENTINEL

    @abstractmethod
    def consume(self, item: Any, stop: threading.Event, ctx: Any) -> None:
        """处理单个 item。sentinel 不会传入,框架自动终止"""

    def on_start(self, ctx: Any) -> None:
        """线程启动前调用一次(默认空)"""

    def on_cleanup(self, ctx: Any, error: Optional[BaseException]) -> None:
        """无论正常/异常都恰好调用一次"""


class Pipeline:
    """
    编排一个 producer 线程 + 一个 consumer 线程

    典型用法::

        producer = MyProducer(...)
        consumer = MyConsumer(..., results=[])
        Pipeline(producer, consumer, queue_size=2).run()
        # run() 返回后,consumer.results 已填好
    """

    def __init__(
        self,
        producer: Producer,
        consumer: Consumer,
        *,
        queue_size: int = 2,
        sentinel: Any = None,
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
        # sentinel=None 时回落到模块默认哨兵对象,避免与 None 合法 item 冲突
        self.sentinel = _DEFAULT_SENTINEL if sentinel is None else sentinel

    def run(self) -> None:
        """
        启动 producer/consumer 线程,阻塞直到双方都退出。

        正常:producer 发 sentinel,consumer 收到后退出,run() 正常返回。
        异常:任一方崩溃 → 解除另一方阻塞 → 重新抛出第一个异常(保留 traceback)。
        """
        q: "queue.Queue[Any]" = queue.Queue(maxsize=self.queue_size)
        stop = threading.Event()
        error_box: list = []  # [(role, exc), ...]

        # 注入 sentinel,业务方 produce() 内 q.put(self.sentinel) 即可
        self.producer.sentinel = self.sentinel
        self.consumer.sentinel = self.sentinel

        producer_t = threading.Thread(
            target=self._run_producer,
            args=(q, stop, error_box),
            name="pipeline-producer",
            daemon=True,
        )
        consumer_t = threading.Thread(
            target=self._run_consumer,
            args=(q, stop, error_box),
            name="pipeline-consumer",
            daemon=True,
        )
        producer_t.start()
        consumer_t.start()

        # 主线程 poll-join:正常路径无限等,异常路径主动解阻塞后 break
        while producer_t.is_alive() or consumer_t.is_alive():
            producer_t.join(timeout=self.poll_interval)
            consumer_t.join(timeout=self.poll_interval)
            if error_box:
                stop.set()
                self._drain(q)              # 解除 producer 在满队列 put 上的阻塞
                self._try_put_sentinel(q)   # 补 sentinel 解除 consumer 在 get 上的阻塞
                break

        # 异常路径给存活方一个宽限期(正常路径 grace=None,无限等到结束)
        grace = self.error_grace_timeout if error_box else None
        producer_t.join(timeout=grace)
        consumer_t.join(timeout=grace)

        if error_box:
            _role, exc = error_box[0]
            raise exc

    # ---- worker 包装(捕获异常 / 保证 on_cleanup / 记录 error) ----

    def _run_producer(
        self,
        q: "queue.Queue[Any]",
        stop: threading.Event,
        error_box: list,
    ) -> None:
        error: Optional[BaseException] = None
        try:
            self.producer.on_start(self.ctx)
            self.producer.produce(q, stop, self.ctx)
        except BaseException as e:
            error = e
            error_box.append(("producer", e))
            stop.set()
        finally:
            self._safe_cleanup("producer", self.producer, error_box, error)

    def _run_consumer(
        self,
        q: "queue.Queue[Any]",
        stop: threading.Event,
        error_box: list,
    ) -> None:
        error: Optional[BaseException] = None
        try:
            self.consumer.on_start(self.ctx)
            while not stop.is_set():
                try:
                    item = q.get(timeout=self.poll_interval)
                except queue.Empty:
                    continue
                if item is self.sentinel:
                    break
                self.consumer.consume(item, stop, self.ctx)
        except BaseException as e:
            error = e
            error_box.append(("consumer", e))
            stop.set()
        finally:
            self._safe_cleanup("consumer", self.consumer, error_box, error)

    def _safe_cleanup(
        self,
        role: str,
        worker: "Producer | Consumer",
        error_box: list,
        error: Optional[BaseException],
    ) -> None:
        """调用 on_cleanup;cleanup 自身抛异常也记入 error_box 不吞掉。"""
        try:
            worker.on_cleanup(self.ctx, error)
        except BaseException as ce:
            error_box.append((f"{role}_cleanup", ce))

    # ---- 队列操作辅助 ----

    @staticmethod
    def _drain(q: "queue.Queue[Any]") -> None:
        """排空队列(解除 producer 在满队列 put 上的阻塞)"""
        while True:
            try:
                q.get_nowait()
            except queue.Empty:
                return

    def _try_put_sentinel(self, q: "queue.Queue[Any]") -> None:
        """尽力补投 sentinel, 解除 consumer 在 q.get 上的阻塞"""
        try:
            q.put(self.sentinel, block=False)
        except queue.Full:
            self._drain(q)
            try:
                q.put(self.sentinel, block=False)
            except queue.Full:
                pass
