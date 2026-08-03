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

    defaulting = "默认选择简体中文。",
)



main_menu = SN(
    prompt = """
请选择：

1. 安装 HachimiDX (默认)
2. 重新安装模型推理后端
3. 退出

如果你不清楚选项 2 是什么，请不要选择此选项。

-> """,

    defaulting = "默认选择安装 HachimiDX。",
)



reinstall_backend = SN(
    prompt = """
即将卸载当前已安装的后端，再重新进入安装流程。
你确定要继续吗？

1. 否 (默认)
2. 是

-> """,

    abort = "已取消，未做任何更改。",

    start_uninstall = "正在卸载当前后端...",
    uninstall_done = "卸载完成。",
)



install = SN(
    start = "开始安装 HachimiDX...",
    detect_trt_failed = "检测到 TensorRT 不可用。",
    detect_ncnn_failed = "检测到 NCNN Vulkan GPU 不可用。",
    done = "HachimiDX 安装完成。",
)



ask_use_pypi_mirror = SN(
    prompt = """
PyPI 镜像可以显著加速国内的下载和安装。
你是否想使用 PyPI 镜像?

如果你在中国大陆，强烈建议选择"是"。
如果你在其他地区，请选择"否"。

1. 是 (默认)
2. 否
3. 退出

-> """,

    defaulting = "默认选择「是」。",
)



ask_install_trt = SN(
    prompt = """
TensorRT 能够调用 NVIDIA GPU 进行推理加速，显著提升推理速度。
你是否想安装 NVIDIA TensorRT 后端?

如果你有 NVIDIA GPU，强烈建议选择"是"。
其他情况请选择"否"。

1. 是 (默认)
2. 否
3. 退出

-> """,

    defaulting = "默认选择「是」。",
)



ask_continue_install = SN(
    prompt = """
是否继续安装？

1. 否 (默认)
2. 是

-> """,

    defaulting = "默认选择「否」。",
)



ask_install_ncnn = SN(
    prompt = """
NCNN 可以通过 Vulkan 调用 AMD、Intel、NVIDIA 等品牌的 GPU 进行推理加速。
你是否想安装 NCNN Vulkan 后端？

如果你有支持 Vulkan 的 GPU，建议选择"是"。
其他情况请选择"否"。

1. 是 (默认)
2. 否
3. 退出

-> """,

    defaulting = "默认选择「是」。",
)



pip_install = SN(
    mirror_names = {
        "tsinghua": "清华源",
        "tencent": "腾讯云",
        "huawei": "华为云",
        "aliyun": "阿里云",
    },
    start = "正在安装 {package_name}...",
    success = "{package_name} 安装完成。",
    error = "安装 {package_name} 时发生错误: {e}",
    mirror_switching = "镜像「{old}」安装失败，正在切换到镜像「{new}」重试...",
    mirror_exhausted = "所有镜像均无法安装 {package_name}。",
)



detect_trt = SN(
    start="正在检测 TensorRT 是否可用...",
    gpu_detected_title="检测到 NVIDIA 显卡:",
    select_gpu_prompt="请选择要使用的显卡编号 (0, 1, 2, ...): ",
    select_gpu_try_again="  输入无效，请重新输入。",
    low_compute_cap="显卡的计算能力 {compute_cap} 低于最低要求 {min_compute_cap}, 请升级显卡或使用其他后端。",
    invalid_driver_version="显卡的驱动版本 {driver_version} 低于最低要求 {min_driver_version}, 请升级显卡驱动或使用其他后端。",
)



detect_ncnn = SN(
    start = "正在检测 NCNN Vulkan GPU 是否可用...",
    loader_unavailable = "未找到系统 Vulkan Loader，请安装或升级显卡驱动。",
    api_unavailable = "系统 Vulkan Loader 缺少必要的 Vulkan 1.0 API。",
    no_physical_devices = "Vulkan 未检测到任何物理设备。",
    no_compute_gpu = "未检测到具有 Vulkan 计算队列的独立或集成 GPU。",
    check_failed = "检测 Vulkan GPU 时发生错误。",
    gpu_detected_title = "检测到可用于 NCNN Vulkan 的 GPU:",
    gpu_info = "{index}. {gpu_name}, {device_type}, Vulkan {api_version}, vendor 0x{vendor_id:04X}, device 0x{device_id:04X}",
    device_types = {
        "integrated": "集成 GPU",
        "discrete": "独立 GPU",
    },
)
