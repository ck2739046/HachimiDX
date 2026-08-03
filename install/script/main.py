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
        print("\n-----")
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
    if confirm != "1":
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

    install_trt = ask_install_trt()
    if install_trt:
        # 检测是否可用
        result = detect_trt_availability(T)
        if result.is_ok:
            nvidia_gpu_config: nvidia_config = result.value
        else:
            # 不可用，询问是否继续安装
            print(print_op_result(result))
            print(f"\n{T.install.detect_trt_failed}")
            does_continue = ask_continue_install()
            if not does_continue:
                sys.exit(1)
            nvidia_gpu_config = None

    # install pytorch
    success = install_pytorch(nvidia_gpu_config)
    if not success:
        return err("Failed to install pytorch.")

    # install ultralytics + onnxruntime
    success = install_ultralytics_onnx(nvidia_gpu_config)
    if not success:
        return err("Failed to install ultralytics or onnxruntime.")
    

            

    

    


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
    continue_install = input(T.install.continue_prompt).strip()
    if continue_install == "1":
        return False
    elif continue_install == "2":
        return True
    else:
        print(T.install.continue_defaulting)
        return False





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
        index_url = f"{base_url}/{nvidia_gpu_config.torch_cuda_ver}"
    else:
        # 默认安装 cpu 版本
        torch_ver = "2.10.0"
        torchvision_ver = "0.25.0"
        index_url = f"{base_url}/cpu"

    cmd = [sys.executable, "-m", "pip", "install",
           f"torch=={torch_ver}",
           f"torchvision=={torchvision_ver}",
           "--index-url", index_url,
           "--no-warn-script-location"]
    
    return general_pip_install(f"PyTorch", cmd, add_pypi_mirror=False)  # 显式禁用镜像，已经指定了南京大学





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
                # 显示名按 key 从当前 locale 的 MIRROR_NAMES 查表
                current_name = T.MIRROR_NAMES.get(mirror_key, mirror_key) 
                next_key = attempts[idx + 1][0]
                next_name = T.MIRROR_NAMES.get(next_key, next_key)
                print('\n' + T.pip_install.mirror_switching.format(old=current_name, new=next_name))

    # 全部失败
    if use_mirror:
        print(T.pip_install.mirror_exhausted.format(package_name=package_name))
    return False




if __name__ == "__main__":
    main()
