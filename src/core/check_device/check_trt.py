from .check_pytorch_cuda import check as check_cuda
from .common import DeviceResult, print_device_results


def _get_half_support(tensorrt, torch, index: int) -> bool:
    try:
        logger = tensorrt.Logger(tensorrt.Logger.ERROR)
        with torch.cuda.device(index):
            builder = tensorrt.Builder(logger)
            return bool(builder.platform_has_fast_fp16)
    except Exception as e:
        print(f"  - cuda:{index} TensorRT FP16 capability unavailable: {e}")
        return False





def check() -> list[DeviceResult] | None:

    devices = check_cuda(print_device=False)
    if not devices:
        return None

    try:
        import tensorrt
        print(f"TensorRT installed, version {tensorrt.__version__}")
    except Exception as e:
        print(f"Failed to load TensorRT: {e!r}")
        return None

    # check_cuda 已确认 torch 可导入，这里不应该触发
    try:
        import torch
    except Exception as e:
        print(f"Failed to load PyTorch: {e!r}")
        return None

    results = []
    for device in devices:
        if device.error is not None:
            results.append(device)
            continue
        index = int(device.device_id.partition(":")[2])
        half = device.half and _get_half_support(tensorrt, torch, index)
        results.append(DeviceResult(device.device_id, device.name, half))

    print_device_results("CUDA devices:", results)

    return results
