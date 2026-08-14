# 打印一个库的所有属性
# python -c "import torch; print([attr for attr in dir(torch) if not attr.startswith('_')])" 

import sys
from pathlib import Path
import io
import subprocess

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




def _check_torch_installed() -> tuple[bool, object | None]:
    try:
        import torch
        print(f"PyTorch installed, version {torch.__version__}")
        return True, torch
    except ImportError as e:
        print(f"PyTorch is not installed: {e!r}")
        return False, None



def _get_windows_cpu_name() -> str:
    if sys.platform != "win32":
        return ""

    try:
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "Get-CimInstance Win32_Processor | Select-Object -First 1 -ExpandProperty Name",
            ],
            capture_output=True,
            check=False,
            encoding="utf-8",
            errors="replace",
            timeout=5,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _check_cpu() -> list[tuple[str, str]] | None:

    ok, _ = _check_torch_installed()
    if not ok:
        return None
    cpu_name = _get_windows_cpu_name()
    print("CPU runtime check passed")
    return [("cpu", cpu_name or "CPU")]





def _check_cuda() -> list[tuple[str, str]] | None:
    # 检查 PyTorch 是否安装
    ok, torch = _check_torch_installed()
    if not ok:
        return None

    # 检查 PyTorch 是否支持 cuda
    cuda_support = torch.cuda.is_available()
    cud_version = torch.version.cuda if hasattr(torch.version, "cuda") else "N/A"
    print(f"  - CUDA available: {cuda_support}")
    print(f"  - CUDA version: {cud_version}")
    if not cuda_support or not cud_version or cud_version == "N/A":
        print("CUDA support is not available in PyTorch")
        return None

    # 列出所有 CUDA 设备
    device_count = torch.cuda.device_count()
    if device_count == 0:
        print("No available CUDA devices found")
        return None

    devices: list[tuple[str, str]] = []
    print("CUDA devices:")
    for i in range(device_count):
        try:
            device_name = torch.cuda.get_device_name(i)
            print(f"  - {i}: {device_name}")
            devices.append((f"cuda:{i}", device_name))
        except Exception as e:
            print(f"  - {i}: unavailable ({e})")

    return devices or None


def _check_tensorrt() -> list[tuple[str, str]] | None:
    # 检查 PyTorch 是否支持 cuda
    devices = _check_cuda()
    if not devices:
        return None

    # 检查 TensorRT 是否安装
    try:
        import tensorrt
        print(f"TensorRT installed, version {tensorrt.__version__}")
    except ImportError as e:
        print(f"TensorRT is not installed: {e!r}")
        return None

    return devices





def _check_ncnn_vulkan() -> list[tuple[str, str]] | None:

    # 检查 PyTorch 是否安装
    ok, _ = _check_torch_installed()
    if not ok:
        return None

    # 检查 ncnn 是否安装
    try:
        import ncnn
        print(f"NCNN installed, version {ncnn.__version__}")
    except ImportError as e:
        print(f"NCNN is not installed: {e!r}")
        return None

    gpu_instance_created = False
    try:
        create_result = ncnn.create_gpu_instance()
        if create_result != 0:
            print(f"Failed to initialize NCNN Vulkan, error code: {create_result}")
            return None
        gpu_instance_created = True

        gpu_count = ncnn.get_gpu_count()
        if gpu_count <= 0:
            print("No available NCNN Vulkan devices found")
            return None

        # 逐个设备做实际绑定检查，单个失败不影响其他设备
        devices: list[tuple[str, str]] = []
        print("NCNN Vulkan devices:")
        for index in range(gpu_count):
            gpu_info = ncnn.get_gpu_info(index)
            device_name = gpu_info.device_name()
            print(f"  - {index}: {device_name}")
            try:
                net = ncnn.Net()
                net.opt.use_vulkan_compute = True
                net.set_vulkan_device(index)
                del net
                devices.append((f"vulkan:{index}", device_name))
            except Exception as e:
                print(f"  - {index}: unavailable ({e})")

        if not devices:
            print("No NCNN Vulkan device passed the binding check")
            return None

        return devices

    except Exception as e:
        print(f"Failed to initialize NCNN Vulkan: {e}")
        return None
    finally:
        if gpu_instance_created:
            ncnn.destroy_gpu_instance()





def _check_directml() -> list[tuple[str, str]] | None:

    # 检查 PyTorch 是否安装
    ok, _ = _check_torch_installed()
    if not ok:
        return None

    # 检查 ONNX Runtime 是否安装
    try:
        import onnxruntime as ort
        print(f"ONNX Runtime installed, version {ort.__version__}")
    except ImportError as e:
        print(f"ONNX Runtime is not installed: {e!r}")
        return None

    # 检查 DirectML 支持
    providers = ort.get_available_providers()
    print(f"Available providers: {providers}")
    if "DmlExecutionProvider" not in providers:
        print("DirectML execution provider is unavailable")
        return None
    print("DirectML execution provider is available")

    # 获取 DirectML 支持的设备列表
    try:
        # 获取所有设备
        get_ep_devices = getattr(ort, "get_ep_devices", None)
        if not callable(get_ep_devices):
            print("ONNX Runtime does not support EP device enumeration")
            return None

        devices: list[tuple[str, str]] = []
        seen_indexes: set[int] = set()
        for ep_device in get_ep_devices():
            if getattr(ep_device, "ep_name", "") != "DmlExecutionProvider":
                continue

            hardware_device = getattr(ep_device, "device", None)
            metadata = getattr(hardware_device, "metadata", {}) or {}
            index_text = str(metadata.get("DxgiAdapterNumber", "")).strip()
            if not index_text.isdigit():
                print(f"DirectML device has no valid DXGI adapter number: {metadata}")
                continue

            index = int(index_text)
            if index in seen_indexes:
                continue
            seen_indexes.add(index)
            name = str(metadata.get("Description", "")).strip() or f"DirectML device {index}"
            devices.append((f"dml:{index}", name))

        if not devices:
            print("No available DirectML devices found")
            return None

        devices.sort(key=lambda item: int(item[0].partition(":")[2]))
        print("DirectML devices:")
        for device_id, device_name in devices:
            print(f"  - {device_id}: {device_name}")
        return devices

    except Exception as e:
        print(f"Failed to read DirectML devices: {e}")
        return None





def _emit_device_result(devices: list[tuple[str, str]] | None) -> None:
    # 设备列表协议：成功时输出若干 "INFERENCE_DEVICE_RESULT:<id>|<name>"，失败时不输出
    if not devices:
        return
    for device_id, name in devices:
        print(f"INFERENCE_DEVICE_RESULT:{device_id}|{name}")





def main(runtime: str) -> bool:
    runtime_norm = str(runtime or "").strip().lower()

    devices: list[tuple[str, str]] | None
    if runtime_norm in {"pytorch_cpu", "cpu"}:
        devices = _check_cpu()
    elif runtime_norm in {"pytorch_cuda", "cuda"}:
        devices = _check_cuda()
    elif runtime_norm == "tensorrt":
        devices = _check_tensorrt()
    elif runtime_norm == "ncnn":
        devices = _check_ncnn_vulkan()
    elif runtime_norm in {"directml", "dml", "onnx"}:
        devices = _check_directml()
    else:
        print(f"Unknown runtime: {runtime}")
        return False

    if devices is None:
        return False
    _emit_device_result(devices)
    return True





if __name__ == "__main__":

    if len(sys.argv) <= 2:
        print("No runtime argument provided. Exiting.")
        sys.exit(1)

    # 运行检查并返回退出码
    result = main(sys.argv[2])
    sys.exit(0 if result else 1)
