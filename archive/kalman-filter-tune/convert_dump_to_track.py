"""
convert_dump_to_track.py

将 Dump_Notes 生成的 txt（Slide-Only）转换为 track_result.txt 格式。

用法:
    python convert_dump_to_track.py <dump_output.txt> [--output track_result.txt]
"""

import re
import sys
from collections import defaultdict
from pathlib import Path

# ── 常量（与 label_notes.py 的 Slide 尺寸公式一致） ──
BASE_1080 = 1080.0

# 第一段 StarNote (Scale 状态) 的尺寸系数 (normal, 非EX)
STAR_SCALE_COEFF_NORMAL = 0.05

# 第一段 StarNote (非Scale状态) 的固定半边长 (normal)
STAR_FIXED_HALF_NORMAL = BASE_1080 * 0.049

# 第二段 StarNote-Move 的尺寸系数 (star_skin=0 圆头)
STAR_MOVE_COEFF = 0.055 * 0.88  # 0.055 * 0.88 = 0.0484

# ── 输出格式常量 ──
NOTE_TYPE_SLIDE = "slide"
NOTE_VARIANT_NORMAL = "normal"
CONF_DEFAULT = 1.0


class ParsedNote:
    """解析后的单帧 note 数据（仅 Slide 相关字段）"""
    __slots__ = (
        "note_type",     # str: "StarNote" / "BreakStarNote" / "StarNote-Move" / "BreakStarNote-Move"
        "note_index",    # int
        "pos_x",         # float: Position.x
        "pos_y",         # float: Position.y
        "status",        # str: "Init" / "Scale" / "Move" / "End"
        "unique_id",     # int: UniqueNoteId
        "star_scale_x",  # float: StarScale.x (默认1.0)
        "star_scale_y",  # float: StarScale.y (默认1.0)
    )

    def __init__(
        self,
        note_type: str,
        note_index: int,
        pos_x: float,
        pos_y: float,
        status: str,
        unique_id: int,
        star_scale_x: float = 1.0,
        star_scale_y: float = 1.0,
    ):
        self.note_type = note_type
        self.note_index = note_index
        self.pos_x = pos_x
        self.pos_y = pos_y
        self.status = status
        self.unique_id = unique_id
        self.star_scale_x = star_scale_x
        self.star_scale_y = star_scale_y


def parse_frame(lines: list[str], frame: int) -> list[ParsedNote]:
    """
    从一帧的 note 行列表解析出 Slide 相关音符。

    返回 ParsedNote 列表（仅 Slide 类型）。
    """
    notes: list[ParsedNote] = []

    for line in lines:
        line = line.strip()
        if not line or line.upper() == "NA":
            continue

        # 按 ' | ' 分割
        parts = line.split(" | ")
        if len(parts) < 7:
            continue

        # ── parts[0]: Type-Index ──
        type_index = parts[0].strip()
        # 处理 "StarNote-Move-123" 或 "StarNote-0"
        if "-Move" in type_index:
            # "StarNote-Move-123" → note_type="StarNote-Move", index=123
            idx = type_index.rfind("-")
            note_type = type_index[:idx]
            try:
                note_index = int(type_index[idx + 1:])
            except ValueError:
                continue
        else:
            # "StarNote-0"
            idx = type_index.find("-")
            if idx == -1:
                continue
            note_type = type_index[:idx]
            try:
                note_index = int(type_index[idx + 1:])
            except ValueError:
                continue

        # 仅处理 Slide 类型
        type_lower = note_type.lower()
        if "star" not in type_lower:
            continue

        # ── parts[1]: Position ──
        pos_parts = parts[1].split(", ")
        if len(pos_parts) < 2:
            continue
        try:
            pos_x = float(pos_parts[0])
            pos_y = float(pos_parts[1])
        except ValueError:
            continue

        # ── parts[3]: Status ──
        status = parts[3].strip()

        # ── 从 parts[5..] 中查找 EX: 后面的 UniqueId 和 StarScale ──
        unique_id = -1
        star_scale_x = 1.0
        star_scale_y = 1.0

        for i in range(5, len(parts)):
            p = parts[i].strip()
            p_lower = p.lower()

            if p_lower.startswith("uniqueid:"):
                try:
                    unique_id = int(p.split(":")[1].strip())
                except (ValueError, IndexError):
                    pass
                continue

            if "starscale:" in p_lower:
                match = re.search(
                    r"starscale:\s*([\d.eE+\-]+)\s*,?\s*([\d.eE+\-]*)",
                    p_lower
                )
                if match:
                    try:
                        star_scale_x = float(match.group(1))
                    except ValueError:
                        pass
                    if match.group(2):
                        try:
                            star_scale_y = float(match.group(2))
                        except ValueError:
                            pass
                    else:
                        star_scale_y = star_scale_x
                continue

        if unique_id == -1:
            # 没有 UniqueId 的行忽略（非 Slide 或旧格式）
            continue

        notes.append(ParsedNote(
            note_type=note_type,
            note_index=note_index,
            pos_x=pos_x,
            pos_y=pos_y,
            status=status,
            unique_id=unique_id,
            star_scale_x=star_scale_x,
            star_scale_y=star_scale_y,
        ))

    return notes


def compute_obb(note: ParsedNote):
    """
    将 ParsedNote 转换为 OBB (cx, cy, w, h, x1..y4, r=0)。

    坐标变换与 label_notes.py 一致：
        cx = 1080 + posX
        cy = 120 - posY

    尺寸公式与 label_notes.py 一致：
        - 第二段 (type 含 "Move"): half = 1080 * 0.055 * 0.88 * starScale.x
        - 第一段 Status=Scale:   half = 1080 * 0.05 * starScale.x
        - 第一段 其他:           half = 1080 * 0.049 (固定)
    """
    cx = BASE_1080 + note.pos_x
    cy = 120.0 - note.pos_y

    is_second_stage = "move" in note.note_type.lower()

    if is_second_stage:
        half = BASE_1080 * STAR_MOVE_COEFF * note.star_scale_x
    elif note.status.lower() == "scale":
        half = BASE_1080 * STAR_SCALE_COEFF_NORMAL * note.star_scale_x
    else:
        half = STAR_FIXED_HALF_NORMAL

    w = half * 2.0
    h = half * 2.0

    x1 = cx - half
    y1 = cy - half
    x2 = cx + half
    y2 = cy - half
    x3 = cx + half
    y3 = cy + half
    x4 = cx - half
    y4 = cy + half

    return {
        "cx": cx, "cy": cy,
        "w": w, "h": h,
        "x1": x1, "y1": y1,
        "x2": x2, "y2": y2,
        "x3": x3, "y3": y3,
        "x4": x4, "y4": y4,
        "r": 0.0,
    }


def write_track_result(
    tracks: dict[int, list[tuple[int, ParsedNote, dict]]],
    output_path: str,
):
    """
    按 _save_track_results 格式写入 track_result.txt。

    tracks: {unique_id: [(frame, ParsedNote, obb_dict), ...]}
    """
    with open(output_path, "w", encoding="utf-8") as f:
        for unique_id in sorted(tracks.keys()):
            entries = tracks[unique_id]
            if not entries:
                continue

            # 按 frame 排序
            entries.sort(key=lambda x: x[0])

            f.write(f"track_id: {unique_id}, note_type: {NOTE_TYPE_SLIDE}\n")
            for frame, note, obb in entries:
                data = [
                    f"{frame}",
                    NOTE_TYPE_SLIDE,
                    NOTE_VARIANT_NORMAL,
                    f"{CONF_DEFAULT:.4f}",
                    f"{obb['x1']:.4f}", f"{obb['y1']:.4f}",
                    f"{obb['x2']:.4f}", f"{obb['y2']:.4f}",
                    f"{obb['x3']:.4f}", f"{obb['y3']:.4f}",
                    f"{obb['x4']:.4f}", f"{obb['y4']:.4f}",
                    f"{obb['cx']:.4f}", f"{obb['cy']:.4f}",
                    f"{obb['w']:.4f}", f"{obb['h']:.4f}",
                    f"{obb['r']:.4f}",
                ]
                f.write(", ".join(data) + "\n")
            f.write("\n")



def main(input_path):

    if not input_path.is_file():
        print(f"错误: 文件不存在: {input_path}")
        sys.exit(1)

    # 解析 --output 参数
    output_path = input_path.parent / "track_result.txt"
    for i, arg in enumerate(sys.argv):
        if arg == "--output" and i + 1 < len(sys.argv):
            output_path = Path(sys.argv[i + 1])
            break

    print(f"输入: {input_path}")
    print(f"输出: {output_path}")

    # ── 逐行解析 ──
    frame = 0
    current_time_str: str | None = None
    current_lines: list[str] = []

    # tracks: {unique_id: [(frame, ParsedNote, obb_dict), ...]}
    tracks: dict[int, list[tuple[int, ParsedNote, dict]]] = defaultdict(list)

    total_frames = 0
    total_notes = 0

    with open(input_path, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()

            # 跳过头部注释行
            if not line:
                continue
            if (line.startswith("Note Dump") or
                line.startswith("Music Info") or
                line.startswith("Video File") or
                line.startswith("Format") or
                line.startswith("  ") or    # 说明行 (缩进)
                line.startswith("=")):
                continue

            # 帧分隔符: "Time:{ms}|Count:{n}"
            if line.startswith("Time:"):
                # 先处理上一帧
                if current_lines:
                    notes = parse_frame(current_lines, frame)
                    for note in notes:
                        obb = compute_obb(note)
                        tracks[note.unique_id].append((frame, note, obb))
                        total_notes += 1
                    frame += 1
                    total_frames += 1

                current_lines = []
                continue

            # 累积 note 行
            current_lines.append(line)

        # 处理最后一帧
        if current_lines:
            notes = parse_frame(current_lines, frame)
            for note in notes:
                obb = compute_obb(note)
                tracks[note.unique_id].append((frame, note, obb))
                total_notes += 1
            total_frames += 1

    # ── 写入 ──
    write_track_result(tracks, str(output_path))

    print(f"完成! 共 {total_frames} 帧, {total_notes} 个 note 条目, {len(tracks)} 条 track")
    print(f"输出: {output_path}")




if __name__ == "__main__":

    # if len(sys.argv) < 2:
    #     print(__doc__)
    #     sys.exit(1)
    # pathh = sys.argv[1]

    pathh = r"C:\git\aaa-HachimiDX-Convert\archive\kalman-filter-tweak\11814_2026-05-13_01-02-56.txt"
    
    main(Path(pathh))
