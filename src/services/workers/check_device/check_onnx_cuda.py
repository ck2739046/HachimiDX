from .check_pytorch_cuda import check as check_cuda
from .common import DeviceResult, print_device_results, test_onnx_models


def check() -> list[DeviceResult] | None:
    try:
        import onnxruntime as ort
        print(f"ONNX Runtime installed, version {ort.__version__}")
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

    cuda_devices = check_cuda(print_device=False)
    if not cuda_devices:
        return None

    devices: list[DeviceResult] = []
    for device in cuda_devices:
        if device.error is not None:
            devices.append(device)
            continue
        index = int(device.device_id.partition(":")[2])
        half, error = test_onnx_models(
            ort,
            [("CUDAExecutionProvider", {"device_id": index}), "CPUExecutionProvider"],
            "CUDAExecutionProvider",
            fp16_supported=device.half,
            fp32_supported=True,
        )
        devices.append(DeviceResult(device.device_id, device.name, bool(half), error))

    print_device_results("CUDA devices:", devices)
    return devices
