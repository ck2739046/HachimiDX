"""detect.py worker 失败诊断逻辑的隔离单测。

覆盖本次新增的三块核心逻辑（不依赖真实 YOLO / 视频 / multiprocessing spawn）：
  1. _format_exit_line         — exitcode/win_code 格式化（正/负/None 三类）
  2. _collect_one + __error__   — Python 异常哨兵的状态机转换（done/alive/died/errors）
  3. _inference_worker 异常转发 — predict 抛错时经 results_queue 转发 __error__ 并 raise

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

# --- import detect 前注入 mock，绕过顶层 import（cv2/numpy/ultralytics 仅 import 未即时调用） ---
for _mod in ("ultralytics", "cv2", "numpy"):
    sys.modules.setdefault(_mod, MagicMock())

from src.core.auto_rechart.detect import detect  # noqa: E402


class _FakeYOLO:
    """predict 直接抛错，模拟 YOLO 推理失败（含 CUDA/TRT native 之外的 Python 异常）"""

    def __init__(self, *args, **kwargs):
        pass

    def predict(self, **kwargs):
        raise RuntimeError("simulated predict failure")


def _proc_like(exitcode):
    """构造仅有 exitcode 属性的假 Process 对象"""
    return SimpleNamespace(exitcode=exitcode)


class TestFormatExitLine(unittest.TestCase):
    """_format_exit_line：三类 exitcode 的格式化"""

    def test_negative_renders_win_code_hex(self):
        # Windows ACCESS_VIOLATION：NT 状态码 0xC0000005，mp 进程 exitcode 取其负值
        line = detect._format_exit_line(_proc_like(-0xC0000005), "decode")
        self.assertIn("[decode] worker died", line)
        self.assertIn("exitcode=-3221225477", line)   # -0xC0000005
        self.assertIn("win_code=0xC0000005", line)

    def test_positive_no_win_code(self):
        # Python sys.exit(1)：正值，win_code 应为 N/A
        line = detect._format_exit_line(_proc_like(1), "detect")
        self.assertIn("exitcode=1", line)
        self.assertIn("win_code=N/A", line)

    def test_none_exitcode(self):
        # 进程刚启动，exitcode 尚未生成
        line = detect._format_exit_line(_proc_like(None), "obb")
        self.assertIn("exitcode=None", line)
        self.assertIn("win_code=N/A", line)


class TestCollectOneErrorSentinel(unittest.TestCase):
    """_collect_one：__error__ 哨兵 → done/alive/died/errors 状态机转换"""

    def test_error_marks_done_and_died(self):
        state = detect._PipelineState()
        tb = "Traceback (most recent call last):\nRuntimeError: boom\n"
        item = ("__error__", "obb", tb, 42)

        detect._collect_one(state, item)

        self.assertIn("obb", state.done_workers)      # 视同完成，防 _check_worker_exits 重复判死
        self.assertEqual(state.workers_alive, 1)       # 从 2 递减到 1
        self.assertTrue(state.worker_died)             # 触发 abort
        self.assertEqual(state.worker_errors, [("obb", tb, 42)])

    def test_done_sentinel_unchanged_behavior(self):
        state = detect._PipelineState()
        detect._collect_one(state, ("__done__", "detect"))
        self.assertIn("detect", state.done_workers)
        self.assertEqual(state.workers_alive, 1)
        self.assertFalse(state.worker_died)
        self.assertEqual(state.worker_errors, [])

    def test_normal_result_appended(self):
        state = detect._PipelineState()
        detect._collect_one(state, ("some_note", "obb"))
        self.assertEqual(state.all_raw_results, [("some_note", "obb")])
        self.assertEqual(state.workers_alive, 2)       # 不变


class TestInferenceWorkerErrorForwarding(unittest.TestCase):
    """_inference_worker：predict 抛错 → 转发 __error__ + raise（保留 exitcode 语义）"""

    def setUp(self):
        self._orig_yolo = detect.YOLO
        detect.YOLO = _FakeYOLO  # 主进程内 monkeypatch 生效（非 spawn）

    def tearDown(self):
        detect.YOLO = self._orig_yolo

    def _run_worker(self, frame_count, batch_detect):
        frame_queue = queue.Queue()
        for _ in range(frame_count):
            frame_queue.put(object())  # 内容不重要，predict 会先抛
        frame_queue.put(detect._DECODE_EOF)

        results_queue = queue.Queue()
        progress_val = multiprocessing.Value("i", 0)

        raised = None
        try:
            detect._inference_worker(
                "fake.pt", "detect", frame_queue, batch_detect, None,
                results_queue, progress_val, 1.0,
            )
        except BaseException as e:
            raised = e
        return raised, results_queue

    def test_predict_failure_forwards_error_and_reraises(self):
        raised, results_queue = self._run_worker(frame_count=2, batch_detect=2)

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

    def test_flush_tail_batch_also_covered(self):
        # 帧数 < batch_detect 且以 EOF 结束 → flush 残余仍走 _run_batch → predict 抛 → __error__
        # 验证 try/except 覆盖了 flush 路径（而非仅满 batch 路径）
        raised, results_queue = self._run_worker(frame_count=1, batch_detect=2)
        self.assertIsNotNone(raised)
        self.assertEqual(results_queue.qsize(), 1)
        self.assertEqual(results_queue.get_nowait()[0], "__error__")


if __name__ == "__main__":
    unittest.main(verbosity=2)
