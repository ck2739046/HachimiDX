from types import SimpleNamespace as SN



ask_language = SN(
    prompt = """
Please select your language:
1. Simplified Chinese (Default)
2. English
3. Exit

请选择语言：
1. 简体中文 (默认)
2. 英语
3. 退出

-> """,

    defaulting = "Defaulting to Simplified Chinese.",
)



main_menu = SN(
    prompt = """
Please select:

1. Install HachimiDX (Default)
2. Reinstall model inference backend
3. Exit

If you are not sure what option 2 does, do not select it.

-> """,

    defaulting = "Defaulting to HachimiDX installation.",
)



reinstall_backend = SN(
    prompt = """
The currently installed backend will be uninstalled, then the installation process will start again.
Are you sure you want to continue?

1. No (Default)
2. Yes

-> """,

    abort = "Canceled. No changes were made.",

    start_uninstall = "Uninstalling the current backend...",
    uninstall_done = "Uninstallation completed.",
)



install = SN(
    start = "Starting HachimiDX installation...",
    detect_trt_failed = "TensorRT is unavailable.",
    detect_dml_failed = "DirectML is unavailable.",
    detect_ncnn_failed = "NCNN is unavailable.",
    done = "HachimiDX installation completed.",
)



ask_use_pypi_mirror = SN(
    prompt = """
PyPI mirrors can significantly speed up downloads and installations in China.
Do you want to use a PyPI mirror?

If you are in mainland China, it is highly recommended to choose \"Yes\".
If you are in other regions, please choose \"No\".

1. Yes (Default)
2. No
3. Exit

-> """,

    defaulting = "Defaulting to Yes.",
)



choose_backend = SN(
    detect_start = "Checking all inference backends and GPUs...",
    summary_title = "Inference backend detection results:",
    available = "Available",
    unavailable = "Unavailable",
    unavailable_with_reason = "Unavailable: {reason}",
    backend_status = "{backend}: {status}",
    backend_reason = "  Reason: {reason}",
    gpu_status = "  GPU {index}: {gpu_name}{details} -- {status}",
    gpu_unavailable = "Unavailable: {reason}",
    nvidia_gpu_details = ", VRAM {vram} GB, SM {compute_cap}, driver {driver}, config {config}",
    cpu_backend = "PyTorch CPU",
    trt_backend = "TensorRT",
    dml_backend = "DirectML",
    ncnn_backend = "NCNN Vulkan",
    no_available_gpu = "No usable GPU was detected.",
    no_gpu_detected = "No target GPU was detected.",
    unknown_detection_error = "Detection failed.",
    detection_exception = "An exception occurred while checking {backend}: {error}",
    backend_menu_title = "Select the inference backend to install:",
    backend_option = "{index}. {backend} [{status}]",
    backend_recommendation = "{backend} is the recommended and default option.",
    backend_prompt = "Please enter the backend number (1, 2, 3, ...)\n-> ",
    exit_option = "5. Exit",
    invalid_backend_choice = "Invalid input. Please try again.",
    backend_not_available = "That backend is unavailable. Please select an available backend.",
    backend_selection_failed = "Backend selection failed.",
    user_cancelled = "Backend selection was canceled.",
    trt_not_available = "No usable NVIDIA GPU was detected.",
    trt_selection_failed = "TensorRT GPU configuration selection failed.",
    trt_gpu_menu_title = "Multiple usable NVIDIA GPUs have different configurations. Select a GPU:",
    trt_gpu_option = "{index}. {gpu_name}, VRAM {vram} GB, SM {compute_cap}, driver {driver}, config {config}",
    trt_gpu_prompt = "Please enter the GPU number (0, 1, 2, ...)\n-> ",
    invalid_gpu_choice = "Invalid input. Please try again.",
)



pip_install = SN(
    mirror_names = {
        "tsinghua": "TUNA",
        "tencent": "Tencent Cloud",
        "huawei": "Huawei Cloud",
        "aliyun": "Alibaba Cloud",
    },
    start = "Installing {package_name}...",
    success = "{package_name} installation completed.",
    error = "An error occurred while installing {package_name}: {e}",
    mirror_switching = "Mirror \"{old}\" failed, switching to mirror \"{new}\" and retrying...",
    mirror_exhausted = "All mirrors failed to install {package_name}.",
)



legacy_trt = SN(
    unsupported_version = "TensorRT {version} is not supported by the ZIP installer.",
    download_start = "Downloading {filename} from NVIDIA...",
    download_progress = "Downloaded {downloaded:.1f}/{total:.1f} MB ({percent:.1f}%)",
    download_progress_unknown = "Downloaded {downloaded:.1f} MB",
    download_failed = "An error occurred while downloading the TensorRT ZIP: {e}",
    invalid_archive = "The downloaded TensorRT file is not a valid ZIP archive.",
    install_wheel = "Installing TensorRT Python wheel: {filename}",
    invalid_version = "Invalid TensorRT version: {version}",
    runtime_install_failed = "An error occurred while deploying TensorRT DLLs: {e}",
    verify_success = "TensorRT {version} load verification succeeded.",
    verify_failed = "TensorRT installation verification failed: {e}",
    success = "TensorRT {version} installation completed.",
    install_failed = "An error occurred while installing legacy TensorRT: {e}",
)



detect_trt = SN(
    start = "Checking whether TensorRT is available...",
    gpu_detected_title = "Detected NVIDIA GPU:",
    select_gpu_prompt = "Select the GPU number to use (0, 1, 2, ...): ",
    select_gpu_try_again = "  Invalid input. Please try again.",
    insufficient_memory = "GPU VRAM {real_vram} GB is below the minimum requirement of {min_vram} GB. Please use another GPU or backend.",
    low_compute_cap = "GPU compute capability {compute_cap} is below the minimum requirement {min_compute_cap}. Please upgrade the GPU or use another backend.",
    invalid_driver_version = "GPU driver version {driver_version} is below the minimum requirement {min_driver_version}. Please upgrade the GPU driver or use another backend.",
)



detect_ncnn = SN(
    start = "Checking whether an NCNN Vulkan GPU is available...",
    loader_unavailable = "The system Vulkan Loader was not found. Install or update the GPU driver.",
    api_unavailable = "The system Vulkan Loader does not provide the required Vulkan 1.0 API.",
    no_compute_gpu = "No integrated or discrete GPU with a Vulkan compute queue was detected.",
    no_compute_queue = "The GPU has no Vulkan compute queue.",
    check_failed = "An error occurred while checking Vulkan GPUs.",
    gpu_detected_title = "Detected GPU available for NCNN Vulkan:",
    gpu_info = "{index}. {gpu_name}",
)



detect_dml = SN(
    start = "Checking for a DirectX 12 GPU required by DirectML...",
    loader_unavailable = "The system DXGI or Direct3D 12 runtime was not found. Update Windows and the GPU driver.",
    api_unavailable = "The system does not provide the required DXGI or Direct3D 12 API.",
    no_d3d12_gpu = "No hardware GPU capable of creating a Direct3D 12 device was detected. Update the GPU driver or use another backend.",
    device_unavailable = "A Direct3D 12 device could not be created.",
    check_failed = "An error occurred while checking DirectX 12 GPUs.",
    gpu_detected_title = "Detected DirectX 12 GPU available for DirectML:",
    gpu_info = "{index}. {gpu_name}",
)



modify_ultralytics_for_dml = SN(
    file_not_exist = "Target file {file} does not exist.",
    modify_failed = "An error occurred while replacing files: {e}",
)
