import unittest

from pydantic import ValidationError

from src.core.schemas.settings_config import SettingsConfig_Definitions as S_Defs
from src.core.schemas.settings_model import SettingsModel


class TestInferenceDeviceConfig(unittest.TestCase):

    def test_supported_device_id_formats(self):
        expected = {
            "cpu": ("cpu", None),
            "cuda:0": ("cuda", 0),
            "cuda:12": ("cuda", 12),
            "dml:0": ("dml", 0),
            "dml:3": ("dml", 3),
            "vulkan:0": ("vulkan", 0),
            "vulkan:7": ("vulkan", 7),
        }
        for device_id, parsed in expected.items():
            with self.subTest(device_id=device_id):
                self.assertEqual(S_Defs.parse_inference_device(device_id), parsed)

    def test_unsupported_device_id_formats(self):
        for device_id in (None, "", "cuda", "dml", "vulkan", "cpu:0", "cuda:", "dml:-1", "vulkan:x"):
            with self.subTest(device_id=device_id):
                self.assertIsNone(S_Defs.parse_inference_device(device_id))

    def test_device_id_is_normalized(self):
        self.assertEqual(S_Defs.normalize_inference_device_id(" cuda:01 "), "cuda:1")
        self.assertEqual(S_Defs.normalize_inference_device_id("dml:003"), "dml:3")
        self.assertEqual(S_Defs.normalize_inference_device_id("vulkan:002"), "vulkan:2")

    def test_backend_rules_and_fallbacks(self):
        cases = {
            ("PyTorch CPU", "cpu"): "cpu",
            ("PyTorch CPU", "cuda:1"): "cpu",
            ("PyTorch CUDA", "cuda:1"): "cuda:1",
            ("PyTorch CUDA", "cpu"): "cuda:0",
            ("TensorRT", "cuda:1"): "cuda:1",
            ("TensorRT", "vulkan:1"): "cuda:0",
            ("NCNN", "vulkan:1"): "vulkan:1",
            ("NCNN", "cuda:1"): "vulkan:0",
            ("DirectML", "dml:1"): "dml:1",
            ("DirectML", "cuda:1"): "dml:0",
        }
        for (backend, device_id), expected in cases.items():
            with self.subTest(backend=backend, device_id=device_id):
                self.assertEqual(
                    S_Defs.normalize_inference_device_for_backend(backend, device_id),
                    expected,
                )

    def test_settings_model_rejects_legacy_cuda_without_index(self):
        with self.assertRaises(ValidationError):
            SettingsModel(model_backend="TensorRT", inference_device="cuda")

    def test_settings_model_rejects_old_pytorch_backend_name(self):
        with self.assertRaises(ValidationError):
            SettingsModel(model_backend="PyTorch", inference_device="cpu")

    def test_settings_model_uses_central_backend_rules(self):
        self.assertEqual(
            SettingsModel(model_backend="TensorRT", inference_device="cuda:01").inference_device,
            "cuda:1",
        )
        self.assertEqual(
            SettingsModel(model_backend="NCNN", inference_device="cuda:1").inference_device,
            "vulkan:0",
        )
        self.assertEqual(
            SettingsModel(model_backend="DirectML", inference_device="dml:01").inference_device,
            "dml:1",
        )
        self.assertEqual(
            SettingsModel(model_backend="PyTorch CPU", inference_device="cuda:1").inference_device,
            "cpu",
        )
        self.assertEqual(
            SettingsModel(model_backend="PyTorch CUDA", inference_device="cuda:01").inference_device,
            "cuda:1",
        )

    def test_directml_runtime_device_mapping(self):
        self.assertEqual(S_Defs.get_directml_device_index("dml:2"), 2)
        self.assertIsNone(S_Defs.get_directml_device_index("cuda:2"))
        self.assertEqual(S_Defs.get_runtime_inference_device("DirectML", "dml:2"), "cpu")
        self.assertEqual(S_Defs.get_runtime_inference_device("TensorRT", "cuda:2"), "cuda:2")
        self.assertEqual(S_Defs.get_runtime_inference_device("PyTorch CPU", "cpu"), "cpu")
        self.assertEqual(S_Defs.get_runtime_inference_device("PyTorch CUDA", "cuda:2"), "cuda:2")


if __name__ == "__main__":
    unittest.main(verbosity=2)
