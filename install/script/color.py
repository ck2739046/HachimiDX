"""
ANSI 彩色文本辅助。

颜色属于展示层，只在打印点包装，不写入 i18n 字符串。
"""

import unicodedata


RESET = "\x1b[0m"
REVERSE = "\x1b[7m"

GREEN = "\x1b[92m"
RED = "\x1b[91m"
YELLOW = "\x1b[93m"
CYAN = "\x1b[96m"



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


def reverse(s: str) -> str:
    """反显：背景是颜色，文字镂空"""
    return f"{REVERSE}{s}{RESET}"


def hint(s: str) -> str:
    """提示：表示需要用户输入，前面补一个空行与正文分隔"""
    return "\n" + yellow(s)


def note_on_hint(hint_colored: str, note: str) -> str:
    """把默认提示追加到提示行末尾（上一行），避免默认提示另起一行"""
    return f"\x1b[1A\r{hint_colored}{note}\x1b[K"


def get_separator(text: str) -> str:
    """获取分隔线：与文本等宽的一行 === """
    width = 0
    for c in text:
        if unicodedata.east_asian_width(c) in "WF":
            width += 2  # 中文占2格
        else:
            width += 1  # 其他占1格
    return "=" * width
