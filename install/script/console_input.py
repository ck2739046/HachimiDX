"""在提问前清空 stdin 缓冲区，避免历史按键被误当作下一次 input() 的答案。"""
import base64
import os
import sys


INPUT_EVENT_PREFIX = "\x1eHACHIMIDX_INPUT:"
INPUT_EVENT_SUFFIX = "\x1f"


def flush_stdin() -> None:
    """丢弃控制台输入缓冲区中已积累、尚未被读取的按键。"""
    # Windows: 用 msvcrt 抽干控制台输入队列
    try:
        import msvcrt
        while msvcrt.kbhit():
            msvcrt.getch()
        return
    except ImportError:
        pass

    # POSIX: 直接刷掉输入队列
    try:
        import termios
        termios.tcflush(sys.stdin, termios.TCIFLUSH)
    except (ImportError, OSError):
        # 非 TTY（重定向/管道）时无需处理
        pass


def _record_input(value: str) -> None:
    if os.environ.get("HACHIMIDX_TEE") != "1":
        return
    payload = base64.b64encode(value.encode("utf-8")).decode("ascii")
    sys.stdout.write(f"{INPUT_EVENT_PREFIX}{payload}{INPUT_EVENT_SUFFIX}")
    sys.stdout.flush()


def ask(prompt: str) -> str:
    """清空输入缓冲后向用户提问，返回去除首尾空白后的回答。"""
    flush_stdin()
    value = input(prompt).strip()
    _record_input(value)
    return value
