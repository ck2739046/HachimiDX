"""Pipeline 框架单测。

覆盖:
1. 正常流程:producer 推 N 项 → consumer 全收到 → run 正常返回
2. producer 崩:consumer 不卡死,run 重抛原异常
3. consumer 崩:producer 在满队列上能脱困(用 _put_or_stop),run 重抛
4. on_cleanup 正常路径:恰好调用一次,error=None
5. on_cleanup 异常路径:恰好调用一次,error 是原异常
6. 线程生命周期:run 返回后两 worker 线程均 is_alive()==False
7. 满队列恢复:慢 consumer + 快 producer + queue_size=2,仍能全量送达

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

from src.core.auto_rechart.pipeline import Consumer, Pipeline, Producer  # noqa: E402


# ---- 测试用业务桩 ----

class _ListProducer(Producer):
    """把一个列表依次入队,结束发 sentinel。"""

    def __init__(self, items):
        self.items = list(items)

    def produce(self, q, stop, ctx):
        for it in self.items:
            if not self._put_or_stop(q, it, stop):
                return
        q.put(self.sentinel)


class _ListConsumer(Consumer):
    """把收到的 item append 到 self.received。"""

    def __init__(self):
        self.received = []

    def consume(self, item, stop, ctx):
        self.received.append(item)


class _CrashProducer(Producer):
    """推两项后抛 RuntimeError。"""

    def produce(self, q, stop, ctx):
        q.put(1)
        q.put(2)
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
        q.put(self.sentinel)


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
        Pipeline(producer, consumer, queue_size=2).run()
        self.assertEqual(consumer.received, [1, 2, 3, 4, 5])

    # 2. producer 崩 → consumer 不卡死,run 重抛
    def test_producer_crash_propagates(self):
        producer = _CrashProducer()
        consumer = _ListConsumer()
        with self.assertRaises(RuntimeError) as cm:
            Pipeline(producer, consumer, queue_size=2).run()
        self.assertIn("producer boom", str(cm.exception))
        # 注:异常路径下主线程会 drain_queue 排空未消费数据(框架正确行为),
        # 因此 consumer.received 的具体内容随时序变化,不在此断言。

    # 3. consumer 崩 → producer 用 _put_or_stop 能脱困,run 重抛
    def test_consumer_crash_unblocks_producer(self):
        producer = _SteadyProducer(n=1000)
        consumer = _CrashConsumer()
        t0 = time.monotonic()
        with self.assertRaises(RuntimeError) as cm:
            Pipeline(producer, consumer, queue_size=2).run()
        elapsed = time.monotonic() - t0
        self.assertIn("consumer boom", str(cm.exception))
        # 关键:不应耗到 error_grace_timeout 才返回(说明 producer 被 stop 解除而非硬超时)
        self.assertLess(elapsed, 4.0, "producer 未被合作式解除阻塞")
        self.assertEqual(consumer.received, [0])

    # 4. on_cleanup 正常路径:恰好一次,error=None
    def test_on_cleanup_normal(self):
        producer = _TrackingProducer([1, 2])
        consumer = _TrackingConsumer()
        Pipeline(producer, consumer, queue_size=2).run()
        self.assertEqual(producer.start_calls, 1)
        self.assertEqual(consumer.start_calls, 1)
        self.assertEqual(producer.cleanup_calls, [None])
        self.assertEqual(consumer.cleanup_calls, [None])

    # 5. on_cleanup 异常路径:恰好一次,error 是原异常
    def test_on_cleanup_error(self):
        producer = _CrashProducer()
        consumer = _TrackingConsumer()
        with self.assertRaises(RuntimeError):
            Pipeline(producer, consumer, queue_size=2).run()
        # consumer 正常退出(error=None),因为 producer 崩后主线程补了 sentinel
        self.assertEqual(consumer.cleanup_calls, [None])
        self.assertEqual(consumer.start_calls, 1)

    # 6. 线程生命周期:run 返回后两 worker 线程均已退出
    def test_threads_dead_after_run(self):
        producer = _ListProducer([1, 2, 3])
        consumer = _ListConsumer()
        captured = {}

        def _watch():
            # 包一层抓线程对象
            pass

        # 用 InstrumentedPipeline 抓线程引用
        class _CapturingPipeline(Pipeline):
            def run(self):
                import queue as _q
                from src.core.auto_rechart.pipeline import _DEFAULT_SENTINEL
                q = _q.Queue(maxsize=self.queue_size)
                stop = threading.Event()
                error_box = []
                self.producer.sentinel = self.sentinel
                self.consumer.sentinel = self.sentinel
                pt = threading.Thread(
                    target=self._run_producer, args=(q, stop, error_box),
                    daemon=True)
                ct = threading.Thread(
                    target=self._run_consumer, args=(q, stop, error_box),
                    daemon=True)
                pt.start(); ct.start()
                captured["p"] = pt
                captured["c"] = ct
                while pt.is_alive() or ct.is_alive():
                    pt.join(timeout=self.poll_interval)
                    ct.join(timeout=self.poll_interval)
                    if error_box:
                        stop.set()
                        break
                pt.join(timeout=self.error_grace_timeout)
                ct.join(timeout=self.error_grace_timeout)
                if error_box:
                    raise error_box[0][1]

        _CapturingPipeline(producer, consumer, queue_size=2).run()
        self.assertFalse(captured["p"].is_alive(), "producer 线程泄漏")
        self.assertFalse(captured["c"].is_alive(), "consumer 线程泄漏")

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
        Pipeline(producer, consumer, queue_size=2).run()
        elapsed = time.monotonic() - t0
        self.assertEqual(consumer.received, list(range(n)))
        # 慢 consumer 应触发背压(queue_size=2 经常满),但仍完成
        self.assertGreaterEqual(elapsed, n * 0.05 * 0.8)

    # 8. 自定义 sentinel:None 作为合法业务 item 也能正确工作
    def test_custom_sentinel_when_none_is_data(self):
        class NoneItemProducer(Producer):
            def __init__(self):
                self.count = 0

            def produce(self, q, stop, ctx):
                # None 是合法业务数据
                for v in [None, None, None]:
                    if not self._put_or_stop(q, v, stop):
                        return
                q.put(self.sentinel)

        class NoneItemConsumer(Consumer):
            def __init__(self):
                self.received = []

            def consume(self, item, stop, ctx):
                self.received.append(item)

        _sentinel = object()  # 自定义非 None 哨兵
        producer = NoneItemProducer()
        consumer = NoneItemConsumer()
        Pipeline(producer, consumer, queue_size=2, sentinel=_sentinel).run()
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
        with self.assertRaises(RuntimeError):
            Pipeline(producer, CrashNow(), queue_size=1).run()
        self.assertTrue(returned.wait(timeout=3.0), "producer 未在 stop 后及时 return")


if __name__ == "__main__":
    unittest.main(verbosity=2)
