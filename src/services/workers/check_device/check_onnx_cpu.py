from src.services.workers.check_device.common import DeviceResult, get_windows_cpu_name


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
    if "CPUExecutionProvider" not in providers:
        print("CPU execution provider is unavailable")
        return None

    return [DeviceResult("cpu", get_windows_cpu_name() or "CPU", False)]
