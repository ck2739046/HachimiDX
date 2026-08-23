from .common import DeviceResult, check_torch_installed


def _read_half_support(net) -> bool:
    try:
        result = net.load_param_mem("7767517\n1 1\nInput input 0 1 input\n")
        if result != 0:
            return False
        return bool(net.opt.use_fp16_storage and net.opt.use_fp16_arithmetic)
    except Exception:
        return False


def check() -> list[DeviceResult] | None:

    ok, _ = check_torch_installed()
    if not ok:
        return None

    try:
        import ncnn
        print(f"NCNN installed, version {ncnn.__version__}")
    except Exception as e:
        print(f"Failed to load NCNN: {e!r}")
        return None

    gpu_instance_created = False
    try:
        create_result = ncnn.create_gpu_instance()
        if create_result != 0:
            print(f"Failed to initialize NCNN, error code: {create_result}")
            return None
        gpu_instance_created = True

        gpu_count = ncnn.get_gpu_count()
        if gpu_count <= 0:
            print("No available NCNN devices found")
            return None

        devices: list[DeviceResult] = []
        print("NCNN devices:")
        for index in range(gpu_count):
            try:
                gpu_info = ncnn.get_gpu_info(index)
                device_name = gpu_info.device_name()
                net = ncnn.Net()
                net.opt.use_vulkan_compute = True
                net.set_vulkan_device(index)
                half = _read_half_support(net)
                del net
                print(f"  - {index}: {device_name}, half={half}")
                devices.append(DeviceResult(f"vulkan:{index}", device_name, half))
            except Exception as e:
                print(f"  - {index}: unavailable ({e})")

        if not devices:
            print("No NCNN device passed the binding check")
            return None

        return devices

    except Exception as e:
        print(f"Failed to initialize NCNN: {e}")
        return None
    finally:
        if gpu_instance_created:
            try:
                ncnn.destroy_gpu_instance()
            except Exception as e:
                print(f"Failed to destroy NCNN instance: {e}")
