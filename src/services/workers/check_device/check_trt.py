from .check_pytorch_cuda import check as check_cuda
from .common import DeviceResult


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
    except ImportError as e:
        print(f"TensorRT is not installed: {e!r}")
        return None

    # check_cuda 已确认 torch 可导入,这里静默兜底
    try:
        import torch
    except ImportError:
        return None

    results = []
    for device in devices:
        index = int(device.device_id.partition(":")[2])
        trt_half = _get_half_support(tensorrt, torch, index)
        half = device.half and trt_half
        results.append(DeviceResult(device.device_id, device.name, half))

    print("CUDA devices:")
    for device in results:
        print(f"  - {device.device_id}: {device.name}, half={device.half}")

    return results
