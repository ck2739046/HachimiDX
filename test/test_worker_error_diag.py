"""detect.py actor 失败诊断逻辑的隔离单测（重构版：DataLoader + torch.mp）。

覆盖本次重构后的核心逻辑（不依赖真实 YOLO / 视频 / multiprocessing spawn）：
  1. format_exit_line            — exitcode/win_code 格式化（正/负/None 三类）
  2. _collect_result + __error__ — Python 异常哨兵的状态机转换（done/alive/died/errors）
  3. _infer_worker_target 异常转发 — predict 抛错时经 results_queue 转发 __error__ 并 raise
  4. _VideoFrameDataset           — mock cv2.VideoCapture 验证 yield/StopIteration/cap.release

运行：
    python test/test_worker_error_diag.py
    python -m pytest test/test_worker_error_diag.py
"""
import os
import sys
import queue
import unittest
import multiprocessing
from types import SimpleNamespace
from unittest.mock import MagicMock

# --- 让 src.* 可 import（namespace package，src 无 __init__.py） ---
_WS_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if _WS_ROOT not in sys.path:
    sys.path.insert(0, _WS_ROOT)

# --- import detect 前注入 mock ---
# torch 必须真实（_VideoFrameDataset 继承 torch.utils.data.IterableDataset），
# cv2/ultralytics 仅 import 未即时调用，可 mock。
for _mod in ("ultralytics", "cv2"):
    sys.modules.setdefault(_mod, MagicMock())

import numpy as np  # noqa: E402
from src.core.auto_rechart.detect import detect  # noqa: E402


class _FakeYOLO:
    """predict 直接抛错，模拟 YOLO 推理失败（含 CUDA/TRT native 之外的 Python 异常）。"""

    def __init__(self, *args, **kwargs):
        pass

    def predict(self, **kwargs):
        raise RuntimeError("simulated predict failure")


def _proc_like(exitcode):
    """构造仅有 exitcode 属性的假 Process 对象。"""
    return SimpleNamespace(exitcode=exitcode)


class TestFormatExitLine(unittest.TestCase):
    """format_exit_line：三类 exitcode 的格式化。"""

    def test_negative_renders_win_code_hex(self):
        # Windows ACCESS_VIOLATION：NT 状态码 0xC0000005，mp 进程 exitcode 取其负值
        line = detect.format_exit_line(_proc_like(-0xC0000005), "detect")
        self.assertIn("[detect] actor died", line)
        self.assertIn("exitcode=-3221225477", line)   # -0xC0000005
        self.assertIn("win_code=0xC0000005", line)

    def test_positive_no_win_code(self):
        # Python sys.exit(1)：正值，win_code 应为 N/A
        line = detect.format_exit_line(_proc_like(1), "obb")
        self.assertIn("exitcode=1", line)
        self.assertIn("win_code=N/A", line)

    def test_none_exitcode(self):
        # 进程刚启动，exitcode 尚未生成
        line = detect.format_exit_line(_proc_like(None), "detect")
        self.assertIn("exitcode=None", line)
        self.assertIn("win_code=N/A", line)


class TestCollectResultErrorSentinel(unittest.TestCase):
    """_collect_result：__error__ 哨兵 → done/alive/died/errors 状态机转换。"""

    def test_error_marks_done_and_died(self):
        state = detect._ResultCollector(workers_alive=2)
        tb = "Traceback (most recent call last):\nRuntimeError: boom\n"
        item = ("__error__", "obb", tb, 42)

        detect._collect_result(state, item)

        self.assertIn("obb", state.done_workers)      # 视同完成，防 _check_worker_dead 重复判死
        self.assertEqual(state.workers_alive, 1)       # 从 2 递减到 1
        self.assertTrue(state.worker_died)             # 触发 abort
        self.assertEqual(state.worker_errors, [("obb", tb, 42)])

    def test_done_sentinel_unchanged_behavior(self):
        state = detect._ResultCollector(workers_alive=2)
        detect._collect_result(state, ("__done__", "detect"))
        self.assertIn("detect", state.done_workers)
        self.assertEqual(state.workers_alive, 1)
        self.assertFalse(state.worker_died)
        self.assertEqual(state.worker_errors, [])

    def test_normal_result_appended(self):
        state = detect._ResultCollector(workers_alive=2)
        detect._collect_result(state, ("some_note", "obb"))
        self.assertEqual(state.all_raw_results, [("some_note", "obb")])
        self.assertEqual(state.workers_alive, 2)       # 不变


class TestInferWorkerTargetErrorForwarding(unittest.TestCase):
    """_infer_worker_target：predict 抛错 → 转发 __error__ + raise（保留 exitcode 语义）。"""

    def setUp(self):
        self._orig_yolo = detect.YOLO
        detect.YOLO = _FakeYOLO  # 主进程内 monkeypatch 生效（非 spawn）

    def tearDown(self):
        detect.YOLO = self._orig_yolo

    def _run_target(self, n_batches):
        """构造 in_queue 含 n_batches 个 batch + EOF，调 _infer_worker_target。

        新签名：(model_path, task_name, batch_size, device, in_queue, results_queue,
                progress_val, coord_scale, stop_event)
        """
        in_queue = queue.Queue()
        for _ in range(n_batches):
            in_queue.put([object(), object()])  # List[ndarray-like] = 1 batch（2 帧）
        in_queue.put(detect._INFER_EOF)

        results_queue = queue.Queue()
        progress_val = multiprocessing.Value("i", 0)

        raised = None
        try:
            detect._infer_worker_target(
                "fake.pt", "detect", 2, None,
                in_queue, results_queue, progress_val, 1.0, None,
            )
        except BaseException as e:
            raised = e
        return raised, results_queue

    def test_predict_failure_forwards_error_and_reraises(self):
        raised, results_queue = self._run_target(n_batches=1)

        # 必须 raise（保留进程 exitcode 语义：Python 异常→1，native→负值）
        self.assertIsNotNone(raised)
        self.assertIsInstance(raised, RuntimeError)

        # results_queue 应收到一条 __error__
        self.assertEqual(results_queue.qsize(), 1)
        item = results_queue.get_nowait()
        self.assertEqual(item[0], "__error__")
        self.assertEqual(item[1], "detect")
        self.assertIn("RuntimeError", item[2])        # traceback 字符串
        self.assertIn("simulated predict failure", item[2])
        self.assertEqual(item[3], 0)                   # next_frame_idx（首次 batch）

    def test_eof_without_batch_exits_cleanly(self):
        """in_queue 只有 EOF（无 batch）→ actor 正常发 __done__ 退出，不 raise。"""
        raised, results_queue = self._run_target(n_batches=0)

        self.assertIsNone(raised)
        self.assertEqual(results_queue.qsize(), 1)
        self.assertEqual(results_queue.get_nowait(), ("__done__", "detect"))


class TestVideoFrameDataset(unittest.TestCase):
    """_VideoFrameDataset：mock cv2.VideoCapture 验证 yield/StopIteration/cap.release。

    detect.cv2 是 sys.modules['cv2'] 的 MagicMock 引用（顶部注入），可直接配置 side_effect。
    """

    def _setup_mock_cv2(self, n_frames, resize_side_effect=None):
        fake_frame = np.zeros((10, 10, 3), dtype=np.uint8)
        count = [0]
        released = [False]

        cap = MagicMock()

        def _read():
            if count[0] < n_frames:
                count[0] += 1
                return (True, fake_frame)
            return (False, None)

        cap.read.side_effect = _read
        cap.release.side_effect = lambda: released.__setitem__(0, True)
        cap.get.side_effect = lambda prop: 100  # CAP_PROP_FRAME_WIDTH

        detect.cv2.VideoCapture.return_value = cap
        detect.cv2.resize.side_effect = resize_side_effect or (
            lambda frame, sz, interpolation=None: frame
        )
        detect.cv2.INTER_LINEAR = 5
        return cap, released

    def tearDown(self):
        # 复位 MagicMock 调用计数与 side_effect，避免测试间污染
        detect.cv2.VideoCapture.reset_mock(return_value=True, side_effect=True)
        detect.cv2.resize.reset_mock(return_value=True, side_effect=True)

    def test_iter_yields_resized_frames_then_stops(self):
        self._setup_mock_cv2(n_frames=3)
        ds = detect._VideoFrameDataset("fake.mp4", 960)

        frames = list(ds)

        self.assertEqual(len(frames), 3)
        self.assertEqual(detect.cv2.resize.call_count, 3)

    def test_iter_releases_cap_on_normal_eof(self):
        cap, released = self._setup_mock_cv2(n_frames=2)
        ds = detect._VideoFrameDataset("fake.mp4", 960)

        list(ds)  # 耗尽迭代器

        self.assertTrue(released[0])
        cap.release.assert_called_once()

    def test_iter_releases_cap_on_exception(self):
        """迭代中 resize 抛异常时 finally 仍 release cap。"""

        def _raise(*a, **kw):
            raise RuntimeError("resize boom")

        cap, released = self._setup_mock_cv2(n_frames=5, resize_side_effect=_raise)
        ds = detect._VideoFrameDataset("fake.mp4", 960)

        with self.assertRaises(RuntimeError):
            list(ds)

        self.assertTrue(released[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
