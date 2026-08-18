import unittest

from pydantic import ValidationError

from src.core.schemas.settings_config import SettingsConfig_Definitions as S_Defs
from src.core.schemas.settings_model import SettingsModel
from src.services.model_inference_manage import ModelInferenceManage


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
                self.assertEqual(ModelInferenceManage.parse_inference_device(device_id), parsed)

    def test_unsupported_device_id_formats(self):
        for device_id in (None, "", "cuda", "dml", "vulkan", "cpu:0", "cuda:", "dml:-1", "vulkan:x"):
            with self.subTest(device_id=device_id):
                self.assertIsNone(ModelInferenceManage.parse_inference_device(device_id))

    def test_device_id_is_normalized(self):
        self.assertEqual(ModelInferenceManage.normalize_inference_device_id(" cuda:01 "), "cuda:1")
        self.assertEqual(ModelInferenceManage.normalize_inference_device_id("dml:003"), "dml:3")
        self.assertEqual(ModelInferenceManage.normalize_inference_device_id("vulkan:002"), "vulkan:2")

    def test_backend_rules_and_fallbacks(self):
        cases = {
            ("ONNX CPU", "cpu"): "cpu",
            ("ONNX CPU", "cuda:1"): "cpu",
            ("ONNX Cuda", "cuda:1"): "cuda:1",
            ("ONNX Cuda", "cpu"): "cuda:0",
            ("TensorRT", "cuda:1"): "cuda:1",
            ("TensorRT", "vulkan:1"): "cuda:0",
            ("NCNN", "vulkan:1"): "vulkan:1",
            ("NCNN", "cuda:1"): "vulkan:0",
            ("ONNX DML", "dml:1"): "dml:1",
            ("ONNX DML", "cuda:1"): "dml:0",
        }
        for (backend, device_id), expected in cases.items():
            with self.subTest(backend=backend, device_id=device_id):
                self.assertEqual(
                    ModelInferenceManage.normalize_inference_device_for_backend(backend, device_id),
                    expected,
                )

    def test_settings_model_rejects_legacy_cuda_without_index(self):
        with self.assertRaises(ValidationError):
            SettingsModel(model_backend="TensorRT", inference_device="cuda")

    def test_settings_model_rejects_removed_backend_names(self):
        with self.assertRaises(ValidationError):
            SettingsModel(model_backend="PyTorch CPU", inference_device="cpu")
        with self.assertRaises(ValidationError):
            SettingsModel(model_backend="DirectML", inference_device="dml:0")

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
            SettingsModel(model_backend="ONNX DML", inference_device="dml:01").inference_device,
            "dml:1",
        )
        self.assertEqual(
            SettingsModel(model_backend="ONNX CPU", inference_device="cuda:1").inference_device,
            "cpu",
        )
        self.assertEqual(
            SettingsModel(model_backend="ONNX Cuda", inference_device="cuda:01").inference_device,
            "cuda:1",
        )

    def test_directml_runtime_device_mapping(self):
        self.assertEqual(ModelInferenceManage.get_directml_device_index("dml:2"), 2)
        self.assertIsNone(ModelInferenceManage.get_directml_device_index("cuda:2"))
        self.assertEqual(ModelInferenceManage.get_runtime_inference_device("ONNX DML", "dml:2"), "cpu")
        self.assertEqual(ModelInferenceManage.get_runtime_inference_device("TensorRT", "cuda:2"), "cuda:2")
        self.assertEqual(ModelInferenceManage.get_runtime_inference_device("ONNX CPU", "cpu"), "cpu")
        self.assertEqual(ModelInferenceManage.get_runtime_inference_device("ONNX Cuda", "cuda:2"), "cuda:2")

    def test_backend_ids_and_model_groups(self):
        expected = {
            "ONNX CPU": ("onnx_cpu", "onnx"),
            "ONNX DML": ("onnx_dml", "onnx"),
            "ONNX Cuda": ("onnx_cuda", "onnx"),
            "NCNN": ("ncnn", "ncnn"),
            "TensorRT": ("tensorrt", "trt"),
        }
        for backend, (backend_id, group) in expected.items():
            with self.subTest(backend=backend):
                self.assertEqual(ModelInferenceManage.get_model_backend_id(backend), backend_id)
                self.assertEqual(ModelInferenceManage.get_model_group(backend), group)

    def test_model_half_defaults_and_validation(self):
        settings = SettingsModel()
        self.assertFalse(settings.inference_device_half)
        self.assertEqual(
            settings.model_half.model_dump(mode="python"),
            {"onnx": None, "ncnn": None, "trt": None},
        )

        valid = SettingsModel(model_half={"onnx": True, "ncnn": False, "trt": None})
        self.assertEqual(
            valid.model_half.model_dump(mode="python"),
            {"onnx": True, "ncnn": False, "trt": None},
        )

        for invalid in (
            None,
            {"onnx": True, "ncnn": False},
            {"onnx": True, "ncnn": False, "trt": None, "extra": None},
            {"onnx": 1, "ncnn": False, "trt": None},
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValidationError):
                    SettingsModel(model_half=invalid)

    def test_model_half_compatibility_matrix(self):
        self.assertFalse(ModelInferenceManage.is_model_half_compatible(None, False))
        self.assertFalse(ModelInferenceManage.is_model_half_compatible(None, True))
        self.assertTrue(ModelInferenceManage.is_model_half_compatible(False, False))
        self.assertTrue(ModelInferenceManage.is_model_half_compatible(False, True))
        self.assertFalse(ModelInferenceManage.is_model_half_compatible(True, False))
        self.assertTrue(ModelInferenceManage.is_model_half_compatible(True, True))
        self.assertTrue(ModelInferenceManage.can_upgrade_model_to_half(False, True))
        self.assertFalse(ModelInferenceManage.can_upgrade_model_to_half(True, True))


if __name__ == "__main__":
    unittest.main(verbosity=2)
