import sys
import unittest
from pathlib import Path
from unittest.mock import patch

_WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
if str(_WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(_WORKSPACE_ROOT))

from src.app.pages.settings_page import PYTORCH_BACKENDS, SettingsPage
from src.services.path_manage import PathManage


class TestPytorchBackendSettingsPage(unittest.TestCase):

    def test_pytorch_backend_constant(self):
        self.assertEqual(PYTORCH_BACKENDS, {"PyTorch CPU", "PyTorch CUDA"})

    def test_device_results_are_filtered_by_pytorch_backend(self):
        output = "\n".join([
            "INFERENCE_DEVICE_RESULT:cpu|CPU",
            "INFERENCE_DEVICE_RESULT:cuda:0|GPU 0",
            "INFERENCE_DEVICE_RESULT:dml:0|DML GPU",
        ])

        cpu_items = SettingsPage._parse_inference_device_results(output, "PyTorch CPU")
        cuda_items = SettingsPage._parse_inference_device_results(output, "PyTorch CUDA")

        self.assertEqual(cpu_items, [("cpu", "CPU")])
        self.assertEqual(cuda_items, [("cuda:0", "GPU 0")])

    def test_pytorch_backends_resolve_same_model_paths(self):
        cpu_paths = PathManage.get_model_paths("PyTorch CPU")
        cuda_paths = PathManage.get_model_paths("PyTorch CUDA")

        self.assertTrue(cpu_paths.is_ok)
        self.assertTrue(cuda_paths.is_ok)
        self.assertEqual(cpu_paths.value, cuda_paths.value)


if __name__ == "__main__":
    unittest.main(verbosity=2)
