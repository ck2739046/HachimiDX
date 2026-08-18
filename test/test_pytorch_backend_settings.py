import sys
import unittest
from pathlib import Path
_WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
if str(_WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(_WORKSPACE_ROOT))

from src.services.path_manage import PathManage


class TestOnnxBackendPaths(unittest.TestCase):

    def test_onnx_backends_share_model_paths(self):
        cpu_paths = PathManage.get_model_paths("ONNX CPU")
        cuda_paths = PathManage.get_model_paths("ONNX Cuda")
        dml_paths = PathManage.get_model_paths("ONNX DML")

        self.assertTrue(cpu_paths.is_ok)
        self.assertTrue(cuda_paths.is_ok)
        self.assertTrue(dml_paths.is_ok)
        self.assertEqual(cpu_paths.value, cuda_paths.value)
        self.assertEqual(cpu_paths.value, dml_paths.value)
        self.assertEqual(cpu_paths.value.detect.name, "detect_ONNX.onnx")

    def test_removed_pytorch_backends_are_rejected(self):
        self.assertFalse(PathManage.get_model_paths("PyTorch CPU").is_ok)
        self.assertFalse(PathManage.get_model_paths("PyTorch CUDA").is_ok)

    def test_source_models_are_separate_from_runtime_paths(self):
        source_paths = PathManage.get_source_model_paths()
        runtime_paths = PathManage.get_model_paths("ONNX CPU").value
        self.assertEqual(source_paths.detect.suffix, ".pt")
        self.assertEqual(runtime_paths.detect.suffix, ".onnx")
        self.assertNotEqual(source_paths, runtime_paths)


if __name__ == "__main__":
    unittest.main(verbosity=2)
