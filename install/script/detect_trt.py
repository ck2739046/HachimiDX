from dataclasses import dataclass
import subprocess

@dataclass
class nvidia_config:
    compute_capability:  tuple[int, int]
    cuda_ver:            tuple[int, int]
    win_driver_ver:      tuple[int, int]
    torch_ver:           str
    torchvision_ver:     str
    onnxruntime_gpu_ver: str
    tensorRT_ver:        str
    numpy_ver:           str


# 以 sm 从高到低排序
nvidia_config_list: list[nvidia_config] = [

    # sm7.5, Turing and later
    nvidia_config( 
        compute_capability= (7, 5),
        cuda_ver=           (12, 8),
        win_driver_ver=     (572, 61),
        torch_ver=          "2.10.0+cu128",
        torchvision_ver=    "0.25.0",
        onnxruntime_gpu_ver="1.24.4",
        tensorRT_ver=       "10.15.1.29",
        numpy_ver=          "2.4.3"
    ),

    # sm6.0 Pascal & sm7.0 Volta
    nvidia_config( 
        compute_capability= (6, 0),
        cuda_ver=           (11, 8),
        win_driver_ver=     (452, 39),
        torch_ver=          "2.7.1+cu118",
        torchvision_ver=    "0.22.1",
        onnxruntime_gpu_ver="1.18.1",
        tensorRT_ver=       "8.6.1",
        numpy_ver=          "2.2.6"
    ),

    # sm5.0 Maxwell
    nvidia_config( 
        compute_capability= (5, 0),
        cuda_ver=           (11, 8),
        win_driver_ver=     (452, 39),
        torch_ver=          "2.7.1+cu118",
        torchvision_ver=    "0.22.1",
        onnxruntime_gpu_ver="1.18.1",
        tensorRT_ver=       "8.5.3.1",
        numpy_ver=          "2.2.6"
    ),
]




def main(T) -> nvidia_config | None:
    """detect_trt.py 主入口"""
    info = _get_nvidia_gpu_info(T)
    if info is None:
        return None
    _, compute_cap, driver_version = info
    valid, cfg = _is_gpu_valid(T, compute_cap, driver_version)
    return cfg if valid else None



def _get_nvidia_gpu_info(T) -> tuple[str, tuple[int, int], tuple[int, int]] | None:
    """
    返回:
    - gpu_name: str
    - compute_capability: tuple[int, int]
    - driver_version: tuple[int, int]
    """

    try:
        # 获取输出
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,compute_cap,driver_version", "--format=csv,noheader"],
            capture_output=True, text=True
        )
        stdout = result.stdout.strip()
        if not stdout:
            return None
        
        # 仅取第一张显卡
        first_line = stdout.splitlines()[0]

        # 解析数据
        gpu_name_str, compute_cap_str, driver_version_str = (p.strip() for p in first_line.split(",", 2))
        compute_cap_parts = compute_cap_str.split(".")
        driver_version_parts = driver_version_str.split(".")
        compute_cap = (int(compute_cap_parts[0]), int(compute_cap_parts[1]))
        driver_version = (int(driver_version_parts[0]), int(driver_version_parts[1]))

        print(T.detect_trt._get_nvidia_gpu_info.success.format(
                  gpu_name=gpu_name_str,
                  compute_cap=f"sm {compute_cap[0]}.{compute_cap[1]}",
                  driver_version=f"{driver_version[0]}.{driver_version[1]}",
             ))
        return gpu_name_str, compute_cap, driver_version
    
    except Exception as e:
        print(f"Error in _get_nvidia_gpu_info(): {e}")
        return None



def _is_gpu_valid(T,
                  compute_cap: tuple[int, int],
                  driver_ver:  tuple[int, int],
                 ) -> tuple[bool, nvidia_config | None]:
    """
    根据计算能力和驱动版本判断显卡是否可用，并返回对应的配置。

    返回：
    - bool: 是否可用
    - nvidia_config | None: 可用时返回对应的配置，否则返回 None
    """

    target_cfg: nvidia_config | None = None

    # 计算输入的 compute_cap 属于哪一个配置
    for cfg in nvidia_config_list:
        if compute_cap >= cfg.compute_capability:
            if target_cfg is None or cfg.compute_capability > target_cfg.compute_capability:
                target_cfg = cfg
    if target_cfg is None:
        # 计算能力低于最低配置
        print(T.detect_trt._is_gpu_valid.low_compute_cap.format(
            compute_cap=f"sm {compute_cap[0]}.{compute_cap[1]}",
            min_compute_cap=f"sm {nvidia_config_list[-1].compute_capability[0]}.{nvidia_config_list[-1].compute_capability[1]}",
        ))
        return False, None

    # 驱动版本不达标：不允许回退到其他区间，直接判为不可用
    if driver_ver < target_cfg.win_driver_ver:
        print(T.detect_trt._is_gpu_valid.invalid_driver_version.format(
            driver_version=f"{driver_ver[0]}.{driver_ver[1]}",
            min_driver_version=f"{target_cfg.win_driver_ver[0]}.{target_cfg.win_driver_ver[1]}",
        ))
        return False, None

    return True, target_cfg
