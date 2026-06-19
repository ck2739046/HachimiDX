from __future__ import annotations

import subprocess
from pathlib import Path

from src.services import PathManage
from src.core.schemas.op_result import OpResult, ok, err
from src.core.tools import generate_uid
from src.core.build_bpm_measurer_cmd import build_parse_config_cmd


# Bpm-Measurer --parse_config 无头模式退出码语义（见 App.HeadlessExport.cs）。
# 0（成功）不在表中；其他码 / None（崩溃）均视为失败。
_EXIT_CODE_REASON: dict[int, str] = {
    1: "failed to read or parse config",
    2: "failed to write notify file",
    3: "unexpected error",
}


def parse_config(config_path: str | Path, *, timeout: float | None = 60.0) -> OpResult[Path]:
    """
    同步调用 Bpm-Measurer 的 --parse_config 无头模式，解析 bpm 配置文件。

    流程：
        1. 校验 config_path 存在。
        2. 生成 uuid notify 路径：TEMP_DIR / bpm_parse_notify_<uuid>.json
           （沿用 measure_bpm_page 的 notify 命名约定；若已存在先删，避免读到旧结果）。
        3. build_parse_config_cmd 拼命令，subprocess.run 阻塞等待退出码。
        4. 按退出码归类：成功返回 notify_path，失败返回带退出码与原因的 err。

    Bpm-Measurer 退出码语义（详见 App.HeadlessExport.cs）：
        0   = 成功：notify_path 已写入 JSON（global_offset + timing_points）
        1   = 读取或解析配置失败
        2   = 写 notify 文件失败
        3   = 其他未预期异常
        None= 进程崩溃（非正常退出）

    Args:
        config_path: bpm 配置文件路径（.txt）。
        timeout: subprocess.run 超时秒数（None 表示不限时）。默认 60s。

    Returns:
        OpResult[Path]:
            成功（exit_code == 0）→ value = notify_path，可读取其中的 JSON。
            失败 → config 不存在 / 清理旧 notify 失败 / 启动失败 / 退出码非 0（error_raw 存退出码）。
    """
    cfg = Path(config_path)
    if not cfg.is_file():
        return err(f"bpm config not found: {cfg}")

    notify_path = PathManage.TEMP_DIR / f"bpm_parse_notify_{generate_uid()}.json"
    if notify_path.exists():
        try:
            notify_path.unlink()
        except OSError as e:
            return err(f"failed to clean stale notify path: {notify_path}", error_raw=e)

    cmd = build_parse_config_cmd(notify_path, cfg)
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as e:
        return err(f"failed to launch Bpm-Measurer: {e}", error_raw=e)

    exit_code = proc.returncode
    if exit_code == 0:
        return ok(notify_path)

    reason = _EXIT_CODE_REASON.get(exit_code, "unknown error")
    stderr_tail = proc.stderr.decode("utf-8", errors="replace").strip()
    return err(
        f"Bpm-Measurer parse_config failed (exit={exit_code}): {reason}"
        + (f"\nstderr: {stderr_tail}" if stderr_tail else ""),
        error_raw=exit_code,
    )
