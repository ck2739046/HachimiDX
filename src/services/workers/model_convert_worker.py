import sys
from pathlib import Path
from typing import NamedTuple
import io
import shutil

# 解决 Windows 控制台 Unicode 编码问题
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', write_through=True)
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace', write_through=True)



if len(sys.argv) <= 1:
    print("No root args provided. Exiting.")
    sys.exit(1)

# 第一个参数是项目根目录
# 确保能正确使用间接导入
root = str(Path(sys.argv[1]).resolve())
if root not in sys.path:
    sys.path.insert(0, root)

from ultralytics import YOLO

from src.services import PathManage
from src.core.auto_rechart.detect.note_definition import get_imgsz



class ModelEntry(NamedTuple):
    name: str
    task: str
    pt_path: Path
    ncnn_path: Path
    onnx_path: Path
    trt_onnx_path: Path
    engine_path: Path


models: list[ModelEntry] = [
    ModelEntry(
        "detect", "detect",
        PathManage.DETECT_PT_PATH,
        PathManage.DETECT_NCNN_PATH,
        PathManage.DETECT_ONNX_PATH,
        PathManage.TEMP_TRT_DETECT_ONNX_PATH,
        PathManage.DETECT_ENGINE_PATH),

    ModelEntry("obb", "obb",
               PathManage.OBB_PT_PATH,
               PathManage.OBB_NCNN_PATH,
               PathManage.OBB_ONNX_PATH,
               PathManage.TEMP_TRT_OBB_ONNX_PATH,
               PathManage.OBB_ENGINE_PATH),

    ModelEntry("cls_break", "classify",
               PathManage.CLS_BREAK_PT_PATH,
               PathManage.CLS_BREAK_NCNN_PATH,
               PathManage.CLS_BREAK_ONNX_PATH,
               PathManage.TEMP_TRT_CLS_BREAK_ONNX_PATH,
               PathManage.CLS_BREAK_ENGINE_PATH),

    ModelEntry("cls_ex", "classify",
               PathManage.CLS_EX_PT_PATH,
               PathManage.CLS_EX_NCNN_PATH,
               PathManage.CLS_EX_ONNX_PATH,
               PathManage.TEMP_TRT_CLS_EX_ONNX_PATH,
               PathManage.CLS_EX_ENGINE_PATH),

    ModelEntry("touch_hold", "detect",
               PathManage.TOUCH_HOLD_PT_PATH,
               PathManage.TOUCH_HOLD_NCNN_PATH,
               PathManage.TOUCH_HOLD_ONNX_PATH,
               PathManage.TEMP_TRT_TOUCH_HOLD_ONNX_PATH,
               PathManage.TOUCH_HOLD_ENGINE_PATH),
]


def _get_batch_size(model_name, detect_obb_batch, cls_batch, touch_hold_batch):
    if model_name in {"detect", "obb"}:
        return detect_obb_batch
    if model_name == "touch_hold":
        return touch_hold_batch
    return cls_batch






def _convert_to_tensorrt(detect_obb_batch, cls_batch, touch_hold_batch) -> bool:
    try:
        for m in models:

            m.trt_onnx_path.unlink(missing_ok=True)
            m.engine_path.unlink(missing_ok=True)

            print(f"- Export engine from: {m.pt_path.name}")

            model = YOLO(str(m.pt_path), task=m.task)

            imgsz = get_imgsz(m.name)
            batch = _get_batch_size(m.name, detect_obb_batch, cls_batch, touch_hold_batch)

            try:
                model.export(
                    format="engine",
                    imgsz=imgsz,
                    quantize=16,
                    dynamic=True,
                    simplify=True,
                    workspace=None,
                    batch=batch
                )
                exported_path = m.pt_path.with_suffix(".engine")
                if not exported_path.is_file():
                    raise RuntimeError(f"TensorRT engine export is incomplete, missing: {exported_path}")
                if exported_path.resolve() != m.engine_path.resolve():
                    m.engine_path.unlink(missing_ok=True)
                    exported_path.replace(m.engine_path)
            finally:
                m.trt_onnx_path.unlink(missing_ok=True)

        return True
    
    except Exception as e:
        print(f"TensorRT conversion failed: {e}")
        return False





def _convert_to_ncnn(detect_obb_batch, cls_batch, touch_hold_batch) -> bool:
    current_ncnn_path = None
    try:
        for m in models:
            current_ncnn_path = m.ncnn_path

            if m.ncnn_path.exists():
                if not m.ncnn_path.is_dir():
                    raise RuntimeError(f"NCNN output path is not a directory: {m.ncnn_path}")
                shutil.rmtree(m.ncnn_path)

            print(f"- Export NCNN from: {m.pt_path.name}")

            model = YOLO(str(m.pt_path), task=m.task)

            imgsz = get_imgsz(m.name)
            exported_path = Path(model.export(
                format="ncnn",
                imgsz=imgsz,
                quantize=16,
                batch=1,
                device="cpu",
            )).resolve()

            if exported_path != m.ncnn_path.resolve():
                raise RuntimeError(
                    f"Unexpected NCNN export path: expected {m.ncnn_path}, got {exported_path}"
                )

            missing_files = [
                m.ncnn_path / file_name
                for file_name in PathManage.NCNN_REQUIRED_FILE_NAMES
                if not (m.ncnn_path / file_name).is_file()
            ]
            if missing_files:
                raise RuntimeError(f"NCNN export is incomplete, missing: {missing_files[0]}")

        return True

    except Exception as e:
        if current_ncnn_path is not None and current_ncnn_path.is_dir():
            shutil.rmtree(current_ncnn_path)
        print(f"NCNN conversion failed: {e}")
        return False





def _convert_to_onnx(detect_obb_batch, cls_batch, touch_hold_batch) -> bool:
    current_temp_path = None
    try:
        for m in models:
            current_temp_path = m.trt_onnx_path
            m.trt_onnx_path.unlink(missing_ok=True)

            if m.onnx_path.exists() and not m.onnx_path.is_file():
                raise RuntimeError(f"ONNX output path is not a file: {m.onnx_path}")

            print(f"- Export ONNX from: {m.pt_path.name}")

            model = YOLO(str(m.pt_path), task=m.task)
            imgsz = get_imgsz(m.name)
            batch = _get_batch_size(m.name, detect_obb_batch, cls_batch, touch_hold_batch)
            exported_path = Path(model.export(
                format="onnx",
                opset=17,
                imgsz=imgsz,
                dynamic=True,
                simplify=True,
                batch=batch,
                device="cpu",
            )).resolve()

            if exported_path != m.trt_onnx_path.resolve():
                raise RuntimeError(
                    f"Unexpected ONNX export path: expected {m.trt_onnx_path}, got {exported_path}"
                )
            if not exported_path.is_file():
                raise RuntimeError(f"ONNX export is incomplete: {exported_path}")

            exported_path.replace(m.onnx_path)

        return True

    except Exception as e:
        if current_temp_path is not None:
            current_temp_path.unlink(missing_ok=True)
        print(f"ONNX conversion failed: {e}")
        return False





def main(backend, detect_obb_batch, cls_batch, touch_hold_batch) -> bool:

    try:
        backend = str(backend or "").strip().lower()
        detect_obb_batch = int(detect_obb_batch)
        cls_batch = int(cls_batch)
        touch_hold_batch = int(touch_hold_batch)
    except Exception as e:
        print(f"Invalid arguments: {e}")
        return False
    
    if detect_obb_batch < 1 or cls_batch < 1 or touch_hold_batch < 1:
        print("Batch sizes must be >= 1")
        return False

    if backend == "tensorrt":
        return _convert_to_tensorrt(detect_obb_batch, cls_batch, touch_hold_batch)
    if backend == "ncnn":
        return _convert_to_ncnn(detect_obb_batch, cls_batch, touch_hold_batch)
    if backend in {"onnx"}:
        return _convert_to_onnx(detect_obb_batch, cls_batch, touch_hold_batch)

    print(f"Unsupported backend for conversion: {backend}")
    return False





if __name__ == "__main__":

    if len(sys.argv) <= 5:
        print("plz provide root, backend, detect_obb_batch, cls_batch, touch_hold_batch in args")
        sys.exit(1)

    result = main(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5])
    sys.exit(0 if result else 1)
