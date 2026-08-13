from dataclasses import dataclass
from .detect_nvidia import NvidiaGpuInfo, get_nvidia_gpu_info
from .op_result import OpResult, ok, err

# 最低显存需要 3GB
MIN_TRT_VRAM_MIB = 3 * 1024


def _format_mb_to_gb(mib: int) -> str:
    # 最多 1 位小数，整数时去掉 ".0"
    text = f"{mib / 1024:.1f}"
    return text[:-2] if text.endswith(".0") else text

@dataclass
class tensorrt_config:
    compute_capability:  tuple[int, int] 
    win_driver_ver:      tuple[int, int]
    torch_ver:           str
    torch_cuda_ver:      str
    torchvision_ver:     str
    onnxruntime_gpu_ver: str
    tensorRT_ver:        str
    is_trt_legacy:       bool
    numpy_ver:           str
    opencv_ver:          str


@dataclass
class TensorRTGpuDetection:
    gpu_name: str
    compute_capability: tuple[int, int]
    driver_version: tuple[int, int]
    vram_mib: int
    is_available: bool
    reason: str | None = None
    config: tensorrt_config | None = None


# 以 sm 从高到低排序
tensorrt_config_list: list[tensorrt_config] = [

    # sm7.5, Turing and later
    tensorrt_config( 
        compute_capability= (7, 5),
        win_driver_ver=     (572, 61),
        torch_ver=          "2.10.0",
        torch_cuda_ver=     "cu128",
        torchvision_ver=    "0.25.0",
        onnxruntime_gpu_ver="1.24.4",
        tensorRT_ver=       "10.15.1.29",
        is_trt_legacy=      False,
        numpy_ver=          "2.4.3",
        opencv_ver=         "5.0.0.93",
    ),

    # sm6.0 Pascal & sm7.0 Volta
    tensorrt_config( 
        compute_capability= (6, 0),
        win_driver_ver=     (452, 39),
        torch_ver=          "2.3.1",      # 最后 cudnn 8 的版本
        torch_cuda_ver=     "cu118",
        torchvision_ver=    "0.18.1",
        onnxruntime_gpu_ver="1.18.1",     # 最后 cuda 11 的版本
        tensorRT_ver=       "8.6.1",      # 最后支持 sm6.0 的版本
        is_trt_legacy=      True,
        numpy_ver=          "1.26.4",     # 最后 1.x 版本，旧版 onnxruntime-gpu 需要
        opencv_ver=         "4.11.0.86",  # 最后符合 numpy < 2.0 的 opencv
    ),

    # 已禁用，因为 trt 8.5.3 zip 需要登录英伟达账户才能下载
    # # sm5.0 Maxwell
    # tensorrt_config( 
    #     compute_capability= (5, 0),
    #     win_driver_ver=     (452, 39),
    #     torch_ver=          "2.3.1",      # 最后 cudnn 8 的版本
    #     torch_cuda_ver=     "cu118",
    #     torchvision_ver=    "0.18.1",
    #     onnxruntime_gpu_ver="1.18.1",     # 最后 cuda 11 的版本
    #     tensorRT_ver=       "8.5.3.1",    # 最后支持 sm5.0 的版本
    #     is_trt_legacy=      True,
    #     numpy_ver=          "1.26.4",     # 最后 1.x 版本，旧版 onnxruntime-gpu 需要
    #     opencv_ver=         "4.11.0.86",  # 最后符合 numpy < 2.0 的 opencv
    # ),
]




def detect_trt_availability(
    T,
    gpus: list[NvidiaGpuInfo] | None = None,
) -> OpResult[list[TensorRTGpuDetection]]:
    """detect_trt.py 主入口"""

    if gpus is None:
        result = get_nvidia_gpu_info()
        if not result.is_ok:
            return err("Failed to get nvidia gpu info.", inner=result)
        gpus = result.value
    if gpus is None:
        return err("NVIDIA GPU detection did not contain a value.")

    detections = []
    for gpu in gpus:
        config, reason = _check_gpu(
            T,
            gpu.compute_capability,
            gpu.driver_version,
            gpu.vram_mib,
        )
        detections.append(
            TensorRTGpuDetection(
                gpu_name=gpu.gpu_name,
                compute_capability=gpu.compute_capability,
                driver_version=gpu.driver_version,
                vram_mib=gpu.vram_mib,
                is_available=config is not None,
                reason=reason,
                config=config,
            )
        )

    return ok(detections)
def _check_gpu(
    T,
    compute_cap: tuple[int, int],
    driver_ver: tuple[int, int],
    vram_mib: int,
) -> tuple[tensorrt_config | None, str | None]:
    """
    根据 显存/计算能力/驱动版本 判断显卡是否可用，并返回对应的配置。

    返回配置和不可用原因。
    """

    target_config: tensorrt_config | None = None

    # 检查显存是否达标
    if vram_mib < MIN_TRT_VRAM_MIB:
        return None, T.detect_trt.insufficient_memory.format(
            real_vram=_format_mb_to_gb(vram_mib),
            min_vram=_format_mb_to_gb(MIN_TRT_VRAM_MIB),
        )

    # 计算输入的 compute_cap 属于哪一个配置
    for config in tensorrt_config_list:
        if compute_cap >= config.compute_capability:
            if target_config is None or config.compute_capability > target_config.compute_capability:
                target_config = config
    if target_config is None:
        # 计算能力低于最低配置
        return None, T.detect_trt.low_compute_cap.format(
            compute_cap=f"sm {compute_cap[0]}.{compute_cap[1]}",
            min_compute_cap=f"sm {tensorrt_config_list[-1].compute_capability[0]}.{tensorrt_config_list[-1].compute_capability[1]}",
        )

    # 驱动版本不达标：不允许回退到其他区间，直接判为不可用
    if driver_ver < target_config.win_driver_ver:
        return None, T.detect_trt.invalid_driver_version.format(
            driver_version=f"{driver_ver[0]}.{driver_ver[1]}",
            min_driver_version=f"{target_config.win_driver_ver[0]}.{target_config.win_driver_ver[1]}",
        )

    return target_config, None
