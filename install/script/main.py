import datetime
import sys
import subprocess
from pathlib import Path
import shutil

from . import console_journal, en_us, zh_cn
from .op_result import OpResult, ok, err, print_op_result
from .console_input import ask
from .color import *

from .choose_backend import choose_backend
from .detect_onnx_cuda import onnx_cuda_config
from .detect_trt import tensorrt_config
from .download_legacy_trt import install_legacy_tensorrt, remove_legacy_tensorrt_runtime


ROOT = Path(__file__).resolve().parents[2] # 往上三级目录

# 在 ask_language() 中赋值
T = en_us

# 在 install.ask_pypi_mirror() 中赋值
USE_PyPI_Mirror = False

# 特殊返回码：告知 install.bat 安装成功且用户选择立即启动软件，跳过 pause
EXIT_LAUNCH_HACHIMIDX = 273




def main():

    # 必须在任何输出之前接手控制台，日志靠跟随屏幕缓冲区产生
    console_journal.start()
    print(datetime.datetime.now().strftime("%Y/%m/%d %H:%M:%S") + "\n")

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

    print(cyan(title))

    try:
        # ask language
        global T
        language = ask(en_us.ask_language.prompt + hint(en_us.ask_language.input_hint))
        if language == "1":
            T = zh_cn
        elif language == "2":
            T = en_us
        elif language == "3":
            sys.exit(0)
        else:
            print(note_on_hint(yellow(en_us.ask_language.input_hint), zh_cn.ask_language.defaulting))
            T = zh_cn

        # ask whether to use PyPI mirror
        ask_use_pypi_mirror()

        # 预先更新 pip 与 wheel 确保安装流程稳定
        general_pip_install("pip & wheel", [sys.executable, "-m", "pip", "install",
                                            "--upgrade", "pip", "wheel",
                                            "--no-warn-script-location"])

        # main menu
        print("\n-----")
        choice = ask(T.main_menu.prompt + hint(T.input_hint))
        if choice == "1":
            result = install()
            if not result.is_ok:
                print(red(print_op_result(result)))

        elif choice == "2":
            result = reinstall_backend()
            if not result.is_ok:
                print(red(print_op_result(result)))

        elif choice == "3":
            sys.exit(0)

        else:
            print(note_on_hint(yellow(T.input_hint), T.main_menu.defaulting))
            result = install()
            if not result.is_ok:
                print(red(print_op_result(result)))

    except KeyboardInterrupt:
        print("\n" + yellow("KeyboardInterrupt detected, exiting..."))
        sys.exit(1)
    except Exception as e:
        result = err("Unexpected error in main()", error_raw=e)
        print(f"\n-----\n\n{red(print_op_result(result))}\n")
        sys.exit(1)
    finally:
        console_journal.finish()






def reinstall_backend() -> OpResult[None]:

    # 确认
    print("\n-----")
    confirm = ask(T.reinstall_backend.prompt + hint(T.input_hint))
    if confirm != "2":
        print(T.reinstall_backend.abort)
        return ok()

    # 1. 撤销 Ultralytics DirectML 修改
    result = modify_ultralytics_for_dml(recover=True)
    if not result.is_ok:
        msg = f"Failed to recover Ultralytics from DirectML modification."
        return err(msg, inner=result)

    # 2. 删除相关库
    print(f"\n-----\n\n{cyan(T.reinstall_backend.start_uninstall)}\n")
    cmd = [sys.executable, "-m", "pip", "uninstall", "-y",
        "onnxruntime", "onnxruntime-gpu", "onnxruntime-directml",
        "torch", "torchvision",
        "tensorrt", "opencv-python",
        "tensorrt_cu12", "tensorrt_cu12_bindings", "tensorrt_cu12_libs",
        "tensorrt_cu13", "tensorrt_cu13_bindings", "tensorrt_cu13_libs",
        "ncnn", "pnnx",
        ]
    try:
        subprocess.run(cmd, check=True)
    except Exception as e:
        return err("failed to uninstall existing backend.", error_raw=e)

    result = remove_legacy_tensorrt_runtime(ROOT)
    if not result.is_ok:
        return err("failed to remove legacy TensorRT runtime.", inner=result)
    
    print("\n-----\n")
    print(green(T.reinstall_backend.uninstall_done))

    # 3. 进入安装流程
    result = install(is_reinstall=True)
    if not result.is_ok:
        msg = f"Failed to reinstall."
        return err(msg, inner=result)

    return ok()








def install(is_reinstall: bool = False) -> OpResult[None]:

    print("\n-----\n")
    print(cyan(T.install.start))

    # 检测并选择后端
    result = choose_backend(T)
    if not result.is_ok:
        return err("Failed to choose inference backend.", inner=result)
    if result.value is None:
        return err("Backend choice did not contain a value.", inner=result)
    backend_choice = result.value
    backend = backend_choice.backend
    tensorrt_gpu_config = backend_choice.tensorrt_config
    onnx_cuda_gpu_config = backend_choice.onnx_cuda_config
    install_dml = backend == "onnx_dml"
    install_ncnn_ = backend == "ncnn"

    # install pytorch
    success = install_pytorch(tensorrt_gpu_config, onnx_cuda_gpu_config)
    if not success:
        return err("Failed to install pytorch.")

    # install ultralytics + onnxruntime
    success = install_ultralytics_onnx(
        backend,
        tensorrt_gpu_config,
        onnx_cuda_gpu_config,
    )
    if not success:
        return err("Failed to install ultralytics or onnxruntime.")

    # model inference acceleration
    if backend == "trt" and tensorrt_gpu_config is not None:
        # install TensorRT
        is_success = install_tensorrt(tensorrt_gpu_config)
        if not is_success: sys.exit(1)
    elif install_dml:
        # modify ultralytics for DirectML
        result = modify_ultralytics_for_dml()
        if not result.is_ok:
            print(red(print_op_result(result)))
            sys.exit(1)
    elif install_ncnn_:
        # install NCNN
        is_success = install_ncnn()
        if not is_success: sys.exit(1)

    # install others
    dependencies = [
        "PyQt6==6.10.2",
        "pywin32==312",
        "librosa==0.11.0",
        "pydantic==2.13.4",
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
    print(green(T.install.done))

    # 提示用户去应用内完成模型后端配置
    print_model_backend_reminder(backend, is_reinstall)

    # 询问是否立即打开 HachimiDX
    ask_open_hachimidx()

    return ok()





def ask_use_pypi_mirror():
    global USE_PyPI_Mirror
    print("\n-----")
    use_mirror = ask(T.ask_use_pypi_mirror.prompt + hint(T.input_hint))
    if use_mirror == "1":
        USE_PyPI_Mirror = True
    elif use_mirror == "2":
        USE_PyPI_Mirror = False
    elif use_mirror == "3":
        sys.exit(0)
    else:
        print(note_on_hint(yellow(T.input_hint), T.ask_use_pypi_mirror.defaulting))
        USE_PyPI_Mirror = True




def install_pytorch(tensorrt_gpu_config: tensorrt_config | None,
                    onnx_cuda_gpu_config: onnx_cuda_config | None,
                   ) -> bool:

    if tensorrt_gpu_config is not None:
        # 使用配置指定的版本
        torch_ver = tensorrt_gpu_config.torch_ver
        torchvision_ver = tensorrt_gpu_config.torchvision_ver
        target = tensorrt_gpu_config.torch_cuda_ver
    elif onnx_cuda_gpu_config is not None:
        # 使用配置指定的版本
        torch_ver = onnx_cuda_gpu_config.torch_ver
        torchvision_ver = onnx_cuda_gpu_config.torchvision_ver
        target = onnx_cuda_gpu_config.torch_cuda_ver
    else:
        # 默认安装 cpu 版本
        torch_ver = "2.11.0"
        torchvision_ver = "0.26.0"
        target = "cpu"

    # 包含 PyTorch Cuda 本体的镜像列表
    pytorch_mirrors = [
        ("nju",  ["-i", f"https://mirrors.nju.edu.cn/pytorch/whl/{target}"]),
        ("aliyun_pytorch", ["-f", f"https://mirrors.aliyun.com/pytorch-wheels/{target}"]),
        ("sjtu", ["-i", f"https://mirror.sjtu.edu.cn/pytorch-wheels/{target}"]),
    ]

    cmd = [sys.executable, "-m", "pip", "install",
           f"torch=={torch_ver}",
           f"torchvision=={torchvision_ver}",
           "--no-warn-script-location"]
    if not USE_PyPI_Mirror:
        # 不使用镜像时, 附加官方 whl 地址
        cmd.append("-i")
        cmd.append(f"https://download.pytorch.org/whl/{target}")

    return general_pip_install(f"PyTorch ({target})", cmd, pypi_mirrors=pytorch_mirrors)






def install_ultralytics_onnx(backend: str,
                             tensorrt_gpu_config: tensorrt_config | None,
                             onnx_cuda_gpu_config: onnx_cuda_config | None,
                            ) -> bool:

    # 检查 gpu_config 是否为 None
    if backend == "trt":
        if tensorrt_gpu_config is None:
            print(red("Error: tensorrt_gpu_config is None while backend is 'trt'."))
            return False
        gpu_config = tensorrt_gpu_config
    elif backend == "onnx_cuda":
        if onnx_cuda_gpu_config is None:
            print(red("Error: onnx_cuda_gpu_config is None while backend is 'onnx_cuda'."))
            return False
        gpu_config = onnx_cuda_gpu_config
    else:
        gpu_config = None

    # onnx/onnxslim 必装
    libs = ["onnx==1.17.0", "onnxslim==0.1.95"]

    # onnxruntime 三选一
    if backend in ["trt", "onnx_cuda"]:
        # onnxruntime-gpu 需要 cuda/cudnn 环境
        # 前面已经安装了 pytorch cuda
        # sitecustomize 会在运行时自动加载 pytorch 的 cuda 依赖
        # onnx 可以借用这个依赖
        # 所以这里不再通过 ort extra 显式安装 cuda 依赖
        libs += [f"onnxruntime-gpu=={gpu_config.onnxruntime_gpu_ver}"]
    elif backend == "onnx_dml":
        libs += ["onnxruntime-directml==1.24.4"]
    else:
        libs += ["onnxruntime==1.20.1"]

    cmd = [sys.executable, "-m", "pip", "install",
           *libs, "--no-warn-script-location"]
    is_success = general_pip_install("ONNX Runtime", cmd)
    if not is_success:
        return False

    # 安装 Ultralytics
    numpy_ver = gpu_config.numpy_ver if gpu_config is not None else "2.4.6"
    libs = ["ultralytics==8.4.125", "lap==0.5.13", f"numpy=={numpy_ver}"]
    # 可选显式指定 cv2 版本，否则 ultralytics 会自动安装
    if gpu_config is not None:
        libs += [f"opencv-python=={gpu_config.opencv_ver}"]

    cmd = [sys.executable, "-m", "pip", "install",
           *libs, "--no-warn-script-location"]
    is_success = general_pip_install("Ultralytics", cmd)
    if not is_success:
        return False
    
    return True





def install_tensorrt(config: tensorrt_config) -> bool:

    if config.is_trt_legacy:
        print(f"\n-----\n")
        result = install_legacy_tensorrt(T, ROOT, sys.executable,
                                         config.tensorRT_ver)
        if not result.is_ok:
            print(red(print_op_result(result)))
            return False
        return True

    # 以下是 not trt legacy 安装

    # 先安装 wheel-stub
    cmd = [sys.executable, "-m", "pip", "install",
           "wheel-stub==0.5.0", "--no-warn-script-location"]
    is_success = general_pip_install("wheel-stub", cmd)
    if not is_success:
        return False

    # 再安装 NVIDIA TensorRT
    cmd = [sys.executable, "-m", "pip", "install",
           f"tensorrt=={config.tensorRT_ver}",
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
            print(red(f"Error deleting TensorRT temporary directory {tmp_dir}\n{e}"))

    return True





def install_ncnn() -> bool:
    cmd = [sys.executable, "-m", "pip", "install",
           "ncnn==1.0.20260526", "pnnx==20260526",
           "--no-warn-script-location"]
    return general_pip_install("NCNN", cmd)




def modify_ultralytics_for_dml(recover: bool = False) -> OpResult[None]:

    ultralytics = ROOT / "python" / "Lib" / "site-packages" / "ultralytics"
    target_path_onnx = ultralytics / "nn" / "backends" / "onnx.py"
    target_path_exporter = ultralytics / "engine" / "exporter.py"

    dml_support_dir = ROOT / "install" / "dml_support"
    modified_onnx = dml_support_dir / "modified" / "onnx.py"
    modified_exporter = dml_support_dir / "modified" / "exporter.py"
    original_onnx = dml_support_dir / "original" / "onnx.py"
    original_exporter = dml_support_dir / "original" / "exporter.py"

    # ckech file exists
    for file in [target_path_onnx, target_path_exporter,
                 modified_onnx, modified_exporter,
                 original_onnx, original_exporter]:
        if not file.exists() or not file.is_file():
            msg = T.modify_ultralytics_for_dml.file_not_exist.format(file=file)
            return err(msg)

    # replace files
    try:
        if not recover:
            # replace modified
            shutil.copyfile(modified_onnx, target_path_onnx)
            shutil.copyfile(modified_exporter, target_path_exporter)
        else:
            # replace original
            shutil.copyfile(original_onnx, target_path_onnx)
            shutil.copyfile(original_exporter, target_path_exporter)
    except Exception as e:
        msg = T.modify_ultralytics_for_dml.modify_failed.format(e=e)
        return err(msg, error_raw=e)

    return ok()





def print_model_backend_reminder(backend: str, is_reinstall: bool) -> None:

    # 后端 key -> 与 GUI 设置页「模型后端」下拉框一致
    MODEL_BACKEND_DISPLAY_NAMES = {
        "trt": "TensorRT",
        "onnx_cuda": "ONNX Cuda",
        "onnx_dml": "ONNX DML",
        "ncnn": "NCNN",
        "onnx_cpu": "ONNX CPU",
    }

    reminder = T.model_backend_reminder
    backend_name = MODEL_BACKEND_DISPLAY_NAMES.get(backend, backend)

    steps = [
        reminder.step1,
        reminder.step2_again if is_reinstall else reminder.step2,
        reminder.step3,
        reminder.step4_again if is_reinstall else reminder.step4,
        reminder.step5,
    ]

    print("\n-----\n")
    print(red(get_separator(reminder.title)))
    print(red(reminder.title))
    print(red(reminder.title))
    print(red(reminder.title))
    print(red(get_separator(reminder.title)))
    print()

    for step in steps:
        print(yellow(step.format(backend=backend_name)))

    print()
    print(red(get_separator(reminder.footnote)))
    print(red(reminder.footnote))
    print(red(reminder.footnote))
    print(red(reminder.footnote))
    print(red(get_separator(reminder.footnote)))




def ask_open_hachimidx() -> None:
    print("\n-----")
    is_launch = ask(T.open_hachimidx.prompt + hint(T.input_hint))
    if is_launch == "1":
        pass
    elif is_launch == "2":
        return
    elif is_launch == "3":
        sys.exit(0)
    else:
        print(note_on_hint(yellow(T.input_hint), T.open_hachimidx.defaulting))
    # 启动 HachimiDX
    print("\n-----\n")
    exe = ROOT / "HachimiDX.exe"
    if not exe.exists():
        print(red(T.open_hachimidx.not_found))
        return
    print(green(T.open_hachimidx.launching))
    subprocess.Popen([str(exe)], cwd=str(ROOT))
    sys.exit(EXIT_LAUNCH_HACHIMIDX)





def general_pip_install(package_name, cmd: list[str],
                        add_pypi_mirror: bool | None = None,
                        pypi_mirrors: list[tuple[str, list[str]]] | None = None) -> bool:
    """
    执行一次 pip 安装，自动处理镜像切换。

    add_pypi_mirror（可选）:
      - None： 跟随全局 USE_PyPI_Mirror
      - False：强制禁用 PyPI 镜像（即使全局启用）
      - True： 不支持强制启用, 视为 None
    pypi_mirrors（可选）:
      自定义镜像列表（key, args_list），默认使用内置 PYPI_MIRRORS。
    """

    # PyPI 镜像列表（key, args_list）优先级从上到下，首选清华源
    PYPI_MIRRORS = [
        ("thu",     ["-i", "https://pypi.tuna.tsinghua.edu.cn/simple"]),
        ("tencent", ["-i", "https://mirrors.cloud.tencent.com/pypi/simple"]),
        ("huawei",  ["-i", "https://repo.huaweicloud.com/repository/pypi/simple"]),
        ("aliyun",  ["-i", "https://mirrors.aliyun.com/pypi/simple"]),
    ]

    use_mirror = bool(USE_PyPI_Mirror) and add_pypi_mirror is not False

    # 构造使用每个镜像源的完整命令
    if use_mirror:
        # 优先使用自定义镜像列表，否则使用默认 PYPI_MIRRORS
        mirror_list = pypi_mirrors if pypi_mirrors is not None else PYPI_MIRRORS
        attempts = [(name, cmd + mirror_args)
                    for name, mirror_args in mirror_list]
    else:
        attempts = [("None", cmd)]

    for idx, (mirror_key, full_cmd) in enumerate(attempts):
        # 打印即将执行的指令
        print("\n-----\n")
        print(cyan(T.pip_install.start.format(package_name=package_name)))
        print()
        print(subprocess.list2cmdline(full_cmd))

        try:
            # 执行安装命令
            print("\n-----\n")
            subprocess.run(full_cmd, check=True)
            # 安装成功
            print("\n-----\n")
            print(green(T.pip_install.success.format(package_name=package_name)))
            return ok()
        except Exception as e:
            # 安装失败
            print("\n-----\n")
            print(red(T.pip_install.error.format(package_name=package_name, e=e)))
            # 如果启用镜像, 尝试切换到下一个镜像
            if use_mirror and idx < len(attempts) - 1:
                # 显示名按 key 从当前 locale 的 mirror_names 查表
                current_name = T.pip_install.mirror_names.get(mirror_key, mirror_key) 
                next_key = attempts[idx + 1][0]
                next_name = T.pip_install.mirror_names.get(next_key, next_key)
                print('\n' + yellow(T.pip_install.mirror_switching.format(old=current_name, new=next_name)))

    # 全部失败
    if use_mirror:
        print(red(T.pip_install.mirror_exhausted.format(package_name=package_name)))
    return False




if __name__ == "__main__":
    main()
