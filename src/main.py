import os
import subprocess
import sys
from pathlib import Path

# 定义 ROOT（main.py 在 src/ 下，需要往上两级到项目根目录）
project_root = Path(__file__).parent.parent.resolve()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))




def prompt_missing_dependencies() -> None:
    """依赖库缺失时弹窗，引导用户先跑安装脚本"""
    import subprocess
    from tkinter import messagebox
    from src.services import PathManage
    install_bat = PathManage.INSTALL_BAT_PATH

    # 先检查安装脚本是否存在
    if not install_bat.is_file():
        messagebox.showerror(
            "HachimiDX",
            "尚未安装依赖库，且安装脚本不存在，请检查安装包完整性。\n" +
            "Dependencies are not installed, and the installation script is missing. Please check the integrity of the installation package.",
        )
        return 1
    # 选 No 直接退出
    if not messagebox.askyesno(
        "HachimiDX",
        "尚未安装依赖库，是否现在安装？\n" +
        "Dependencies are not installed, install now?",
    ):
        return
    # 选 Yes 启动安装脚本
    subprocess.Popen(
        ["cmd", "/c", str(install_bat)],
        creationflags=subprocess.CREATE_NEW_CONSOLE,
    )





try:
    from PyQt6.QtCore import QSharedMemory
    from PyQt6.QtWidgets import QApplication, QStyleFactory
    from PyQt6.QtGui import QFont
except ModuleNotFoundError:
    prompt_missing_dependencies()
    sys.exit(0)


from src.core.schemas.op_result import print_op_result
from src.app import MainWindow
from src.services import AllServices


# Exit-code:
# 0. normal exit
# 1. general error
# 2. app already running
# 3. initialization error

author = "ck2739046"
repo_name = "HachimiDX"

VERSION = "1.6.3"
REPO = f"https://github.com/{author}/{repo_name}"
API_RELEASE_LATEST = f"https://api.github.com/repos/{author}/{repo_name}/releases/latest"





# generate by https://patorjk.com/software/taag using font "Terrace"
logo = """

    ░██     ░██                       ░██        ░██                 ░██     ░███████   ░██    ░██ 
    ░██     ░██                       ░██                                    ░██   ░██   ░██  ░██  
    ░██     ░██  ░██████    ░███████  ░████████  ░██ ░█████████████  ░██     ░██    ░██   ░██░██   
    ░██████████       ░██  ░██    ░██ ░██    ░██ ░██ ░██   ░██   ░██ ░██     ░██    ░██    ░███    
    ░██     ░██  ░███████  ░██        ░██    ░██ ░██ ░██   ░██   ░██ ░██     ░██    ░██   ░██░██   
    ░██     ░██ ░██   ░██  ░██    ░██ ░██    ░██ ░██ ░██   ░██   ░██ ░██     ░██   ░██   ░██  ░██  
    ░██     ░██  ░█████░██  ░███████  ░██    ░██ ░██ ░██   ░██   ░██ ░██     ░███████   ░██    ░██ 

"""






def setup_font(app: QApplication) -> None:
    try:
        # 加载外部字体文件
        # font_path = PathManage.FONT_EN_PATH
        # font_id = QFontDatabase.addApplicationFont(str(font_path))
        # if font_id == -1:
            # print(f"[Font] 外部字体文件加载失败: {font_path.name}")
            # return
        # loaded = QFontDatabase.applicationFontFamilies(font_id)
        # if not loaded:
            # print(f"[Font] 外部字体注册后未获取到 family 名称")
            # return
        families = ["Microsoft YaHei UI"]
        font = QFont()
        font.setFamilies(families)
        app.setFont(font)
    except Exception as e:
        print(f"Error setting up font: {e}")


def build_str(input) -> str:
    return f"\n{'-' * 25}\n{input}\n{'-' * 25}\n"


def exception_handler(exctype, value, traceback):
    print(build_str("Error caught by main.py:"))
    # Print the original error
    sys.__excepthook__(exctype, value, traceback)
    print(build_str("End of error."))


def main() -> int:
    """程序主入口，返回退出码"""

    print(logo)

    # 设置全局异常处理器
    sys.excepthook = exception_handler

    # 单实例检测
    shared_memory = QSharedMemory("HachimiDX_SingleInstance")
    if shared_memory.attach(QSharedMemory.AccessMode.ReadOnly):
        shared_memory.detach()
        print("程序已在运行中。\nApp is already running.")
        return 2
    if not shared_memory.create(1, QSharedMemory.AccessMode.ReadWrite):
        print("程序已在运行中。\nApp is already running.")
        return 2
    
    # 启动 watchdog (清理 Majdata 进程)
    watchdog_path = project_root / "src" / "services" / "watchdog.py"
    subprocess.Popen(
        [sys.executable, str(watchdog_path), str(os.getpid())],
        creationflags=subprocess.CREATE_NO_WINDOW,
    )

    # 阶段1: 前初始化 在创建 QApplication 之前执行
    result = AllServices.pre_initialize()
    if not result.is_ok:
        print(build_str("Pre-Initialization Error:"))
        print(print_op_result(result))
        print(build_str("End of Pre-Initialization Error."))
        return 3

    # 创建应用
    app = QApplication(sys.argv)
    app.aboutToQuit.connect(AllServices.shutdown_all)

    # 阶段2: 后初始化 在创建 QApplication 之后执行
    result = AllServices.post_initialize()
    if not result.is_ok:
        print(build_str("Post-Initialization Error:"))
        print(print_op_result(result))
        print(build_str("End of Post-Initialization Error."))
        return 3

    app._single_instance_lock = shared_memory # 保持引用

    # 设置界面风格
    # print(f"Available styles: {QStyleFactory.keys()}")
    # print(f"Current style: {app.style().objectName()}")
    app.setStyle("fusion")

    # 设置全局字体
    setup_font(app)

    # 启动主窗口
    window = MainWindow()
    window.show()

    exit_code = app.exec()
    print(f"[main] app.exec() returned exit code = {exit_code}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
