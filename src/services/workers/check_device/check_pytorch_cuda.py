from .common import DeviceResult, check_torch_installed


def check(print_device: bool = True) -> list[DeviceResult] | None:

    ok, torch = check_torch_installed()
    if not ok:
        return None

    try:
        cuda_support = torch.cuda.is_available()
        cud_version = torch.version.cuda if hasattr(torch.version, "cuda") else "N/A"
    except Exception as e:
        print(f"Failed to initialize PyTorch CUDA: {e}")
        return None
    print(f"  - CUDA available: {cuda_support}")
    print(f"  - CUDA version: {cud_version}")
    if not cuda_support or not cud_version or cud_version == "N/A":
        print("CUDA support is not available in PyTorch")
        return None

    try:
        device_count = torch.cuda.device_count()
    except Exception as e:
        print(f"Failed to enumerate CUDA devices: {e}")
        return None
    if device_count == 0:
        print("No available CUDA devices found")
        return None

    devices: list[DeviceResult] = []
    for i in range(device_count):
        try:
            device_name = torch.cuda.get_device_name(i)
            try:
                capability = tuple(torch.cuda.get_device_capability(i))
                half = capability >= (7, 0)
            except Exception as e:
                devices.append(DeviceResult(
                    f"cuda:{i}", device_name, False,
                    f"failed to detect FP16/FP32 support: {e!r}",
                ))
                continue
            devices.append(DeviceResult(f"cuda:{i}", device_name, half))
        except Exception as e:
            print(f"  - {i}: unavailable ({e})")

    if devices and print_device:
        print("CUDA devices:")
        for device in devices:
            if device.error is not None:
                print(f"  - {device.device_id}: {device.name}, failed: {device.error}")
            else:
                print(f"  - {device.device_id}: {device.name}, half={device.half}")
            
    return devices or None
