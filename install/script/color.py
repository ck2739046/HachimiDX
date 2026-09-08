"""ANSI 彩色文本辅助。

颜色属于展示层，只在打印点包装，不写入 i18n 字符串。
"""

import re

RESET = "\x1b[0m"
GREEN = "\x1b[32m"
RED = "\x1b[31m"
YELLOW = "\x1b[33m"
CYAN = "\x1b[96m"
BOLD = "\x1b[1m"

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\r")


def green(s: str) -> str:
    """绿色：表示成功/完成的提示（安装完成、卸载完成等）"""
    return f"{GREEN}{s}{RESET}"


def red(s: str) -> str:
    """红色：表示失败/错误提示（安装失败、文件未找到、非法输入、报错等）"""
    return f"{RED}{s}{RESET}"


def yellow(s: str) -> str:
    """黄色：表示警告/需注意但非致命的信息（如切换镜像源）"""
    return f"{YELLOW}{s}{RESET}"


def cyan(s: str) -> str:
    """青色：表示进行中的状态标题/流程开始（开始安装、进度标题等）"""
    return f"{CYAN}{s}{RESET}"


def bold(s: str) -> str:
    """加粗：作为强调修饰"""
    return f"{BOLD}{s}{RESET}"


def hint(s: str) -> str:
    """提示：表示需要用户输入，前面补一个空行与正文分隔"""
    return "\n" + yellow(s)


def note_on_hint(hint_colored: str, note: str) -> str:
    """把默认提示追加到提示行末尾（上一行），避免默认提示另起一行"""
    return f"\x1b[1A\r{hint_colored}{note}\x1b[K"


def strip_ansi(s: str) -> str:
    """剥离 ANSI 转义序列，供写入日志文件时使用"""
    return _ANSI_RE.sub("", s)
