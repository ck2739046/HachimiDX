import sys
import json
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


from src.core.tools import redirect_native_stderr

from src.services.workers.check_device.check_onnx_cpu import check as check_onnx_cpu
from src.services.workers.check_device.check_onnx_cuda import check as check_onnx_cuda
from src.services.workers.check_device.check_onnx_dml import check as check_onnx_dml
from src.services.workers.check_device.check_ncnn import check as check_ncnn_vulkan
from src.services.workers.check_device.check_trt import check as check_tensorrt



def main(runtime: str) -> bool:
    runtime_norm = str(runtime or "").strip().lower()

    devices = None
    if runtime_norm == "onnx_cpu":
        devices = check_onnx_cpu()
    elif runtime_norm == "onnx_cuda":
        devices = check_onnx_cuda()
    elif runtime_norm == "onnx_dml":
        devices = check_onnx_dml()
    elif runtime_norm == "tensorrt":
        devices = check_tensorrt()
    elif runtime_norm == "ncnn":
        devices = check_ncnn_vulkan()
    else:
        print(f"Unknown runtime: {runtime}")
        return False

    if devices is None:
        return False

    if not devices:
        return False
    successful_devices = [device for device in devices if device.error is None]
    if not successful_devices:
        return False
    print("INFERENCE_DEVICE_RESULT:" + json.dumps({
        "devices": [
            {
                "device_id": device.device_id,
                "name": device.name,
                "half": device.half,
            }
            for device in successful_devices
        ],
    }, ensure_ascii=False, separators=(",", ":")))

    return True


if __name__ == "__main__":

    # 探测 ONNX 设备时会真实创建 session, ORT 原生日志走 stderr。
    # 转发到 stdout 并加前缀, 免得原生日志的 \r\n 行尾被日志组件当成进度行。
    native_stderr = redirect_native_stderr("check_device")

    try:
        if len(sys.argv) <= 2:
            print("No runtime argument provided. Exiting.")
            sys.exit(1)

        result = main(sys.argv[2])
        sys.exit(0 if result else 1)
    finally:
        native_stderr.close()
