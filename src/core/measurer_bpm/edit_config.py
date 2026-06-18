from __future__ import annotations

import re

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
    读 Bpm-Measurer 原始配置文本，把 global_offset 加上 offset_ms/1000，
    其余行（段表 beat_index/bpm、注释、空行）原样保留。

    校验责任仍在 Bpm-Measurer（导出时已过滤非法段）。本函数只做 global_offset 行的
    加法 + 段表逐字拷贝，不解析 beat_index/bpm。

    Args:
        raw_config_text: Bpm-Measurer 导出的 timing_config.txt 全文（UTF-8）。
        offset_ms: 对齐偏移，整数毫秒。
                   + 表示测量音频比谱面确认视频早；- 表示晚。
                   与 align_audio 输出语义一致（delay → 正，trim → 负）。

    Returns:
        OpResult[str]: 成功时 value 为最终配置文本（换行符与原文一致）。
    """
    if raw_config_text is None:
        return err("raw_config_text is None")

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
            new_val = base + offset_sec
            out_lines.append(f"{prefix}{new_val:.3f}{suffix}")
            found_offset = True
        else:
            out_lines.append(ln)

    if not found_offset:
        return err("原始配置缺少 global_offset 行，无法合并 offset")

    return ok("\n".join(out_lines))
