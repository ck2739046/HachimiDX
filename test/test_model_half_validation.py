import unittest
from pathlib import Path
from unittest.mock import patch

from src.core.schemas.op_result import err, ok
from src.core.schemas.settings_model import SettingsModel
from src.services.model_inference_manage import ModelInferenceManage
from src.services.path_manage import ModelPaths, PathManage
from src.services.settings_manage import SettingsManage


class TestModelHalfValidation(unittest.TestCase):

    def setUp(self):
        self.original_config = SettingsManage._config
        self.paths = ModelPaths(*[Path(f"model_{index}.onnx") for index in range(5)])

    def tearDown(self):
        SettingsManage._config = self.original_config

    def _set_config(self, model_half, device_half):
        SettingsManage._config = SettingsModel(
            model_backend="ONNX Cuda",
            inference_device="cuda:0",
            inference_device_half=device_half,
            model_half=model_half,
        )

    def test_null_model_half_requires_conversion(self):
        self._set_config({"onnx": None, "ncnn": None, "trt": None}, True)
        with patch.object(PathManage, "resolve_model_paths", return_value=ok(self.paths)):
            result = ModelInferenceManage.inspect(
                "ONNX Cuda",
                SettingsManage._config.model_half,
                True,
            )
        self.assertTrue(result.is_ok)
        self.assertEqual(result.value.half_evaluation.status, "not_converted")
        self.assertFalse(result.value.is_usable)

    def test_fp32_model_on_half_device_is_valid_with_upgrade_tip(self):
        self._set_config({"onnx": False, "ncnn": None, "trt": None}, True)
        with patch.object(PathManage, "resolve_model_paths", return_value=ok(self.paths)):
            result = ModelInferenceManage.inspect(
                "ONNX Cuda",
                SettingsManage._config.model_half,
                True,
            )
        self.assertTrue(result.is_ok)
        self.assertFalse(result.value.model_half)
        self.assertTrue(result.value.half_evaluation.can_upgrade_to_half)

    def test_fp16_model_on_non_half_device_is_rejected(self):
        self._set_config({"onnx": True, "ncnn": None, "trt": None}, False)
        with patch.object(PathManage, "resolve_model_paths", return_value=ok(self.paths)):
            result = ModelInferenceManage.inspect(
                "ONNX CPU",
                SettingsManage._config.model_half,
                False,
            )
        self.assertTrue(result.is_ok)
        self.assertEqual(result.value.half_evaluation.status, "incompatible")
        self.assertFalse(result.value.is_usable)

    def test_missing_artifacts_clear_only_current_model_group(self):
        self._set_config({"onnx": True, "ncnn": False, "trt": True}, True)

        def fake_set(key, value):
            setattr(SettingsManage._config, key, value)
            return ok()

        with (
            patch.object(PathManage, "resolve_model_paths", return_value=err("missing")),
        ):
            result = ModelInferenceManage.inspect(
                "ONNX DML",
                SettingsManage._config.model_half,
                True,
            )

        self.assertTrue(result.is_ok)
        self.assertFalse(result.value.artifacts_available)
        self.assertEqual(result.value.half_evaluation.status, "not_converted")
        self.assertEqual(SettingsManage._config.model_half.onnx, True)

        with patch.object(SettingsManage, "set", side_effect=fake_set) as set_value:
            model_half = dict(SettingsManage._config.model_half)
            model_half["onnx"] = None
            clear_result = SettingsManage.set("model_half", model_half)
        self.assertTrue(clear_result.is_ok)
        set_value.assert_called_once_with(
            "model_half",
            {"onnx": None, "ncnn": False, "trt": True},
        )

    def test_explicit_device_half_uses_task_snapshot(self):
        self._set_config({"onnx": True, "ncnn": None, "trt": None}, False)
        with patch.object(PathManage, "resolve_model_paths", return_value=ok(self.paths)):
            result = ModelInferenceManage.inspect(
                "ONNX Cuda",
                SettingsManage._config.model_half,
                True,
            )
        self.assertTrue(result.is_ok)
        self.assertTrue(result.value.device_half)

    def test_settings_manage_writes_model_half_with_normal_set(self):
        self._set_config({"onnx": None, "ncnn": None, "trt": None}, False)
        with patch.object(SettingsManage, "set", return_value=ok()) as set_value:
            model_half = dict(SettingsManage._config.model_half)
            model_half["trt"] = True
            result = SettingsManage.set("model_half", model_half)
        self.assertTrue(result.is_ok)
        set_value.assert_called_once_with(
            "model_half",
            {"onnx": None, "ncnn": None, "trt": True},
        )

    def test_inspect_reads_optional_values_from_settings(self):
        self._set_config({"onnx": False, "ncnn": None, "trt": None}, True)
        with patch.object(PathManage, "resolve_model_paths", return_value=ok(self.paths)):
            result = ModelInferenceManage.inspect("ONNX Cuda")
        self.assertTrue(result.is_ok)
        self.assertEqual(result.value.model_half, False)
        self.assertTrue(result.value.device_half)
        self.assertEqual(result.value.half_evaluation.status, "upgrade_available")


if __name__ == "__main__":
    unittest.main(verbosity=2)