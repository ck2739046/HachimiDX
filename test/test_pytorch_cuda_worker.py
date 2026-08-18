import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

_WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
if str(_WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(_WORKSPACE_ROOT))

from src.core.schemas.op_result import ok
from src.services.path_manage import PathManage
from src.services.workers import auto_rechart_worker


class TestAutoRechartWorker(unittest.TestCase):

    def setUp(self):
        self.original_dml_device = os.environ.get("HACHIMIDX_DML_DEVICE_ID")

    def tearDown(self):
        if self.original_dml_device is None:
            os.environ.pop("HACHIMIDX_DML_DEVICE_ID", None)
        else:
            os.environ["HACHIMIDX_DML_DEVICE_ID"] = self.original_dml_device

    def _run_worker(self, backend, inference_device, *, half=False, dml_index=None):
        model_paths = PathManage.get_model_paths(backend).value
        args = [
            "--is_standardize_enabled", "false",
            "--is_detect_enabled", "true",
            "--is_analyze_enabled", "false",
            "--std_video_path", "video.mp4",
            "--model_backend", backend,
            "--inference_device", inference_device,
            "--half", "true" if half else "false",
            "--predict_batch_size_detect_obb", "2",
            "--predict_batch_size_classify", "16",
            "--predict_batch_size_touch_hold", "16",
            "--skip_detect", "false",
            "--skip_cls", "false",
            "--skip_export_tracked_video", "true",
        ]
        if dml_index is not None:
            args.extend(["--directml_device_index", str(dml_index)])

        with (
            patch.object(
                auto_rechart_worker.PathManage,
                "get_model_paths",
                return_value=ok(model_paths),
            ) as get_model_paths,
            patch.object(auto_rechart_worker, "detect_main", return_value=ok()) as detect_main,
        ):
            result = auto_rechart_worker.main(args)
        return result, detect_main, get_model_paths

    def test_worker_passes_prevalidated_runtime_device(self):
        result, detect_main, get_model_paths = self._run_worker(
            "ONNX CPU",
            "cuda:9",
            half=False,
        )

        self.assertTrue(result)
        self.assertEqual(detect_main.call_args.kwargs["inference_device"], "cuda:9")
        self.assertEqual(detect_main.call_args.kwargs["detect_model_path"].suffix, ".onnx")
        get_model_paths.assert_called_once_with("ONNX CPU")

    def test_worker_accepts_model_half_snapshot(self):
        result, detect_main, _ = self._run_worker(
            "ONNX Cuda",
            "cuda:2",
            half=True,
        )

        self.assertTrue(result)
        self.assertEqual(detect_main.call_args.kwargs["inference_device"], "cuda:2")

    def test_worker_applies_prevalidated_directml_environment(self):
        os.environ["HACHIMIDX_DML_DEVICE_ID"] = "9"

        result, detect_main, get_model_paths = self._run_worker(
            "ONNX DML",
            "cpu",
            half=False,
            dml_index=3,
        )

        self.assertTrue(result)
        self.assertEqual(os.environ["HACHIMIDX_DML_DEVICE_ID"], "3")
        self.assertEqual(detect_main.call_args.kwargs["inference_device"], "cpu")
        get_model_paths.assert_called_once_with("ONNX DML")

    def test_worker_clears_stale_directml_environment(self):
        os.environ["HACHIMIDX_DML_DEVICE_ID"] = "4"

        result, _, _ = self._run_worker("TensorRT", "cuda:1", half=True)

        self.assertTrue(result)
        self.assertNotIn("HACHIMIDX_DML_DEVICE_ID", os.environ)


if __name__ == "__main__":
    unittest.main(verbosity=2)
