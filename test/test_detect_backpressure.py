"""detect 推理队列反压处理的隔离测试。"""
import os
import sys
import unittest
from collections import deque
from queue import Empty, Full
from types import SimpleNamespace
from unittest.mock import patch

_WS_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if _WS_ROOT not in sys.path:
    sys.path.insert(0, _WS_ROOT)

from src.core.auto_rechart.detect import detect
from src.core.auto_rechart.detect import detect_inference


class _FakeProcess:
    def is_alive(self):
        return True


class _FakeQueue:
    def __init__(self, items=(), put_outcomes=()):
        self._items = deque(items)
        self._put_outcomes = deque(put_outcomes)
        self.put_calls = []

    def get_nowait(self):
        if not self._items:
            raise Empty
        return self._items.popleft()

    def put(self, value, block, timeout):
        _ = block, timeout
        self.put_calls.append(value)
        if self._put_outcomes:
            outcome = self._put_outcomes.popleft()
            if outcome is Full:
                raise Full
            if isinstance(outcome, BaseException):
                raise outcome
        self._items.append(value)


class _FakeEvent:
    def is_set(self):
        return False


class TestInferencerBackpressure(unittest.TestCase):
    def test_put_batch_drains_output_when_input_is_full(self):
        output_item = ("ready-result", "detect")
        detect_input = _FakeQueue(put_outcomes=(Full, None))
        obb_input = _FakeQueue()
        output_queue = _FakeQueue(items=(output_item,))
        deps = detect_inference._InferencerDeps(
            process_detect=_FakeProcess(),
            process_obb=_FakeProcess(),
            input_queue_detect=detect_input,
            input_queue_obb=obb_input,
            output_queue=output_queue,
            control_queue_detect=_FakeQueue(),
            control_queue_obb=_FakeQueue(),
            stop_event=_FakeEvent(),
            progress_ref_detect=SimpleNamespace(value=0),
            progress_ref_obb=SimpleNamespace(value=0),
        )
        inferencer = detect_inference.Inferencer(deps)

        put_result = inferencer.put_batch("batch", timeout=1.0)
        get_result = inferencer.get_results()

        self.assertTrue(put_result.is_ok)
        self.assertTrue(get_result.is_ok)
        self.assertEqual(detect_input.put_calls, ["batch", "batch"])
        self.assertEqual(obb_input.put_calls, ["batch"])
        self.assertEqual(get_result.value, [output_item])

    def test_send_eof_drains_output_when_input_is_full(self):
        output_item = ("ready-result", "obb")
        detect_input = _FakeQueue(put_outcomes=(Full, None))
        obb_input = _FakeQueue()
        output_queue = _FakeQueue(items=(output_item,))
        deps = detect_inference._InferencerDeps(
            process_detect=_FakeProcess(),
            process_obb=_FakeProcess(),
            input_queue_detect=detect_input,
            input_queue_obb=obb_input,
            output_queue=output_queue,
            control_queue_detect=_FakeQueue(),
            control_queue_obb=_FakeQueue(),
            stop_event=_FakeEvent(),
            progress_ref_detect=SimpleNamespace(value=0),
            progress_ref_obb=SimpleNamespace(value=0),
        )
        inferencer = detect_inference.Inferencer(deps)

        eof_result = inferencer.send_eof(timeout=1.0)
        get_result = inferencer.get_results()

        self.assertTrue(eof_result.is_ok)
        self.assertTrue(get_result.is_ok)
        self.assertEqual(detect_input.put_calls, [None, None])
        self.assertEqual(obb_input.put_calls, [None])
        self.assertEqual(get_result.value, [output_item])


class _MainDecoder:
    def __init__(self, events):
        self._events = events
        self._batches = iter((["batch"], None))

    def get_next_batch(self):
        self._events.append("decode")
        return detect.ok(next(self._batches))

    def close(self):
        self._events.append("decoder-close")


class _MainInferencer:
    def __init__(self, events):
        self._events = events

    @property
    def progress(self):
        return (0, 0)

    @property
    def is_done(self):
        return True

    def get_results(self):
        self._events.append("get")
        return detect.ok([])

    def put_batch(self, _batch):
        _ = _batch
        self._events.append("put")
        return detect.ok()

    def send_eof(self):
        self._events.append("eof")
        return detect.ok()

    def stop(self):
        self._events.append("inferencer-stop")


class TestMainLoopOrder(unittest.TestCase):
    def test_main_consumes_results_before_decoding_and_putting(self):
        events = []
        inferencer = _MainInferencer(events)

        def create_decoder(*args):
            _ = args
            return _MainDecoder(events)

        with (
            patch.object(detect.cv2, "VideoCapture") as video_capture,
            patch.object(detect, "Decoder", side_effect=create_decoder),
            patch.object(detect, "create_inferencer", return_value=detect.ok(inferencer)),
            patch.object(detect, "_postprocess_results", return_value=[]),
            patch.object(detect, "_save_detect_results"),
        ):
            video_capture.return_value.get.return_value = 1920
            result = detect.main(
                std_video_path=SimpleNamespace(parent="."),
                total_frames=1,
                batch_detect=1,
                inference_device="cpu",
                detect_model_path="detect.pt",
                obb_model_path="obb.pt",
            )

        self.assertTrue(result.is_ok)
        self.assertEqual(events[:5], ["get", "decode", "put", "get", "decode"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
