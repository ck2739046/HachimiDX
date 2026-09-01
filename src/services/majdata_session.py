from __future__ import annotations

try:
    import win32gui
except ImportError:
    from win32 import win32gui

import time
from typing import Optional

from PyQt6.QtCore import QObject, QProcess, QTimer, pyqtSignal

from src.core.schemas.op_result import OpResult, ok, err
from .path_manage import PathManage
from .watchdog import shutdown_majdata
from .majdata_command_client import MajdataCommandClient


class MajdataSession(QObject):
    """
    Launche/End MajdataView/MajdataEdit and provides their window handles for embedding.

    Notes:
    1. 同时启动 majdataview 和 majdataedit
    2. 先通过 control file 请求 majdataedit 退出，轮询等待/超时强杀，再强杀 majdataview
    3. 通过轮询方式获取两个程序的窗口句柄（hwnd），通过信号通知调用方
    """

    # signals
    # ready -> 启动时成功找到两个窗口句柄
    # error -> 启动超时，未找到窗口句柄
    # shutdown_finished -> 通知程序退出完成
    ready = pyqtSignal(int, int)  # (majdataview_hwnd, majdataedit_hwnd)
    error = pyqtSignal(str)
    shutdown_finished = pyqtSignal()


    @property
    def majdataview_hwnd(self) -> Optional[int]:
        return self._majdataview_hwnd

    @property
    def majdataedit_hwnd(self) -> Optional[int]:
        return self._majdataedit_hwnd



    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)

        self._majdataview_proc: Optional[QProcess] = None
        self._majdataedit_proc: Optional[QProcess] = None
        self._majdataview_hwnd: Optional[int] = None
        self._majdataedit_hwnd: Optional[int] = None

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(20)
        self._poll_timer.timeout.connect(self._poll_hwnds)
        self._poll_started_at: Optional[float] = None
        self._poll_timeout_s: float = 5.0

        self._shutdown_in_progress: bool = False
        
        self._shutdown_timer = QTimer(self)
        self._shutdown_timer.setInterval(20)
        self._shutdown_timer.timeout.connect(self._poll_majdataedit_exit)
        self._shutdown_started_at: Optional[float] = None
        self._shutdown_timeout_s: float = 10.0
        # 此处设置 10s 是因为 majdataedit 退出时可能有弹窗提示用户是否保存谱面更改
        # 留 10s 时间让用户看到弹窗并点击，然后再强制退出

    

    def start(self) -> OpResult[None]:

        shutdown_majdata()

        majdataview_exe = PathManage.MajdataView_EXE_PATH
        majdataedit_exe = PathManage.MajdataEdit_EXE_PATH

        working_dir = str(majdataedit_exe.parent)

        self._majdataview_proc = QProcess(self)
        self._majdataview_proc.setWorkingDirectory(working_dir)
        self._majdataview_proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self._majdataview_proc.setProgram(str(majdataview_exe))

        self._majdataedit_proc = QProcess(self)
        self._majdataedit_proc.setWorkingDirectory(working_dir)
        self._majdataedit_proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self._majdataedit_proc.setProgram(str(majdataedit_exe))

        self._majdataview_proc.readyReadStandardOutput.connect(self._on_majdataview_stdout_ready)
        self._majdataedit_proc.readyReadStandardOutput.connect(self._on_majdataedit_stdout_ready)

        self._majdataview_proc.start()
        self._majdataedit_proc.start()

        self._majdataview_hwnd = None
        self._majdataedit_hwnd = None

        # 开始轮询窗口句柄
        self._poll_started_at = time.time()
        self._poll_timer.start()

        return ok(None)






    def _on_majdataview_stdout_ready(self) -> None:

        # 过滤输出
        filters = (
            # 启动的 unity memory config 日志
            '[unitymemory] configuration parameters',
            '"memorysetup-'
        )

        if self._majdataview_proc:
            data = self._decode_stdout(self._majdataview_proc.readAllStandardOutput().data())
            if not data: return
            new_lines = []
            for line in data.splitlines():
                if line.lower().strip().startswith(filters):
                    continue
                # 每一行都加上前缀
                time_str = time.strftime("%H:%M:%S")
                new_lines.append(f"[{time_str} MajdataView] " + line.rstrip())
            if new_lines:
                print("\n".join(new_lines))


    def _on_majdataedit_stdout_ready(self) -> None:

        # 过滤输出
        filters = (
            # iniwave 打印
            'initwave'
        )
        
        if self._majdataedit_proc:
            data = self._decode_stdout(self._majdataedit_proc.readAllStandardOutput().data())
            if not data: return
            new_lines = []
            for line in data.splitlines():
                if line.lower().strip().startswith(filters):
                    continue
                # 每一行都加上前缀
                time_str = time.strftime("%H:%M:%S")
                new_lines.append(f"[{time_str} MajdataEdit] " + line.rstrip())
            if new_lines:
                print("\n".join(new_lines))


    @staticmethod
    def _decode_stdout(raw: bytes) -> str:
        for encoding in ('utf-8', 'gbk'):
            try:
                return raw.decode(encoding)
            except (UnicodeDecodeError, LookupError):
                continue
        # 全部失败，用 replace 兜底
        return raw.decode('utf-8', errors='replace')






    def _poll_hwnds(self) -> None:

        if self._poll_started_at is None:
            return

        elapsed = time.time() - self._poll_started_at
        if elapsed > self._poll_timeout_s:
            self._poll_timer.stop()
            self.error.emit("MajdataSession: timed out waiting for MajdataView/MajdataEdit windows.")
            return
        
        def _find_hwnd(keyword: str) -> Optional[int]:
            # 窗口句柄 startswith 匹配
            found = []
            def _enum_cb(hwnd, _):
                if win32gui.IsWindowVisible(hwnd):
                    title = win32gui.GetWindowText(hwnd)
                    if title.startswith(keyword):
                        found.append(int(hwnd))
                return True
            win32gui.EnumWindows(_enum_cb, None)
            return found[0] if found else None

        if self._majdataview_hwnd is None:
            self._majdataview_hwnd = _find_hwnd("MajdataViewX")
        if self._majdataedit_hwnd is None:
            self._majdataedit_hwnd = _find_hwnd("MajdataEdit Neo")

        if self._majdataview_hwnd is not None and self._majdataedit_hwnd is not None:
            self._poll_timer.stop()
            # 延迟 50ms 发出 ready 确保窗口完全就绪
            QTimer.singleShot(
                50, lambda: self.ready.emit(int(self._majdataview_hwnd), int(self._majdataedit_hwnd))
            )







    def shutdown(self) -> None:

        if self._shutdown_in_progress:
            return

        self._shutdown_in_progress = True

        # Stop polling to avoid late emits during teardown.
        self._poll_timer.stop()

        # 1) 暂停 view，关闭 edit
        stop_majdata(exit=True)

        # 2) 非阻塞轮询 MajdataEdit 退出，超时强制杀掉
        self._shutdown_started_at = time.time()
        self._shutdown_timer.start()


    def _poll_majdataedit_exit(self) -> None:

        proc = self._majdataedit_proc

        if proc and proc.state() != QProcess.ProcessState.NotRunning:
            # 如果 majdataedit 还在运行，检查是否超时
            elapsed = time.time() - self._shutdown_started_at
            if elapsed < self._shutdown_timeout_s:
                return
            
            # 超时，强制杀掉
            proc.kill()
            proc.waitForFinished(200)

        # MajdataEdit 已退出（或超时强杀）
        # 3) 关闭 MajdataView
        view_proc = self._majdataview_proc
        if view_proc:
            view_proc.kill()
            view_proc.waitForFinished(200)



        # cleanup
        self._shutdown_timer.stop()
        self._poll_timer.stop()

        self._shutdown_timer = None
        self._poll_timer = None

        self._majdataview_proc = None
        self._majdataedit_proc = None
        self._majdataview_hwnd = None
        self._majdataedit_hwnd = None

        self._shutdown_in_progress = False

        # 发送信号，通知关闭完成
        try:
            self.shutdown_finished.emit()
        except Exception:
            pass






# static method
def stop_majdata(exit=False) -> None:
    """请求 Edit-Neo 复位或退出"""
    client = MajdataCommandClient.get_instance()
    if exit:
        client.send_exit()
    else:
        client.send_reset()
