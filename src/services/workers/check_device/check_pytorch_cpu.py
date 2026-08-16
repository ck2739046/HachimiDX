from .common import DeviceResult, check_torch_installed, get_windows_cpu_name


def check() -> list[DeviceResult] | None:

    ok, _ = check_torch_installed()
    if not ok:
        return None
    cpu_name = get_windows_cpu_name()
    print("CPU runtime check passed")
    return [DeviceResult("cpu", cpu_name or "CPU", False)]
