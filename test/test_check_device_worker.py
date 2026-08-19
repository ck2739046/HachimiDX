import builtins
import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch


_WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
if str(_WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(_WORKSPACE_ROOT))

from src.services.path_manage import PathManage
from src.services.workers.check_device import (
    check_dml,
    check_ncnn,
    check_pytorch_cuda,
    check_trt,
    common,
)
from src.services.workers.check_device import main as main_module


class _FakeCuda:
    def __init__(self, available=True, names=(), capabilities=()):
        self._available = available
        self._names = list(names)
        self._capabilities = list(capabilities or [(7, 0)] * len(self._names))

    def is_available(self):
        return self._available

    def device_count(self):
        return len(self._names)

    def get_device_name(self, index):
        value = self._names[index]
        if isinstance(value, BaseException):
            raise value
        return value

    def get_device_capability(self, index):
        value = self._capabilities[index]
        if isinstance(value, BaseException):
            raise value
        return value

    def get_arch_list(self):
        return ["sm_70", "sm_120"]

    def device(self, _index):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class TestEntryAndPath(unittest.TestCase):

    def test_worker_path_points_to_package_main(self):
        self.assertEqual(PathManage.CHECK_DEVICE_WORKER_PATH.name, "main.py")
        self.assertTrue(PathManage.CHECK_DEVICE_WORKER_PATH.is_file())
        self.assertFalse((PathManage.WORKERS_DIR / "check_device_worker.py").exists())

    def test_runtime_routes_and_output_protocol(self):
        cases = {
            "onnx_cpu": ("check_onnx_cpu", [common.DeviceResult("cpu", "CPU", False)]),
            "onnx_cuda": ("check_onnx_cuda", [common.DeviceResult("cuda:0", "GPU", True)]),
            "onnx_dml": ("check_onnx_dml", [common.DeviceResult("dml:0", "GPU", True)]),
            "tensorrt": ("check_tensorrt", [common.DeviceResult("cuda:0", "GPU", True)]),
        }
        for runtime, (attr_name, devices) in cases.items():
            with self.subTest(runtime=runtime):
                output = io.StringIO()
                with patch.object(main_module, attr_name, return_value=devices), redirect_stdout(output):
                    self.assertTrue(main_module.main(runtime))
                half = "true" if devices[0].half else "false"
                self.assertIn(
                    f"INFERENCE_DEVICE_RESULT:{devices[0].device_id}|{devices[0].name}|half={half}",
                    output.getvalue(),
                )

    def test_unknown_runtime_fails(self):
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertFalse(main_module.main("unknown"))
        self.assertIn("Unknown runtime: unknown", output.getvalue())


class TestPyTorchCuda(unittest.TestCase):

    def _torch(self, *, available=True, cuda_version="12.8", names=(), capabilities=()):
        return SimpleNamespace(
            __version__="test",
            cuda=_FakeCuda(available=available, names=names, capabilities=capabilities),
            version=SimpleNamespace(cuda=cuda_version),
        )

    def test_half_requires_sm70_or_above(self):
        torch = self._torch(
            names=("GPU 0", "GPU 1", "GPU 2"),
            capabilities=((6, 9), (7, 0), (12, 0)),
        )
        with patch.object(check_pytorch_cuda, "check_torch_installed", return_value=(True, torch)):
            devices = check_pytorch_cuda.check()
        self.assertEqual(devices, [
            common.DeviceResult("cuda:0", "GPU 0", False),
            common.DeviceResult("cuda:1", "GPU 1", True),
            common.DeviceResult("cuda:2", "GPU 2", True),
        ])

    def test_failure_paths(self):
        cases = [
            self._torch(available=False, names=("GPU",)),
            self._torch(cuda_version=None, names=("GPU",)),
            self._torch(names=()),
        ]
        for torch in cases:
            with self.subTest(torch=torch):
                with patch.object(check_pytorch_cuda, "check_torch_installed", return_value=(True, torch)):
                    self.assertIsNone(check_pytorch_cuda.check())

    def test_skips_device_name_failure(self):
        torch = self._torch(names=(RuntimeError("bad gpu"), "GPU 1"))
        with patch.object(check_pytorch_cuda, "check_torch_installed", return_value=(True, torch)):
            devices = check_pytorch_cuda.check()
        self.assertEqual(devices, [common.DeviceResult("cuda:1", "GPU 1", True)])

    def test_capability_failure_keeps_device_with_half_false(self):
        torch = self._torch(
            names=("GPU 0", "GPU 1"),
            capabilities=(RuntimeError("bad capability"), (7, 1)),
        )
        with patch.object(check_pytorch_cuda, "check_torch_installed", return_value=(True, torch)):
            devices = check_pytorch_cuda.check()
        self.assertEqual(devices, [
            common.DeviceResult("cuda:0", "GPU 0", False),
            common.DeviceResult("cuda:1", "GPU 1", True),
        ])

    def test_print_device_flag_controls_device_list_output(self):
        torch = self._torch(names=("GPU 0",))
        with patch.object(check_pytorch_cuda, "check_torch_installed", return_value=(True, torch)):
            output = io.StringIO()
            with redirect_stdout(output):
                devices = check_pytorch_cuda.check(print_device=False)
            self.assertEqual(devices, [common.DeviceResult("cuda:0", "GPU 0", True)])
            self.assertNotIn("CUDA devices:", output.getvalue())

            output = io.StringIO()
            with redirect_stdout(output):
                check_pytorch_cuda.check()
            self.assertIn(
                "CUDA devices:\n  - cuda:0: GPU 0, half=True\n",
                output.getvalue(),
            )


class TestTensorRt(unittest.TestCase):

    def _torch(self):
        return SimpleNamespace(
            __version__="test",
            cuda=_FakeCuda(names=("GPU",)),
            version=SimpleNamespace(cuda="12.8"),
        )

    def test_requires_package(self):
        devices = [common.DeviceResult("cuda:0", "GPU 0", True)]
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "tensorrt":
                raise ImportError("missing")
            return real_import(name, *args, **kwargs)

        with (
            patch.object(check_trt, "check_cuda", return_value=devices),
            patch("builtins.__import__", side_effect=fake_import),
        ):
            self.assertIsNone(check_trt.check())

    def test_combines_cuda_half_with_fast_fp16_capability(self):
        devices = [common.DeviceResult("cuda:0", "GPU 0", True)]
        tensorrt = ModuleType("tensorrt")
        tensorrt.__version__ = "test"
        torch = ModuleType("torch")
        output = io.StringIO()
        with (
            patch.object(check_trt, "check_cuda", return_value=devices),
            patch.object(check_trt, "_get_half_support", return_value=True),
            patch.dict(sys.modules, {"tensorrt": tensorrt, "torch": torch}),
            redirect_stdout(output),
        ):
            self.assertEqual(check_trt.check(), devices)
        self.assertEqual(output.getvalue().count("CUDA devices:"), 1)
        self.assertIn("  - cuda:0: GPU 0, half=True", output.getvalue())

    def test_combines_to_false_when_trt_fp16_unavailable(self):
        devices = [common.DeviceResult("cuda:0", "GPU 0", True)]
        tensorrt = ModuleType("tensorrt")
        tensorrt.__version__ = "test"
        torch = ModuleType("torch")
        with (
            patch.object(check_trt, "check_cuda", return_value=devices),
            patch.object(check_trt, "_get_half_support", return_value=False),
            patch.dict(sys.modules, {"tensorrt": tensorrt, "torch": torch}),
        ):
            self.assertEqual(
                check_trt.check(),
                [common.DeviceResult("cuda:0", "GPU 0", False)],
            )

    def _fake_trt(self, **builder_attrs):
        class FakeBuilder:
            def __init__(self, _logger):
                pass

            def create_network(self, *_args):
                raise AssertionError("network creation must not run")

        for key, value in builder_attrs.items():
            setattr(FakeBuilder, key, value)
        return SimpleNamespace(
            Logger=type("Logger", (), {"ERROR": 1, "__init__": lambda self, _level: None}),
            Builder=FakeBuilder,
        )

    def test_reads_only_platform_has_fast_fp16(self):
        tensorrt = self._fake_trt(platform_has_fast_fp16=True)
        self.assertTrue(check_trt._get_half_support(tensorrt, self._torch(), 0))

        tensorrt = self._fake_trt(platform_has_fast_fp16=False)
        self.assertFalse(check_trt._get_half_support(tensorrt, self._torch(), 0))

    def test_platform_has_fp16_alias_is_not_used(self):
        tensorrt = self._fake_trt(platform_has_fp16=True)
        self.assertFalse(check_trt._get_half_support(tensorrt, self._torch(), 0))


class TestNcnn(unittest.TestCase):

    def _fake_ncnn(self, gpu_infos):
        class FakeNet:
            opt = SimpleNamespace(use_vulkan_compute=False)

            def set_vulkan_device(self, _index):
                return None

        return SimpleNamespace(
            __version__="test",
            create_gpu_instance=lambda: 0,
            destroy_gpu_instance=lambda: None,
            get_gpu_count=lambda: len(gpu_infos),
            get_gpu_info=lambda index: gpu_infos[index],
            Net=FakeNet,
        )

    def _gpu_info(self, *, storage, arithmetic):
        attrs = {"device_name": lambda: "GPU"}
        if storage is not None:
            attrs["support_fp16_storage"] = storage
        if arithmetic is not None:
            attrs["support_fp16_arithmetic"] = arithmetic
        return SimpleNamespace(**attrs)

    def _run(self, gpu_infos):
        ncnn = self._fake_ncnn(gpu_infos)
        with (
            patch.object(check_ncnn, "check_torch_installed", return_value=(True, object())),
            patch.dict(sys.modules, {"ncnn": ncnn}),
        ):
            return check_ncnn.check()

    def test_half_requires_storage_and_arithmetic_apis(self):
        devices = self._run([
            self._gpu_info(storage=lambda: True, arithmetic=lambda: True),
            self._gpu_info(storage=lambda: True, arithmetic=lambda: False),
        ])
        self.assertEqual(devices, [
            common.DeviceResult("vulkan:0", "GPU", True),
            common.DeviceResult("vulkan:1", "GPU", False),
        ])

    def test_missing_api_returns_false(self):
        devices = self._run([
            self._gpu_info(storage=lambda: True, arithmetic=None),
            self._gpu_info(storage=None, arithmetic=None),
        ])
        self.assertEqual(devices, [
            common.DeviceResult("vulkan:0", "GPU", False),
            common.DeviceResult("vulkan:1", "GPU", False),
        ])

    def test_api_error_returns_false(self):
        def _boom():
            raise RuntimeError("bad driver")

        devices = self._run([self._gpu_info(storage=_boom, arithmetic=lambda: True)])
        self.assertEqual(devices, [common.DeviceResult("vulkan:0", "GPU", False)])


class TestDirectMl(unittest.TestCase):

    def test_uses_capability_query_without_session(self):
        devices = [
            SimpleNamespace(
                ep_name="DmlExecutionProvider",
                device=SimpleNamespace(metadata={"DxgiAdapterNumber": "0", "Description": "GPU 0"}),
            ),
            SimpleNamespace(
                ep_name="DmlExecutionProvider",
                device=SimpleNamespace(metadata={"DxgiAdapterNumber": "1", "Description": "GPU 1"}),
            ),
        ]
        ort = ModuleType("onnxruntime")
        ort.__version__ = "test"
        ort.get_available_providers = lambda: ["DmlExecutionProvider"]
        ort.get_ep_devices = lambda: devices
        with (
            patch.object(check_dml, "check_torch_installed", return_value=(True, object())),
            patch.object(check_dml, "query_directml_fp16_support", side_effect=(True, False)),
            patch.dict(sys.modules, {"onnxruntime": ort}),
        ):
            results = check_dml.check()
        self.assertEqual(results, [
            common.DeviceResult("dml:0", "GPU 0", True),
            common.DeviceResult("dml:1", "GPU 1", False),
        ])
        self.assertFalse(hasattr(ort, "InferenceSession"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
