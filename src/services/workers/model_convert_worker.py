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
    path_field: str
    task: str
    pt_path: Path
    trt_onnx_path: Path


models: list[ModelEntry] = [
    ModelEntry(
        "detect", "detect", "detect",
        PathManage.DETECT_PT_PATH,
        PathManage.TEMP_TRT_DETECT_ONNX_PATH),

    ModelEntry("obb", "obb", "obb",
               PathManage.OBB_PT_PATH,
               PathManage.TEMP_TRT_OBB_ONNX_PATH),

    ModelEntry("cls_break", "cls_break", "classify",
               PathManage.CLS_BREAK_PT_PATH,
               PathManage.TEMP_TRT_CLS_BREAK_ONNX_PATH),

    ModelEntry("cls_ex", "cls_ex", "classify",
               PathManage.CLS_EX_PT_PATH,
               PathManage.TEMP_TRT_CLS_EX_ONNX_PATH),

    ModelEntry("touch_hold", "touch_hold", "detect",
               PathManage.TOUCH_HOLD_PT_PATH,
               PathManage.TEMP_TRT_TOUCH_HOLD_ONNX_PATH),
]


def _get_batch_size(model_name, detect_obb_batch, cls_batch, touch_hold_batch):
    if model_name in {"detect", "obb"}:
        return detect_obb_batch
    if model_name == "touch_hold":
        return touch_hold_batch
    return cls_batch


def _get_target_paths(backend: str, half: bool):
    result = PathManage.get_model_paths(backend, half)
    if not result.is_ok:
        raise RuntimeError(result.error_msg)
    return result.value


def _get_target_path(paths, model: ModelEntry) -> Path:
    return getattr(paths, model.path_field)






def _convert_to_tensorrt(detect_obb_batch, cls_batch, touch_hold_batch, half: bool) -> bool:
    current_engine_path = None
    current_exported_path = None
    try:
        target_paths = _get_target_paths("TensorRT", half)
        for m in models:
            current_engine_path = _get_target_path(target_paths, m)
            current_exported_path = m.pt_path.with_suffix(".engine")

            m.trt_onnx_path.unlink(missing_ok=True)
            current_engine_path.unlink(missing_ok=True)
            if current_exported_path.resolve() != current_engine_path.resolve():
                current_exported_path.unlink(missing_ok=True)

            print(f"- Export engine from: {m.pt_path.name}")

            model = YOLO(str(m.pt_path), task=m.task)

            imgsz = get_imgsz(m.name)
            batch = _get_batch_size(m.name, detect_obb_batch, cls_batch, touch_hold_batch)

            try:
                model.export(
                    format="engine",
                    imgsz=imgsz,
                    quantize=16 if half else 32,
                    dynamic=True,
                    simplify=True,
                    workspace=None,
                    batch=batch
                )
                exported_path = current_exported_path
                if not exported_path.is_file():
                    raise RuntimeError(f"TensorRT engine export is incomplete, missing: {exported_path}")
                if exported_path.resolve() != current_engine_path.resolve():
                    exported_path.replace(current_engine_path)
            finally:
                m.trt_onnx_path.unlink(missing_ok=True)

        return True

    except Exception as e:
        if current_engine_path is not None:
            current_engine_path.unlink(missing_ok=True)
        if current_exported_path is not None:
            current_exported_path.unlink(missing_ok=True)
        print(f"TensorRT conversion failed: {e}")
        return False





def _convert_to_ncnn(detect_obb_batch, cls_batch, touch_hold_batch, half: bool) -> bool:
    current_ncnn_path = None
    current_exported_path = None
    try:
        target_paths = _get_target_paths("NCNN", half)
        for m in models:
            current_ncnn_path = _get_target_path(target_paths, m)
            current_exported_path = m.pt_path.with_name(f"{m.pt_path.stem}_ncnn_model")

            for path in (current_ncnn_path, current_exported_path):
                if path.exists():
                    if not path.is_dir():
                        raise RuntimeError(f"NCNN output path is not a directory: {path}")
                    shutil.rmtree(path)

            print(f"- Export NCNN from: {m.pt_path.name}")

            model = YOLO(str(m.pt_path), task=m.task)

            imgsz = get_imgsz(m.name)
            exported_path = Path(model.export(
                format="ncnn",
                imgsz=imgsz,
                quantize=16 if half else 32,
                batch=1,
                device="cpu",
            )).resolve()

            if exported_path != current_exported_path.resolve():
                raise RuntimeError(
                    f"Unexpected NCNN export path: expected {current_exported_path}, got {exported_path}"
                )

            missing_files = [
                exported_path / file_name
                for file_name in PathManage.NCNN_REQUIRED_FILE_NAMES
                if not (exported_path / file_name).is_file()
            ]
            if missing_files:
                raise RuntimeError(f"NCNN export is incomplete, missing: {missing_files[0]}")
            shutil.move(str(exported_path), str(current_ncnn_path))

        return True

    except Exception as e:
        if current_ncnn_path is not None and current_ncnn_path.is_dir():
            shutil.rmtree(current_ncnn_path)
        if current_exported_path is not None and current_exported_path.is_dir():
            shutil.rmtree(current_exported_path)
        print(f"NCNN conversion failed: {e}")
        return False





def _convert_to_onnx(detect_obb_batch, cls_batch, touch_hold_batch, half: bool) -> bool:
    current_temp_path = None
    current_onnx_path = None
    try:
        target_paths = _get_target_paths("ONNX CPU", half)
        for m in models:
            current_temp_path = m.trt_onnx_path
            current_onnx_path = _get_target_path(target_paths, m)
            m.trt_onnx_path.unlink(missing_ok=True)

            if current_onnx_path.exists() and not current_onnx_path.is_file():
                raise RuntimeError(f"ONNX output path is not a file: {current_onnx_path}")
            current_onnx_path.unlink(missing_ok=True)

            print(f"- Export ONNX from: {m.pt_path.name}")

            model = YOLO(str(m.pt_path), task=m.task)
            imgsz = get_imgsz(m.name)
            batch = _get_batch_size(m.name, detect_obb_batch, cls_batch, touch_hold_batch)
            exported_path = Path(model.export(
                format="onnx",
                opset=18,
                imgsz=imgsz,
                dynamic=True,
                simplify=True,
                batch=batch,
                device="cpu",
                quantize=16 if half else 32,
            )).resolve()

            if exported_path != m.trt_onnx_path.resolve():
                raise RuntimeError(
                    f"Unexpected ONNX export path: expected {m.trt_onnx_path}, got {exported_path}"
                )
            if not exported_path.is_file():
                raise RuntimeError(f"ONNX export is incomplete: {exported_path}")

            exported_path.replace(current_onnx_path)

        return True

    except Exception as e:
        if current_temp_path is not None:
            current_temp_path.unlink(missing_ok=True)
        if current_onnx_path is not None:
            current_onnx_path.unlink(missing_ok=True)
        print(f"ONNX conversion failed: {e}")
        return False





def main(backend, detect_obb_batch, cls_batch, touch_hold_batch, half="false") -> bool:

    try:
        backend = str(backend or "").strip().lower()
        detect_obb_batch = int(detect_obb_batch)
        cls_batch = int(cls_batch)
        touch_hold_batch = int(touch_hold_batch)
        half_text = str(half).strip().lower()
        if half_text not in {"true", "false"}:
            raise ValueError(f"Invalid half value: {half}")
        half = half_text == "true"
    except Exception as e:
        print(f"Invalid arguments: {e}")
        return False
    
    if detect_obb_batch < 1 or cls_batch < 1 or touch_hold_batch < 1:
        print("Batch sizes must be >= 1")
        return False

    if backend == "tensorrt":
        return _convert_to_tensorrt(detect_obb_batch, cls_batch, touch_hold_batch, half)
    if backend == "ncnn":
        return _convert_to_ncnn(detect_obb_batch, cls_batch, touch_hold_batch, half)
    if backend in {"onnx", "onnx_cpu", "onnx_cuda", "onnx_dml"}:
        return _convert_to_onnx(detect_obb_batch, cls_batch, touch_hold_batch, half)

    print(f"Unsupported backend for conversion: {backend}")
    return False





if __name__ == "__main__":

    if len(sys.argv) <= 6:
        print("plz provide root, backend, detect_obb_batch, cls_batch, touch_hold_batch, half in args")
        sys.exit(1)

    result = main(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5], sys.argv[6])
    sys.exit(0 if result else 1)
