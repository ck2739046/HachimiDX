"""
visualize_boxes.py

在纯黑 1080×1080 画布上逐帧绘制 OBB 框并导出视频。

用法:
    python visualize_boxes.py --track track_result.txt --detect detect_result.txt
        [--output-dir ./] [--fps 60]

生成两个视频:
    track_visualization.mp4  — 读取 track_result.txt，框带 track_id 标签
    detect_visualization.mp4 — 读取 detect_result.txt
    左上角均标注帧号。
"""

import sys
import os
import re
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np

# ── 画布 ──
CANVAS_W = 1080
CANVAS_H = 1080

# ── 音符颜色 (BGR)，与 label_notes.py 一致 ──
NOTE_COLORS = {
    "tap":        (0, 255, 0),    # 绿色
    "slide":      (0, 255, 255),  # 黄色
    "touch":      (255, 0, 255),  # 紫色
    "touch_hold": (255, 255, 0),  # 青色
    "hold":       (255, 0, 0),    # 蓝色
}
FALLBACK_COLOR = (255, 255, 255)  # 白色


# ── track_result.txt 解析 ──
def load_track_data(path: str) -> dict[int, list[list[str]]]:
    """
    返回: {track_id: [raw_parts_list, ...]}  每个元素是按逗号分割的字段列表
    """
    tracks: dict[int, list[list[str]]] = defaultdict(list)
    current_tid = -1

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                current_tid = -1
                continue
            if line.startswith("track_id:"):
                m = re.search(r"track_id:\s*(\d+)", line)
                if m:
                    current_tid = int(m.group(1))
                continue
            if current_tid >= 0:
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 17:
                    tracks[current_tid].append(parts)
    return dict(tracks)


# ── detect_result.txt 解析 ──
def load_detect_data(path: str) -> list[list[str]]:
    """
    返回: [raw_parts_list, ...]  每个元素是按逗号分割的字段列表（含 frame 列）
    """
    detections: list[list[str]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("frame:"):
                continue
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 17:
                detections.append(parts)
    return detections


# ── 解析 OBB ──
def parse_obb_parts(parts: list[str]) -> dict | None:
    """从 17 字段列表中提取 OBB 信息"""
    try:
        frame = int(parts[0])
        note_type = parts[1]
        x1 = float(parts[4]);  y1 = float(parts[5])
        x2 = float(parts[6]);  y2 = float(parts[7])
        x3 = float(parts[8]);  y3 = float(parts[9])
        x4 = float(parts[10]); y4 = float(parts[11])
        return {
            "frame": frame,
            "note_type": note_type,
            "pts": np.array([
                [x1, y1], [x2, y2], [x3, y3], [x4, y4]
            ], dtype=np.int32),
        }
    except (ValueError, IndexError):
        return None


# ── 绘制 ──
def draw_boxes(
    canvas: np.ndarray,
    obb_list: list[dict],
    labels: list[str] | None = None,
):
    """
    在 canvas 上绘制 OBB 框。
    labels: 可选标签列表，与 obb_list 一一对应，绘制在框左上角。
    """
    for i, obb in enumerate(obb_list):
        color = NOTE_COLORS.get(obb["note_type"], FALLBACK_COLOR)
        cv2.polylines(canvas, [obb["pts"]], isClosed=True, color=color, thickness=2)

        if labels and i < len(labels):
            x, y = obb["pts"][0]
            cv2.putText(
                canvas, labels[i],
                (int(x), int(y) - 4),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1, cv2.LINE_AA,
            )


def write_video(
    writer,
    total_frames: int,
    frame_data_map: dict[int, list[dict]],
    label_map: dict[int, list[str]] | None = None,
):
    """逐帧写入视频"""
    for fno in range(total_frames + 1):
        canvas = np.zeros((CANVAS_H, CANVAS_W, 3), dtype=np.uint8)

        # 帧号
        cv2.putText(
            canvas, f"Frame: {fno}",
            (10, 24),
            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1, cv2.LINE_AA,
        )

        obb_list = frame_data_map.get(fno, [])
        labels = label_map.get(fno, []) if label_map else None
        draw_boxes(canvas, obb_list, labels)

        writer.write(canvas)


# ── 主流程 ──
def _resolve_path(value: str | None, default: str = ".") -> Path:
    """若非绝对路径，则以脚本所在目录为基准解析。"""
    if value is None:
        return Path(default)
    p = Path(value)
    if p.is_absolute():
        return p
    script_dir = Path(__file__).resolve().parent
    return (script_dir / p).resolve()


def main():
    import argparse

    ap = argparse.ArgumentParser(description="OBB 可视化")
    ap.add_argument("--track", type=str, default=None, help="track_result.txt 路径")
    ap.add_argument("--detect", type=str, default=None, help="detect_result.txt 路径")
    ap.add_argument("--output-dir", type=str, default=".", help="输出目录")
    ap.add_argument("--fps", type=int, default=60, help="视频帧率")
    args = ap.parse_args()

    if not args.track and not args.detect:
        print("至少需要 --track 或 --detect")
        sys.exit(1)

    out_dir = _resolve_path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    fps = args.fps
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")

    # ── Track 视频 ──
    if args.track:
        track_path = str(_resolve_path(args.track))
        print(f"[track] 读取: {track_path}")
        tracks = load_track_data(track_path)

        # 构建 frame → [(track_id, obb_dict)]
        frame_data_map: dict[int, list[dict]] = defaultdict(list)
        frame_label_map: dict[int, list[str]] = defaultdict(list)
        max_frame = 0

        for tid, rows in tracks.items():
            for parts in rows:
                obb = parse_obb_parts(parts)
                if obb is None:
                    continue
                fno = obb["frame"]
                if fno > max_frame:
                    max_frame = fno
                frame_data_map[fno].append(obb)
                frame_label_map[fno].append(f"ID:{tid}")

        out_path = str(out_dir / "track_visualization.mp4")
        writer = cv2.VideoWriter(out_path, fourcc, fps, (CANVAS_W, CANVAS_H))
        print(f"[track] 总帧数: {max_frame + 1}, 输出: {out_path}")
        write_video(writer, max_frame, dict(frame_data_map), dict(frame_label_map))
        writer.release()
        print("[track] 完成")

    # ── Detect 视频 ──
    if args.detect:
        detect_path = str(_resolve_path(args.detect))
        print(f"[detect] 读取: {detect_path}")
        detections = load_detect_data(detect_path)

        frame_data_map: dict[int, list[dict]] = defaultdict(list)
        max_frame = 0

        for parts in detections:
            obb = parse_obb_parts(parts)
            if obb is None:
                continue
            fno = obb["frame"]
            if fno > max_frame:
                max_frame = fno
            frame_data_map[fno].append(obb)

        out_path = str(out_dir / "detect_visualization.mp4")
        writer = cv2.VideoWriter(out_path, fourcc, fps, (CANVAS_W, CANVAS_H))
        print(f"[detect] 总帧数: {max_frame + 1}, 输出: {out_path}")
        write_video(writer, max_frame, dict(frame_data_map))
        writer.release()
        print("[detect] 完成")


if __name__ == "__main__":
    main()
