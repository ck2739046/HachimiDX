from __future__ import annotations

from src.core.schemas.op_result import OpResult, err

from .task_scheduler import TaskScheduler, TaskType


def get_signals():
    """Get TaskScheduler signals for UI/subscribers."""
    return TaskScheduler.get_instance().signals


def register(task_type: TaskType, concurrency: int = 1) -> None:
    """Register a task type with its concurrency limit."""

    if not isinstance(concurrency, int) or concurrency < 1:
        concurrency = 1

    TaskScheduler.get_instance().register(task_type, concurrency=concurrency)


def submit_task(
    task_type: TaskType, cmd: list[str], *, task_name: str | None = ""
) -> OpResult[str]:
    """Submit a new task (pre-built cmd) to the scheduler.

    Args:
        task_type: TaskType
        cmd: list[str] where cmd[0] is program, cmd[1:] are args.
        task_name: optional task name

    Returns:
        OpResult[str]: runner_id
    """
    if not isinstance(cmd, list) or not cmd:
        return err("cmd must be a non-empty list[str]")
    if not isinstance(cmd[0], str) or not cmd[0].strip():
        return err("cmd[0] must be program path")

    return TaskScheduler.get_instance().submit_task(
        task_type, cmd=cmd, task_name=task_name
    )


def cancel(runner_id: str) -> OpResult[None]:
    """Cancel a running task by runner_id."""

    rid = str(runner_id or "").strip()
    if not rid:
        return err("Invalid runner_id")

    return TaskScheduler.get_instance().cancel(rid)
