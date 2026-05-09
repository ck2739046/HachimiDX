import sys
import re
import subprocess
from pathlib import Path
import shutil


# 全局变量
LANGUAGE = ""
USE_PyPI_Mirror = ""

QingHua_PyPI_Mirror = "-i https://pypi.tuna.tsinghua.edu.cn/simple"

ROOT = Path(__file__).resolve().parents[2] # 往上三级目录




def main():
    global LANGUAGE

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
    LANGUAGE = ask_language()

    main_menu_en = """
Please select an option:

1. Install Hachimi DX (Default)

2. Undo Ultralytics DirectML Modification

3. Exit

Please don't choose "2" if you don't know what it is.

-> """
    main_menu_zh = """
请选择：

1. 安装 Hachimi DX (默认)

2. 撤销 Ultralytics DirectML 修改

3. 退出

如果你不清楚选项 2 是什么，请不要选择此选项。

-> """
    print("\n-----")
    choice = input(main_menu_en if LANGUAGE == "en" else main_menu_zh).strip()
    if choice == "1":
        install()
    elif choice == "2":
        success = modify_ultralytics_for_dml(recover=True)
        if success:
            info_en = "Ultralytics has been restored to its original state."
            info_zh = "Ultralytics 已恢复到原始状态。"
            print(f"{info_en if LANGUAGE == 'en' else info_zh}")
        else:
            info_en = "An error occurred while trying to restore ultralytics."
            info_zh = "尝试恢复 ultralytics 时发生错误。"
            print(f"{info_en if LANGUAGE == 'en' else info_zh}")
    elif choice == "3":
        sys.exit(0)
    else:
        print("Defaulting to Install Hachimi DX.")
        install()





def install():
    global USE_PyPI_Mirror
    
    # ask if use PyPI Mirror
    USE_PyPI_Mirror = ask_use_pypi_mirror()

    # define pytorch version
    torch_version = "cpu" # default
    install_trt = ask_install_trt()
    if install_trt:
        torch_cuda_version = detect_cuda_version_for_torch()
        if torch_cuda_version:
            torch_version = torch_cuda_version

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
    cmd = f"{sys.executable} -m pip install {' '.join(dependencies)} --no-warn-script-location"
    if USE_PyPI_Mirror:
        cmd += f" {QingHua_PyPI_Mirror}"
    is_success = general_pip_install("Other dependencies", cmd)
    if not is_success: sys.exit(1)

    # 解决 pywin32 导入错误
    cmd = [sys.executable, f"{ROOT}/python/Scripts/pywin32_postinstall.py", "-install"]
    subprocess.run(cmd, capture_output=True) # 隐藏输出
    





def ask_language() -> str:
    info = """
Please select your language:
1. Simplified Chinese (Default)
2. English
3. Exit

请选择语言：
1. 简体中文 (默认)
2. 英语
3. 退出

-> """
    print("\n-----")
    language = input(info).strip()
    if language == "1":
        return "zh"
    elif language == "2":
        return "en"
    elif language == "3":
        sys.exit(0)
    else:
        print("Defaulting to Simplified Chinese.")
        return "zh"
    



def ask_use_pypi_mirror() -> bool:
    info_zh = """
清华/阿里云的 PyPI 镜像可以显著加速国内的下载和安装。
你是否想使用 PyPI 镜像?

如果你在中国大陆，强烈建议选择"是"。
如果你在其他地区，请选择"否"。

1. 是 (默认)
2. 否
3. 退出

-> """
    info_en = """
THU/Aliyun PyPI mirrors can significantly speed up downloads and installations in China.
Do you want to use PyPI mirror?

If you are in mainland China, it is highly recommended to choose "Yes".
If you are in other regions, please choose "No".

1. Yes (Default)
2. No
3. Exit

-> """
    print("\n-----")
    use_mirror = input(info_en if LANGUAGE == "en" else info_zh).strip()
    if use_mirror == "1":
        return True
    elif use_mirror == "2":
        return False
    elif use_mirror == "3":
        sys.exit(0)
    else:
        print("Defaulting to Yes.")
        return True




def ask_install_trt() -> bool:
    info_zh = """
NVIDIA TensorRT 能够调用 NVIDIA GPU 进行推理加速，显著提升推理速度。
你是否想安装 NVIDIA TensorRT ?

如果你有 NVIDIA GPU，强烈建议选择"是"。
其他情况请选择"否"。

1. 是 (默认)
2. 否
3. 退出

-> """
    info_en = """
NVIDIA TensorRT can leverage NVIDIA GPUs for inference acceleration, significantly improving inference speed.
Do you want to install NVIDIA TensorRT?

If you have an NVIDIA GPU, it is highly recommended to choose "Yes".
In other cases, please choose "No".

1. Yes (Default)
2. No
3. Exit

-> """
    print("\n-----")
    install_trt = input(info_en if LANGUAGE == "en" else info_zh).strip()
    if install_trt == "1":
        return True
    elif install_trt == "2":
        return False
    elif install_trt == "3":
        sys.exit(0)
    else:
        print("Defaulting to Yes.")
        return True
    



def detect_cuda_version_for_torch() -> str | None:
    print("")
    # 通过 cmd 运行 nvidia-smi 命令来检测 CUDA 版本
    try:
        result = subprocess.run(["nvidia-smi"], capture_output=True, text=True)
        output = result.stdout
        # 使用正则表达式提取 CUDA 版本
        match = re.search(r"CUDA Version:\s+(\d+\.\d+)", output)
        if match:
            cuda_version = match.group(1).strip()
            cuda_version_10x = round(float(cuda_version) * 10)
        else:
            info_en = "Could not detect CUDA version from nvidia-smi output."
            info_zh = "无法从 nvidia-smi 输出中检测到 CUDA 版本。"
            print(f"{info_en if LANGUAGE == 'en' else info_zh}")
            return None
    except Exception as e:
        print(f"Error running nvidia-smi: {e}")
        return None
    
    info_en = f"Detected CUDA version: {cuda_version}"
    info_zh = f"检测到 CUDA 版本: {cuda_version}"
    print(f"{info_en if LANGUAGE == 'en' else info_zh}")

    if cuda_version_10x >= 130:
        return "cu130"
    elif cuda_version_10x >= 128:
        return "cu128"
    elif cuda_version_10x >= 126:
        return "cu126"
    elif cuda_version_10x >= 118:
        return "cu118"
    
    info_en = "This CUDA version is outdated. Minimum requirement is CUDA 11.8+"
    info_zh = "此 CUDA 版本已过时，最低要求为 CUDA 11.8+"
    print(f"{info_en if LANGUAGE == 'en' else info_zh}")
    return None




def install_pytorch(torch_version) -> bool:

    # 清华源没有 pytorch cuda 本体，但是有其他的包
    # 阿里源仅有 pytorch cuda 本体，但没有其他的包
    # 两者结合使用
    if USE_PyPI_Mirror:
        url = f"{QingHua_PyPI_Mirror} --find-links https://mirrors.aliyun.com/pytorch-wheels"
    else:
        url = "--index-url https://download.pytorch.org/whl"

    # cuda 11.8 使用旧版 2.7.1
    if torch_version == "cu118":
        torch_cmd = f"torch==2.7.1 torchvision==0.22.1 {url}/cu118"
    # 其他版本使用新版 2.10.0
    elif torch_version == "cpu":
        torch_cmd = f"torch==2.10.0 torchvision==0.25.0 {url}/cpu"
    else:
        torch_cmd = f"torch==2.10.0 torchvision==0.25.0 {url}/{torch_version}"

    cmd = f"{sys.executable} -m pip install {torch_cmd} --no-warn-script-location"
    
    return general_pip_install(f"PyTorch ({torch_version})", cmd)




def install_ultralytics_onnx(has_nvidia_gpu) -> bool:

    # 安装 onnxruntime
    libs = "onnx==1.20.1 onnxslim==0.1.90"
    if has_nvidia_gpu:
        libs += " onnxruntime-gpu==1.24.4"
    cmd = f"{sys.executable} -m pip install {libs} --no-warn-script-location"
    if USE_PyPI_Mirror:
        cmd += f" {QingHua_PyPI_Mirror}"
    is_success = general_pip_install("ONNX Runtime", cmd)
    if not is_success:
        return False
        
    # 安装 ultralytics
    cmd = f"{sys.executable} -m pip install ultralytics==8.4.24 --no-warn-script-location"
    if USE_PyPI_Mirror:
        cmd += f" {QingHua_PyPI_Mirror}"
    is_success = general_pip_install("Ultralytics 8.4.24", cmd)
    if not is_success:
        return False
    
    # 安装其他依赖
    libs = "lap==0.5.13 numpy==2.4.3"
    cmd = f"{sys.executable} -m pip install {libs} --no-warn-script-location"
    if USE_PyPI_Mirror:
        cmd += f" {QingHua_PyPI_Mirror}"
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
    cmd = f"{sys.executable} -m pip install wheel-stub==0.4.2 --no-warn-script-location"
    if USE_PyPI_Mirror:
        cmd += f" {QingHua_PyPI_Mirror}"
    is_success = general_pip_install("wheel-stub 0.4.2", cmd)
    if not is_success:
        return False

    # 再安装 TensorRT
    cmd = f"{sys.executable} -m pip install tensorrt=={tensorrt_version} --no-warn-script-location"
    if USE_PyPI_Mirror:
        cmd += f" {QingHua_PyPI_Mirror}"
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
    info_zh = """
DirectML 能够调用多个品牌的 GPU（如 AMD、Intel、NVIDIA 等）进行硬件加速。
你是否想安装 DirectML ?

如果你有支持 DirectML 的 GPU，并且性能显著优于 CPU，强烈建议选择"是"。
其他情况请选择"否"。

1. 是 (默认)
2. 否
3. 退出

-> """
    info_en = """
DirectML can leverage GPUs from multiple brands (such as AMD, Intel, NVIDIA, etc.) for hardware acceleration.
Do you want to install DirectML?

If you have a GPU that supports DirectML and offers significantly better performance than CPU, it is highly recommended to choose "Yes".
In other cases, please choose "No".

1. Yes (Default)
2. No
3. Exit

-> """
    print("\n-----")
    install_dml = input(info_en if LANGUAGE == "en" else info_zh).strip()
    if install_dml == "1":
        return True
    elif install_dml == "2":
        return False
    elif install_dml == "3":
        sys.exit(0)
    else:
        print("Defaulting to Yes.")
        return True
    


def install_directml_onnx() -> bool:

    cmd = f"{sys.executable} -m pip install onnxruntime-directml==1.24.4 --no-warn-script-location"
    if USE_PyPI_Mirror:
        cmd += f" {QingHua_PyPI_Mirror}"
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
            info_en = f"modify_ultralytics_for_dml(): Error: Target file {file} does not exist."
            info_zh = f"modify_ultralytics_for_dml(): 错误: 目标文件 {file} 不存在。。"
            print(f"{info_en if LANGUAGE == 'en' else info_zh}")
            return False

    if not recover:  
        # replace target files with modified files
        try:
            shutil.copyfile(modified_onnx, target_path_onnx)
            shutil.copyfile(modified_exporter, target_path_exporter)
        except Exception as e:
            info_en = f"modify_ultralytics_for_dml(): Error replacing with modified files: {e}"
            info_zh = f"modify_ultralytics_for_dml(): 替换为修改后的文件时发生错误: {e}"
            print(f"{info_en if LANGUAGE == 'en' else info_zh}")
            return False
    else:
        # replace target files with original files
        try:
            shutil.copyfile(original_onnx, target_path_onnx)
            shutil.copyfile(original_exporter, target_path_exporter)
        except Exception as e:
            info_en = f"modify_ultralytics_for_dml(): Error replacing with original files: {e}"
            info_zh = f"modify_ultralytics_for_dml(): 替换为原始文件时发生错误: {e}"
            print(f"{info_en if LANGUAGE == 'en' else info_zh}")
            return False

    return True



def general_pip_install(package_name, cmd) -> bool:
    
    # 执行安装命令
    print("\n-----\n")
    info_en = f"Installing {package_name}...\n\n{cmd}"
    info_zh = f"正在安装 {package_name}...\n\n{cmd}"
    print(f"{info_en if LANGUAGE == 'en' else info_zh}")
    print("\n-----\n")

    try:
        subprocess.run(cmd, shell=True, check=True)
        print("\n-----\n")
        info_en = f"{package_name} installation completed successfully."
        info_zh = f"{package_name} 安装成功完成。"
        print(f"{info_en if LANGUAGE == 'en' else info_zh}")
        return True

    except Exception as e:
        print("\n-----\n")
        info_en = f"Error occurred while installing {package_name}: {e}"
        info_zh = f"安装 {package_name} 时发生错误: {e}"
        print(f"{info_en if LANGUAGE == 'en' else info_zh}")
        return False




if __name__ == "__main__":
    main()
