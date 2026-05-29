import sys
from pathlib import Path
import io

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

import torch

from ultralytics import YOLO

from src.services import PathManage
from src.core.auto_rechart.detect.note_definition import get_imgsz



# 转换为 enigne 时，中间会转换出临时用的 onnx 文件
# 这个要和正式的 onnx 文件区别开来
models = [
    ("detect", "detect", PathManage.DETECT_PT_PATH, PathManage.DETECT_ONNX_PATH, PathManage.TEMP_DETECT_ONNX_PATH),
    ("obb", "obb", PathManage.OBB_PT_PATH, PathManage.OBB_ONNX_PATH, PathManage.TEMP_OBB_ONNX_PATH),
    ("cls_break", "classify", PathManage.CLS_BREAK_PT_PATH, PathManage.CLS_BREAK_ONNX_PATH, PathManage.TEMP_CLS_BREAK_ONNX_PATH),
    ("cls_ex", "classify", PathManage.CLS_EX_PT_PATH, PathManage.CLS_EX_ONNX_PATH, PathManage.TEMP_CLS_EX_ONNX_PATH),
    ("touch_hold", "detect", PathManage.TOUCH_HOLD_PT_PATH, PathManage.TOUCH_HOLD_ONNX_PATH, PathManage.TEMP_TOUCH_HOLD_ONNX_PATH),
]






def _convert_to_tensorrt(detect_obb_batch, cls_batch, touch_hold_batch) -> bool:
    try:
        for model_name, task, pt_path, onnx_path, temp_onnx_path in models:

            # 开始前删
            if temp_onnx_path.exists():
                temp_onnx_path.unlink()

            print(f"- Export engine from: {pt_path.name}")

            model = YOLO(str(pt_path), task=task)

            imgsz = get_imgsz(model_name)
            if model_name in {"detect", "obb"}:
                batch = detect_obb_batch
            elif model_name == "touch_hold":
                batch = touch_hold_batch
            else:
                batch = cls_batch

            model.export(
                format="engine",
                imgsz=imgsz,
                half=True,
                dynamic=True,
                simplify=True,
                workspace=None,
                batch=batch
            )

            # 结束后再删
            if temp_onnx_path.exists():
                temp_onnx_path.unlink()

        return True
    
    except Exception as e:
        print(f"TensorRT conversion failed: {e}")
        return False





def _convert_to_onnx(detect_obb_batch, cls_batch, touch_hold_batch) -> bool:
    try:
        for model_name, task, pt_path, onnx_path, temp_onnx_path in models:

            # 开始前删
            if temp_onnx_path.exists():
                temp_onnx_path.unlink()

            print(f"- Export onnx from: {pt_path.name}")

            model = YOLO(str(pt_path), task=task)

            imgsz = get_imgsz(model_name)
            if model_name in {"detect", "obb"}:
                batch = detect_obb_batch
            elif model_name == "touch_hold":
                batch = touch_hold_batch
            else:
                batch = cls_batch

            model.export(
                format="onnx",
                opset=20,
                imgsz=imgsz,
                half=True,
                dynamic=True,
                simplify=True,
                batch=batch
            )

            # 删除已存在的正式 onnx 文件
            if onnx_path.exists():
                onnx_path.unlink()

            # 将临时 onnx 重命名为正式 onnx
            if temp_onnx_path.exists():
                temp_onnx_path.rename(onnx_path)

        return True
    
    except Exception as e:
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
    if backend in {"directml", "onnx"}:
        return _convert_to_onnx(detect_obb_batch, cls_batch, touch_hold_batch)

    print(f"Unsupported backend for conversion: {backend}")
    return False





if __name__ == "__main__":

    if len(sys.argv) <= 5:
        print("plz provide root, backend, detect_obb_batch, cls_batch, touch_hold_batch in args")
        sys.exit(1)

    result = main(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5])
    sys.exit(0 if result else 1)
