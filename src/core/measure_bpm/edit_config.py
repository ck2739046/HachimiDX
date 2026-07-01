from __future__ import annotations

import re
from pathlib import Path
from PyQt6.QtWidgets import QFileDialog

from src.core.schemas.op_result import OpResult, ok, err
from .parse_config import parse_config, compute_aligned_global_offset

# 仅识别 Bpm-Measurer 导出格式的 global_offset 行：
#   global_offset = <number>     (number 可带千分位 / 小数 / 前导符号)
# 大小写不敏感；前导空白容错。
# 其余行（段表 beat_index/bpm、注释、空行）逐字透传，不做任何解析或校验。
_GLOBAL_OFFSET_RE = re.compile(
    r'^(\s*global_offset\s*=\s*)(-?[\d,]+(?:\.\d+)?)(.*)$',
    re.IGNORECASE,
)






def set_global_offset(raw_config_text: str, new_offset_sec: float) -> OpResult[str]:
    """
    读 Bpm-Measurer 原始配置文本
    将 global_offset 行替换为 new_offset_sec
    其余行（段表 beat_index/bpm、注释、空行）原样保留

    Args:
        raw_config_text: Bpm-Measurer 导出的 timing_config.txt 全文。
        new_offset_sec: 目标 global_offset（秒，float）。

    Returns:
        OpResult[str]: 最终配置全文。
    """

    if raw_config_text is None or not raw_config_text.strip():
        return err("selected bpm config file is None or empty")

    try:
        new_offset_sec = float(new_offset_sec)
    except (TypeError, ValueError):
        return err(f"new_offset_sec must be a number, got: {new_offset_sec!r}")

    out_lines: list[str] = []
    found_offset = False

    for ln in raw_config_text.splitlines():
        m = _GLOBAL_OFFSET_RE.match(ln)
        if m:
            prefix, _, suffix = m.group(1), m.group(2), m.group(3)
            out_lines.append(f"{prefix}{new_offset_sec:.3f}{suffix}")
            found_offset = True
        else:
            out_lines.append(ln)

    if not found_offset:
        return err("cannot find <global_offset> in the selected bpm config file")

    return ok("\n".join(out_lines))










def export_aligned_config(
    config_path,
    first_note_time_ms: float,
    beat_index: float,
    *,
    parent=None,
) -> OpResult[Path]:
    """
    measure bpm page - main entry

    流程：
        1. 解析 config 生成 notify JSON
        2. 由 first note time + beat_index 计算新的 global_offset
        3. 写入新的 global_offset
        4. 弹 QFileDialog 让用户选保存路径 → 返回新路径

    Returns:
        OpResult[Path]:
            成功 → 新文件路径
            用户取消保存对话框 → error_msg == "user cancelled save dialog"
    """

    src = Path(config_path)
    if not src.is_file():
        return err(f"bpm config not found: {src}")



    # 1. 解析 config 得 notify JSON
    parse_res = parse_config(src)
    if not parse_res.is_ok:
        return err("export_aligned_config error", inner=parse_res)
    
    notify_path = parse_res.value



    # 2. 计算新 global_offset
    try:
        compute_res = compute_aligned_global_offset(
            notify_path, first_note_time_ms, beat_index
        )
    finally:
        # 删除 notify JSON 文件
        try: notify_path.unlink(missing_ok=True)
        except: pass

    if not compute_res.is_ok:
        return err("export_aligned_config error", inner=compute_res)
    
    new_offset_sec = compute_res.value



    # 3. 写入 global_offset
    try:
        raw_text = src.read_text(encoding="utf-8")
    except OSError as e:
        return err(f"failed to read bpm config '{src}': {e}", error_raw=e)

    set_res = set_global_offset(raw_text, new_offset_sec)
    if not set_res.is_ok:
        return err("export_aligned_config error", inner=set_res)
    
    new_raw_text = set_res.value



    # 4. 保存对话框
    default_name = src.stem + "_aligned.txt"
    default_dir = src.parent / default_name
    out_path, _ = QFileDialog.getSaveFileName(parent, "save bpm config", str(default_dir), "bpm config (*.txt)")
    # 对话框关闭后，确保主窗口回到前台
    if parent:
        parent.window().raise_()
        parent.window().activateWindow()
    if not out_path:
        return err("user cancelled save dialog")

    try:
        Path(out_path).write_text(new_raw_text, encoding="utf-8")
    except OSError as e:
        return err(f"failed to write bpm config '{out_path}': {e}", error_raw=e)

    return ok(Path(out_path))
