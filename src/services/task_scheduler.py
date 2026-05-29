from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from collections import deque

from PyQt6.QtCore import QObject, pyqtSignal

from src.core.schemas.op_result import OpResult, ok, err
from src.core.tools import generate_uid
from . import process_manager_api


class TaskType(str, Enum):
    MEDIA = "media"
    AUTO_RECHART = "auto_rechart"


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    ENDED = "ended"
    CANCELLED = "cancelled"


@dataclass(slots=True)
class TaskInfo:
    runner_id: str
    task_type: TaskType
    task_name: str = ""
    accepted_at: Optional[datetime] = None
    status: TaskStatus = TaskStatus.PENDING
    cmd: Optional[list[str]] = None
    error_msg: Optional[str] = None


class TaskSchedulerSignals(QObject):
    task_list_changed = pyqtSignal(object)


@dataclass(slots=True)
class _RegisteredType:
    concurrency: int = 1


class TaskScheduler(QObject):
    """Minimal scheduler.

    - Owns NO QProcess.
    - Runs commands via ProcessManager (runner_id is used as process runner_id).
    - Pipelines build cmd themselves and submit to scheduler.
    - Emits task_list_changed snapshots for UI.
    """

    _instance: Optional["TaskScheduler"] = None

    @classmethod
    def get_instance(cls) -> "TaskScheduler":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.signals = TaskSchedulerSignals()
        self._registry: dict[TaskType, _RegisteredType] = {}
        self._tasks: dict[str, TaskInfo] = {}
        self._pending: dict[TaskType, deque[str]] = {}
        self._running: dict[TaskType, set[str]] = {}
        self._done: dict[TaskType, deque[str]] = {}
        self._done_keep_limit: int = 60 # 最多保留最近60个已完成任务

        try:
            process_manager_api.get_signals().runner_ended.connect(self._on_runner_ended)
        except Exception:
            pass




    # -------------------
    # Registration
    # -------------------

    def register(self, task_type: TaskType, *, concurrency: int = 1) -> None:

        self._registry[task_type] = _RegisteredType(concurrency=concurrency)
        self._pending.setdefault(task_type, deque())
        self._running.setdefault(task_type, set())
        self._done.setdefault(task_type, deque())





    # -------------------
    # Public API
    # -------------------

    def submit_task(self,
                    task_type: TaskType,
                    *,
                    cmd: list[str],
                    task_name: str = "") -> OpResult[str]:

        if task_type not in self._registry:
            return err(f"Task type not registered: {task_type}")

        # 尝试生成 runner_id
        for attempt in range(3):
            rid = generate_uid()
            if rid not in self._tasks:
                break
        else:
            return err(f"Failed to generate unique runner_id.")

        info = TaskInfo(
            runner_id=rid,
            task_type=task_type,
            task_name=str(task_name or "").strip(),
            accepted_at=datetime.now(),
            status=TaskStatus.PENDING,
            cmd=cmd,
        )
        self._tasks[rid] = info
        self._pending.setdefault(task_type, deque()).append(rid)

        self._emit_snapshot()
        self._dispatch(task_type)

        return ok(rid)




    def cancel(self, runner_id: str) -> OpResult[None]:

        rid = str(runner_id)

        task = self._tasks.get(rid)
        if task is None:
            return err(f"Task not found: {rid}")

        ttype = task.task_type
        pending_list = self._pending.get(ttype, deque())
        running_set = self._running.get(ttype, set())
        done_list = self._done.get(ttype, deque())

        if rid in pending_list:
            self._pending[ttype] = deque(x for x in pending_list if x != rid)
            task.status = TaskStatus.CANCELLED
            self._mark_done(ttype, rid)
            self._emit_snapshot()
            return ok()

        if rid in running_set:
            # 仅调用 process manager 取消
            # 真正的 end 状态由 _on_runner_ended 处理
            res = process_manager_api.cancel(rid)
            if not res.is_ok:
                return err(f"Failed to cancel running task: {res.error_msg}")
            return ok()

        if rid in done_list:
            # 如果在 done 中，执行彻底删除（类似 Dismiss）
            self._done[ttype] = deque(x for x in done_list if x != rid)
            self._purge_task(rid)
            self._emit_snapshot()
            return ok()

        return ok()



    # -------------------
    # Dispatch
    # -------------------

    def _dispatch(self, task_type: TaskType) -> None:
        reg = self._registry.get(task_type)
        if reg is None:
            return

        pending_list = self._pending.setdefault(task_type, deque())
        running_set = self._running.setdefault(task_type, set())

        # 如果有 pending 任务，且未达并发上限，则启动新任务
        while pending_list and len(running_set) < reg.concurrency:
            rid = pending_list.popleft()
            task = self._tasks.get(rid)
            if task is None:
                continue
            if task.status == TaskStatus.CANCELLED:
                continue

            # Start process
            start_res = process_manager_api.start(task.cmd, runner_id=rid)
            if not start_res.is_ok:
                task.status = TaskStatus.ENDED
                task.error_msg = start_res.error_msg or "process start failed"
                self._mark_done(task_type, rid)
                self._emit_snapshot()
                continue

            # Success! Now it is officially RUNNING
            task.status = TaskStatus.RUNNING
            running_set.add(rid)
            self._emit_snapshot()







    # -------------------
    # Process callbacks
    # -------------------

    def _on_runner_ended(self, runner_id: str, result: object) -> None:

        rid = str(runner_id).strip()
        task = self._tasks.get(rid)
        if task is None:
            return

        # finalize status
        cancelled = False
        crashed = False
        exit_code: Optional[int] = None
        error_msg: Optional[str] = None

        # Best-effort inspect ProcessManager.RunnerEnded
        try:
            cancelled = bool(getattr(result, "cancelled", False))
            crashed = bool(getattr(result, "crashed", False))
            exit_code = getattr(result, "exit_code", None)
            error_msg = getattr(result, "error_msg", None)
        except Exception:
            pass

        if cancelled or task.status == TaskStatus.CANCELLED:
            task.status = TaskStatus.CANCELLED
        else:
            task.status = TaskStatus.ENDED

        # Map runner result into a readable error message for UI diagnostics.
        if error_msg:
            task.error_msg = str(error_msg)
        elif task.status != TaskStatus.CANCELLED:
            if crashed:
                task.error_msg = "crashed"
            elif isinstance(exit_code, int) and exit_code != 0:
                task.error_msg = f"exit_code={exit_code}"
            else:
                task.error_msg = None

        self._running.get(task.task_type, set()).discard(rid)
        self._mark_done(task.task_type, rid)
        self._emit_snapshot()
        self._dispatch(task.task_type)







    def _mark_done(self, task_type: TaskType, runner_id: str) -> None:
        dq = self._done.setdefault(task_type, deque())
        if dq and dq[-1] == runner_id:
            return
        if runner_id in dq:
            try:
                dq.remove(runner_id)
            except Exception:
                pass
        dq.append(runner_id)
        while len(dq) > self._done_keep_limit:
            old_id = dq.popleft()
            # Purge old completed task to avoid unbounded memory growth.
            self._purge_task(old_id)






    def _purge_task(self, runner_id: str) -> None:
        """Remove a task from all scheduler registries.

        This is only called for tasks that have fallen off the done-history limit.
        """
        rid = str(runner_id)
        task = self._tasks.pop(rid, None)
        if task is None:
            return

        ttype = task.task_type
        # Ensure it is not tracked elsewhere.
        try:
            self._running.get(ttype, set()).discard(rid)
        except Exception:
            pass

        try:
            pending = self._pending.get(ttype)
            if pending is not None and rid in pending:
                self._pending[ttype] = deque(x for x in pending if x != rid)
        except Exception:
            pass






    # -------------------
    # Snapshot
    # -------------------

    def _emit_snapshot(self) -> None:
        try:
            snapshot: dict[str, list[TaskInfo]] = {}
            for ttype in self._registry.keys():
                # Collect running/pending/done, then stably sort by accepted_at.
                by_id: dict[str, TaskInfo] = {}
                for rid in self._running.get(ttype, set()):
                    task = self._tasks.get(rid)
                    if task is not None:
                        by_id[rid] = task
                for rid in self._pending.get(ttype, deque()):
                    task = self._tasks.get(rid)
                    if task is not None:
                        by_id[rid] = task
                for rid in self._done.get(ttype, deque()):
                    task = self._tasks.get(rid)
                    if task is not None:
                        by_id[rid] = task

                def sort_key(t: TaskInfo):
                    # accepted_at should always exist, but keep a stable fallback.
                    ts = t.accepted_at.timestamp() if t.accepted_at else float("inf")
                    return (ts, t.runner_id)

                items = sorted(by_id.values(), key=sort_key)
                snapshot[ttype.value] = items
            self.signals.task_list_changed.emit(snapshot)
        except Exception:
            pass
