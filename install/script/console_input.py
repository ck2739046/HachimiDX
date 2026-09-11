"""在提问前清空 stdin 缓冲区，避免历史按键被误当作下一次 input() 的答案。"""
import sys


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


def ask(prompt: str) -> str:
    """清空输入缓冲后向用户提问，返回去除首尾空白后的回答。"""
    flush_stdin()
    return input(prompt).strip()
