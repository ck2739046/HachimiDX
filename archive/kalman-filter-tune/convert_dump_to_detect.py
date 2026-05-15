"""
convert_dump_to_detect.py

将 Dump_Notes 生成的 txt 转换为 detect_result.txt 格式（与 detect.py 的 _save_detect_results 一致）。

用法:
    python convert_dump_to_detect.py <dump_output.txt> [--output detect_result.txt]

支持转换所有音符类型：Tap(含Break)、Slide(含第一段StarNote和第二段StarNote-Move)、Touch、TouchHold、Hold
"""

import re
import sys
from collections import defaultdict
from pathlib import Path

# ── 常量（与 label_notes.py 的尺寸公式一致） ──
BASE_1080 = 1080.0

# ── OBB 尺寸系数 ──

# Tap: normal 半边长系数
TAP_HALF_NORMAL = 0.049
# Tap: EX 半边长系数
TAP_HALF_EX = 0.055

# Slide:
#   第一段 Scale: half = 1080 * 0.05 * starScale.x (normal)
SLIDE_STAR_SCALE_COEFF = 0.05
#   第一段 非Scale: half = 1080 * 0.049 (normal 固定)
SLIDE_FIXED_HALF_NORMAL = BASE_1080 * 0.049
#   第二段 Move: half = 1080 * 0.055 * 0.88 * starScale.x
SLIDE_MOVE_COEFF = 0.055 * 0.88

# Touch
TOUCH_HALF_BASE_OFFSET = 54  # touchDecor + 54
# TouchHold
TOUCH_HOLD_HALF_BASE_OFFSET = 68  # touchDecor + 68

# Hold
#   宽度: 140 * 0.5 * 0.77 * holdScale.x
HOLD_WIDTH_COEFF = 140 * 0.5 * 0.77
#   长度: (holdSize - 20) * 0.5 * holdScale.x

# ── 坐标变换 ──
def world_to_pixel(pos_x: float, pos_y: float) -> tuple[float, float]:
    """游戏世界坐标 → 屏幕像素坐标"""
    return (BASE_1080 + pos_x, 120.0 - pos_y)


# ── 数据类 ──
class ParsedNote:
    """解析后的单帧 note 数据"""
    __slots__ = (
        "note_type",     # str: 原始类型名
        "note_index",    # int
        "pos_x",         # float
        "pos_y",         # float
        "status",        # str
        "is_ex",         # bool
        # Touch
        "touch_decor",   # float (默认 0)
        "touch_alpha",   # float (默认 0)
        # Hold
        "hold_scale_x",  # float (默认 1)
        "hold_scale_y",  # float (默认 1)
        "hold_body_size",# float (默认 0)
        # Tap
        "tap_scale_x",   # float (默认 1)
        "tap_scale_y",   # float (默认 1)
        # Star/Slide
        "star_scale_x",  # float (默认 1)
        "star_scale_y",  # float (默认 1)
    )

    def __init__(self, **kwargs):
        for slot in self.__slots__:
            setattr(self, slot, kwargs.get(slot, None))
        # 默认值
        if self.touch_decor is None: self.touch_decor = 0.0
        if self.touch_alpha is None: self.touch_alpha = 0.0
        if self.hold_scale_x is None: self.hold_scale_x = 1.0
        if self.hold_scale_y is None: self.hold_scale_y = 1.0
        if self.hold_body_size is None: self.hold_body_size = 0.0
        if self.tap_scale_x is None: self.tap_scale_x = 1.0
        if self.tap_scale_y is None: self.tap_scale_y = 1.0
        if self.star_scale_x is None: self.star_scale_x = 1.0
        if self.star_scale_y is None: self.star_scale_y = 1.0
        if self.is_ex is None: self.is_ex = False


# ── 类型映射 ──
def map_note_type(note: ParsedNote) -> tuple[str, str]:
    """
    返回 (detect_note_type, note_variant)
    detect_note_type: "tap" / "slide" / "touch" / "touch_hold" / "hold"
    note_variant: "normal" / "break" / "ex" / "break_ex"
    """
    tl = note.note_type.lower()

    # Variant
    is_break = "break" in tl
    if is_break and note.is_ex:
        variant = "break_ex"
    elif is_break:
        variant = "break"
    elif note.is_ex:
        variant = "ex"
    else:
        variant = "normal"

    # Type
    if "tap" in tl or tl == "breaknote":
        return ("tap", variant)
    elif "star" in tl:
        return ("slide", variant)
    elif "touchhold" in tl:
        return ("touch_hold", variant)
    elif "touch" in tl:
        return ("touch", variant)
    elif "hold" in tl:
        return ("hold", variant)
    else:
        return (None, None)


def is_slide_type(note: ParsedNote) -> bool:
    tl = note.note_type.lower()
    return "star" in tl


def is_second_stage(note: ParsedNote) -> bool:
    return "move" in note.note_type.lower()


# ── OBB 计算 ──
def compute_obb_for_note(note: ParsedNote) -> dict | None:
    """
    根据音符类型计算 OBB。
    返回 {"x1".."y4", "cx", "cy", "w", "h", "r"} 或 None（应跳过）。
    """
    detect_type, variant = map_note_type(note)
    if detect_type is None:
        return None

    # 跳过 Init 状态（音符尚未出现）
    if note.status.lower() == "init":
        return None

    cx, cy = world_to_pixel(note.pos_x, note.pos_y)

    if detect_type == "tap":
        half = _tap_half(note)
    elif detect_type == "slide":
        half = _slide_half(note)
    elif detect_type == "touch":
        half = _touch_half(note)
    elif detect_type == "touch_hold":
        half = _touch_hold_half(note)
    elif detect_type == "hold":
        return _hold_obb(note, cx, cy)
    else:
        return None

    if half is None or half <= 0:
        return None

    w = half * 2.0
    h = half * 2.0
    return _make_obb(cx, cy, w, h)


def _tap_half(note: ParsedNote) -> float | None:
    if note.status.lower() == "scale":
        index = note.tap_scale_x
        if index < 0.5:
            return None
        coeff = TAP_HALF_EX if note.is_ex else TAP_HALF_NORMAL
        return BASE_1080 * coeff * index
    else:
        # 非 Scale 状态，固定尺寸
        coeff = TAP_HALF_EX if note.is_ex else TAP_HALF_NORMAL
        return BASE_1080 * coeff


def _slide_half(note: ParsedNote) -> float | None:
    if is_second_stage(note):
        return BASE_1080 * SLIDE_MOVE_COEFF * note.star_scale_x
    elif note.status.lower() == "scale":
        # 第一段 Scale
        index = note.star_scale_x
        if index < 0.5:
            return None
        return BASE_1080 * SLIDE_STAR_SCALE_COEFF * index
    else:
        # 第一段 非Scale（Move/End），固定尺寸
        return SLIDE_FIXED_HALF_NORMAL


def _touch_half(note: ParsedNote) -> float:
    return note.touch_decor + TOUCH_HALF_BASE_OFFSET


def _touch_hold_half(note: ParsedNote) -> float:
    return note.touch_decor + TOUCH_HOLD_HALF_BASE_OFFSET


def _hold_obb(note: ParsedNote, cx: float, cy: float) -> dict | None:
    """
    计算 Hold 音符的 OBB（轴对齐近似）。
    Hold 实际是沿径向旋转的矩形，这里简化为轴对齐。
    """
    if note.status.lower() == "scale":
        index = note.hold_scale_x
        if index < 0.5:
            return None
    else:
        index = 1.0

    half_w = HOLD_WIDTH_COEFF * index
    half_h = (note.hold_body_size - 20) * 0.5 * index
    if half_h <= 0:
        half_h = half_w  # fallback

    w = half_w * 2.0
    h = half_h * 2.0
    return _make_obb(cx, cy, w, h)


def _make_obb(cx: float, cy: float, w: float, h: float) -> dict:
    half_w = w / 2.0
    half_h = h / 2.0
    return {
        "x1": cx - half_w, "y1": cy - half_h,
        "x2": cx + half_w, "y2": cy - half_h,
        "x3": cx + half_w, "y3": cy + half_h,
        "x4": cx - half_w, "y4": cy + half_h,
        "cx": cx, "cy": cy,
        "w": w, "h": h,
        "r": 0.0,
    }


# ── 解析 ──
def parse_frame(lines: list[str], frame: int) -> list[ParsedNote]:
    """
    从一帧的 note 行列表解析出所有音符。
    """
    notes: list[ParsedNote] = []

    for line in lines:
        line = line.strip()
        if not line or line.upper() == "NA":
            continue

        parts = line.split(" | ")
        if len(parts) < 6:
            continue

        # --- parts[0]: Type-Index ---
        type_index = parts[0].strip()
        if "-Move" in type_index:
            idx = type_index.rfind("-")
            note_type = type_index[:idx]
            try:
                note_index = int(type_index[idx + 1:])
            except ValueError:
                continue
        else:
            idx = type_index.find("-")
            if idx == -1:
                continue
            note_type = type_index[:idx]
            try:
                note_index = int(type_index[idx + 1:])
            except ValueError:
                continue

        # --- parts[1]: Position ---
        pos_parts = parts[1].split(", ")
        if len(pos_parts) < 2:
            continue
        try:
            pos_x = float(pos_parts[0])
            pos_y = float(pos_parts[1])
        except ValueError:
            continue

        # --- parts[3]: Status ---
        status = parts[3].strip()

        # --- parts[5]: EX ---
        is_ex = parts[5].strip().lower() == "ex:y"

        # --- 解析额外字段 ---
        touch_decor = 0.0
        touch_alpha = 0.0
        hold_scale_x = 1.0
        hold_scale_y = 1.0
        hold_body_size = 0.0
        tap_scale_x = 1.0
        tap_scale_y = 1.0
        star_scale_x = 1.0
        star_scale_y = 1.0

        for i in range(6, len(parts)):
            p = parts[i].strip()
            p_lower = p.lower()

            if "touchdecorposition:" in p_lower:
                try:
                    touch_decor = float(p.split(":")[1].strip())
                except (ValueError, IndexError):
                    pass
                continue

            if p_lower.startswith("alpha:"):
                try:
                    touch_alpha = float(p.split(":")[1].strip())
                except (ValueError, IndexError):
                    pass
                continue

            if "holdscale:" in p_lower:
                m = re.search(r"([\d.eE+\-]+)\s*,?\s*([\d.eE+\-]*)", p_lower)
                if m:
                    try: hold_scale_x = float(m.group(1))
                    except ValueError: pass
                    if m.group(2):
                        try: hold_scale_y = float(m.group(2))
                        except ValueError: pass
                    else: hold_scale_y = hold_scale_x
                continue

            if "holdbodysize:" in p_lower:
                try:
                    hold_body_size = float(p.split(":")[1].strip())
                except (ValueError, IndexError):
                    pass
                continue

            if "tapscale:" in p_lower:
                m = re.search(r"([\d.eE+\-]+)\s*,?\s*([\d.eE+\-]*)", p_lower)
                if m:
                    try: tap_scale_x = float(m.group(1))
                    except ValueError: pass
                    if m.group(2):
                        try: tap_scale_y = float(m.group(2))
                        except ValueError: pass
                    else: tap_scale_y = tap_scale_x
                continue

            if "starscale:" in p_lower:
                m = re.search(r"([\d.eE+\-]+)\s*,?\s*([\d.eE+\-]*)", p_lower)
                if m:
                    try: star_scale_x = float(m.group(1))
                    except ValueError: pass
                    if m.group(2):
                        try: star_scale_y = float(m.group(2))
                        except ValueError: pass
                    else: star_scale_y = star_scale_x
                continue

        notes.append(ParsedNote(
            note_type=note_type,
            note_index=note_index,
            pos_x=pos_x,
            pos_y=pos_y,
            status=status,
            is_ex=is_ex,
            touch_decor=touch_decor,
            touch_alpha=touch_alpha,
            hold_scale_x=hold_scale_x,
            hold_scale_y=hold_scale_y,
            hold_body_size=hold_body_size,
            tap_scale_x=tap_scale_x,
            tap_scale_y=tap_scale_y,
            star_scale_x=star_scale_x,
            star_scale_y=star_scale_y,
        ))

    return notes


# ── 输出 ──
def write_detect_result(
    all_detections: list[tuple[int, ParsedNote, dict]],
    output_path: str,
):
    """
    按 _save_detect_results 格式写入 detect_result.txt。

    all_detections: [(frame, ParsedNote, obb_dict), ...]  已按 frame 排序
    """
    with open(output_path, "w", encoding="utf-8") as f:
        current_frame = -1
        for frame, note, obb in all_detections:
            detect_type, variant = map_note_type(note)
            if detect_type is None:
                continue

            if frame != current_frame:
                f.write(f"frame: {frame}\n")
                current_frame = frame

            data = [
                f"{frame}",
                detect_type,
                variant,
                "1.0000",  # conf 固定
                f"{obb['x1']:.4f}", f"{obb['y1']:.4f}",
                f"{obb['x2']:.4f}", f"{obb['y2']:.4f}",
                f"{obb['x3']:.4f}", f"{obb['y3']:.4f}",
                f"{obb['x4']:.4f}", f"{obb['y4']:.4f}",
                f"{obb['cx']:.4f}", f"{obb['cy']:.4f}",
                f"{obb['w']:.4f}", f"{obb['h']:.4f}",
                f"{obb['r']:.4f}",
            ]
            f.write(", ".join(data) + "\n")


def main(input_path: Path):
    if not input_path.is_file():
        print(f"错误: 文件不存在: {input_path}")
        sys.exit(1)

    output_path = input_path.parent / "detect_result.txt"
    for i, arg in enumerate(sys.argv):
        if arg == "--output" and i + 1 < len(sys.argv):
            output_path = Path(sys.argv[i + 1])
            break

    print(f"输入: {input_path}")
    print(f"输出: {output_path}")

    # ── 解析 ──
    frame = 0
    current_lines: list[str] = []
    all_detections: list[tuple[int, ParsedNote, dict]] = []

    with open(input_path, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()

            if not line:
                continue
            if (line.startswith("Note Dump") or
                line.startswith("Music Info") or
                line.startswith("Video File") or
                line.startswith("Format") or
                line.startswith("  ") or
                line.startswith("=")):
                continue

            if line.startswith("Time:"):
                if current_lines:
                    notes = parse_frame(current_lines, frame)
                    for note in notes:
                        obb = compute_obb_for_note(note)
                        if obb is not None:
                            all_detections.append((frame, note, obb))
                    frame += 1
                current_lines = []
                continue

            current_lines.append(line)

        # 最后一帧
        if current_lines:
            notes = parse_frame(current_lines, frame)
            for note in notes:
                obb = compute_obb_for_note(note)
                if obb is not None:
                    all_detections.append((frame, note, obb))
            frame += 1

    # ── 写入 ──
    write_detect_result(all_detections, str(output_path))

    # 统计
    type_counts: dict[str, int] = defaultdict(int)
    for _, note, _ in all_detections:
        dt, _ = map_note_type(note)
        if dt:
            type_counts[dt] += 1

    print(f"完成! 共 {frame} 帧, {len(all_detections)} 个检测条目")
    for t in sorted(type_counts.keys()):
        print(f"  {t}: {type_counts[t]}")
    print(f"输出: {output_path}")


if __name__ == "__main__":
    # if len(sys.argv) < 2:
    #     print(__doc__)
    #     sys.exit(1)
    # main(Path(sys.argv[1]))

    # 调试用
    pathh = r"C:\git\aaa-HachimiDX-Convert\archive\kalman-filter-tweak\11814_2026-05-13_01-02-56.txt"
    main(Path(pathh))
