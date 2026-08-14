import builtins
import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch


_WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
_original_argv = sys.argv[:]
sys.argv = ["check_device_worker.py", str(_WORKSPACE_ROOT), "pytorch_cpu"]
try:
    from src.services.workers import check_device_worker as worker
finally:
    sys.argv = _original_argv


class _FakeCuda:
    def __init__(self, available=True, names=()):
        self._available = available
        self._names = list(names)

    def is_available(self):
        return self._available

    def device_count(self):
        return len(self._names)

    def get_device_name(self, index):
        value = self._names[index]
        if isinstance(value, BaseException):
            raise value
        return value


class TestCheckDeviceWorker(unittest.TestCase):

    def _torch(self, *, available=True, cuda_version="12.8", names=()):
        return SimpleNamespace(
            __version__="test",
            cuda=_FakeCuda(available=available, names=names),
            version=SimpleNamespace(cuda=cuda_version),
        )

    def test_pytorch_cpu_returns_only_cpu(self):
        with (
            patch.object(worker, "_check_torch_installed", return_value=(True, object())),
            patch.object(worker, "_get_windows_cpu_name", return_value="Test CPU"),
        ):
            self.assertEqual(worker._check_cpu(), [("cpu", "Test CPU")])

    def test_pytorch_cuda_does_not_require_tensorrt(self):
        torch = self._torch(names=("GPU 0", "GPU 1"))
        with patch.object(worker, "_check_torch_installed", return_value=(True, torch)):
            devices = worker._check_cuda()
        self.assertEqual(devices, [("cuda:0", "GPU 0"), ("cuda:1", "GPU 1")])

    def test_cuda_failure_paths(self):
        cases = [
            self._torch(available=False, names=("GPU",)),
            self._torch(cuda_version=None, names=("GPU",)),
            self._torch(names=()),
        ]
        for torch in cases:
            with self.subTest(torch=torch):
                with patch.object(worker, "_check_torch_installed", return_value=(True, torch)):
                    self.assertIsNone(worker._check_cuda())

    def test_cuda_skips_device_name_failure(self):
        torch = self._torch(names=(RuntimeError("bad gpu"), "GPU 1"))
        with patch.object(worker, "_check_torch_installed", return_value=(True, torch)):
            devices = worker._check_cuda()
        self.assertEqual(devices, [("cuda:1", "GPU 1")])

    def test_tensorrt_requires_package(self):
        devices = [("cuda:0", "GPU 0")]
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "tensorrt":
                raise ImportError("missing")
            return real_import(name, *args, **kwargs)

        with (
            patch.object(worker, "_check_cuda", return_value=devices),
            patch("builtins.__import__", side_effect=fake_import),
        ):
            self.assertIsNone(worker._check_tensorrt())

        tensorrt = ModuleType("tensorrt")
        tensorrt.__version__ = "test"
        with (
            patch.object(worker, "_check_cuda", return_value=devices),
            patch.dict(sys.modules, {"tensorrt": tensorrt}),
        ):
            self.assertEqual(worker._check_tensorrt(), devices)

    def test_runtime_routes_and_output_protocol(self):
        cases = {
            "pytorch_cpu": ("_check_cpu", [("cpu", "CPU")]),
            "pytorch_cuda": ("_check_cuda", [("cuda:0", "GPU")]),
            "tensorrt": ("_check_tensorrt", [("cuda:0", "GPU")]),
        }
        for runtime, (method_name, devices) in cases.items():
            with self.subTest(runtime=runtime):
                output = io.StringIO()
                with patch.object(worker, method_name, return_value=devices), redirect_stdout(output):
                    self.assertTrue(worker.main(runtime))
                self.assertIn(
                    f"INFERENCE_DEVICE_RESULT:{devices[0][0]}|{devices[0][1]}",
                    output.getvalue(),
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
