import codecs
import datetime
import os
import subprocess
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOG_FILE = ROOT / "data" / "logs" / "install_log.txt"
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)


# 强制子进程 stdout/stderr 使用 utf-8，避免中文 gbk 报错
ENV = os.environ.copy()
ENV["PYTHONIOENCODING"] = "utf-8"

# 控制台写入永不因编码失败而抛错，避免 pump 线程崩溃导致管道未排空、安装挂死
try:
    sys.stdout.reconfigure(errors="replace")
    sys.stderr.reconfigure(errors="replace")
except (AttributeError, ValueError):
    pass

_log = open(LOG_FILE, "w", encoding="utf-8")
_write_lock = threading.Lock()




def _emit(text: str, to_stderr: bool) -> None:
    """把文本同时写入日志文件和控制台。"""
    with _write_lock:
        _log.write(text)
        _log.flush()
        stream = sys.stderr if to_stderr else sys.stdout
        stream.write(text)
        stream.flush()


def _pump(pipe, to_stderr: bool) -> None:
    """把子进程管道输出实时（逐块）转发到控制台和日志。"""
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    try:
        while True:
            chunk = pipe.read1(4096)
            if not chunk:
                break
            text = decoder.decode(chunk)
            if text:
                _emit(text, to_stderr)
    finally:
        text = decoder.decode(b"", final=True)
        if text:
            _emit(text, to_stderr)
        pipe.close()


def _run(step_cmd: list[str]) -> int:
    """运行一条命令并实时转发其 stdout/stderr，返回退出码。"""
    proc = subprocess.Popen(
        step_cmd,
        env=ENV,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        # stdin 继承控制台，保证交互式安装脚本能正常读取用户输入
        stdin=None,
    )
    threads = [
        threading.Thread(target=_pump, args=(proc.stdout, False), daemon=True),
        threading.Thread(target=_pump, args=(proc.stderr, True), daemon=True),
    ]
    for t in threads:
        t.start()

    while True:
        try:
            code = proc.wait()
            break
        # 用户按下 Ctrl+C, 信号传播路径是
        # install.bat → tee.py → main.py
        # 这里需要忽略 KeyboardInterrupt, 让子进程处理
        except KeyboardInterrupt:
            continue

    for t in threads:
        t.join()
    return code





def main() -> None:
    try:
        time = datetime.datetime.now().strftime("%Y/%m/%d %H:%M:%S")
        _emit(f"{time}\n\n", False)

        cmd = [sys.executable, "-u", "-m", "script.main"]
        exit_code = _run(cmd)
        if exit_code != 0:
            _emit(f"\nProgram ended, exited code: {exit_code}\n", False)
    finally:
        _log.close()

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
