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

    result = detect_trt_availability(T)
    if not result.is_ok:
        print_op_result(result)
        print(f"\n-----\n\n{T.install.detect_trt_failed}\n")

    

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




if __name__ == "__main__":
    main()
