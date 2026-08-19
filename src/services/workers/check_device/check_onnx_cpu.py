from src.services.workers.check_device.common import DeviceResult, get_windows_cpu_name


def check() -> list[DeviceResult] | None:
    try:
        import onnxruntime as ort
        print(f"ONNX Runtime installed, version {ort.__version__}")
    except ImportError as e:
        print(f"ONNX Runtime is not installed: {e!r}")
        return None

    providers = ort.get_available_providers()
    print(f"Available providers: {providers}")
    if "CPUExecutionProvider" not in providers:
        print("CPU execution provider is unavailable")
        return None

    return [DeviceResult("cpu", get_windows_cpu_name() or "CPU", False)]
