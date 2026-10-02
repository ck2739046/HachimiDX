from __future__ import annotations

from src.core.schemas.op_result import OpResult, err

from .process_manager import ProcessManager, ProcessManagerSignals


def get_signals() -> ProcessManagerSignals:
    """Get ProcessManager signals for UI/subscribers."""
    return ProcessManager.get_instance().signals


def start(cmd: list[str], *, runner_id: str | None = None) -> OpResult[str]:
    """Start a new process.

    Args:
        cmd: list[str] where cmd[0] is program, cmd[1:] are args.
        runner_id: optional explicit runner_id (must be unique). When omitted, ProcessManager generates one.

    Returns:
        OpResult[str]: runner_id
    """
    mgr = ProcessManager.get_instance()

    if not isinstance(cmd, list) or not cmd:
        return err("cmd must be a non-empty list[str]")
    if not cmd[0] or not isinstance(cmd[0], str):
        return err("cmd[0] must be program path")

    rid = str(runner_id or "").strip()
    if not rid:
        runner_id = None  # Let ProcessManager generate one

    return mgr.start(cmd, runner_id=runner_id)


def cancel(runner_id: str) -> OpResult[None]:
    """Cancel a running process by runner_id."""

    runner_id = str(runner_id or "").strip()
    if not runner_id:
        return err("runner_id is empty")

    mgr = ProcessManager.get_instance()
    return mgr.cancel(runner_id)
