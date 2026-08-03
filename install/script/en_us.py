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
TensorRT can use NVIDIA GPUs for inference acceleration, significantly improving inference speed.
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



ask_install_dml = SN(
    prompt = """
DirectML can use GPUs from multiple brands (such as AMD, Intel, and NVIDIA) for hardware acceleration.
Do you want to install DirectML?

If you have a GPU that supports DirectML and performs significantly better than the CPU, it is highly recommended to choose \"Yes\".
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
