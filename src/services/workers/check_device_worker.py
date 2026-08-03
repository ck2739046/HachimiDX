# 打印一个库的所有属性
# python -c "import torch; print([attr for attr in dir(torch) if not attr.startswith('_')])" 

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




def _check_torch_installed() -> tuple[bool, object | None]:
    try:
        import torch
        print(f"PyTorch installed, version {torch.__version__}")
        return True, torch
    except ImportError as e:
        print(f"PyTorch is not installed: {e!r}")
        return False, None



def _check_cpu() -> bool:

    # 仅检查 PyTorch 是否安装
    ok, _ = _check_torch_installed()
    if ok:
        print("CPU runtime check passed")
    return ok





def _check_cuda_or_tensorrt() -> bool:

    # 检查 PyTorch 是否安装
    ok, torch = _check_torch_installed()
    if not ok:
        return False
    
    # 检查 PyTorch 是否支持 cuda
    cuda_support = torch.cuda.is_available()
    cud_version = torch.version.cuda if hasattr(torch.version, "cuda") else "N/A"
    print(f"  - CUDA available: {cuda_support}")
    print(f"  - CUDA version: {cud_version}")
    if not cuda_support or cud_version == "N/A":
        print("CUDA support is not available in PyTorch")
        return False

    # 检查 TensorRT 是否安装
    try:
        import tensorrt
        print(f"TensorRT installed, version {tensorrt.__version__}")
    except ImportError as e:
        print(f"TensorRT is not installed: {e!r}")
        return False

    # 列出所有 CUDA 设备
    device_count = torch.cuda.device_count()
    if device_count == 0:
        print("No available CUDA devices found")
        return False

    print("CUDA devices:")
    for i in range(device_count):
        device_name = torch.cuda.get_device_name(i)
        print(f"  - {i}: {device_name}")

    return True





def _check_ncnn_vulkan() -> bool:

    # 检查 PyTorch 是否安装
    ok, _ = _check_torch_installed()
    if not ok:
        return False

    # 检查 ncnn 是否安装
    try:
        import ncnn
        print(f"NCNN installed, version {ncnn.__version__}")
    except ImportError as e:
        print(f"NCNN is not installed: {e!r}")
        return False

    # 检查 Vulkan 是否可用
    gpu_instance_created = False
    try:
        create_result = ncnn.create_gpu_instance()
        if create_result != 0:
            print(f"Failed to initialize NCNN Vulkan, error code: {create_result}")
            return False
        gpu_instance_created = True

        # 列出可用的 Vulkan 设备
        gpu_count = ncnn.get_gpu_count()
        if gpu_count <= 0:
            print("No available NCNN Vulkan devices found")
            return False

        print("NCNN Vulkan devices:")
        for index in range(gpu_count):
            gpu_info = ncnn.get_gpu_info(index)
            print(f"  - {index}: {gpu_info.device_name()}")

        net = ncnn.Net()
        net.opt.use_vulkan_compute = True
        net.set_vulkan_device(0)
        del net
        print("NCNN Vulkan device 0 is available")
        return True

    except Exception as e:
        print(f"Failed to initialize NCNN Vulkan: {e}")
        return False
    finally:
        if gpu_instance_created:
            ncnn.destroy_gpu_instance()





def _check_openvino() -> bool:

    # 检查 PyTorch 是否安装
    ok, _ = _check_torch_installed()
    if not ok:
        return False
    
    # 检查 OpenVINO 是否安装
    try:
        import openvino
        print(f"OpenVINO installed, version {openvino.__version__}")
    except ImportError as e:
        print(f"OpenVINO is not installed: {e!r}")
        return False
    
    # 列出可用设备
    core = openvino.Core()
    devices = core.available_devices
    if not devices:
        print("No available OpenVINO devices found")
        return False

    print("OpenVINO devices:")
    for device in devices:
        device_name = core.get_property(device, "FULL_DEVICE_NAME")
        print(f"  - '{device}': {device_name}")

    return True





def main(runtime: str) -> bool:
    runtime_norm = str(runtime or "").strip().lower()

    if runtime_norm in {"pytorch", "cpu"}:
        return _check_cpu()
    if runtime_norm in {"cuda", "tensorrt"}:
        return _check_cuda_or_tensorrt()
    if runtime_norm == "ncnn":
        return _check_ncnn_vulkan()
    # if runtime_norm == "openvino":
        # return _check_openvino()

    print(f"Unknown runtime: {runtime}")
    return False





if __name__ == "__main__":

    if len(sys.argv) <= 2:
        print("No runtime argument provided. Exiting.")
        sys.exit(1)

    # 运行检查并返回退出码
    result = main(sys.argv[2])
    sys.exit(0 if result else 1)
