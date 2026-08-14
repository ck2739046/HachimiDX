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


class TestPytorchCudaWorker(unittest.TestCase):

    def test_pytorch_backends_share_pt_model_paths(self):
        cpu_result = PathManage.get_model_paths("PyTorch CPU")
        cuda_result = PathManage.get_model_paths("PyTorch CUDA")
        old_result = PathManage.get_model_paths("PyTorch")

        self.assertTrue(cpu_result.is_ok)
        self.assertTrue(cuda_result.is_ok)
        self.assertEqual(cpu_result.value, cuda_result.value)
        self.assertEqual(cpu_result.value.detect.suffix, ".pt")
        self.assertFalse(old_result.is_ok)

    def _run_worker(self, backend, inference_device):
        model_paths = PathManage.get_model_paths(backend).value
        args = [
            "--is_standardize_enabled", "false",
            "--is_detect_enabled", "true",
            "--is_analyze_enabled", "false",
            "--std_video_path", "video.mp4",
            "--model_backend", backend,
            "--inference_device", inference_device,
            "--predict_batch_size_detect_obb", "2",
            "--predict_batch_size_classify", "16",
            "--predict_batch_size_touch_hold", "16",
            "--skip_detect", "false",
            "--skip_cls", "false",
            "--skip_export_tracked_video", "true",
        ]
        with (
            patch.object(PathManage, "resolve_model_paths", return_value=ok(model_paths)),
            patch.object(auto_rechart_worker, "detect_main", return_value=ok()) as detect_main,
        ):
            result = auto_rechart_worker.main(args)
        return result, detect_main

    def test_pytorch_cpu_passes_cpu_to_pt_inference(self):
        result, detect_main = self._run_worker("PyTorch CPU", "cpu")

        self.assertTrue(result)
        self.assertEqual(detect_main.call_args.kwargs["inference_device"], "cpu")
        self.assertEqual(detect_main.call_args.kwargs["detect_model_path"].suffix, ".pt")

    def test_pytorch_cuda_passes_cuda_to_pt_inference(self):
        result, detect_main = self._run_worker("PyTorch CUDA", "cuda:2")

        self.assertTrue(result)
        self.assertEqual(detect_main.call_args.kwargs["inference_device"], "cuda:2")
        self.assertEqual(detect_main.call_args.kwargs["detect_model_path"].suffix, ".pt")
        self.assertNotIn("HACHIMIDX_DML_DEVICE_ID", os.environ)

    def test_worker_rejects_mismatched_pytorch_devices(self):
        cpu_result, cpu_detect = self._run_worker("PyTorch CPU", "cuda:0")
        cuda_result, cuda_detect = self._run_worker("PyTorch CUDA", "cpu")

        self.assertFalse(cpu_result)
        self.assertFalse(cuda_result)
        cpu_detect.assert_not_called()
        cuda_detect.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
