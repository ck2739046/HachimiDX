import sys
import re
import subprocess
from pathlib import Path
import shutil

from . import en_us, zh_cn
from .op_result import OpResult, ok, err, print_op_result

from .detect_trt import detect_trt_availability, nvidia_config


ROOT = Path(__file__).resolve().parents[2] # 往上三级目录

# 在 ask_language() 中赋值
T = en_us

# 在 install.ask_pypi_mirror() 中赋值
USE_PyPI_Mirror = False




def main():

    # generate by https://patorjk.com/software/taag using font "Terrace"
    title = """

    ░██     ░██                       ░██        ░██                ░██     ░███████   ░██    ░██ 
    ░██     ░██                       ░██                                   ░██   ░██   ░██  ░██  
    ░██     ░██  ░██████    ░███████  ░████████  ░██░█████████████  ░██     ░██    ░██   ░██░██   
    ░██████████       ░██  ░██    ░██ ░██    ░██ ░██░██   ░██   ░██ ░██     ░██    ░██    ░███    
    ░██     ░██  ░███████  ░██        ░██    ░██ ░██░██   ░██   ░██ ░██     ░██    ░██   ░██░██   
    ░██     ░██ ░██   ░██  ░██    ░██ ░██    ░██ ░██░██   ░██   ░██ ░██     ░██   ░██   ░██  ░██  
    ░██     ░██  ░█████░██  ░███████  ░██    ░██ ░██░██   ░██   ░██ ░██     ░███████   ░██    ░██ 

    """

    print(title)

    try:
        # ask language
        global T
        language = input(en_us.ask_language.prompt).strip()
        if language == "1":
            T = zh_cn
        elif language == "2":
            T = en_us
        elif language == "3":
            sys.exit(0)
        else:
            print(zh_cn.ask_language.defaulting)
            T = zh_cn

        # main menu
        print("\n-----")
        choice = input(T.main_menu.prompt).strip()

        if choice == "1":
            result = install()
            if not result.is_ok:
                print_op_result(result)

        elif choice == "2":
            result = reinstall_backend()
            if not result.is_ok:
                print_op_result(result)

        elif choice == "3":
            sys.exit(0)

        else:
            print(T.main_menu.defaulting)
            result = install()
            if not result.is_ok:
                print_op_result(result)

    except KeyboardInterrupt:
        print("\nKeyboardInterrupt detected, exiting...")
        sys.exit(1)
    except Exception as e:
        result = err("Unexpected error in main()", error_raw=e)
        print(f"\n-----\n\n{print_op_result(result)}\n")
        sys.exit(1)






def reinstall_backend() -> OpResult[None]:

    # 确认
    print("\n-----")
    confirm = input(T.reinstall_backend.prompt).strip()
    if confirm != "2":
        print(T.reinstall_backend.abort)
        return ok()

    # 1. 撤销 Ultralytics DirectML 修改
    result = modify_ultralytics_for_dml(recover=True)
    if not result.is_ok:
        msg = f"Failed to recover Ultralytics from DirectML modification."
        return err(msg, inner=result)

    # 2. 删除相关库
    print(f"\n-----\n\n{T.reinstall_backend.start_uninstall}\n")
    cmd = [sys.executable, "-m", "pip", "uninstall",
        "onnxruntime-gpu", "onnxruntime-directml",
        "torch", "torchvision", "tensorrt", "-y"]
    try:
        subprocess.run(cmd, check=True)
        print("\n-----\n")
        print(T.reinstall_backend.uninstall_done)
    except Exception as e:
        return err("failed to uninstall existing backend.", error_raw=e)

    # 3. 进入安装流程
    result = install()
    if not result.is_ok:
        msg = f"Failed to reinstall."
        return err(msg, inner=result)

    return ok()








def install() -> OpResult[None]:

    print("\n-----\n")
    print(T.install.start)

    ask_use_pypi_mirror()

    # ask install TensorRT
    nvidia_gpu_config: nvidia_config|None = None
    install_trt = ask_install_trt()
    if install_trt:
        # 检测是否可用
        result = detect_trt_availability(T)
        if result.is_ok:
            nvidia_gpu_config = result.value
        else:
            # 不可用，询问是否继续安装
            print(print_op_result(result))
            print(f"\n{T.install.detect_trt_failed}")
            does_continue = ask_continue_install()
            if not does_continue:
                sys.exit(1)

    # install pytorch
    success = install_pytorch(nvidia_gpu_config)
    if not success:
        return err("Failed to install pytorch.")

    # install ultralytics + onnxruntime
    success = install_ultralytics_onnx(nvidia_gpu_config)
    if not success:
        return err("Failed to install ultralytics or onnxruntime.")
    
    # model inference acceleration
    if nvidia_gpu_config is not None:
        # install TensorRT
        is_success = install_tensorrt(nvidia_gpu_config)
        if not is_success: sys.exit(1)
    else:
        # install DirectML
        install_dml = ask_install_dml()
        if install_dml:
            is_success = install_directml()
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
    cmd = [sys.executable, "-m", "pip", "install",
           *dependencies, "--no-warn-script-location"]
    is_success = general_pip_install("Other dependencies", cmd)
    if not is_success: sys.exit(1)
        
    # 结束
    print("\n-----\n")
    print(T.install.done)
    print("\n-----\n")

    

    


    return ok()





def ask_use_pypi_mirror():
    global USE_PyPI_Mirror
    print("\n-----")
    use_mirror = input(T.ask_use_pypi_mirror.prompt).strip()
    if use_mirror == "1":
        USE_PyPI_Mirror = True
    elif use_mirror == "2":
        USE_PyPI_Mirror = False
    elif use_mirror == "3":
        sys.exit(0)
    else:
        print(T.ask_use_pypi_mirror.defaulting)
        USE_PyPI_Mirror = True

def ask_install_trt() -> bool:
    print("\n-----")
    install_trt = input(T.ask_install_trt.prompt).strip()
    if install_trt == "1":
        return True
    elif install_trt == "2":
        return False
    elif install_trt == "3":
        sys.exit(0)
    else:
        print(T.ask_install_trt.defaulting)
        return True

def ask_continue_install() -> bool:
    print("\n-----")
    continue_install = input(T.ask_continue_install.prompt).strip()
    if continue_install == "1":
        return False
    elif continue_install == "2":
        return True
    else:
        print(T.ask_continue_install.defaulting)
        return False

def ask_install_dml() -> bool:
    print("\n-----")
    install_dml = input(T.ask_install_dml.prompt).strip()
    if install_dml == "1":
        return True
    elif install_dml == "2":
        return False
    elif install_dml == "3":
        sys.exit(0)
    else:
        print(T.ask_install_dml.defaulting)
        return True





def install_pytorch(nvidia_gpu_config: nvidia_config|None) -> bool:

    if USE_PyPI_Mirror:
        # 南京大学源有 pytorch cuda 本体
        base_url = "https://mirrors.nju.edu.cn/pytorch/whl"
    else:
        base_url = "https://download.pytorch.org/whl"

    if nvidia_gpu_config is not None:
        # 使用配置指定的版本
        torch_ver = nvidia_gpu_config.torch_ver
        torchvision_ver = nvidia_gpu_config.torchvision_ver
        target = nvidia_gpu_config.torch_cuda_ver
    else:
        # 默认安装 cpu 版本
        torch_ver = "2.10.0"
        torchvision_ver = "0.25.0"
        target = "cpu"

    cmd = [sys.executable, "-m", "pip", "install",
           f"torch=={torch_ver}",
           f"torchvision=={torchvision_ver}",
           "--index-url", f"{base_url}/{target}",
           "--no-warn-script-location"]
    
    return general_pip_install(f"PyTorch ({target})", cmd, add_pypi_mirror=False)  # 显式禁用镜像，已经指定了南京大学





def install_ultralytics_onnx(nvidia_gpu_config: nvidia_config|None) -> bool:

    # 安装 onnxruntime
    libs = ["onnx==1.20.1", "onnxslim==0.1.90"]
    if nvidia_gpu_config is not None:
        # 增加安装 GPU 版本
        libs += [f"onnxruntime-gpu=={nvidia_gpu_config.onnxruntime_gpu_ver}"]

    cmd = [sys.executable, "-m", "pip", "install",
           *libs, "--no-warn-script-location"]
    is_success = general_pip_install("ONNX Runtime", cmd)
    if not is_success:
        return False
        
    # 安装 ultralytics
    cmd = [sys.executable, "-m", "pip", "install",
           "ultralytics==8.4.102", "--no-warn-script-location"]
    is_success = general_pip_install("Ultralytics", cmd)
    if not is_success:
        return False
    
    # 安装其他依赖
    if nvidia_gpu_config is not None:
        numpy_ver = nvidia_gpu_config.numpy_ver
    else:
        numpy_ver = "2.4.3"

    libs = ["lap==0.5.13", f"numpy=={numpy_ver}"]
    cmd = [sys.executable, "-m", "pip", "install",
           *libs, "--no-warn-script-location"]
    is_success = general_pip_install("lap & numpy", cmd)
    if not is_success:
        return False
    
    return True





def install_tensorrt(nvidia_gpu_config: nvidia_config) -> bool:

    # 先安装 wheel-stub
    cmd = [sys.executable, "-m", "pip", "install",
           "wheel-stub==0.4.2", "--no-warn-script-location"]
    is_success = general_pip_install("wheel-stub", cmd)
    if not is_success:
        return False
    
    # 再安装 NVIDIA TensorRT
    cmd = [sys.executable, "-m", "pip", "install",
           f"tensorrt=={nvidia_gpu_config.tensorRT_ver}",
           "--no-warn-script-location",
           "--extra-index-url", "https://pypi.nvidia.com"]
    is_success = general_pip_install("TensorRT", cmd)
    if not is_success:
        return False
    
    # 最后删除临时文件
    tmp_dir = ROOT / "_tmp_trt"
    if tmp_dir.exists() and tmp_dir.is_dir():
        try:
            shutil.rmtree(tmp_dir)
        except Exception as e:
            print(f"Error deleting TensorRT temporary directory {tmp_dir}\n{e}")

    return True





def install_directml() -> bool:

    cmd = [sys.executable, "-m", "pip", "install",
           "onnxruntime-directml==1.24.4", "--no-warn-script-location"]
    is_success = general_pip_install("ONNX Runtime for DirectML", cmd)
    if not is_success:
        return False
    
    result = modify_ultralytics_for_dml()
    if not result.is_ok:
        print(print_op_result(result))
        return False
    
    return True





def modify_ultralytics_for_dml(recover = False) -> OpResult[None]:

    return ok()

    print("\n-----\n")
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





def general_pip_install(package_name, cmd: list[str],
                        add_pypi_mirror: bool | None = None) -> bool:
    """
    执行一次 pip 安装，自动处理镜像切换。

    add_pypi_mirror（可选）:
      - None： 跟随全局 USE_PyPI_Mirror
      - False：强制禁用 PyPI 镜像（即使全局启用）
      - True： 不支持强制启用, 视为 None
    """

    # PyPI 镜像列表（key, args_list）优先级从上到下，首选清华源
    PYPI_MIRRORS = [
        ("tsinghua", ["-i", "https://pypi.tuna.tsinghua.edu.cn/simple"]),
        ("tencent",  ["-i", "https://mirrors.cloud.tencent.com/pypi/simple"]),
        ("huawei",   ["-i", "https://repo.huaweicloud.com/repository/pypi/simple"]),
        ("aliyun",   ["-i", "https://mirrors.aliyun.com/pypi/simple"]),
    ]

    use_mirror = bool(USE_PyPI_Mirror) and add_pypi_mirror is not False

    # 构造使用每个镜像源的完整命令
    if use_mirror:
        attempts = [(name, cmd + mirror_args)
                    for name, mirror_args in PYPI_MIRRORS]
    else:
        attempts = [("None", cmd)]

    for idx, (mirror_key, full_cmd) in enumerate(attempts):
        # 打印即将执行的指令
        print("\n-----\n")
        print(T.pip_install.start.format(package_name=package_name))
        print()
        print(subprocess.list2cmdline(full_cmd))

        try:
            # 执行安装命令
            print("\n-----\n")
            subprocess.run(full_cmd, check=True)
            # 安装成功
            print("\n-----\n")
            print(T.pip_install.success.format(package_name=package_name))
            return ok()
        except Exception as e:
            # 安装失败
            print("\n-----\n")
            print(T.pip_install.error.format(package_name=package_name, e=e))
            # 如果启用镜像, 尝试切换到下一个镜像
            if use_mirror and idx < len(attempts) - 1:
                # 显示名按 key 从当前 locale 的 mirror_names 查表
                current_name = T.pip_install.mirror_names.get(mirror_key, mirror_key) 
                next_key = attempts[idx + 1][0]
                next_name = T.pip_install.mirror_names.get(next_key, next_key)
                print('\n' + T.pip_install.mirror_switching.format(old=current_name, new=next_name))

    # 全部失败
    if use_mirror:
        print(T.pip_install.mirror_exhausted.format(package_name=package_name))
    return False




if __name__ == "__main__":
    main()
