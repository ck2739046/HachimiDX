import unittest
from types import SimpleNamespace
from unittest.mock import patch

from install.script import choose_backend as module
from install.script import main as install_main
from install.script.choose_backend import BackendChoice
from install.script.detect_nvidia import NvidiaGpuInfo
from install.script.detect_pytorch_cuda import (
    PytorchCudaGpuDetection,
    pytorch_cuda_config,
)
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
                pytorch_cuda_backend="PyTorch CUDA",
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
                exit_option="6 exit",
                invalid_backend_choice="invalid backend",
                backend_not_available="not available",
                backend_selection_failed="selection failed",
                trt_not_available="trt unavailable",
                trt_selection_failed="trt selection failed",
                trt_gpu_menu_title="trt gpu menu",
                trt_gpu_option="{index} {gpu_name} {vram} {compute_cap} {driver} {config}",
                trt_gpu_prompt="trt gpu",
                pytorch_cuda_not_available="pytorch cuda unavailable",
                pytorch_cuda_selection_failed="pytorch cuda selection failed",
                pytorch_cuda_gpu_menu_title="pytorch cuda gpu menu",
                pytorch_cuda_gpu_option="{index} {gpu_name} {vram} {compute_cap} {driver} {config}",
                pytorch_cuda_gpu_prompt="pytorch cuda gpu",
                invalid_gpu_choice="invalid gpu",
            )
        )
        self.nvidia_gpus = [
            NvidiaGpuInfo(
                gpu_name="GPU 0",
                compute_capability=(7, 5),
                driver_version=(572, 61),
                vram_mib=8192,
            )
        ]

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

    def _pytorch_config(self, cuda="cu128"):
        if cuda == "cu128":
            return pytorch_cuda_config(
                compute_capability=(7, 5),
                win_driver_ver=(572, 61),
                torch_ver="2.10.0",
                torch_cuda_ver="cu128",
                torchvision_ver="0.25.0",
            )
        return pytorch_cuda_config(
            compute_capability=(5, 0),
            win_driver_ver=(452, 39),
            torch_ver="2.3.1",
            torch_cuda_ver="cu118",
            torchvision_ver="0.18.1",
        )

    def _pytorch_gpu(self, name, available, config=None):
        return PytorchCudaGpuDetection(
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

    @patch.object(module, "get_nvidia_gpu_info")
    @patch.object(module, "detect_trt_availability")
    @patch.object(module, "detect_pytorch_cuda_availability")
    @patch.object(module, "detect_dml_availability")
    @patch.object(module, "detect_ncnn_availability")
    def test_all_backends_are_detected_and_cpu_is_fallback(
        self, ncnn, dml, pytorch_cuda, trt, get_nvidia
    ):
        get_nvidia.return_value = ok(self.nvidia_gpus)
        trt.return_value = err("trt failed")
        pytorch_cuda.return_value = err("pytorch cuda failed")
        dml.return_value = err("dml failed")
        ncnn.return_value = err("ncnn failed")

        with patch("builtins.input", return_value=""):
            result = module.choose_backend(self.text)

        self.assertTrue(result.is_ok)
        self.assertEqual(result.value.backend, "cpu")
        get_nvidia.assert_called_once_with()
        trt.assert_called_once_with(self.text, self.nvidia_gpus)
        pytorch_cuda.assert_called_once_with(self.text, self.nvidia_gpus)
        dml.assert_called_once_with(self.text)
        ncnn.assert_called_once_with(self.text)

    @patch.object(module, "get_nvidia_gpu_info")
    @patch.object(module, "detect_trt_availability")
    @patch.object(module, "detect_pytorch_cuda_availability")
    @patch.object(module, "detect_dml_availability")
    @patch.object(module, "detect_ncnn_availability")
    def test_trt_same_config_does_not_ask_gpu(
        self, ncnn, dml, pytorch_cuda, trt, get_nvidia
    ):
        get_nvidia.return_value = ok(self.nvidia_gpus)
        config = self._config("10.15.1.29")
        trt.return_value = self._result([
            self._gpu("GPU 0", True, config),
            self._gpu("GPU 1", True, self._config("10.15.1.29")),
        ])
        pytorch_cuda.return_value = self._result([])
        dml.return_value = self._result([])
        ncnn.return_value = self._result([])

        with patch("builtins.input", side_effect=["1"]) as input_mock:
            result = module.choose_backend(self.text)

        self.assertTrue(result.is_ok)
        self.assertEqual(result.value.backend, "trt")
        self.assertEqual(result.value.nvidia_gpu_config.tensorRT_ver, config.tensorRT_ver)
        self.assertEqual(input_mock.call_count, 1)

    @patch.object(module, "get_nvidia_gpu_info")
    @patch.object(module, "detect_trt_availability")
    @patch.object(module, "detect_pytorch_cuda_availability")
    @patch.object(module, "detect_dml_availability")
    @patch.object(module, "detect_ncnn_availability")
    def test_trt_different_config_asks_gpu(
        self, ncnn, dml, pytorch_cuda, trt, get_nvidia
    ):
        get_nvidia.return_value = ok(self.nvidia_gpus)
        trt.return_value = self._result([
            self._gpu("GPU 0", True, self._config("10.15.1.29")),
            self._gpu("GPU 1", True, self._config("8.6.1")),
        ])
        pytorch_cuda.return_value = self._result([])
        dml.return_value = self._result([])
        ncnn.return_value = self._result([])

        with patch("builtins.input", side_effect=["1", "1"]) as input_mock:
            result = module.choose_backend(self.text)

        self.assertTrue(result.is_ok)
        self.assertEqual(result.value.backend, "trt")
        self.assertEqual(result.value.nvidia_gpu_config.tensorRT_ver, "8.6.1")
        self.assertEqual(input_mock.call_count, 2)

    @patch.object(module, "get_nvidia_gpu_info")
    @patch.object(module, "detect_trt_availability")
    @patch.object(module, "detect_pytorch_cuda_availability")
    @patch.object(module, "detect_dml_availability")
    @patch.object(module, "detect_ncnn_availability")
    def test_pytorch_cuda_is_next_default_after_trt(
        self, ncnn, dml, pytorch_cuda, trt, get_nvidia
    ):
        get_nvidia.return_value = ok(self.nvidia_gpus)
        trt.return_value = self._result([self._gpu("GPU 0", False)])
        config = self._pytorch_config()
        pytorch_cuda.return_value = self._result([
            self._pytorch_gpu("GPU 0", True, config)
        ])
        dml.return_value = self._result([])
        ncnn.return_value = self._result([])

        with patch("builtins.input", return_value=""):
            result = module.choose_backend(self.text)

        self.assertTrue(result.is_ok)
        self.assertEqual(result.value.backend, "pytorch_cuda")
        self.assertEqual(result.value.pytorch_cuda_config, config)

    @patch.object(module, "get_nvidia_gpu_info")
    @patch.object(module, "detect_trt_availability")
    @patch.object(module, "detect_pytorch_cuda_availability")
    @patch.object(module, "detect_dml_availability")
    @patch.object(module, "detect_ncnn_availability")
    def test_trt_has_priority_over_pytorch_cuda(
        self, ncnn, dml, pytorch_cuda, trt, get_nvidia
    ):
        get_nvidia.return_value = ok(self.nvidia_gpus)
        trt_config = self._config("10.15.1.29")
        trt.return_value = self._result([
            self._gpu("GPU 0", True, trt_config)
        ])
        pytorch_cuda.return_value = self._result([
            self._pytorch_gpu("GPU 0", True, self._pytorch_config())
        ])
        dml.return_value = self._result([])
        ncnn.return_value = self._result([])

        with patch("builtins.input", return_value=""):
            result = module.choose_backend(self.text)

        self.assertTrue(result.is_ok)
        self.assertEqual(result.value.backend, "trt")
        self.assertEqual(result.value.nvidia_gpu_config, trt_config)

    @patch.object(module, "get_nvidia_gpu_info")
    @patch.object(module, "detect_trt_availability")
    @patch.object(module, "detect_pytorch_cuda_availability")
    @patch.object(module, "detect_dml_availability")
    @patch.object(module, "detect_ncnn_availability")
    def test_pytorch_cuda_same_config_does_not_ask_gpu(
        self, ncnn, dml, pytorch_cuda, trt, get_nvidia
    ):
        get_nvidia.return_value = ok(self.nvidia_gpus)
        config = self._pytorch_config()
        trt.return_value = self._result([])
        pytorch_cuda.return_value = self._result([
            self._pytorch_gpu("GPU 0", True, config),
            self._pytorch_gpu("GPU 1", True, self._pytorch_config()),
        ])
        dml.return_value = self._result([])
        ncnn.return_value = self._result([])

        with patch("builtins.input", side_effect=["2"]) as input_mock:
            result = module.choose_backend(self.text)

        self.assertTrue(result.is_ok)
        self.assertEqual(result.value.backend, "pytorch_cuda")
        self.assertEqual(result.value.pytorch_cuda_config, config)
        self.assertEqual(input_mock.call_count, 1)

    @patch.object(module, "get_nvidia_gpu_info")
    @patch.object(module, "detect_trt_availability")
    @patch.object(module, "detect_pytorch_cuda_availability")
    @patch.object(module, "detect_dml_availability")
    @patch.object(module, "detect_ncnn_availability")
    def test_pytorch_cuda_different_config_asks_gpu(
        self, ncnn, dml, pytorch_cuda, trt, get_nvidia
    ):
        get_nvidia.return_value = ok(self.nvidia_gpus)
        trt.return_value = self._result([])
        pytorch_cuda.return_value = self._result([
            self._pytorch_gpu("GPU 0", True, self._pytorch_config("cu128")),
            self._pytorch_gpu("GPU 1", True, self._pytorch_config("cu118")),
        ])
        dml.return_value = self._result([])
        ncnn.return_value = self._result([])

        with patch("builtins.input", side_effect=["2", "1"]) as input_mock:
            result = module.choose_backend(self.text)

        self.assertTrue(result.is_ok)
        self.assertEqual(result.value.backend, "pytorch_cuda")
        self.assertEqual(result.value.pytorch_cuda_config.torch_cuda_ver, "cu118")
        self.assertEqual(input_mock.call_count, 2)


class TestPytorchCudaInstallBranch(unittest.TestCase):

    def _config(self):
        return pytorch_cuda_config(
            compute_capability=(7, 5),
            win_driver_ver=(572, 61),
            torch_ver="2.10.0",
            torch_cuda_ver="cu128",
            torchvision_ver="0.25.0",
        )

    @patch.object(install_main, "ask_use_pypi_mirror")
    @patch.object(install_main, "choose_backend")
    @patch.object(install_main, "install_pytorch")
    @patch.object(install_main, "install_ultralytics_onnx")
    @patch.object(install_main, "install_tensorrt")
    @patch.object(install_main, "install_ncnn")
    @patch.object(install_main, "modify_ultralytics_for_dml")
    @patch.object(install_main, "general_pip_install")
    def test_pytorch_cuda_uses_plain_onnx_and_skips_other_accelerators(
        self,
        pip_install,
        modify_dml,
        install_ncnn,
        install_trt,
        install_onnx,
        install_pytorch,
        choose_backend,
        ask_mirror,
    ):
        config = self._config()
        choose_backend.return_value = ok(
            BackendChoice(
                backend="pytorch_cuda",
                pytorch_cuda_config=config,
            )
        )
        install_pytorch.return_value = True
        install_onnx.return_value = True
        pip_install.return_value = True

        result = install_main.install()

        self.assertTrue(result.is_ok)
        install_pytorch.assert_called_once_with(None, config)
        install_onnx.assert_called_once_with("pytorch_cuda", None)
        install_trt.assert_not_called()
        install_ncnn.assert_not_called()
        modify_dml.assert_not_called()

    @patch.object(install_main, "general_pip_install")
    def test_pytorch_cuda_install_command_uses_cuda_index(self, pip_install):
        pip_install.return_value = True

        result = install_main.install_pytorch(None, self._config())

        self.assertTrue(result)
        command = pip_install.call_args.args[1]
        self.assertIn("torch==2.10.0", command)
        self.assertIn("torchvision==0.25.0", command)
        self.assertIn("cu128", command[-2])

    @patch.object(install_main, "general_pip_install")
    def test_pytorch_cuda_uses_cpu_onnxruntime_package(self, pip_install):
        pip_install.return_value = True

        result = install_main.install_ultralytics_onnx("pytorch_cuda", None)

        self.assertTrue(result)
        onnx_command = pip_install.call_args_list[0].args[1]
        self.assertIn("onnxruntime==1.20.1", onnx_command)
        self.assertNotIn("onnxruntime-gpu==1.24.4", onnx_command)
        self.assertNotIn("onnxruntime-directml==1.24.4", onnx_command)


if __name__ == "__main__":
    unittest.main(verbosity=2)
