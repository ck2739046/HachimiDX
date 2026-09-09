import base64
import binascii
import codecs
import ctypes
import datetime
import os
import re
import subprocess
import sys
import threading
from pathlib import Path

from .color import strip_ansi
from .console_input import INPUT_EVENT_PREFIX, INPUT_EVENT_SUFFIX

ROOT = Path(__file__).resolve().parents[2]
LOG_FILE = ROOT / "data" / "logs" / "install_log.txt"
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)


# 强制子进程 stdout/stderr 使用 utf-8，避免中文 gbk 报错
ENV = os.environ.copy()
ENV["PYTHONIOENCODING"] = "utf-8"
ENV["HACHIMIDX_TEE"] = "1"

# 控制台写入永不因编码失败而抛错，避免 pump 线程崩溃导致管道未排空、安装挂死
try:
    sys.stdout.reconfigure(errors="replace")
    sys.stderr.reconfigure(errors="replace")
except (AttributeError, ValueError):
    pass

# 终端是否支持 ANSI 彩色（仅在真实控制台启用 VT）
_CONSOLE_COLOR = False
if sys.stdout.isatty():
    if os.name == "nt":
        try:
            handle = ctypes.windll.kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
            mode = ctypes.c_uint32()
            if ctypes.windll.kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                mode.value |= 0x0004  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
                ctypes.windll.kernel32.SetConsoleMode(handle, mode)
                _CONSOLE_COLOR = True
        except Exception:
            _CONSOLE_COLOR = False
    else:
        _CONSOLE_COLOR = True

_log = open(LOG_FILE, "w", encoding="utf-8")
_write_lock = threading.Lock()




def _emit(text: str, to_stderr: bool) -> None:
    """把文本同时写入日志文件和控制台（日志剥离 ANSI，终端按支持与否透传或剥离）。"""
    with _write_lock:
        _log.write(strip_ansi(text))
        _log.flush()
        stream = sys.stderr if to_stderr else sys.stdout
        stream.write(text if _CONSOLE_COLOR else strip_ansi(text))
        stream.flush()


def _record_input(value: str) -> None:
    with _write_lock:
        clean_value = strip_ansi(value)
        clean_value = "".join(char for char in clean_value if char.isprintable() or char == "\t")
        _log.write(clean_value)
        _log.write("\n")
        _log.flush()


def _partial_prefix_length(text: str) -> int:
    for length in range(min(len(text), len(INPUT_EVENT_PREFIX) - 1), 0, -1):
        if text.endswith(INPUT_EVENT_PREFIX[:length]):
            return length
    return 0


_ANSI_TAIL_RE = re.compile(r"\x1b(?:\[[0-9;?]*)?$")


def _split_ansi_tail(buf: str) -> tuple[str, str]:
    """返回 (可安全输出的文本, 待定的不完整 ANSI 尾部)。

    管道输出按块到达，ANSI 转义序列可能被截断在块边界。此处把结尾处
    可能仍是未结束转义序列的部分扣下，待下一块补齐后再处理，避免残缺
    ANSI 序列漏进日志文件。
    """
    m = _ANSI_TAIL_RE.search(buf)
    if m:
        return buf[:m.start()], m.group()
    return buf, ""


def _process_stdout(text: str, pending: str) -> str:
    data = pending + text
    while data:
        start = data.find(INPUT_EVENT_PREFIX)
        if start < 0:
            keep = _partial_prefix_length(data)
            if keep:
                visible = data[:-keep]
                if visible:
                    _emit(visible, False)
                return data[-keep:]
            _emit(data, False)
            return ""

        if start:
            _emit(data[:start], False)

        end = data.find(INPUT_EVENT_SUFFIX, start + len(INPUT_EVENT_PREFIX))
        if end < 0:
            return data[start:]

        payload = data[start + len(INPUT_EVENT_PREFIX):end]
        try:
            value = base64.b64decode(payload, validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError):
            _emit(data[start:end + len(INPUT_EVENT_SUFFIX)], False)
        else:
            _record_input(value)
        data = data[end + len(INPUT_EVENT_SUFFIX):]
    return ""


def _pump(pipe, to_stderr: bool) -> None:
    """把子进程管道输出实时（逐块）转发到控制台和日志。"""
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    pending = ""
    ansi_tail = ""
    try:
        while True:
            chunk = pipe.read1(4096)
            if not chunk:
                break
            text = decoder.decode(chunk)
            if text:
                buf, ansi_tail = _split_ansi_tail(ansi_tail + text)
                if buf:
                    if to_stderr:
                        _emit(buf, True)
                    else:
                        pending = _process_stdout(buf, pending)
    finally:
        text = decoder.decode(b"", final=True)
        if text:
            buf, ansi_tail = _split_ansi_tail(ansi_tail + text)
            if buf:
                if to_stderr:
                    _emit(buf, True)
                else:
                    pending = _process_stdout(buf, pending)
        # 流结束时仍未闭合的 ANSI 尾部视为残缺，丢弃
        if pending:
            _emit(pending, False)
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
