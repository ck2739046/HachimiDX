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



def generate_notify_path() -> Path:
    return PathManage.TEMP_DIR / f"bpm_parse_notify_{generate_uid()}.json"




def parse_config(config_path: str | Path, timeout: float | None = 60.0) -> OpResult[Path]:
    """
    同用 Bpm-Measurer 的 --parse_config 模式，生成 bpm notify 文件。

    Bpm-Measurer 退出码语义（详见 App.HeadlessExport.cs）：
        0   = 成功：notify_path 已写入 JSON
        1   = 读取或解析配置失败
        2   = 写 notify 文件失败
        3   = 其他未预期异常
        None= 进程崩溃（非正常退出）

    Args:
        config_path: bpm 配置文件路径
        timeout: subprocess.run 超时秒数 (默认 60s)

    Returns:
        OpResult[Path]:
            成功 → notify_path
    """

    if timeout is None or timeout <= 0: timeout = 60

    cfg = Path(config_path)
    if not cfg.is_file():
        return err(f"bpm config not found: {cfg}")

    notify_path = generate_notify_path()
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
        f"Bpm-Measurer parse_config failed (exit={exit_code}): {reason}",
        error_raw=f"stderr: {stderr_tail}" if stderr_tail else ""
    )











def load_timing_points(notify_path: str | Path) -> OpResult[list[tuple[float, float, float]]]:
    """
    读取 Bpm-Measurer 输出的 notify JSON，计算每个 bpm 段的起始绝对时间(ms)。

    Args:
        notify_path: notify JSON 文件路径（通常由 parse_config 生成）。

    Returns:
        OpResult[list[tuple[float, float, float]]]:
            成功 → value = 每段 (beat_index, bpm, start_ms)
    """
    res = _load_notify(notify_path)
    if not res.is_ok:
        return err("failed to load notify JSON", inner=res)
    global_offset_sec, timing_points = res.value

    # 计算各段起始时间
    res = _compute_segment_starts(global_offset_sec, timing_points)
    if not res.is_ok:
        return err("failed to compute segment starts", inner=res)

    return ok(res.value)




def _load_notify(notify_path: str | Path) -> OpResult[tuple[float, list[dict]]]:
    """
    读取 Bpm-Measurer notify JSON

    notify JSON 格式（见 Bpm-Measurer/App.HeadlessExport.cs）：
        {
          "global_offset": <秒, float>,
          "timing_points": [
            {"beat_index": <float>, "bpm": <float>, "beats_per_bar": <int>},
            ...
          ]
        }

    Args:
        notify_path: notify JSON 文件路径（通常由 parse_config 生成）。

    Returns:
        OpResult[tuple[float, list[dict]]]:
            成功 → (global_offset_sec, timing_points)
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

    raw_timing_points = data.get("timing_points")
    if not raw_timing_points:
        return err(f"notify json has no timing_points: {path}")

    # 按 beat_index 升序排序（C# 端已保证严格递增，稳妥再排一次）
    try:
        timing_points = sorted(raw_timing_points, key=lambda p: float(p["beat_index"]))
    except (KeyError, TypeError, ValueError) as e:
        return err(f"invalid beat_index in timing_points: {e}", error_raw=e)

    return ok((global_offset_sec, timing_points))




def _compute_segment_starts(global_offset_sec: float, timing_points: list[dict]) -> OpResult[list[tuple[float, float, float]]]:
    """
    段起始绝对时间计算（复刻 Bpm-Measurer/TimingEngine.cs RecalculateTiming)
        time_sec[0] = global_offset
        time_sec[i] = time_sec[i-1] + (beat_index[i] - beat_index[i-1]) * 60.0 / bpm[i-1]

    连续相同 bpm 的段会被合并：仅保留该组首个段，后续相同数值的段不再作为独立段。

    Args:
        global_offset_sec, timing_points

    Returns:
        OpResult[list[tuple[float, float, float]]]: 成功 → [(beat_index, bpm, start_ms), ...]
    """

    if not timing_points:
        return err("timing_points is empty")

    base_sec = float(global_offset_sec)
    segments: list[tuple[float, float, float]] = []
    time_sec = base_sec

    for i, point in enumerate(timing_points):
        try:
            bpm = float(point["bpm"])
            beat_index = float(point["beat_index"])
        except (KeyError, TypeError, ValueError) as e:
            return err(f"invalid timing_point[{i}]: {e}", error_raw=e)

        if i == 0:
            if beat_index != 0:
                return err(
                    f"first timing_point beat_index must be 0, got {beat_index}"
                )
            time_sec = base_sec
        else:
            prev_beat_index = float(timing_points[i - 1]["beat_index"])
            prev_bpm = float(timing_points[i - 1]["bpm"])
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

        # 连续相同 bpm 段去重
        # 如果与最新已保留段 bpm 数值相同, 跳过该段
        # 等 time_sec 累加完成后再跳过 append 本段，不影响后续段
        if segments and bpm == segments[-1][1]:
            continue

        segments.append((beat_index, bpm, time_sec * 1000.0)) # 转成毫秒

    return ok(segments)










def compute_aligned_global_offset(notify_json_path: str | Path,
                                  first_note_time_ms: float,
                                  beat_index: float) -> OpResult[float]:
    """
    根据 first_note_time 与 beat_index 反推 global_offset_sec

    先用 beat_index 算出 first_note 在 bpm 配置中的原始时间。
    将这个时间和 first_note 的实际出现时间的差值，
    应用到原始 global_offset 上，得到新的 global_offset。

    Args:
        notify_json_path
        first_note_time_ms
        beat_index

    Returns:
        OpResult[float]: 成功 → 新 global_offset_sec
    """

    # 读取并解析 notify JSON
    res = _load_notify(notify_json_path)
    if not res.is_ok:
        return err("failed to load notify JSON", inner=res)
    old_global_offset_sec, timing_points = res.value

    # 校验输入数值
    try:
        new_first_note_time_sec = float(first_note_time_ms) / 1000.0
    except (TypeError, ValueError):
        return err(f"first_note_time must be a number, got: {first_note_time_ms!r}")
    if new_first_note_time_sec < 0:
        return err(f"first_note_time must be non-negative, got: {first_note_time_ms}")
    try:
        beat_index = float(beat_index)
    except (TypeError, ValueError):
        return err(f"beat_index must be a number, got: {beat_index!r}")
    if beat_index < 0:
        return err(f"beat_index must be non-negative, got: {beat_index}")

    # 获取 beat_index 在原始 global_offset 下应出现的时间
    res = beat_to_time_sec(beat_index, old_global_offset_sec, timing_points)
    if not res.is_ok:
        return err("failed to compute beat time", inner=res)
    old_first_note_time_sec = res.value

    # 计算新的
    g_new = old_global_offset_sec + new_first_note_time_sec - old_first_note_time_sec
    return ok(g_new)




def beat_to_time_sec(target_beat_index: float,
                     global_offset_sec: float,
                     timing_points: list[dict]) -> OpResult[float]:
    """
    给定 global_offset 与 timing_points，返回指定 beat 对应的绝对时间

    Args:
        target_beat_index
        global_offset_sec
        timing_points

    Returns:
        OpResult[float]: 成功 → 该 beat 的绝对时间
    """
    try:
        target_beat = float(target_beat_index)
    except (TypeError, ValueError):
        return err(f"target_beat_index must be a number, got: {target_beat_index!r}")
    if target_beat < 0:
        return err(f"target_beat_index must be non-negative, got: {target_beat_index!r}")

    res = _compute_segment_starts(global_offset_sec, timing_points)
    if not res.is_ok:
        return err("failed to compute segment starts", inner=res)
    segments = res.value

    # 找到 beat 落在哪段：最后一个 beat_index <= beat
    target_idx = 0
    for i, (seg_beat_index, _, _) in enumerate(segments):
        if seg_beat_index <= target_beat:
            target_idx = i
        else:
            break

    seg_beat_index, seg_bpm, seg_start_sec = segments[target_idx]
    time_sec = seg_start_sec + (target_beat - seg_beat_index) * (60.0 / seg_bpm)
    return ok(time_sec)
