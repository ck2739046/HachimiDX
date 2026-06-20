from __future__ import annotations

import json
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






def load_bpm_segments(notify_path: str | Path) -> OpResult[list[list]]:
    """
    读取 Bpm-Measurer 输出的 notify JSON，计算每个 bpm 段的起始绝对时间(ms)。

    notify JSON 格式（见 Bpm-Measurer/App.HeadlessExport.cs）：
        {
          "global_offset": <秒, float>,
          "timing_points": [
            {"beat_index": <int>, "bpm": <float>, "beats_per_bar": <int>},
            ...
          ]
        }

    段起始绝对时间计算（复刻 Bpm-Measurer/TimingEngine.cs RecalculateTiming，单位秒）：
        time_sec[0] = global_offset
        time_sec[i] = time_sec[i-1] + (beat_index[i] - beat_index[i-1]) * 60.0 / bpm[i-1]
    全程用浮点秒累加，最后一次性 ×1000 取整，避免逐段 round 累积误差。

    Args:
        notify_path: notify JSON 文件路径（通常由 parse_config 生成）。

    Returns:
        OpResult[list[list]]:
            成功 → value = 每段 [bpm, start_ms]；bpm 为 float，start_ms 为 int。
                   示例: [[180.0, 1000], [200.0, 129000]]
            失败 → 文件不存在 / JSON 解析失败 / timing_points 为空 / beat_index 非法等，
                   error_msg 描述原因，error_raw 存原始异常。
    """
    path = Path(notify_path)
    if not path.is_file():
        return err(f"notify file not found: {path}")

    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        return err(f"failed to read notify json {path}: {e}", error_raw=e)

    try:
        global_offset_sec = float(data.get("global_offset", 0.0))
    except (TypeError, ValueError) as e:
        return err(f"invalid global_offset: {e}", error_raw=e)

    raw_points = data.get("timing_points")
    if not raw_points:
        return err(f"notify json has no timing_points: {path}")

    # 按 beat_index 升序排序（C# 端已保证严格递增，稳妥再排一次）
    try:
        points = sorted(raw_points, key=lambda p: int(p["beat_index"]))
    except (KeyError, TypeError, ValueError) as e:
        return err(f"invalid beat_index in timing_points: {e}", error_raw=e)

    segments: list[list] = []
    time_sec = global_offset_sec
    for i, point in enumerate(points):
        try:
            bpm = float(point["bpm"])
            beat_index = int(point["beat_index"])
        except (KeyError, TypeError, ValueError) as e:
            return err(f"invalid timing_point[{i}]: {e}", error_raw=e)

        if i == 0:
            if beat_index != 0:
                return err(
                    f"first timing_point beat_index must be 0, got {beat_index}"
                )
            time_sec = global_offset_sec
        else:
            prev_beat_index = int(points[i - 1]["beat_index"])
            prev_bpm = float(points[i - 1]["bpm"])
            beat_diff = beat_index - prev_beat_index
            if beat_diff <= 0:
                return err(
                    f"beat_index must be strictly increasing, got {prev_beat_index} -> {beat_index}"
                )
            if prev_bpm <= 0:
                return err(f"bpm must be positive, got {prev_bpm}")
            time_sec = time_sec + beat_diff * (60.0 / prev_bpm)

        if bpm <= 0:
            return err(f"bpm must be positive, got {bpm}")

        segments.append([bpm, round(time_sec * 1000)])

    return ok(segments)
