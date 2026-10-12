"""detect 共享帧缓冲反压处理的隔离测试。"""

import os
import sys
import unittest
from collections import deque
from queue import Empty
from types import SimpleNamespace
from unittest.mock import patch

_WS_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if _WS_ROOT not in sys.path:
    sys.path.insert(0, _WS_ROOT)

from src.core.auto_rechart.detect import detect, detect_inference


class _FakeProcess:
    def is_alive(self):
        return True


class _FakeFrameBuffer:
    def __init__(self, publish_outcomes=()):
        self._publish_outcomes = deque(publish_outcomes)
        self.publish_calls = []
        self.finish_calls = 0
        self.wake_calls = 0

    def publish(self, frame_index, frame, *, timeout, stop_event):
        self.publish_calls.append((frame_index, frame, timeout, stop_event))
        if self._publish_outcomes:
            return self._publish_outcomes.popleft()
        return True

    def finish_input(self):
        self.finish_calls += 1

    def wake_all(self):
        self.wake_calls += 1

    def close(self):
        pass

    def unlink(self):
        pass


class _FakeQueue:
    def __init__(self, items=()):
        self._items = deque(items)

    def get_nowait(self):
        if not self._items:
            raise Empty
        return self._items.popleft()


class _FakeEvent:
    def is_set(self):
        return False


class TestInferencerBackpressure(unittest.TestCase):
    def test_put_batch_drains_output_when_input_is_full(self):
        output_item = ("ready-result", "detect")
        frame_buffer = _FakeFrameBuffer(publish_outcomes=(False, True))
        output_queue = _FakeQueue(items=(output_item,))
        deps = detect_inference._InferencerDeps(
            process_detect=_FakeProcess(),
            process_obb=_FakeProcess(),
            frame_buffer=frame_buffer,
            output_queue=output_queue,
            control_queue_detect=_FakeQueue(),
            control_queue_obb=_FakeQueue(),
            stop_event=_FakeEvent(),
            progress_ref_detect=SimpleNamespace(value=0),
            progress_ref_obb=SimpleNamespace(value=0),
        )
        inferencer = detect_inference.Inferencer(deps)

        put_result = inferencer.put_batch([(7, "frame")], timeout=1.0)
        get_result = inferencer.get_results()

        self.assertTrue(put_result.is_ok)
        self.assertTrue(get_result.is_ok)
        self.assertEqual([call[0] for call in frame_buffer.publish_calls], [7, 7])
        self.assertEqual(get_result.value, [output_item])

    def test_send_eof_drains_output_when_input_is_full(self):
        output_item = ("ready-result", "obb")
        frame_buffer = _FakeFrameBuffer()
        output_queue = _FakeQueue(items=(output_item,))
        deps = detect_inference._InferencerDeps(
            process_detect=_FakeProcess(),
            process_obb=_FakeProcess(),
            frame_buffer=frame_buffer,
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
        self.assertEqual(frame_buffer.finish_calls, 1)
        self.assertEqual(get_result.value, [output_item])


class _MainDecoder:
    def __init__(self, events):
        self._events = events
        self._done = False

    @property
    def is_done(self):
        return self._done

    def check(self):
        self._events.append("decode-check")
        self._done = True
        return detect.ok()

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

    def create_decoder(self, *_args):
        return _MainDecoder(self._events)

    def send_eof(self):
        self._events.append("eof")
        return detect.ok()

    def stop(self):
        self._events.append("inferencer-stop")


class TestMainLoopOrder(unittest.TestCase):
    def test_main_consumes_results_before_polling_decoder_and_eof(self):
        events = []
        inferencer = _MainInferencer(events)

        with (
            patch.object(detect.cv2, "VideoCapture") as video_capture,
            patch.object(
                detect, "create_inferencer", return_value=detect.ok(inferencer)
            ),
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
                model_backend="ONNX CPU",
                half=False,
            )

        self.assertTrue(result.is_ok)
        self.assertEqual(
            events,
            [
                "get",
                "decode-check",
                "decode-check",
                "eof",
                "get",
                "decoder-close",
                "inferencer-stop",
            ],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
