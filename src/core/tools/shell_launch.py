import subprocess
from pathlib import Path


def launch_console_script(script: Path, work_dir: Path | None = None) -> bool:
    """
    在独立控制台中启动脚本，并使脚本脱离本进程的进程树。

    主程序退出后 watchdog.cleanup() 会强杀主进程的所有后代进程，
    因此这里经 `cmd /c start` 转手：脚本的父进程是包装 cmd 而非本进程，
    包装 cmd 退出后 psutil 的祖先链即断裂，脚本不再被视为后代。
    """
    wrapper = subprocess.Popen(
        # 标题传空串：start 只在标题被引号包裹时才识别它，否则会当成要执行的命令。
        # 显式 cmd /c 承载脚本，否则 start 会用 cmd /K 拉起 .bat，脚本结束后窗口不关。
        ["cmd", "/c", "start", "", "/d", str(work_dir or script.parent), "cmd", "/c", str(script)],
        creationflags=subprocess.CREATE_NO_WINDOW,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # 必须等包装 cmd 退出，否则脚本仍是本进程的后代，会被 watchdog 杀掉
    try:
        wrapper.wait(timeout=10)
    except subprocess.TimeoutExpired:
        wrapper.kill()
        return False
    return wrapper.returncode == 0
