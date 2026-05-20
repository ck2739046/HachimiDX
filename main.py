import os
import subprocess
import sys
from pathlib import Path

# 定义 ROOT
project_root = Path(__file__).parent.resolve()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from PyQt6.QtCore import QSharedMemory
from PyQt6.QtWidgets import QApplication, QStyleFactory
from PyQt6.QtGui import QFont
from src.core.schemas.op_result import print_op_result
from src.app import MainWindow
from src.services import AllServices


# Exit-code:
# 0. normal exit
# 1. general error
# 2. app already running
# 3. initialization error





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

    # 初始化
    result = AllServices.initialize_all()
    if not result.is_ok:
        print(build_str("Initialization Error:"))
        print(print_op_result(result))
        print(build_str("End of Initialization Error."))
        return 3

    # 创建应用
    app = QApplication(sys.argv)
    app.aboutToQuit.connect(AllServices.shutdown_all)

    app._single_instance_lock = shared_memory # 保持引用

    # 设置界面风格
    # print(f"Available styles: {QStyleFactory.keys()}")
    # print(f"Current style: {app.style().objectName()}")
    available_styles = QStyleFactory.keys()
    if "windows11" in available_styles:
        app.setStyle("windows11")

    # 设置全局字体
    setup_font(app)

    # 启动主窗口
    window = MainWindow()
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
