import sys
from pathlib import Path
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



models = [
    ("detect", "detect", PathManage.DETECT_PT_PATH, PathManage.DETECT_NCNN_PATH, PathManage.TEMP_TRT_DETECT_ONNX_PATH),
    ("obb", "obb", PathManage.OBB_PT_PATH, PathManage.OBB_NCNN_PATH, PathManage.TEMP_TRT_OBB_ONNX_PATH),
    ("cls_break", "classify", PathManage.CLS_BREAK_PT_PATH, PathManage.CLS_BREAK_NCNN_PATH, PathManage.TEMP_TRT_CLS_BREAK_ONNX_PATH),
    ("cls_ex", "classify", PathManage.CLS_EX_PT_PATH, PathManage.CLS_EX_NCNN_PATH, PathManage.TEMP_TRT_CLS_EX_ONNX_PATH),
    ("touch_hold", "detect", PathManage.TOUCH_HOLD_PT_PATH, PathManage.TOUCH_HOLD_NCNN_PATH, PathManage.TEMP_TRT_TOUCH_HOLD_ONNX_PATH),
]


def _get_batch_size(model_name, detect_obb_batch, cls_batch, touch_hold_batch):
    if model_name in {"detect", "obb"}:
        return detect_obb_batch
    if model_name == "touch_hold":
        return touch_hold_batch
    return cls_batch






def _convert_to_tensorrt(detect_obb_batch, cls_batch, touch_hold_batch) -> bool:
    try:
        for model_name, task, pt_path, _, temp_onnx_path in models:

            temp_onnx_path.unlink(missing_ok=True)

            print(f"- Export engine from: {pt_path.name}")

            model = YOLO(str(pt_path), task=task)

            imgsz = get_imgsz(model_name)
            batch = _get_batch_size(model_name, detect_obb_batch, cls_batch, touch_hold_batch)

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
            finally:
                temp_onnx_path.unlink(missing_ok=True)

        return True
    
    except Exception as e:
        print(f"TensorRT conversion failed: {e}")
        return False





def _convert_to_ncnn(detect_obb_batch, cls_batch, touch_hold_batch) -> bool:
    current_ncnn_path = None
    try:
        for model_name, task, pt_path, ncnn_path, _ in models:
            current_ncnn_path = ncnn_path

            if ncnn_path.exists():
                if not ncnn_path.is_dir():
                    raise RuntimeError(f"NCNN output path is not a directory: {ncnn_path}")
                shutil.rmtree(ncnn_path)

            print(f"- Export NCNN from: {pt_path.name}")

            model = YOLO(str(pt_path), task=task)

            imgsz = get_imgsz(model_name)
            exported_path = Path(model.export(
                format="ncnn",
                imgsz=imgsz,
                quantize=16,
                batch=1,
                device="cpu",
            )).resolve()

            if exported_path != ncnn_path.resolve():
                raise RuntimeError(
                    f"Unexpected NCNN export path: expected {ncnn_path}, got {exported_path}"
                )

            missing_files = [
                ncnn_path / file_name
                for file_name in PathManage.NCNN_REQUIRED_FILE_NAMES
                if not (ncnn_path / file_name).is_file()
            ]
            if missing_files:
                raise RuntimeError(f"NCNN export is incomplete, missing: {missing_files[0]}")

        return True

    except Exception as e:
        if current_ncnn_path is not None and current_ncnn_path.is_dir():
            shutil.rmtree(current_ncnn_path)
        print(f"NCNN conversion failed: {e}")
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

    print(f"Unsupported backend for conversion: {backend}")
    return False





if __name__ == "__main__":

    if len(sys.argv) <= 5:
        print("plz provide root, backend, detect_obb_batch, cls_batch, touch_hold_batch in args")
        sys.exit(1)

    result = main(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5])
    sys.exit(0 if result else 1)
