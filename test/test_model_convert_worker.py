import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from src.services.workers import model_convert_worker


class _FakeYOLO:
    export_calls = []
    output_path = None
    create_metadata = True
    fail_after_write = False

    def __init__(self, model_path, task):
        self.model_path = model_path
        self.task = task

    def export(self, **kwargs):
        self.__class__.export_calls.append(kwargs)
        output_path = self.__class__.output_path
        if kwargs["format"] == "ncnn":
            output_path.mkdir(parents=True)
            (output_path / model_convert_worker.PathManage.NCNN_PARAM_FILE_NAME).write_bytes(b"param")
            (output_path / model_convert_worker.PathManage.NCNN_BIN_FILE_NAME).write_bytes(b"bin")
            if self.__class__.create_metadata:
                (output_path / model_convert_worker.PathManage.NCNN_METADATA_FILE_NAME).write_text(
                    "task: detect", encoding="utf-8"
                )
        else:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"onnx")
        if self.__class__.fail_after_write:
            raise RuntimeError("export failed")
        return str(output_path)


class TestModelConvertWorker(unittest.TestCase):

    def setUp(self):
        _FakeYOLO.export_calls = []
        _FakeYOLO.create_metadata = True
        _FakeYOLO.fail_after_write = False

    def test_ncnn_export_uses_fp16_single_sample_graph(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            pt_path = root / "detect.pt"
            pt_path.write_bytes(b"pt")
            ncnn_path = root / "detect_ncnn_model"
            temp_onnx_path = root / "detect.onnx"
            _FakeYOLO.output_path = ncnn_path

            model_spec = [("detect", "detect", pt_path, ncnn_path, root / "detect_DirectML.onnx", temp_onnx_path)]
            with (
                patch.object(model_convert_worker, "models", model_spec),
                patch.object(model_convert_worker, "YOLO", _FakeYOLO),
                patch.object(model_convert_worker, "get_imgsz", return_value=960),
            ):
                result = model_convert_worker._convert_to_ncnn(2, 16, 8)

            self.assertTrue(result)
            self.assertEqual(
                _FakeYOLO.export_calls,
                [{"format": "ncnn", "imgsz": 960, "quantize": 16, "batch": 1, "device": "cpu"}],
            )
            self.assertTrue((ncnn_path / model_convert_worker.PathManage.NCNN_METADATA_FILE_NAME).is_file())

    def test_incomplete_ncnn_export_is_removed(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            pt_path = root / "detect.pt"
            pt_path.write_bytes(b"pt")
            ncnn_path = root / "detect_ncnn_model"
            _FakeYOLO.output_path = ncnn_path
            _FakeYOLO.create_metadata = False

            model_spec = [("detect", "detect", pt_path, ncnn_path, root / "detect_DirectML.onnx", root / "detect.onnx")]
            with (
                patch.object(model_convert_worker, "models", model_spec),
                patch.object(model_convert_worker, "YOLO", _FakeYOLO),
                patch.object(model_convert_worker, "get_imgsz", return_value=960),
            ):
                result = model_convert_worker._convert_to_ncnn(2, 16, 8)

            self.assertFalse(result)
            self.assertFalse(ncnn_path.exists())

    def test_directml_export_uses_named_onnx_artifact(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            pt_path = root / "detect.pt"
            pt_path.write_bytes(b"pt")
            directml_path = root / "detect_DirectML.onnx"
            temp_onnx_path = root / "detect.onnx"
            _FakeYOLO.output_path = temp_onnx_path

            model_spec = [("detect", "detect", pt_path, root / "detect_ncnn_model", directml_path, temp_onnx_path)]
            with (
                patch.object(model_convert_worker, "models", model_spec),
                patch.object(model_convert_worker, "YOLO", _FakeYOLO),
                patch.object(model_convert_worker, "get_imgsz", return_value=960),
            ):
                result = model_convert_worker._convert_to_onnx(2, 16, 8)

            self.assertTrue(result)
            self.assertEqual(
                _FakeYOLO.export_calls,
                [{
                    "format": "onnx",
                    "opset": 17,
                    "imgsz": 960,
                    "dynamic": True,
                    "simplify": True,
                    "batch": 2,
                    "device": "cpu",
                }],
            )
            self.assertEqual(directml_path.read_bytes(), b"onnx")
            self.assertFalse(temp_onnx_path.exists())

    def test_failed_directml_export_preserves_existing_artifact(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            pt_path = root / "detect.pt"
            pt_path.write_bytes(b"pt")
            directml_path = root / "detect_DirectML.onnx"
            directml_path.write_bytes(b"existing")
            temp_onnx_path = root / "detect.onnx"
            _FakeYOLO.output_path = temp_onnx_path
            _FakeYOLO.fail_after_write = True

            model_spec = [("detect", "detect", pt_path, root / "detect_ncnn_model", directml_path, temp_onnx_path)]
            with (
                patch.object(model_convert_worker, "models", model_spec),
                patch.object(model_convert_worker, "YOLO", _FakeYOLO),
                patch.object(model_convert_worker, "get_imgsz", return_value=960),
            ):
                result = model_convert_worker._convert_to_onnx(2, 16, 8)

            self.assertFalse(result)
            self.assertEqual(directml_path.read_bytes(), b"existing")
            self.assertFalse(temp_onnx_path.exists())

    def test_batch_size_selection(self):
        self.assertEqual(model_convert_worker._get_batch_size("detect", 2, 16, 8), 2)
        self.assertEqual(model_convert_worker._get_batch_size("cls_ex", 2, 16, 8), 16)
        self.assertEqual(model_convert_worker._get_batch_size("touch_hold", 2, 16, 8), 8)

    def test_onnx_model_paths_are_shared(self):
        result = model_convert_worker.PathManage.get_model_paths("ONNX DML")
        self.assertTrue(result.is_ok)
        self.assertEqual(
            [path.name for path in (
                result.value.detect,
                result.value.obb,
                result.value.cls_break,
                result.value.cls_ex,
                result.value.touch_hold,
            )],
            [
                "detect_ONNX.onnx",
                "obb_ONNX.onnx",
                "cls-break_ONNX.onnx",
                "cls-ex_ONNX.onnx",
                "detect-touch-hold_ONNX.onnx",
            ],
        )
        self.assertEqual(
            result.value,
            model_convert_worker.PathManage.get_model_paths("ONNX CPU").value,
        )
        self.assertEqual(
            result.value,
            model_convert_worker.PathManage.get_model_paths("ONNX Cuda").value,
        )

    def test_removed_backends_are_rejected(self):
        self.assertFalse(model_convert_worker.main("unsupported", 2, 16, 8))


if __name__ == "__main__":
    unittest.main(verbosity=2)
