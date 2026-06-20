from __future__ import annotations

import re
from pathlib import Path
from PyQt6.QtWidgets import QFileDialog

from src.core.schemas.op_result import OpResult, ok, err

# 仅识别 Bpm-Measurer 导出格式的 global_offset 行：
#   global_offset = <number>     (number 可带千分位 / 小数 / 前导符号)
# 大小写不敏感；前导空白容错。
# 其余行（段表 beat_index/bpm、注释、空行）逐字透传，不做任何解析或校验。
_GLOBAL_OFFSET_RE = re.compile(
    r'^(\s*global_offset\s*=\s*)(-?[\d,]+(?:\.\d+)?)(.*)$',
    re.IGNORECASE,
)


def update_global_offset(raw_config_text: str, offset_ms: int) -> OpResult[str]:
    """
    读 Bpm-Measurer 原始配置文本，用 offset_ms/1000 修正 global_offset，
    其余行（段表 beat_index/bpm、注释、空行）原样保留。

    校验责任仍在 Bpm-Measurer（导出时已过滤非法段）。
    本函数只做 global_offset 行的修正 + 段表逐字拷贝，不解析 beat_index/bpm。

    Args:
        raw_config_text: Bpm-Measurer 导出的 timing_config.txt 全文（UTF-8）。
        offset_ms: 对齐偏移，整数毫秒。
                   + 表示谱面确认视频比测量音频早；- 表示晚。
                   与 parse_offset_ms 返回值语义一致：delay → 正，trim → 负

    Returns:
        OpResult[str]: 成功时 value 为最终配置文本（换行符与原文一致）。
    """
    if raw_config_text is None or not raw_config_text.strip():
        return err("selected bpm config file is None or empty")

    try:
        offset_sec = int(offset_ms) / 1000.0
    except (TypeError, ValueError):
        return err(f"offset_ms must be an integer, got: {offset_ms!r}")

    out_lines: list[str] = []
    found_offset = False

    for ln in raw_config_text.splitlines():
        m = _GLOBAL_OFFSET_RE.match(ln)
        if m:
            prefix, num_str, suffix = m.group(1), m.group(2), m.group(3)
            num_clean = num_str.replace(",", "")
            try:
                base = float(num_clean)
            except ValueError:
                # 数字解析失败：原样透传该行，不修改（避免静默丢数据）。
                out_lines.append(ln)
                continue
            new_val = base - offset_sec
            out_lines.append(f"{prefix}{new_val:.3f}{suffix}")
            found_offset = True
        else:
            out_lines.append(ln)

    if not found_offset:
        return err("cannot find <global_offset> in the selected bpm config file")

    return ok("\n".join(out_lines))






def edit_config(
    config_path,
    offset_ms: int,
    *,
    parent=None,
) -> OpResult[Path]:
    """
    读 bpm config 文本 → 用 update_global_offset 修正 global_offset
    → 弹 QFileDialog 让用户选保存路径 → 写入 → 返回新路径。

    Args:
        config_path: 原始 bpm config 文件路径（.txt）。
        offset_ms: 对齐偏移，整数毫秒；语义同 update_global_offset。
        parent: QFileDialog 的父窗口（可选）。

    Returns:
        OpResult[Path]:
            成功 → value 为写入的新文件路径。
            失败 → 读失败 / update_global_offset 失败 / 用户取消保存 / 写失败，
                  error_msg 描述原因。
    """
    src = Path(config_path)
    try:
        raw_text = src.read_text(encoding="utf-8")
    except OSError as e:
        return err(f"failed to read bpm config '{src}': {e}", error_raw=e)

    res = update_global_offset(raw_text, offset_ms)
    if not res.is_ok:
        return res  # 透传 OpResult[str] 的 err（类型兼容 OpResult[Any]）

    default_name = src.stem + "_aligned.txt"
    default_dir = src.parent / default_name
    out_path, _ = QFileDialog.getSaveFileName(parent, "save bpm config", str(default_dir), "bpm config (*.txt)")
    if not out_path:
        return err("user cancelled save dialog")

    try:
        Path(out_path).write_text(res.value, encoding="utf-8")
    except OSError as e:
        return err(f"failed to write bpm config '{out_path}': {e}", error_raw=e)

    return ok(Path(out_path))
