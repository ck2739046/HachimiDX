from .check_pytorch_cuda import check as check_cuda
from .common import DeviceResult


def check() -> list[DeviceResult] | None:
    try:
        import onnxruntime as ort
    except ImportError as e:
        print(f"ONNX Runtime is not installed: {e!r}")
        return None

    providers = ort.get_available_providers()
    print(f"Available providers: {providers}")
    if "CUDAExecutionProvider" not in providers:
        print("CUDA execution provider is unavailable")
        return None

    return check_cuda(print_device=True)
