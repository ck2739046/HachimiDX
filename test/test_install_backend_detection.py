import unittest
from types import SimpleNamespace
from unittest.mock import patch

from install.script import choose_backend as module
from install.script.detect_trt import NvidiaGpuDetection, nvidia_config
from install.script.op_result import err, ok


class TestChooseBackend(unittest.TestCase):

    def setUp(self):
        self.text = SimpleNamespace(
            choose_backend=SimpleNamespace(
                detect_start="detect",
                summary_title="summary",
                available="available",
                unavailable="unavailable",
                unavailable_with_reason="unavailable: {reason}",
                backend_status="{backend}: {status}",
                backend_reason="reason: {reason}",
                gpu_status="gpu {index}: {gpu_name}{details} {status}",
                gpu_unavailable="unavailable: {reason}",
                nvidia_gpu_details=" vram {vram} sm {compute_cap} driver {driver} config {config}",
                cpu_backend="CPU",
                trt_backend="TRT",
                dml_backend="DML",
                ncnn_backend="NCNN",
                no_available_gpu="no available gpu",
                no_gpu_detected="no gpu",
                unknown_detection_error="unknown error",
                detection_exception="{backend}: {error}",
                backend_menu_title="backend menu",
                backend_option="{index} {backend} {status}",
                backend_recommendation="{backend} recommended",
                backend_prompt="-> ",
                exit_option="5 exit",
                invalid_backend_choice="invalid backend",
                backend_not_available="not available",
                backend_selection_failed="selection failed",
                trt_not_available="trt unavailable",
                trt_selection_failed="trt selection failed",
                trt_gpu_menu_title="trt gpu menu",
                trt_gpu_option="{index} {gpu_name} {vram} {compute_cap} {driver} {config}",
                trt_gpu_prompt="trt gpu",
                invalid_gpu_choice="invalid gpu",
            )
        )

    def _config(self, trt_version):
        return nvidia_config(
            compute_capability=(7, 5),
            win_driver_ver=(572, 61),
            torch_ver="2.10.0",
            torch_cuda_ver="cu128",
            torchvision_ver="0.25.0",
            onnxruntime_gpu_ver="1.24.4",
            tensorRT_ver=trt_version,
            is_trt_legacy=False,
            numpy_ver="2.4.3",
            opencv_ver="5.0.0.93",
        )

    def _gpu(self, name, available, config=None):
        return NvidiaGpuDetection(
            gpu_name=name,
            compute_capability=(7, 5),
            driver_version=(572, 61),
            vram_mib=8192,
            is_available=available,
            reason=None if available else "invalid",
            config=config,
        )

    def _result(self, value):
        return ok(value)

    @patch.object(module, "detect_trt_availability")
    @patch.object(module, "detect_dml_availability")
    @patch.object(module, "detect_ncnn_availability")
    def test_all_backends_are_detected_and_cpu_is_fallback(self, ncnn, dml, trt):
        trt.return_value = err("trt failed")
        dml.return_value = err("dml failed")
        ncnn.return_value = err("ncnn failed")

        with patch("builtins.input", return_value=""):
            result = module.choose_backend(self.text)

        self.assertTrue(result.is_ok)
        self.assertEqual(result.value.backend, "cpu")
        trt.assert_called_once_with(self.text)
        dml.assert_called_once_with(self.text)
        ncnn.assert_called_once_with(self.text)

    @patch.object(module, "detect_trt_availability")
    @patch.object(module, "detect_dml_availability")
    @patch.object(module, "detect_ncnn_availability")
    def test_trt_same_config_does_not_ask_gpu(self, ncnn, dml, trt):
        config = self._config("10.15.1.29")
        trt.return_value = self._result([
            self._gpu("GPU 0", True, config),
            self._gpu("GPU 1", True, self._config("10.15.1.29")),
        ])
        dml.return_value = self._result([])
        ncnn.return_value = self._result([])

        with patch("builtins.input", side_effect=["1"]) as input_mock:
            result = module.choose_backend(self.text)

        self.assertTrue(result.is_ok)
        self.assertEqual(result.value.backend, "trt")
        self.assertEqual(result.value.nvidia_gpu_config.tensorRT_ver, config.tensorRT_ver)
        self.assertEqual(input_mock.call_count, 1)

    @patch.object(module, "detect_trt_availability")
    @patch.object(module, "detect_dml_availability")
    @patch.object(module, "detect_ncnn_availability")
    def test_trt_different_config_asks_gpu(self, ncnn, dml, trt):
        trt.return_value = self._result([
            self._gpu("GPU 0", True, self._config("10.15.1.29")),
            self._gpu("GPU 1", True, self._config("8.6.1")),
        ])
        dml.return_value = self._result([])
        ncnn.return_value = self._result([])

        with patch("builtins.input", side_effect=["1", "1"]) as input_mock:
            result = module.choose_backend(self.text)

        self.assertTrue(result.is_ok)
        self.assertEqual(result.value.backend, "trt")
        self.assertEqual(result.value.nvidia_gpu_config.tensorRT_ver, "8.6.1")
        self.assertEqual(input_mock.call_count, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
