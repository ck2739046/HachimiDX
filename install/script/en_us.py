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



ask_install_trt = SN(
    prompt = """
TensorRT can use NVIDIA GPUs for model inference acceleration.
Do you want to install NVIDIA TensorRT?

If you have an NVIDIA GPU, it is highly recommended to choose \"Yes\".
In other cases, please choose \"No\".

1. Yes (Default)
2. No
3. Exit

-> """,

    defaulting = "Defaulting to Yes.",
)



ask_continue_install = SN(
    prompt = """
Do you want to continue the installation?

1. No (Default)
2. Yes

-> """,

    defaulting = "Defaulting to No.",
)



ask_install_ncnn = SN(
    prompt = """
NCNN can use GPUs through Vulkan for model inference acceleration.
Do you want to install the NCNN?

If you have a Vulkan-capable GPU, it is highly recommended to choose \"Yes\".
In other cases, please choose \"No\".

1. Yes (Default)
2. No
3. Exit

-> """,

    defaulting = "Defaulting to Yes.",
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



detect_trt = SN(
    start = "Checking whether TensorRT is available...",
    gpu_detected_title = "Detected NVIDIA GPU:",
    select_gpu_prompt = "Select the GPU number to use (0, 1, 2, ...): ",
    select_gpu_try_again = "  Invalid input. Please try again.",
    low_compute_cap = "GPU compute capability {compute_cap} is below the minimum requirement {min_compute_cap}. Please upgrade the GPU or use another backend.",
    invalid_driver_version = "GPU driver version {driver_version} is below the minimum requirement {min_driver_version}. Please upgrade the GPU driver or use another backend.",
)



detect_ncnn = SN(
    start = "Checking whether an NCNN Vulkan GPU is available...",
    loader_unavailable = "The system Vulkan Loader was not found. Install or update the GPU driver.",
    api_unavailable = "The system Vulkan Loader does not provide the required Vulkan 1.0 API.",
    no_compute_gpu = "No integrated or discrete GPU with a Vulkan compute queue was detected.",
    check_failed = "An error occurred while checking Vulkan GPUs.",
    gpu_detected_title = "Detected GPU available for NCNN Vulkan:",
    gpu_info = "{index}. {gpu_name}",
)



detect_dml = SN(
    start = "Checking for a DirectX 12 GPU required by DirectML...",
    loader_unavailable = "The system DXGI or Direct3D 12 runtime was not found. Update Windows and the GPU driver.",
    api_unavailable = "The system does not provide the required DXGI or Direct3D 12 API.",
    no_d3d12_gpu = "No hardware GPU capable of creating a Direct3D 12 device was detected. Update the GPU driver or use another backend.",
    check_failed = "An error occurred while checking DirectX 12 GPUs.",
    gpu_detected_title = "Detected DirectX 12 GPU available for DirectML:",
    gpu_info = "{index}. {gpu_name}",
)



ask_install_dml = SN(
    prompt = """
DirectML can use GPUs for model inference acceleration.
Do you want to install DirectML?

If you have a DX12-capable GPU, it is highly recommended to choose \"Yes\".
In other cases, please choose \"No\".

1. Yes (Default)
2. No
3. Exit

-> """,

    defaulting = "Defaulting to Yes.",
)



modify_ultralytics_for_dml = SN(
    file_not_exist = "Target file {file} does not exist.",
    modify_failed = "An error occurred while replacing files: {e}",
)
