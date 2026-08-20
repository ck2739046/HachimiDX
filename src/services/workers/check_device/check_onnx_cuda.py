from .check_pytorch_cuda import check as check_cuda
from .common import DeviceResult


def check() -> list[DeviceResult] | None:
    try:
        import onnxruntime as ort
    except Exception as e:
        print(f"Failed to load ONNX Runtime: {e!r}")
        return None

    try:
        providers = ort.get_available_providers()
    except Exception as e:
        print(f"Failed to read ONNX Runtime providers: {e}")
        return None
    # print(f"Available providers: {providers}")
    if "CUDAExecutionProvider" not in providers:
        print("CUDA execution provider is unavailable")
        return None

    return check_cuda(print_device=True)
