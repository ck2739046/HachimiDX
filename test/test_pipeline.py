"""Pipeline 框架单测。

覆盖正常流程、OpResult 错误链、背压解除、cleanup 和线程生命周期。

运行::

    python -m pytest test/test_pipeline.py -v
    # 或直接
    python test/test_pipeline.py
"""

from __future__ import annotations

import sys
import threading
import time
import unittest
from pathlib import Path

# 把 workspace root 加入 sys.path,使 from src.core.auto_rechart.pipeline import ... 可解析
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.core.auto_rechart.pipeline import (  # noqa: E402
    Consumer,
    Pipeline,
    Producer,
    WorkerStatus,
)


def _result_text(result):
    parts = []
    current = result
    while current is not None:
        parts.append(current.error_msg)
        if current.error_raw:
            parts.append(str(current.error_raw))
        current = current.inner
    return "\n".join(parts)


# ---- 测试用业务桩 ----

class _ListProducer(Producer):
    """把一个列表依次入队，正常返回后由框架发送 DONE。"""

    def __init__(self, items):
        self.items = list(items)

    def produce(self, q, stop, ctx):
        for it in self.items:
            if not self._put_or_stop(q, it, stop):
                return


class _ListConsumer(Consumer):
    """把收到的 item append 到 self.received。"""

    def __init__(self):
        self.received = []

    def consume(self, item, stop, ctx):
        self.received.append(item)


class _CrashProducer(Producer):
    """推两项后抛 RuntimeError。"""

    def produce(self, q, stop, ctx):
        self._put_or_stop(q, 1, stop)
        self._put_or_stop(q, 2, stop)
        raise RuntimeError("producer boom")


class _CrashConsumer(Consumer):
    """收到第一个 item 后抛 RuntimeError。"""

    def __init__(self):
        self.received = []

    def consume(self, item, stop, ctx):
        self.received.append(item)
        raise RuntimeError("consumer boom")


class _SteadyProducer(Producer):
    """持续推 0..N-1,全程用 _put_or_stop,被 stop 时即刻 return。"""

    def __init__(self, n):
        self.n = n

    def produce(self, q, stop, ctx):
        for i in range(self.n):
            if not self._put_or_stop(q, i, stop):
                return


class _TrackingMixin:
    """记录 on_start / on_cleanup 调用情况。"""

    def __init__(self):
        self.start_calls = 0
        self.cleanup_calls = []  # 收集每次 error 参数

    def on_start(self, ctx):
        self.start_calls += 1

    def on_cleanup(self, ctx, error):
        self.cleanup_calls.append(error)


class _TrackingProducer(_TrackingMixin, _ListProducer):
    def __init__(self, items):
        _TrackingMixin.__init__(self)
        _ListProducer.__init__(self, items)


class _TrackingConsumer(_TrackingMixin, _ListConsumer):
    def __init__(self):
        _TrackingMixin.__init__(self)
        _ListConsumer.__init__(self)


# ---- 单测用例 ----

class PipelineTests(unittest.TestCase):

    # 1. 正常流程
    def test_normal_flow(self):
        producer = _ListProducer([1, 2, 3, 4, 5])
        consumer = _ListConsumer()
        pipeline = Pipeline(producer, consumer, queue_size=2)
        result = pipeline.run()
        self.assertTrue(result.is_ok, _result_text(result))
        self.assertEqual(consumer.received, [1, 2, 3, 4, 5])
        self.assertEqual(
            pipeline.worker_status,
            {"producer": WorkerStatus.DONE, "consumer": WorkerStatus.DONE},
        )

    # 2. producer 崩 → consumer 不卡死，run 返回错误链
    def test_producer_crash_propagates(self):
        producer = _CrashProducer()
        consumer = _ListConsumer()
        pipeline = Pipeline(producer, consumer, queue_size=2)
        result = pipeline.run()
        self.assertFalse(result.is_ok)
        self.assertIn("producer boom", _result_text(result))
        self.assertEqual(pipeline.worker_status["producer"], WorkerStatus.FAILED)
        self.assertEqual(pipeline.worker_status["consumer"], WorkerStatus.FAILED)

    # 3. consumer 崩 → producer 用 _put_or_stop 能脱困
    def test_consumer_crash_unblocks_producer(self):
        producer = _SteadyProducer(n=1000)
        consumer = _CrashConsumer()
        t0 = time.monotonic()
        pipeline = Pipeline(producer, consumer, queue_size=2)
        result = pipeline.run()
        elapsed = time.monotonic() - t0
        self.assertFalse(result.is_ok)
        self.assertIn("consumer boom", _result_text(result))
        self.assertLess(elapsed, 4.0, "producer 未被合作式解除阻塞")
        self.assertEqual(consumer.received, [0])

    # 4. on_cleanup 正常路径:恰好一次,error=None
    def test_on_cleanup_normal(self):
        producer = _TrackingProducer([1, 2])
        consumer = _TrackingConsumer()
        result = Pipeline(producer, consumer, queue_size=2).run()
        self.assertTrue(result.is_ok, _result_text(result))
        self.assertEqual(producer.start_calls, 1)
        self.assertEqual(consumer.start_calls, 1)
        self.assertEqual(producer.cleanup_calls, [None])
        self.assertEqual(consumer.cleanup_calls, [None])

    # 5. 对端异常时 cleanup 收到对应 OpResult
    def test_on_cleanup_error(self):
        producer = _CrashProducer()
        consumer = _TrackingConsumer()
        result = Pipeline(producer, consumer, queue_size=2).run()
        self.assertFalse(result.is_ok)
        self.assertEqual(len(consumer.cleanup_calls), 1)
        self.assertIsNotNone(consumer.cleanup_calls[0])
        self.assertFalse(consumer.cleanup_calls[0].is_ok)
        self.assertEqual(consumer.start_calls, 1)

    # 6. 线程生命周期:run 返回后两 worker 线程均已退出
    def test_threads_dead_after_run(self):
        producer = _ListProducer([1, 2, 3])
        consumer = _ListConsumer()
        result = Pipeline(producer, consumer, queue_size=2).run()
        self.assertTrue(result.is_ok, _result_text(result))
        alive = [
            thread.name
            for thread in threading.enumerate()
            if thread.name.startswith("pipeline-") and thread.is_alive()
        ]
        self.assertEqual(alive, [], f"pipeline 线程泄漏: {alive}")

    # 7. 满队列恢复:慢 consumer + 快 producer,仍全量送达
    def test_full_queue_recovery(self):
        class SlowConsumer(_ListConsumer):
            def consume(self, item, stop, ctx):
                time.sleep(0.05)  # 模拟重计算
                self.received.append(item)

        n = 20
        producer = _SteadyProducer(n)
        consumer = SlowConsumer()
        t0 = time.monotonic()
        result = Pipeline(producer, consumer, queue_size=2).run()
        elapsed = time.monotonic() - t0
        self.assertTrue(result.is_ok, _result_text(result))
        self.assertEqual(consumer.received, list(range(n)))
        # 慢 consumer 应触发背压(queue_size=2 经常满),但仍完成
        self.assertGreaterEqual(elapsed, n * 0.05 * 0.8)

    # 8. None 作为合法业务 item 能正确工作
    def test_none_is_data(self):
        class NoneItemProducer(Producer):
            def produce(self, q, stop, ctx):
                for v in [None, None, None]:
                    if not self._put_or_stop(q, v, stop):
                        return

        class NoneItemConsumer(Consumer):
            def __init__(self):
                self.received = []

            def consume(self, item, stop, ctx):
                self.received.append(item)

        producer = NoneItemProducer()
        consumer = NoneItemConsumer()
        result = Pipeline(producer, consumer, queue_size=2).run()
        self.assertTrue(result.is_ok, _result_text(result))
        self.assertEqual(consumer.received, [None, None, None])

    # 9. producer 用 _put_or_stop 在 stop 后及时 return(不被裸 q.put 卡死)
    def test_put_or_stop_respects_stop(self):
        started = threading.Event()
        returned = threading.Event()

        class HangingProducer(Producer):
            def produce(self, q, stop, ctx):
                started.set()
                # 故意只往满队列推,等待 stop
                for i in range(100):
                    if not self._put_or_stop(q, i, stop):
                        returned.set()
                        return

        class NoConsumer(Consumer):
            def consume(self, item, stop, ctx):
                pass  # 永远不会被调用(consumer 崩前 producer 先被 stop)

        # 用一个会立即崩的 consumer 触发 stop
        class CrashNow(Consumer):
            def on_start(self, ctx):
                raise RuntimeError("crash on start")

            def consume(self, item, stop, ctx):
                pass  # 不会到达

        producer = HangingProducer()
        result = Pipeline(producer, CrashNow(), queue_size=1).run()
        self.assertFalse(result.is_ok)
        self.assertIn("crash on start", _result_text(result))
        self.assertTrue(returned.wait(timeout=3.0), "producer 未在 stop 后及时 return")


if __name__ == "__main__":
    unittest.main(verbosity=2)
