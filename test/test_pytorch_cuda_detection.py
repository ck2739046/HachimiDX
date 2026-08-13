import unittest
from types import SimpleNamespace

from install.script.detect_nvidia import NvidiaGpuInfo
from install.script.detect_pytorch_cuda import detect_pytorch_cuda_availability
from install.script.detect_trt import detect_trt_availability


class TestPytorchCudaDetection(unittest.TestCase):

    def setUp(self):
        self.text = SimpleNamespace(
            detect_pytorch_cuda=SimpleNamespace(
                low_compute_cap="{compute_cap} below {min_compute_cap}",
                invalid_driver_version="{driver_version} below {min_driver_version}",
            ),
            detect_trt=SimpleNamespace(
                insufficient_memory="{real_vram} below {min_vram}",
                low_compute_cap="{compute_cap} below {min_compute_cap}",
                invalid_driver_version="{driver_version} below {min_driver_version}",
            ),
        )

    def _detect(self, compute_capability, driver_version, vram_mib=1024):
        result = detect_pytorch_cuda_availability(
            self.text,
            [
                NvidiaGpuInfo(
                    gpu_name="GPU",
                    compute_capability=compute_capability,
                    driver_version=driver_version,
                    vram_mib=vram_mib,
                )
            ],
        )
        self.assertTrue(result.is_ok)
        return result.value[0]

    def test_sm75_uses_cu128(self):
        gpu = self._detect((7, 5), (572, 61))
        self.assertTrue(gpu.is_available)
        self.assertEqual(gpu.config.torch_ver, "2.10.0")
        self.assertEqual(gpu.config.torch_cuda_ver, "cu128")
        self.assertEqual(gpu.config.torchvision_ver, "0.25.0")

    def test_sm50_uses_cu118(self):
        gpu = self._detect((5, 0), (452, 39))
        self.assertTrue(gpu.is_available)
        self.assertEqual(gpu.config.torch_ver, "2.3.1")
        self.assertEqual(gpu.config.torch_cuda_ver, "cu118")
        self.assertEqual(gpu.config.torchvision_ver, "0.18.1")

    def test_low_vram_does_not_make_backend_unavailable(self):
        gpu = self._detect((7, 5), (572, 61), vram_mib=512)
        self.assertTrue(gpu.is_available)

    def test_low_vram_disables_trt_but_not_pytorch_cuda(self):
        gpu_info = NvidiaGpuInfo(
            gpu_name="GPU",
            compute_capability=(7, 5),
            driver_version=(572, 61),
            vram_mib=512,
        )

        trt_result = detect_trt_availability(self.text, [gpu_info])
        pytorch_result = detect_pytorch_cuda_availability(self.text, [gpu_info])

        self.assertFalse(trt_result.value[0].is_available)
        self.assertTrue(pytorch_result.value[0].is_available)

    def test_sm_below_50_is_unavailable(self):
        gpu = self._detect((4, 9), (600, 0))
        self.assertFalse(gpu.is_available)
        self.assertIsNone(gpu.config)

    def test_sm75_driver_does_not_fall_back_to_cu118(self):
        gpu = self._detect((7, 5), (572, 60))
        self.assertFalse(gpu.is_available)
        self.assertIsNone(gpu.config)
        self.assertIn("572.61", gpu.reason)

    def test_sm50_driver_below_minimum_is_unavailable(self):
        gpu = self._detect((5, 0), (452, 38))
        self.assertFalse(gpu.is_available)
        self.assertIn("452.39", gpu.reason)


if __name__ == "__main__":
    unittest.main(verbosity=2)
