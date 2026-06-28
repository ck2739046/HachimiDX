import sys
import re
import subprocess
from pathlib import Path
import shutil

import en_us
import zh_cn

# 全局变量
USE_PyPI_Mirror = ""
T = None  # locale module, set after language selection

QingHua_PyPI_Mirror = ["-i", "https://pypi.tuna.tsinghua.edu.cn/simple"]

ROOT = Path(__file__).resolve().parents[2] # 往上三级目录


# CUDA 版本对应的最低驱动版本要求
# 格式为 (CUDA 版本, 驱动主版本号)
# 从低到高排列
CUDA_DRIVER_REQUIREMENTS = [
    (11.8, 453),
    (12.6, 561),
    (12.8, 572),
    (13.0, 580),
]




def main():

    # generate by https://patorjk.com/software/taag using font "Terrace"
    logo = """

    ░██     ░██                       ░██        ░██                ░██     ░███████   ░██    ░██ 
    ░██     ░██                       ░██                                   ░██   ░██   ░██  ░██  
    ░██     ░██  ░██████    ░███████  ░████████  ░██░█████████████  ░██     ░██    ░██   ░██░██   
    ░██████████       ░██  ░██    ░██ ░██    ░██ ░██░██   ░██   ░██ ░██     ░██    ░██    ░███    
    ░██     ░██  ░███████  ░██        ░██    ░██ ░██░██   ░██   ░██ ░██     ░██    ░██   ░██░██   
    ░██     ░██ ░██   ░██  ░██    ░██ ░██    ░██ ░██░██   ░██   ░██ ░██     ░██   ░██   ░██  ░██  
    ░██     ░██  ░█████░██  ░███████  ░██    ░██ ░██░██   ░██   ░██ ░██     ░███████   ░██    ░██ 

    """

    print(logo)

    # ask language
    global T
    T = ask_language()

    print("\n-----")
    choice = input(T.MAIN_MENU).strip()
    if choice == "1":
        install()
    elif choice == "2":
        success = modify_ultralytics_for_dml(recover=True)
        if success:
            print(T.RESTORE_SUCCESS)
        else:
            print(T.RESTORE_ERROR)
    elif choice == "3":
        uninstall_torch_torchvision()
    elif choice == "4":
        sys.exit(0)
    else:
        print(T.DEFAULTING_TO_INSTALL)
        install()





def uninstall_torch_torchvision():
    print(f"\n-----\n{T.UNINSTALL_TORCH_START}\n")
    cmd = [sys.executable, "-m", "pip", "uninstall", "torch", "torchvision", "-y"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        combined = result.stdout + result.stderr
        print(combined)
        # 检查是否两个包都显示 "not installed"
        torch_not_installed = "Skipping torch as it is not installed" in combined
        torchvision_not_installed = "Skipping torchvision as it is not installed" in combined
        if torch_not_installed and torchvision_not_installed:
            msg = T.UNINSTALL_TORCH_NONE
        elif torch_not_installed:
            msg = T.UNINSTALL_TORCH_ONLY_NOT
        elif torchvision_not_installed:
            msg = T.UNINSTALL_TORCHVISION_ONLY_NOT
        else:
            msg = T.UNINSTALL_TORCH_DONE
        print(f"\n-----\n{msg}\n")
    except Exception as e:
        print(f"\n-----\nError: {e}\n")



def install():
    global USE_PyPI_Mirror
    
    # ask if use PyPI Mirror
    USE_PyPI_Mirror = ask_use_pypi_mirror()

    # define pytorch version
    torch_version = "cpu" # default
    install_trt = ask_install_trt()
    if install_trt:
        new_torch_version = detect_cuda_version_for_torch()
        if new_torch_version:
            torch_version = new_torch_version

    # install pytorch
    is_success = install_pytorch(torch_version)
    if not is_success: sys.exit(1)

    # install ultralytics + onnxruntime
    is_success = install_ultralytics_onnx(install_trt)
    if not is_success: sys.exit(1)

    # model inference acceleration
    if torch_version.startswith("cu"):
        # install TensorRT
        is_success = install_tensorrt(torch_version)
        if not is_success: sys.exit(1)
    else:
        # install DirectML + onnxruntime + modify ultralytics
        install_dml = ask_install_dml()
        if install_dml:
            is_success = install_directml_onnx()
            if not is_success: sys.exit(1)
        
    # install others
    dependencies = [
        "PyQt6==6.10.2",
        "pywin32==311",
        "librosa==0.11.0",
        "pydantic==2.12.5",
        "python-i18n==0.3.9",
        "nanoid==2.0.0",
        "filterpy==1.4.5",
    ]
    cmd = [sys.executable, "-m", "pip", "install", *dependencies, "--no-warn-script-location"]
    if USE_PyPI_Mirror:
        cmd += QingHua_PyPI_Mirror
    is_success = general_pip_install("Other dependencies", cmd)
    if not is_success: sys.exit(1)

    # 解决 pywin32 导入错误
    cmd = [sys.executable, str(ROOT / "python" / "Scripts" / "pywin32_postinstall.py"), "-install"]
    subprocess.run(cmd, capture_output=True) # 隐藏输出
    





def ask_language():
    print("\n-----")
    language = input(en_us.LANGUAGE_PROMPT).strip()
    if language == "1":
        return zh_cn
    elif language == "2":
        return en_us
    elif language == "3":
        sys.exit(0)
    else:
        print(en_us.LANGUAGE_DEFAULT)
        return zh_cn
    



def ask_use_pypi_mirror() -> bool:
    print("\n-----")
    use_mirror = input(T.PYPI_MIRROR_PROMPT).strip()
    if use_mirror == "1":
        return True
    elif use_mirror == "2":
        return False
    elif use_mirror == "3":
        sys.exit(0)
    else:
        print(T.DEFAULTING_YES)
        return True




def ask_install_trt() -> bool:
    print("\n-----")
    install_trt = input(T.TRT_PROMPT).strip()
    if install_trt == "1":
        return True
    elif install_trt == "2":
        return False
    elif install_trt == "3":
        sys.exit(0)
    else:
        print(T.DEFAULTING_YES)
        return True




def _get_installed_nvidia_gpu_name() -> str | None:
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True, text=True
        )
        gpu_name = result.stdout.strip()
        if gpu_name:
            print(T.GPU_DETECTED.format(gpu_name=gpu_name))
            return gpu_name
        else:
            print(T.GPU_NOT_DETECTED)
            return None
    except Exception as e:
        print(f"Error running nvidia-smi: {e}")
        return None




def _get_cuda_and_driver_version() -> tuple[str, str]:
    try:
        result = subprocess.run(["nvidia-smi"], capture_output=True, text=True)
        output = result.stdout

        # 使用正则表达式提取 CUDA 版本
        # NVIDIA 600 系列新驱动输出格式变更：CUDA UMD Version（优先匹配）
        # 兼容旧驱动格式：CUDA Version
        match_cuda = (
            re.search(r"CUDA UMD Version:\s+(\d+\.\d+)", output)
            or re.search(r"CUDA Version:\s+(\d+\.\d+)", output)
        )
        if not match_cuda:
            print(T.CUDA_NOT_DETECTED)
            return (None, None)

        cuda_version = match_cuda.group(1).strip()
        print(T.CUDA_VERSION.format(cuda_version=cuda_version))

        # 使用正则表达式提取驱动版本
        # NVIDIA 600 系列新驱动格式变更：KMD Version（优先匹配）
        # 兼容旧驱动格式：Driver Version
        match_driver = (
            re.search(r"KMD Version:\s+(\d+)\.(\d+)", output)
            or re.search(r"Driver Version:\s+(\d+)\.(\d+)", output)
        )
        if not match_driver:
            print(T.DRIVER_NOT_DETECTED)
            return (None, None)

        driver_full = f"{match_driver.group(1)}.{match_driver.group(2)}"
        print(T.DRIVER_VERSION.format(driver_full=driver_full))

    except Exception as e:
        print(f"Error running nvidia-smi: {e}")
        return (None, None)
    
    return (cuda_version, driver_full)




def _find_compatible_cuda(input_cuda: str, input_driver: str) -> str | None:
    """
    根据 CUDA 版本和驱动主版本号，查找兼容的最高 CUDA 版本。
    返回 cuXXX 字符串，若全部不满足则返回 None。
    """
    input_cuda_10x = round(float(input_cuda) * 10)
    input_driver_major = int(input_driver.split(".")[0])

    highest_cuda_1 = -1
    highest_cuda_2 = -1
    for candidate_cuda, candidate_driver_major in CUDA_DRIVER_REQUIREMENTS:
        candidate_cuda_10x = round(float(candidate_cuda) * 10)
        # 检查 cuda 版本
        if input_cuda_10x >= candidate_cuda_10x: # valid
            if candidate_cuda_10x > highest_cuda_1:
                highest_cuda_1 = candidate_cuda_10x # update highest 1
        # 检查驱动版本
        if input_driver_major >= candidate_driver_major: # valid
            if candidate_cuda_10x > highest_cuda_2:
                highest_cuda_2 = candidate_cuda_10x # update highest 2

    final_cuda = min(highest_cuda_1, highest_cuda_2)
    final_cuda = f"cu{final_cuda}" if final_cuda > 0 else None
    print('')

    if final_cuda:
        print(T.COMPATIBLE_CUDA_FOUND.format(final_cuda=final_cuda))
    else:
        min_cuda, min_driver = CUDA_DRIVER_REQUIREMENTS[0]
        print(T.COMPATIBLE_CUDA_NOT_FOUND.format(min_cuda=min_cuda, min_driver=min_driver))

    return final_cuda




def detect_cuda_version_for_torch() -> str | None:
    print("\n-----\n")
    gpu_name = _get_installed_nvidia_gpu_name()
    if gpu_name is None:
        return None
    (cuda_version, driver_full) = _get_cuda_and_driver_version()
    if cuda_version is None or driver_full is None:
        return None
    compatible_cuda = _find_compatible_cuda(cuda_version, driver_full)
    return compatible_cuda




def install_pytorch(torch_version) -> bool:

    # 清华源没有 pytorch cuda 本体，但是有其他的包
    # 阿里源仅有 pytorch cuda 本体，但没有其他的包
    # 两者结合使用
    if USE_PyPI_Mirror:
        index_args = [*QingHua_PyPI_Mirror, "--find-links"]
        base_url = "https://mirrors.aliyun.com/pytorch-wheels"
    else:
        index_args = ["--index-url"]
        base_url = "https://download.pytorch.org/whl"

    # cuda 11.8 使用旧版 2.7.1
    if torch_version == "cu118":
        packages = ["torch==2.7.1", "torchvision==0.22.1"]
    # 其他版本使用新版 2.10.0
    else:
        packages = ["torch==2.10.0", "torchvision==0.25.0"]

    index_target = f"{base_url}/{torch_version}"

    cmd = [sys.executable, "-m", "pip", "install", *packages, *index_args, index_target, "--no-warn-script-location"]
    
    return general_pip_install(f"PyTorch ({torch_version})", cmd)




def install_ultralytics_onnx(has_nvidia_gpu) -> bool:

    # 安装 onnxruntime
    libs = ["onnx==1.20.1", "onnxslim==0.1.90"]
    if has_nvidia_gpu:
        libs += ["onnxruntime-gpu==1.24.4"]
    cmd = [sys.executable, "-m", "pip", "install", *libs, "--no-warn-script-location"]
    if USE_PyPI_Mirror:
        cmd += QingHua_PyPI_Mirror
    is_success = general_pip_install("ONNX Runtime", cmd)
    if not is_success:
        return False
        
    # 安装 ultralytics
    cmd = [sys.executable, "-m", "pip", "install", "ultralytics==8.4.24", "--no-warn-script-location"]
    if USE_PyPI_Mirror:
        cmd += QingHua_PyPI_Mirror
    is_success = general_pip_install("Ultralytics 8.4.24", cmd)
    if not is_success:
        return False
    
    # 安装其他依赖
    libs = ["lap==0.5.13", "numpy==2.4.3"]
    cmd = [sys.executable, "-m", "pip", "install", *libs, "--no-warn-script-location"]
    if USE_PyPI_Mirror:
        cmd += QingHua_PyPI_Mirror
    is_success = general_pip_install("lap, numpy", cmd)
    if not is_success:
        return False
    
    return True




def install_tensorrt(torch_version) -> bool:

    # 决定版本
    if torch_version == "cu118":
        tensorrt_version = "10.13.0.35" # last version support CUDA 11.8
    else:
        tensorrt_version = "10.15.1.29" # default

    # 先安装 wheel-stub
    cmd = [sys.executable, "-m", "pip", "install", "wheel-stub==0.4.2", "--no-warn-script-location"]
    if USE_PyPI_Mirror:
        cmd += QingHua_PyPI_Mirror
    is_success = general_pip_install("wheel-stub 0.4.2", cmd)
    if not is_success:
        return False

    # 再安装 TensorRT
    cmd = [sys.executable, "-m", "pip", "install", f"tensorrt=={tensorrt_version}", "--no-warn-script-location"]
    if USE_PyPI_Mirror:
        cmd += QingHua_PyPI_Mirror
    is_success = general_pip_install(f"NVIDIA TensorRT {tensorrt_version}", cmd)
    if not is_success:
        return False

    # del tmp files
    tmp_dir = Path(__file__).parent.parent / "_tmp_trt"
    if tmp_dir.exists() and tmp_dir.is_dir():
        try:
            shutil.rmtree(tmp_dir)
        except Exception as e:
            print(f"Error deleting temporary directory {tmp_dir}: {e}")

    return True



def ask_install_dml() -> bool:
    print("\n-----")
    install_dml = input(T.DML_PROMPT).strip()
    if install_dml == "1":
        return True
    elif install_dml == "2":
        return False
    elif install_dml == "3":
        sys.exit(0)
    else:
        print(T.DEFAULTING_YES)
        return True
    


def install_directml_onnx() -> bool:

    cmd = [sys.executable, "-m", "pip", "install", "onnxruntime-directml==1.24.4", "--no-warn-script-location"]
    if USE_PyPI_Mirror:
        cmd += QingHua_PyPI_Mirror
    is_success = general_pip_install("ONNX Runtime DirectML", cmd)
    if not is_success:
        return False
    
    is_success = modify_ultralytics_for_dml()
    if not is_success:
        return False
    
    return True
    


def modify_ultralytics_for_dml(recover = False) -> bool:

    print("")
    ultralytics = ROOT / "python" / "Lib" / "site-packages" / "ultralytics"
    target_path_onnx = ultralytics / "nn" / "backends" / "onnx.py"
    target_path_exporter = ultralytics / "engine" / "exporter.py"

    dml_support_dir = ROOT / "install" / "dml_support"
    modified_onnx = dml_support_dir / "modified" / "onnx.py"
    modified_exporter = dml_support_dir / "modified" / "exporter.py"
    original_onnx = dml_support_dir / "original" / "onnx.py"
    original_exporter = dml_support_dir / "original" / "exporter.py"

    # ckech file exists
    for file in [target_path_onnx, target_path_exporter, modified_onnx, modified_exporter, original_onnx, original_exporter]:
        if not file.exists() or not file.is_file():
            print(T.MODIFY_TARGET_NOT_EXIST.format(file=file))
            return False

    if not recover:  
        # replace target files with modified files
        try:
            shutil.copyfile(modified_onnx, target_path_onnx)
            shutil.copyfile(modified_exporter, target_path_exporter)
        except Exception as e:
            print(T.MODIFY_REPLACE_MODIFIED_ERROR.format(e=e))
            return False
    else:
        # replace target files with original files
        try:
            shutil.copyfile(original_onnx, target_path_onnx)
            shutil.copyfile(original_exporter, target_path_exporter)
        except Exception as e:
            print(T.MODIFY_REPLACE_ORIGINAL_ERROR.format(e=e))
            return False

    return True



def general_pip_install(package_name, cmd: list[str]) -> bool:
    
    # 执行安装命令
    print("\n-----\n")
    cmd_text = subprocess.list2cmdline(cmd)
    print(f"{T.PIP_INSTALLING.format(package_name=package_name)}\n\n{cmd_text}")
    print("\n-----\n")

    try:
        subprocess.run(cmd, check=True)
        print("\n-----\n")
        print(T.PIP_SUCCESS.format(package_name=package_name))
        return True

    except Exception as e:
        print("\n-----\n")
        print(T.PIP_ERROR.format(package_name=package_name, e=e))
        return False




if __name__ == "__main__":
    main()
