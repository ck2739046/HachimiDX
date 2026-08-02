from types import SimpleNamespace as SN

# HachimiDX Installer — English locale constants

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





DEFAULTING_YES = "Defaulting to Yes."
INSTALL_DONE = "\n\n-----\n\nHachimiDX installation completed\n"

# ===== ask_language =====
LANGUAGE_PROMPT = """
Please select your language:
1. Simplified Chinese (Default)
2. English
3. Exit

请选择语言：
1. 简体中文 (默认)
2. 英语
3. 退出

-> """
LANGUAGE_DEFAULT = "Defaulting to Simplified Chinese."





# ===== main menu =====
MAIN_MENU = """
Please select an option:

1. Install HachimiDX (Default)
2. Switch model inference backend
3. Exit

Please don't choose option "2" if you don't know what it is.

-> """
RESTORE_SUCCESS = "Ultralytics has been restored to its original state."
RESTORE_ERROR = "An error occurred while trying to restore ultralytics."
DEFAULTING_TO_INSTALL = "Defaulting to Install HachimiDX."





# ===== reinstall backend =====
REINSTALL_BACKEND_PROMPT = """
The following actions will be performed:

(1) Undo Ultralytics DirectML Modification
(2) Uninstall torch & torchvision
(3) Start the installation flow to choose a new backend

This will clean up the currently installed backend so you can choose a new one during the installation.

Are you sure you want to continue?

1. Yes
2. No (Default)

-> """
REINSTALL_BACKEND_ABORT = "Aborted. No changes were made."





# ===== install =====
INSTALL_STARTING = "Starting HachimiDX installation..."





# ===== CUDA fallback =====
CUDA_FALLBACK_PROMPT = """
No compatible PyTorch CUDA version detected, falling back to PyTorch CPU version.
Do you want to continue the installation?

1. Yes (Default)
2. No (Exit)

-> """





# ===== ask_use_pypi_mirror =====
PYPI_MIRROR_PROMPT = """
PyPI mirrors can significantly speed up downloads and installations in China.
Do you want to use PyPI mirror?

If you are in mainland China, it is highly recommended to choose "Yes".
If you are in other regions, please choose "No".

1. Yes (Default)
2. No
3. Exit

-> """





# ===== ask_install_trt =====
TRT_PROMPT = """
NVIDIA TensorRT can leverage NVIDIA GPUs for inference acceleration, significantly improving inference speed.
Do you want to install NVIDIA TensorRT?

If you have an NVIDIA GPU, it is highly recommended to choose "Yes".
In other cases, please choose "No".

1. Yes (Default)
2. No
3. Exit

-> """





# ===== ask_install_dml =====
DML_PROMPT = """
DirectML can leverage GPUs from multiple brands (such as AMD, Intel, NVIDIA, etc.) for hardware acceleration.
Do you want to install DirectML?

If you have a GPU that supports DirectML and offers significantly better performance than CPU, it is highly recommended to choose "Yes".
In other cases, please choose "No".

1. Yes (Default)
2. No
3. Exit

-> """





# ===== uninstall_torch_torchvision =====
UNINSTALL_TORCH_START = "Uninstalling torch, torchvision, onnxruntime-gpu, onnxruntime-directml, tensorrt, numpy..."
UNINSTALL_TORCH_DONE = "Uninstall completed."





# ===== GPU detection =====
GPU_DETECTED = "Detected GPU: {gpu_name}"
GPU_NOT_DETECTED = "No NVIDIA GPU detected."
CUDA_NOT_DETECTED = "Could not detect CUDA version from nvidia-smi output."
CUDA_VERSION = "CUDA version: {cuda_version}"
DRIVER_NOT_DETECTED = "Could not detect Driver Version from nvidia-smi output."
DRIVER_VERSION = "Driver version: {driver_full}"





# ===== _find_compatible_cuda =====
COMPATIBLE_CUDA_FOUND = "-> Compatible PyTorch CUDA version found: {final_cuda}"
COMPATIBLE_CUDA_NOT_FOUND = (
    "-> No compatible PyTorch CUDA version found.\n"
    "   Minimum supported: CUDA >= {min_cuda}, Driver >= {min_driver}.x\n"
    "   Falling back to PyTorch CPU version"
)





# ===== modify_ultralytics_for_dml =====
MODIFY_TARGET_NOT_EXIST = "modify_ultralytics_for_dml(): Error: Target file {file} does not exist."
MODIFY_REPLACE_MODIFIED_ERROR = "modify_ultralytics_for_dml(): Error replacing with modified files: {e}"
MODIFY_REPLACE_ORIGINAL_ERROR = "modify_ultralytics_for_dml(): Error replacing with original files: {e}"





# ===== general_pip_install =====
PIP_INSTALLING = "Installing {package_name}..."
PIP_SUCCESS = "{package_name} installation completed successfully."
PIP_ERROR = "Error occurred while installing {package_name}: {e}"
MIRROR_NAMES = {
    "tsinghua": "TUNA",
    "tencent": "Tencent Cloud",
    "huawei": "Huawei Cloud",
    "aliyun": "Alibaba Cloud",
}
MIRROR_SWITCHING = 'Mirror "{old}" failed, switching to mirror "{new}" and retrying...'
MIRROR_EXHAUSTED = "All mirrors failed to install {package_name}."
