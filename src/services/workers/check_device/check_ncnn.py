from .common import DeviceResult, check_torch_installed


def _read_half_support(gpu_info) -> bool:
    # 通过 GpuInfo API 查询
    # 绑定未暴露或查询失败时保守返回 False
    storage = getattr(gpu_info, "support_fp16_storage", None)
    arithmetic = getattr(gpu_info, "support_fp16_arithmetic", None)
    if not (callable(storage) and callable(arithmetic)):
        return False
    try:
        return bool(storage() and arithmetic())
    except Exception:
        return False


def check() -> list[DeviceResult] | None:

    ok, _ = check_torch_installed()
    if not ok:
        return None

    try:
        import ncnn
        print(f"NCNN installed, version {ncnn.__version__}")
    except ImportError as e:
        print(f"NCNN is not installed: {e!r}")
        return None

    gpu_instance_created = False
    try:
        create_result = ncnn.create_gpu_instance()
        if create_result != 0:
            print(f"Failed to initialize NCNN Vulkan, error code: {create_result}")
            return None
        gpu_instance_created = True

        gpu_count = ncnn.get_gpu_count()
        if gpu_count <= 0:
            print("No available NCNN Vulkan devices found")
            return None

        devices: list[DeviceResult] = []
        print("NCNN Vulkan devices:")
        for index in range(gpu_count):
            gpu_info = ncnn.get_gpu_info(index)
            device_name = gpu_info.device_name()
            try:
                net = ncnn.Net()
                net.opt.use_vulkan_compute = True
                net.set_vulkan_device(index)
                del net
                half = _read_half_support(gpu_info)
                print(f"  - {index}: {device_name}, half={half}")
                devices.append(DeviceResult(f"vulkan:{index}", device_name, half))
            except Exception as e:
                print(f"  - {index}: unavailable ({e})")

        if not devices:
            print("No NCNN Vulkan device passed the binding check")
            return None

        return devices

    except Exception as e:
        print(f"Failed to initialize NCNN Vulkan: {e}")
        return None
    finally:
        if gpu_instance_created:
            ncnn.destroy_gpu_instance()
