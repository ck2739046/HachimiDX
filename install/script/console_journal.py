"""本模块在后台按行读屏幕缓冲区，把"光标已经离开"的行落进 log"""

import ctypes
import os
import threading
from pathlib import Path

_STD_OUTPUT_HANDLE = -11
_STD_INPUT_HANDLE = -10

_ENABLE_PROCESSED_OUTPUT = 0x0001
_ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
_ENABLE_MOUSE_INPUT = 0x0010
_ENABLE_QUICK_EDIT_MODE = 0x0040
_ENABLE_EXTENDED_FLAGS = 0x0080

# 默认的屏幕缓冲区高度就等于窗口高度，内容一满便整体上移，行号不再稳定。
# 先把缓冲区加高，之后同一个缓冲行号始终对应同一行输出，日志可以纯按行号推进。
_MIN_BUFFER_HEIGHT = 2000
_BUFFER_GROWTH = 4096
_GROW_MARGIN = 256
_MAX_BUFFER_HEIGHT = 32000

# 光标上方保留不落盘的行数：rich 的 live 区域会往上重画，先等它稳定
_HOLD_ROWS = 3
# 轮询间隔。只影响已完成的行进日志的延迟，屏幕本身由控制台直接绘制
_POLL_SECONDS = 0.08


class _COORD(ctypes.Structure):
    _fields_ = [("X", ctypes.c_short), ("Y", ctypes.c_short)]


class _SMALL_RECT(ctypes.Structure):
    _fields_ = [("Left", ctypes.c_short), ("Top", ctypes.c_short),
                ("Right", ctypes.c_short), ("Bottom", ctypes.c_short)]


class _SCREEN_BUFFER_INFO(ctypes.Structure):
    _fields_ = [("dwSize", _COORD), ("dwCursorPosition", _COORD),
                ("wAttributes", ctypes.c_ushort), ("srWindow", _SMALL_RECT),
                ("dwMaximumWindowSize", _COORD)]


class ConsoleJournal:
    """按行跟随真实控制台的屏幕缓冲区写日志。"""

    def __init__(self, log_path: Path) -> None:
        self._log_path = log_path
        self._k32 = None
        self._handle = None
        self._log = None
        self._thread = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._width = 0
        self._cell = None
        self._read = ctypes.c_uint32()
        # 下一个待落盘的缓冲行号
        self._next_row = 0

    def start(self) -> None:
        """接管控制台并开始跟屏；必须在任何输出之前调用。"""
        if not self._attach():
            raise RuntimeError(
                "安装日志需要真实控制台才能记录，请不要重定向输出"
                "（直接运行 install.bat 或 install\\install.bat）。")

        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        self._log = open(self._log_path, "w", encoding="utf-8", newline="\n")

        # 跟随线程此刻还没创建，不存在并发，这里无需加锁
        info = self._screen_info()
        if info is None:
            raise RuntimeError("无法读取控制台屏幕缓冲区，安装日志不可用。")
        if self._needs_growth(info) and not self._grow_buffer(info):
            raise RuntimeError(
                "无法扩大控制台屏幕缓冲区，安装日志会丢行；"
                "请把窗口放在前台并重新运行。")
        # 光标所在行就是本次安装的第一行输出；
        # 它上面的内容（用户敲的命令、上一个命令的输出）不属于本次安装
        self._next_row = info.dwCursorPosition.Y

        self._thread = threading.Thread(target=self._follow, daemon=True)
        self._thread.start()

    def finish(self) -> None:
        """收尾：把屏幕上的剩余内容落盘并关闭日志。"""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

        with self._lock:
            try:
                self._drain(final=True)
            except OSError:
                pass
        self._log.close()
        self._log = None

    def _attach(self) -> bool:
        """打开控制台（开 VT、关快速编辑）；失败说明输出被重定向。"""
        if os.name != "nt":
            return False

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.GetStdHandle.restype = ctypes.c_void_p
        k32.GetConsoleMode.argtypes = [ctypes.c_void_p,
                                       ctypes.POINTER(ctypes.c_uint32)]
        k32.SetConsoleMode.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        k32.GetConsoleScreenBufferInfo.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(_SCREEN_BUFFER_INFO)]
        k32.SetConsoleScreenBufferSize.argtypes = [ctypes.c_void_p, _COORD]
        k32.ReadConsoleOutputCharacterW.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, _COORD,
            ctypes.POINTER(ctypes.c_uint32)]

        stdout_handle = k32.GetStdHandle(_STD_OUTPUT_HANDLE)
        mode = ctypes.c_uint32()
        if not k32.GetConsoleMode(stdout_handle, ctypes.byref(mode)):
            return False
        # 让 pip / rich 直接走 ANSI 渲染（彩色、正确宽度、原地刷新）
        k32.SetConsoleMode(stdout_handle, mode.value
                           | _ENABLE_PROCESSED_OUTPUT
                           | _ENABLE_VIRTUAL_TERMINAL_PROCESSING)

        # 快速编辑会让"用户选中文本"暂停所有控制台写入，装依赖时 pip 会因此卡死；
        # 鼠标输入会让终端把滚轮/触摸板事件转发给应用，应用不读就导致滚轮彻底失效，所以也要关
        stdin_handle = k32.GetStdHandle(_STD_INPUT_HANDLE)
        stdin_mode = ctypes.c_uint32()
        if k32.GetConsoleMode(stdin_handle, ctypes.byref(stdin_mode)):
            k32.SetConsoleMode(stdin_handle,
                               (stdin_mode.value | _ENABLE_EXTENDED_FLAGS)
                               & ~_ENABLE_QUICK_EDIT_MODE
                               & ~_ENABLE_MOUSE_INPUT)

        # 标准输出句柄同时带读写权限，读回与调整缓冲区都靠它；
        # 只读打开的 CONOUT$ 会让 SetConsoleScreenBufferSize 报 ACCESS_DENIED
        self._k32 = k32
        self._handle = stdout_handle
        return True

    def _screen_info(self):
        info = _SCREEN_BUFFER_INFO()
        if not self._k32.GetConsoleScreenBufferInfo(self._handle,
                                                    ctypes.byref(info)):
            return None
        if info.dwSize.X != self._width:
            self._width = info.dwSize.X
            # 一次只读一行：整段读回时全角字符只返回一个字符而不是两个单元格，
            # 会让后面所有行的切分位置错位
            self._cell = ctypes.create_unicode_buffer(self._width)
        return info

    def _needs_growth(self, info) -> bool:
        height = info.dwSize.Y
        if height >= _MAX_BUFFER_HEIGHT:
            return False
        if height >= _MIN_BUFFER_HEIGHT and height - info.dwCursorPosition.Y > _GROW_MARGIN:
            return False
        return True

    def _grow_buffer(self, info) -> bool:
        """给缓冲区留出回滚空间，让光标始终远离缓冲区底部。"""
        target = min(max(_MIN_BUFFER_HEIGHT, info.dwSize.Y + _BUFFER_GROWTH),
                     _MAX_BUFFER_HEIGHT)
        # 加高失败会让输出滚出缓冲区、日志静默丢行，所以必须把结果报上去
        return bool(self._k32.SetConsoleScreenBufferSize(
            self._handle, _COORD(info.dwSize.X, target)))

    def _read_row(self, row: int) -> str:
        ok = self._k32.ReadConsoleOutputCharacterW(
            self._handle, ctypes.cast(self._cell, ctypes.c_void_p),
            self._width, _COORD(0, row), ctypes.byref(self._read))
        if not ok:
            raise OSError("ReadConsoleOutputCharacterW failed")
        # 没写过的单元格可能是 \x00，先当空格再清尾
        return self._cell[:self._read.value].replace("\x00", " ").rstrip()

    def _drain(self, final: bool = False) -> None:
        """把光标已经离开的行按行号顺序落盘。"""
        info = self._screen_info()
        if info is None:
            return
        if self._needs_growth(info):
            # 启动时已经加高过，后台偶发失败（例如用户改窗口）不值得杀掉跟随线程
            self._grow_buffer(info)
        cursor = info.dwCursorPosition.Y

        limit = cursor + 1 if final else cursor - _HOLD_ROWS
        if limit <= self._next_row:
            return

        # 超过窗口宽度的行会被控制台折成多行，日志按屏幕所见记录（控制台不暴露
        # "折行"标志，靠行宽猜会把 rich 那种刚好填满整行的进度条误判成折行）
        rows = [self._read_row(row) for row in range(self._next_row, limit)]
        self._log.write("".join(row + "\n" for row in rows))
        self._log.flush()
        self._next_row = limit

    def _follow(self) -> None:
        while not self._stop.wait(_POLL_SECONDS):
            try:
                with self._lock:
                    self._drain()
            except Exception:
                # 日志跟随出问题绝不能影响安装
                return


_journal = None


def start(log_path: Path) -> None:
    """开始记录安装日志。"""
    global _journal
    _journal = ConsoleJournal(log_path)
    _journal.start()


def finish() -> None:
    """收尾落盘。"""
    _journal.finish()
