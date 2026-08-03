from dataclasses import dataclass
import subprocess
from .op_result import OpResult, ok, err, print_op_result

@dataclass
class nvidia_config:
    compute_capability:  tuple[int, int] 
    win_driver_ver:      tuple[int, int]
    torch_ver:           str
    torch_cuda_ver:      str
    torchvision_ver:     str
    onnxruntime_gpu_ver: str
    tensorRT_ver:        str
    numpy_ver:           str


@dataclass
class _gpu_info:
    gpu_name: str
    compute_capability: tuple[int, int]
    driver_version: tuple[int, int]


# 以 sm 从高到低排序
nvidia_config_list: list[nvidia_config] = [

    # sm7.5, Turing and later
    nvidia_config( 
        compute_capability= (7, 5),
        win_driver_ver=     (572, 61),
        torch_ver=          "2.10.0",
        torch_cuda_ver=     "cu128",
        torchvision_ver=    "0.25.0",
        onnxruntime_gpu_ver="1.24.4",
        tensorRT_ver=       "10.15.1.29",
        numpy_ver=          "2.4.3"
    ),

    # sm6.0 Pascal & sm7.0 Volta
    nvidia_config( 
        compute_capability= (6, 0),
        win_driver_ver=     (452, 39),
        torch_ver=          "2.7.1",
        torch_cuda_ver=     "cu118",
        torchvision_ver=    "0.22.1",
        onnxruntime_gpu_ver="1.18.1",
        tensorRT_ver=       "8.6.1",
        numpy_ver=          "2.2.6"
    ),

    # sm5.0 Maxwell
    nvidia_config( 
        compute_capability= (5, 0),
        win_driver_ver=     (452, 39),
        torch_ver=          "2.7.1",
        torch_cuda_ver=     "cu118",
        torchvision_ver=    "0.22.1",
        onnxruntime_gpu_ver="1.18.1",
        tensorRT_ver=       "8.5.3.1",
        numpy_ver=          "2.2.6"
    ),
]




def detect_trt_availability(T) -> OpResult[nvidia_config]:
    """detect_trt.py 主入口"""

    print(f"\n-----\n\n{T.detect_trt.start}\n")

    # 获取 NVIDIA GPU 信息
    result = _get_nvidia_gpu_info(T)
    if not result.is_ok:
        return err("Failed to get nvidia gpu info.", inner=result)
    gpus = result.value

    # 选择要使用的显卡
    if len(gpus) > 1:
        while True:
            try:
                content = input(T.detect_trt.select_gpu_prompt).strip()
                selected_index = int(content)
                if selected_index < 0 or selected_index >= len(gpus):
                    print(T.detect_trt.select_gpu_try_again)
                    continue
                selected_gpu = gpus[selected_index]
                break
            except ValueError:
                print(T.detect_trt.select_gpu_try_again)
                continue
    else:
        selected_gpu = gpus[0]

    # 检查显卡是否可用
    gpu_config = _is_gpu_valid(T, selected_gpu.compute_capability, selected_gpu.driver_version)
    if gpu_config is None:
        return err("Selected GPU is not valid.")
    
    return ok(gpu_config)




def _get_nvidia_gpu_info(T) -> OpResult[list[_gpu_info]]:

    try:
        # 获取 nvidia-smi 输出
        cmd = ["nvidia-smi",
               "--query-gpu=name,compute_cap,driver_version",
               "--format=csv,noheader"]
        try:
            result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        except Exception as e:
            return err("Failed to run nvidia-smi command.", error_raw=e)

        lines = [line for line in result.stdout.splitlines() if line.strip()]
        if not lines:
            return err("No output from nvidia-smi command.")

        # 解析输出
        gpus = []
        for line in lines:
            gpu_name_str, compute_cap_str, driver_version_str = (p.strip() for p in line.split(",", 2))
            compute_cap_parts = compute_cap_str.split(".")
            driver_version_parts = driver_version_str.split(".")
            compute_cap = (int(compute_cap_parts[0]), int(compute_cap_parts[1]))
            driver_version = (int(driver_version_parts[0]), int(driver_version_parts[1]))

            gpu_info = _gpu_info(
                gpu_name=gpu_name_str,
                compute_capability=compute_cap,
                driver_version=driver_version
            )
            gpus.append(gpu_info)

        if not gpus:
            return err("No NVIDIA GPU detected.")
        
        # 打印显卡信息
        print(T.detect_trt.gpu_detected_title)
        index = 0
        for gpu in gpus:
            compute_cap_print = f"sm {gpu.compute_capability[0]}.{gpu.compute_capability[1]}"
            driver_ver_print = f"{gpu.driver_version[0]}.{gpu.driver_version[1]}"
            print(f"{index}. {gpu.gpu_name}, {compute_cap_print}, {driver_ver_print}")
            index += 1
        print()

        return ok(gpus)
    
    except Exception as e:
        return err("Failed to get NVIDIA GPU info.", error_raw=e)





def _is_gpu_valid(T,
                  compute_cap: tuple[int, int],
                  driver_ver:  tuple[int, int],
                 ) -> nvidia_config | None:
    """
    根据计算能力和驱动版本判断显卡是否可用，并返回对应的配置。

    返回：nvidia_config | None: 可用时返回对应的配置，否则返回 None
    """

    target_cfg: nvidia_config | None = None

    # 计算输入的 compute_cap 属于哪一个配置
    for cfg in nvidia_config_list:
        if compute_cap >= cfg.compute_capability:
            if target_cfg is None or cfg.compute_capability > target_cfg.compute_capability:
                target_cfg = cfg
    if target_cfg is None:
        # 计算能力低于最低配置
        print(T.detect_trt.low_compute_cap.format(
            compute_cap=f"sm {compute_cap[0]}.{compute_cap[1]}",
            min_compute_cap=f"sm {nvidia_config_list[-1].compute_capability[0]}.{nvidia_config_list[-1].compute_capability[1]}",
        ))
        return None

    # 驱动版本不达标：不允许回退到其他区间，直接判为不可用
    if driver_ver < target_cfg.win_driver_ver:
        print(T.detect_trt.invalid_driver_version.format(
            driver_version=f"{driver_ver[0]}.{driver_ver[1]}",
            min_driver_version=f"{target_cfg.win_driver_ver[0]}.{target_cfg.win_driver_ver[1]}",
        ))
        return None

    return target_cfg
