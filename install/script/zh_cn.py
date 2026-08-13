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
    detect_dml_failed = "检测到 DirectML 不可用。",
    detect_ncnn_failed = "检测到 NCNN 不可用。",
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



choose_backend = SN(
    detect_start = "正在检测所有推理后端和显卡...",
    summary_title = "推理后端检测结果：",
    available = "可用",
    unavailable = "不可用",
    unavailable_with_reason = "不可用：{reason}",
    backend_status = "{backend}：{status}",
    backend_reason = "  原因：{reason}",
    gpu_status = "  GPU {index}：{gpu_name}{details} —— {status}",
    gpu_unavailable = "不可用：{reason}",
    nvidia_gpu_details = "，显存 {vram} GB，SM {compute_cap}，驱动 {driver}，配置 {config}",
    cpu_backend = "PyTorch CPU",
    trt_backend = "TensorRT",
    pytorch_cuda_backend = "PyTorch CUDA",
    dml_backend = "DirectML",
    ncnn_backend = "NCNN Vulkan",
    no_available_gpu = "没有可用的 GPU。",
    no_gpu_detected = "没有检测到目标 GPU。",
    unknown_detection_error = "检测失败。",
    detection_exception = "{backend} 检测时发生异常：{error}",
    backend_menu_title = "请选择要安装的推理后端：",
    backend_option = "{index}. {backend} [{status}]",
    backend_recommendation = "推荐安装 {backend}（此为默认选项）",
    backend_prompt = "请输入后端编号（1, 2, 3, ...）\n-> ",
    exit_option = "6. 退出",
    invalid_backend_choice = "输入无效，请重新输入。",
    backend_not_available = "该后端不可用，请选择可用后端。",
    backend_selection_failed = "后端选择失败。",
    user_cancelled = "用户取消了后端选择。",
    trt_not_available = "没有可用的 NVIDIA 显卡。",
    trt_selection_failed = "TensorRT 显卡配置选择失败。",
    trt_gpu_menu_title = "检测到多张配置不同的可用 NVIDIA 显卡，请选择显卡：",
    trt_gpu_option = "{index}. {gpu_name}，显存 {vram} GB，SM {compute_cap}，驱动 {driver}，配置 {config}",
    trt_gpu_prompt = "请输入显卡编号（0, 1, 2, ...）\n-> ",
    pytorch_cuda_not_available = "没有可用于 PyTorch CUDA 的 NVIDIA 显卡。",
    pytorch_cuda_selection_failed = "PyTorch CUDA 显卡配置选择失败。",
    pytorch_cuda_gpu_menu_title = "检测到多张配置不同的可用 NVIDIA 显卡，请选择 PyTorch CUDA 使用的安装配置：",
    pytorch_cuda_gpu_option = "{index}. {gpu_name}，显存 {vram} GB，SM {compute_cap}，驱动 {driver}，配置 {config}",
    pytorch_cuda_gpu_prompt = "请输入显卡编号（0, 1, 2, ...）\n-> ",
    invalid_gpu_choice = "输入无效，请重新输入。",
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



legacy_trt = SN(
    unsupported_version = "不支持通过 ZIP 安装 TensorRT {version}。",
    download_start = "正在从 NVIDIA 官网下载 {filename}...",
    download_progress = "已下载 {downloaded:.1f}/{total:.1f} MB ({percent:.1f}%)",
    download_progress_unknown = "已下载 {downloaded:.1f} MB",
    download_failed = "下载 TensorRT ZIP 时发生错误: {e}",
    invalid_archive = "下载的 TensorRT 文件不是有效的 ZIP 归档。",
    install_wheel = "正在安装 TensorRT Python wheel: {filename}",
    invalid_version = "TensorRT 版本格式无效: {version}",
    runtime_install_failed = "部署 TensorRT DLL 时发生错误: {e}",
    verify_success = "TensorRT {version} 加载验证成功。",
    verify_failed = "TensorRT 安装验证失败: {e}",
    success = "TensorRT {version} 安装完成。",
    install_failed = "安装旧版 TensorRT 时发生错误: {e}",
)



detect_trt = SN(
    start="正在检测 TensorRT 是否可用...",
    gpu_detected_title="检测到 NVIDIA 显卡:",
    select_gpu_prompt="请选择要使用的显卡编号 (0, 1, 2, ...): ",
    select_gpu_try_again="  输入无效，请重新输入。",
    insufficient_memory="显卡的显存 {real_vram} GB 低于最低要求 {min_vram} GB，请更换显卡或使用其他后端。",
    low_compute_cap="显卡的计算能力 {compute_cap} 低于最低要求 {min_compute_cap}, 请升级显卡或使用其他后端。",
    invalid_driver_version="显卡的驱动版本 {driver_version} 低于最低要求 {min_driver_version}, 请升级显卡驱动或使用其他后端。",
)



detect_pytorch_cuda = SN(
    low_compute_cap = "显卡的计算能力 {compute_cap} 低于最低要求 {min_compute_cap}，请升级显卡或使用其他后端。",
    invalid_driver_version = "显卡的驱动版本 {driver_version} 低于最低要求 {min_driver_version}，请升级显卡驱动或使用其他后端。",
)



detect_ncnn = SN(
    start = "正在检测 NCNN Vulkan GPU 是否可用...",
    loader_unavailable = "未找到系统 Vulkan Loader，请安装或升级显卡驱动。",
    api_unavailable = "系统 Vulkan Loader 缺少必要的 Vulkan 1.0 API。",
    no_compute_gpu = "未检测到具有 Vulkan 计算队列的独立或集成 GPU。",
    no_compute_queue = "没有 Vulkan 计算队列。",
    check_failed = "检测 Vulkan GPU 时发生错误。",
    gpu_detected_title = "检测到可用于 NCNN Vulkan 的 GPU:",
    gpu_info = "{index}. {gpu_name}",
)



detect_dml = SN(
    start = "正在检测 DirectML 所需的 DirectX 12 GPU...",
    loader_unavailable = "未找到系统 DXGI 或 Direct3D 12 运行库，请更新 Windows 和显卡驱动。",
    api_unavailable = "系统缺少所需的 DXGI 或 Direct3D 12 API。",
    no_d3d12_gpu = "未检测到可创建 Direct3D 12 设备的硬件 GPU，请更新显卡驱动或使用其他后端。",
    device_unavailable = "无法创建 Direct3D 12 设备。",
    check_failed = "检测 DirectX 12 GPU 时发生错误。",
    gpu_detected_title = "检测到可用于 DirectML 的 DirectX 12 GPU:",
    gpu_info = "{index}. {gpu_name}",
)



modify_ultralytics_for_dml = SN(
    file_not_exist = "目标文件 {file} 不存在。",
    modify_failed = "替换文件时发生错误: {e}",
)
