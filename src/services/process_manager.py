from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Any, Optional
import time

from PyQt6.QtCore import QObject, QProcess, QTimer, pyqtSignal

from src.core.schemas.op_result import OpResult, ok, err
from src.core.tools import generate_uid


@dataclass(slots=True)
class RunnerEnded:
    runner_id: str
    exit_code: Optional[int] = None
    crashed: bool = False
    cancelled: bool = False
    error_msg: Optional[str] = None
    error_raw: Any = None


class ProcessManagerSignals(QObject):
    runner_output = pyqtSignal(str, object)  # (runner_id, bytes)
    runner_ended = pyqtSignal(str, object)   # (runner_id, RunnerEnded)


class ProcessManager(QObject):
    """Centralized QProcess manager.

    Responsibilities (minimal):
    - Own all QProcess instances.
    - Assign/accept runner_id.
    - Read merged output and forward via a single signal with runner_id.
    - Emit ended signal with runner_id.

    Singleton lifecycle:
    - get_instance(): lazy singleton creation (auto-initializes)
    """

    _instance: Optional["ProcessManager"] = None

    @classmethod
    def get_instance(cls) -> "ProcessManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.signals = ProcessManagerSignals()

        # 每 50ms 发送一轮信号
        self._flush_interval_ms: int = 50        

        # dict: runner_id -> QProcess
        self._procs: dict[str, QProcess] = {}

        # dict: runner_id -> output buffer
        self._buffers: dict[str, bytearray] = {}

        # 记录有哪些 runner_id 请求取消了
        # 临时存着，等 process 真正结束后会删掉
        self._cancel_requested: set[str] = set()

        # dict: runner_id -> last error message
        # 临时存着，等 process 结束后会删掉
        self._last_error: dict[str, str] = {}

        # 启动总定时器
        self._flush_timer = QTimer(self)
        self._flush_timer.setInterval(self._flush_interval_ms)
        self._flush_timer.timeout.connect(self._flush_all_buffers)
        self._flush_timer.start()



    # -------------------
    # Public operations
    # -------------------

    def start(self, cmd: list[str], *, runner_id: Optional[str] = None) -> OpResult[str]:
        
        if not runner_id:
            # 尝试生成 runner_id
            for attempt in range(3):
                runner_id = generate_uid()
                if runner_id not in self._procs:
                    break
            else:
                return err("Failed to generate unique runner_id.")
        else:
            # 指定了 runner_id
            if runner_id in self._procs:
                return err(f"runner_id already exists: {runner_id}")
            
        rid = str(runner_id).strip()
            
        process = QProcess(self)
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)

        program = cmd[0]
        args = cmd[1:]

        process.setProgram(program)
        process.setArguments(args)

        self._procs[rid] = process
        self._buffers[rid] = bytearray()

        process.readyReadStandardOutput.connect(lambda rid=rid: self._on_ready_read(rid))
        process.finished.connect(lambda code, status, rid=rid: self._on_finished(rid, int(code), status))
        process.errorOccurred.connect(lambda e, rid=rid: self._on_error(rid, e))

        # 延迟发送开始文本
        start_msg = f"\n-\n{'=' * 30}\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] Task_id '{rid}' start.\n-\n{", ".join(cmd)}\n-\n"
        QTimer.singleShot(0, lambda rid=rid: self.signals.runner_output.emit(rid, bytes(start_msg, 'utf-8')))
        
        process.start()

        return ok(rid)




    def cancel(self, runner_id: str) -> OpResult[None]:

        rid = str(runner_id).strip()

        proc = self._procs.get(rid)
        if proc is None:
            return err(f"runner_id not found: {rid}")

        self._cancel_requested.add(rid)

        try:
            if proc.state() != QProcess.ProcessState.NotRunning:
                proc.terminate()
                QTimer.singleShot(400, lambda rid=rid: self._force_kill_if_running(rid))
        except Exception as e:
            return err("Failed to cancel process", error_raw = e)

        return ok(None)




    # -------------------
    # Internal helpers
    # -------------------  

    def _on_ready_read(self, runner_id: str) -> None:

        proc = self._procs.get(runner_id)
        if proc is None:
            return

        data = proc.readAllStandardOutput()
        if not data:
            return

        buf = self._buffers.get(runner_id)
        if buf is None:
            self._buffers[runner_id] = bytearray()
            buf = self._buffers[runner_id]

        buf.extend(bytes(data))




    def _flush_all_buffers(self) -> None:
        # Emit at most once per interval per runner.
        for rid, buf in list(self._buffers.items()):
            if not buf:
                continue
            payload = bytes(buf)
            buf.clear()
            try:
                self.signals.runner_output.emit(rid, payload)
            except Exception:
                pass

    def _flush_one_buffer(self, runner_id: str) -> None:
        buf = self._buffers.get(runner_id)
        if not buf:
            return
        payload = bytes(buf)
        buf.clear()
        try:
            self.signals.runner_output.emit(runner_id, payload)
        except Exception:
            pass





    def _on_finished(self, runner_id: str, exit_code: int, exit_status: QProcess.ExitStatus) -> None:
        if runner_id not in self._procs:
            return

        self._flush_one_buffer(runner_id)

        cancelled = runner_id in self._cancel_requested
        crashed = exit_status == QProcess.ExitStatus.CrashExit
        error_msg = self._last_error.get(runner_id)

        ended = RunnerEnded(
            runner_id=runner_id,
            exit_code=exit_code,
            crashed=bool(crashed),
            cancelled=bool(cancelled),
            error_msg=error_msg,
        )
        self._emit_and_cleanup_ended(runner_id, ended)




    def _on_error(self, runner_id: str, err_type: QProcess.ProcessError) -> None:

        if runner_id not in self._procs:
            return
        
        # 从 error_type 获取错误信息
        self._last_error[runner_id] = getattr(err_type, "name", str(err_type))

        # 一般情况下，finished() 会被调用，从而触发 ended 信号
        # 但是某些错误不会触发 finished()，所以这里也做一次检查
        proc = self._procs.get(runner_id)
        if proc is None:
            return
        try:
            is_not_running = proc.state() == QProcess.ProcessState.NotRunning
        except RuntimeError:
            # QProcess 的 C++ 对象已被 deleteLater() 销毁
            # _on_finished 先于本槽执行，此时无需重复清理
            return
        if is_not_running:
            self._flush_one_buffer(runner_id)
            ended = RunnerEnded(
                runner_id=runner_id,
                exit_code=None,
                crashed=False,
                cancelled=(runner_id in self._cancel_requested),
                error_msg=self._last_error.get(runner_id),
            )
            self._emit_and_cleanup_ended(runner_id, ended)




    def _force_kill_if_running(self, runner_id: str) -> None:

        proc = self._procs.get(runner_id)
        if proc is None:
            return
        try:
            if proc.state() == QProcess.ProcessState.NotRunning:
                return
        except RuntimeError:
            # QProcess 的 C++ 对象已被销毁
            return
        
        pid = int(proc.processId())
        if pid <= 0:
            proc.kill()
            return

        # /T: tree, /F: force
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


            

    def _emit_and_cleanup_ended(self, runner_id: str, ended: RunnerEnded) -> None:
        try:
            # 先发送结束文本
            end_msg = f"\n-\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] Task_id '{runner_id}' ended.\n-\n"
            self.signals.runner_output.emit(runner_id, bytes(end_msg, 'utf-8'))
            # 然后发送 ended 信号
            self.signals.runner_ended.emit(runner_id, ended)
        except Exception:
            pass

        proc = self._procs.pop(runner_id, None)
        self._buffers.pop(runner_id, None)
        self._cancel_requested.discard(runner_id)
        self._last_error.pop(runner_id, None)

        if proc is not None:
            try:
                proc.deleteLater()
            except Exception:
                pass
