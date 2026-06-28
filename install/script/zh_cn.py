# HachimiDX Installer — 简体中文本地化常量

DEFAULTING_YES = "默认选择「是」。"

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
LANGUAGE_DEFAULT = "默认选择简体中文。"





# ===== main menu =====
MAIN_MENU = """
请选择：

1. 安装 HachimiDX (默认)

2. 切换模型推理后端

3. 退出

如果你不清楚选项 2 是什么，请不要选择此选项。

-> """
RESTORE_SUCCESS = "Ultralytics 已恢复到原始状态。"
RESTORE_ERROR = "尝试恢复 ultralytics 时发生错误。"
DEFAULTING_TO_INSTALL = "默认选择安装 HachimiDX。"





# ===== reinstall backend =====
REINSTALL_BACKEND_PROMPT = """
即将执行以下操作：

(1) 撤销 Ultralytics DirectML 修改
(2) 删除 torch & torchvision
(3) 进入安装流程，选择新的后端

此操作会清理当前已安装的后端，之后你可以在安装流程中选择新的后端。

你确定要继续吗？

1. 是
2. 否 (默认)
3. 退出

-> """
REINSTALL_BACKEND_ABORT = "已取消，未做任何更改。"





# ===== ask_use_pypi_mirror =====
PYPI_MIRROR_PROMPT = """
清华/阿里云的 PyPI 镜像可以显著加速国内的下载和安装。
你是否想使用 PyPI 镜像?

如果你在中国大陆，强烈建议选择"是"。
如果你在其他地区，请选择"否"。

1. 是 (默认)
2. 否
3. 退出

-> """





# ===== ask_install_trt =====
TRT_PROMPT = """
NVIDIA TensorRT 能够调用 NVIDIA GPU 进行推理加速，显著提升推理速度。
你是否想安装 NVIDIA TensorRT ?

如果你有 NVIDIA GPU，强烈建议选择"是"。
其他情况请选择"否"。

1. 是 (默认)
2. 否
3. 退出

-> """





# ===== ask_install_dml =====
DML_PROMPT = """
DirectML 能够调用多个品牌的 GPU（如 AMD、Intel、NVIDIA 等）进行硬件加速。
你是否想安装 DirectML ?

如果你有支持 DirectML 的 GPU，并且性能显著优于 CPU，强烈建议选择"是"。
其他情况请选择"否"。

1. 是 (默认)
2. 否
3. 退出

-> """





# ===== uninstall_torch_torchvision =====
UNINSTALL_TORCH_START = "正在删除 torch 和 torchvision..."
UNINSTALL_TORCH_NONE = "torch 和 torchvision 均未安装，无需删除。"
UNINSTALL_TORCH_ONLY_NOT = "torch 未安装，torchvision 已删除。"
UNINSTALL_TORCHVISION_ONLY_NOT = "torchvision 未安装，torch 已删除。"
UNINSTALL_TORCH_DONE = "torch 和 torchvision 已删除。"





# ===== GPU detection =====
GPU_DETECTED = "检测到显卡: {gpu_name}"
GPU_NOT_DETECTED = "未检测到 NVIDIA 显卡。"
CUDA_NOT_DETECTED = "无法从 nvidia-smi 输出中检测到 CUDA 版本。"
CUDA_VERSION = "CUDA 版本: {cuda_version}"
DRIVER_NOT_DETECTED = "无法从 nvidia-smi 输出中检测到显卡驱动版本。"
DRIVER_VERSION = "显卡驱动版本: {driver_full}"





# ===== _find_compatible_cuda =====
COMPATIBLE_CUDA_FOUND = "-> 找到兼容的 PyTorch CUDA 版本: {final_cuda}"
COMPATIBLE_CUDA_NOT_FOUND = (
    "-> 未找到兼容的 PyTorch CUDA 版本。\n"
    "   最低支持: CUDA >= {min_cuda}，驱动 >= {min_driver}.x\n"
    "   回退到 PyTorch CPU 版本。"
)





# ===== modify_ultralytics_for_dml =====
MODIFY_TARGET_NOT_EXIST = "modify_ultralytics_for_dml(): 错误: 目标文件 {file} 不存在。"
MODIFY_REPLACE_MODIFIED_ERROR = "modify_ultralytics_for_dml(): 替换为修改后的文件时发生错误: {e}"
MODIFY_REPLACE_ORIGINAL_ERROR = "modify_ultralytics_for_dml(): 替换为原始文件时发生错误: {e}"





# ===== general_pip_install =====
PIP_INSTALLING = "正在安装 {package_name}..."
PIP_SUCCESS = "{package_name} 安装成功完成。"
PIP_ERROR = "安装 {package_name} 时发生错误: {e}"
