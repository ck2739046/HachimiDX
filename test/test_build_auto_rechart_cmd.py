import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src.core import build_auto_rechart_cmd
from src.core.schemas.op_result import err, ok
from src.core.schemas.settings_config import SettingsConfig_Definitions as S_Defs
from src.services.model_inference_manage import ModelInferenceManage
from src.services.settings_manage import SettingsManage


class TestBuildAutoRechartInferenceArgs(unittest.TestCase):

    @staticmethod
    def _settings(backend, device, *, device_half, model_half, batches=(2, 16, 16)):
        return {
            S_Defs.model_backend.key: backend,
            S_Defs.inference_device.key: device,
            S_Defs.inference_device_half.key: device_half,
            S_Defs.model_half.key: model_half,
            S_Defs.predict_batch_size_detect_obb.key: batches[0],
            S_Defs.predict_batch_size_classify.key: batches[1],
            S_Defs.predict_batch_size_touch_hold.key: batches[2],
        }

    @staticmethod
    def _validation(model_half, *, usable=True, status="compatible"):
        return SimpleNamespace(
            is_usable=usable,
            model_half=model_half,
            half_evaluation=SimpleNamespace(status=status),
        )

    def test_builds_complete_prevalidated_snapshot_for_all_backends(self):
        cases = (
            ("ONNX CPU", "cpu", False, False, "cpu", None),
            ("NCNN", "vulkan:02", True, True, "vulkan:2", None),
            ("ONNX DML", "dml:03", True, False, "cpu", 3),
            ("ONNX Cuda", "cuda:04", True, True, "cuda:4", None),
            ("TensorRT", "cuda:01", False, False, "cuda:1", None),
        )

        for backend, device, device_half, model_half, runtime_device, dml_index in cases:
            with self.subTest(backend=backend):
                model_half_settings = {
                    "onnx": model_half if backend.startswith("ONNX") else None,
                    "ncnn": model_half if backend == "NCNN" else None,
                    "trt": model_half if backend == "TensorRT" else None,
                }
                settings = self._settings(
                    backend,
                    device,
                    device_half=device_half,
                    model_half=model_half_settings,
                )
                with (
                    patch.object(SettingsManage, "get_many", return_value=ok(settings)) as get_many,
                    patch.object(
                        ModelInferenceManage,
                        "inspect",
                        return_value=ok(self._validation(model_half)),
                    ) as inspect,
                ):
                    result = build_auto_rechart_cmd._build_inference_args()

                self.assertTrue(result.is_ok)
                args = dict(zip(result.value[::2], result.value[1::2]))
                self.assertEqual(args["--model_backend"], backend)
                self.assertEqual(args["--inference_device"], runtime_device)
                self.assertEqual(args["--half"], "true" if model_half else "false")
                self.assertEqual(args["--predict_batch_size_detect_obb"], "2")
                self.assertEqual(args["--predict_batch_size_classify"], "16")
                self.assertEqual(args["--predict_batch_size_touch_hold"], "16")
                self.assertNotIn("--model_path", args)
                if dml_index is None:
                    self.assertNotIn("--directml_device_index", args)
                else:
                    self.assertEqual(args["--directml_device_index"], str(dml_index))
                get_many.assert_called_once()
                inspect.assert_called_once_with(
                    backend,
                    model_half=model_half_settings,
                    device_half=device_half,
                )

    def test_rejects_device_mismatched_with_backend_before_model_inspection(self):
        settings = self._settings(
            "ONNX CPU",
            "cuda:0",
            device_half=False,
            model_half={"onnx": False, "ncnn": None, "trt": None},
        )
        with (
            patch.object(SettingsManage, "get_many", return_value=ok(settings)),
            patch.object(ModelInferenceManage, "inspect") as inspect,
        ):
            result = build_auto_rechart_cmd._build_inference_args()

        self.assertFalse(result.is_ok)
        self.assertIn("Invalid inference_device", result.error_msg)
        inspect.assert_not_called()

    def test_rejects_unusable_or_missing_model_artifacts(self):
        settings = self._settings(
            "TensorRT",
            "cuda:0",
            device_half=True,
            model_half={"onnx": None, "ncnn": None, "trt": None},
        )
        with (
            patch.object(SettingsManage, "get_many", return_value=ok(settings)),
            patch.object(
                ModelInferenceManage,
                "inspect",
                return_value=ok(
                    self._validation(None, usable=False, status="not_converted")
                ),
            ),
        ):
            result = build_auto_rechart_cmd._build_inference_args()

        self.assertFalse(result.is_ok)
        self.assertIn("not_converted", result.error_msg)

    def test_rejects_invalid_batch_size(self):
        settings = self._settings(
            "ONNX Cuda",
            "cuda:0",
            device_half=True,
            model_half={"onnx": False, "ncnn": None, "trt": None},
            batches=(0, 16, 16),
        )
        with (
            patch.object(SettingsManage, "get_many", return_value=ok(settings)),
            patch.object(
                ModelInferenceManage,
                "inspect",
                return_value=ok(self._validation(False)),
            ),
        ):
            result = build_auto_rechart_cmd._build_inference_args()

        self.assertFalse(result.is_ok)
        self.assertIn("positive integer", result.error_msg)

    def test_propagates_settings_snapshot_failure(self):
        with patch.object(SettingsManage, "get_many", return_value=err("settings unavailable")):
            result = build_auto_rechart_cmd._build_inference_args()

        self.assertFalse(result.is_ok)
        self.assertEqual(result.error_msg, "Failed to read inference settings")


if __name__ == "__main__":
    unittest.main(verbosity=2)
