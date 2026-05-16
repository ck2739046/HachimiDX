from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from ...schemas.op_result import OpResult, err, ok
from ..analyze.analyze_slide_movement import is_line_pass_a_zone_endpoint
from ..analyze.preprocess_slide import (
    _guess_target_a_zone_by_inertia,
    _is_close_to_A_zone_endpoint,
)
from ..analyze.shared_context import get_a_zone_endpoint, get_touch_areas
from ..analyze.tool import calculate_all_position, calculate_oct_position, catmull_rom_spline
from .note_definition import NoteType
from .track import _load_track_results, _save_track_results


# 允许回退 20%
TOUCH_REVERSE_GROWTH_RATIO = 0.2
# touch/touch-hold 距离差不多，此处就同一个了
TOUCH_TRAVEL_DIST_STD_1080 = 34.0


@dataclass
class _PostTrackContext:
    std_video_size: int
    std_video_cx: int
    std_video_cy: int
    touch_areas: dict
    a_zone_endpoint: dict
    note_travel_dist: float


def main(std_video_path: Path) -> OpResult[None]:
    try:
        tracks = _load_track_results(std_video_path.parent)
        context = _build_context(std_video_path)
        next_track_id = _get_next_track_id(tracks)

        tracks, next_track_id = _split_touch_notes(tracks, context, next_track_id)
        tracks, next_track_id = _split_slide_notes(tracks, context, next_track_id)

        _save_track_results(tracks, std_video_path.parent, call_fn="post_track")
        return ok()

    except Exception as e:
        return err("Unexpected error in auto_convert > detect > post_track", e)












def _build_context(std_video_path: Path) -> _PostTrackContext:
    """参考 analyze 模块的 shared_context 构建"""

    cap = cv2.VideoCapture(str(std_video_path))
    std_video_size = round(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    cap.release()

    std_video_cx = std_video_size // 2
    std_video_cy = std_video_cx

    touch_areas = get_touch_areas(std_video_size, std_video_cx, std_video_cy)
    a_zone_endpoint = get_a_zone_endpoint(std_video_size, std_video_cx, std_video_cy)

    judgeline_start = std_video_size * 120 / 1080
    judgeline_end = std_video_size * 480 / 1080
    note_travel_dist = judgeline_end - judgeline_start

    return _PostTrackContext(
        std_video_size=std_video_size,
        std_video_cx=std_video_cx,
        std_video_cy=std_video_cy,
        touch_areas=touch_areas,
        a_zone_endpoint=a_zone_endpoint,
        note_travel_dist=note_travel_dist,
    )


def _get_next_track_id(tracks: dict) -> int:
    max_track_id = -1
    for track_id, _note_type in tracks.keys():
        max_track_id = max(max_track_id, int(track_id))
    return max_track_id + 1











def _split_touch_notes(tracks: dict, context: _PostTrackContext, next_track_id: int):
    new_tracks = defaultdict(list)

    touch_travel_dist = TOUCH_TRAVEL_DIST_STD_1080 * context.std_video_size / 1080
    reverse_growth_threshold = TOUCH_REVERSE_GROWTH_RATIO * touch_travel_dist

    for key, value in tracks.items():
        track_id, note_type = key
        note_geometry_list = sorted(value, key=lambda x: x.frame)

        if note_type not in (NoteType.TOUCH, NoteType.TOUCH_HOLD):
            new_tracks[key].extend(note_geometry_list)
            continue

        if len(note_geometry_list) <= 1:
            new_tracks[key].extend(note_geometry_list)
            continue

        segments = _split_single_touch(
            note_geometry_list,
            context.touch_areas,
            reverse_growth_threshold,
        )

        if len(segments) <= 1:
            new_tracks[key].extend(note_geometry_list)
            continue

        assigned_track_ids = []
        for segment_idx, segment in enumerate(segments):
            if not segment:
                continue

            if segment_idx == 0:
                new_key = key
            else:
                new_key = (next_track_id, note_type)
                next_track_id += 1

            assigned_track_ids.append(new_key[0])
            new_tracks[new_key].extend(segment)

        print(f"post_track: split {note_type.value} track_id {track_id} into {assigned_track_ids}")

    return new_tracks, next_track_id





def _split_single_touch(note_geometry_list, touch_areas: dict, reverse_growth_threshold: float):
    """
    分割条件1 位置不同
    分割条件2 dist not decreasing
    """

    segments = []
    start_idx = 0

    first_note = note_geometry_list[0]
    prev_position = calculate_all_position(touch_areas, first_note.cx, first_note.cy)
    prev_size = (first_note.w + first_note.h) / 2.0

    for idx in range(1, len(note_geometry_list)):
        note = note_geometry_list[idx]

        curr_position = calculate_all_position(touch_areas, note.cx, note.cy)
        curr_size = (note.w + note.h) / 2.0
        dist_diff = (curr_size - prev_size) / 2.0

        should_split = False
        if curr_position != prev_position:
            should_split = True
        elif dist_diff > reverse_growth_threshold:
            should_split = True

        if should_split:
            if idx > start_idx:
                segments.append(note_geometry_list[start_idx:idx])
            start_idx = idx

        prev_position = curr_position
        prev_size = curr_size

    if start_idx < len(note_geometry_list):
        segments.append(note_geometry_list[start_idx:])

    return [x for x in segments if len(x) > 0]













def _split_slide_notes(tracks: dict, context: _PostTrackContext, next_track_id: int):
    new_tracks = defaultdict(list)

    for key, value in tracks.items():
        track_id, note_type = key
        note_geometry_list = sorted(value, key=lambda x: x.frame)

        if note_type != NoteType.SLIDE:
            new_tracks[key].extend(note_geometry_list)
            continue

        if len(note_geometry_list) < 5:
            new_tracks[key].extend(note_geometry_list)
            continue

        head_segment, tail_segment, is_split = _classify_segment(context, note_geometry_list, track_id)

        if head_segment is None and tail_segment is None:
            new_tracks[key].extend(note_geometry_list)
            continue

        if not is_split:
            segment = head_segment if head_segment is not None else tail_segment
            if segment is None:
                new_tracks[key].extend(note_geometry_list)
            else:
                new_tracks[key].extend(segment)
            continue

        if head_segment is not None and tail_segment is not None:
            new_tracks[key].extend(head_segment)
            new_key = (next_track_id, note_type)
            next_track_id += 1
            new_tracks[new_key].extend(tail_segment)
            print(f"post_track: split slide track_id {track_id} into {track_id} and {new_key[0]}")
            continue

        if head_segment is not None:
            new_tracks[key].extend(head_segment)
        elif tail_segment is not None:
            new_tracks[key].extend(tail_segment)
        else:
            new_tracks[key].extend(note_geometry_list)

    return new_tracks, next_track_id




# 从 analyze/preprocess_slide.py 迁移而来
# 递归分类音符
def _classify_segment(context: _PostTrackContext, note_geometry_list, track_id, is_segmented=False):
    if len(note_geometry_list) < 5:
        return None, None, False

    oct_positions = [
        calculate_oct_position(
            context.std_video_cx,
            context.std_video_cy,
            note.cx,
            note.cy,
        )
        for note in note_geometry_list
    ]
    # 如果所有 pos 一致, 可能是星星头, return
    # 因为星星尾是从一个A区移动到另一个A区的, 所以 pos 一定不一致
    if len(set(oct_positions)) == 1:
        return note_geometry_list, None, False




    all_positions = [
        calculate_all_position(
            context.touch_areas,
            note.cx,
            note.cy,
        )
        for note in note_geometry_list
    ]
    # 如果开头在A区, 可能是星星尾，return
    if all_positions[0].startswith("A"):
        return None, note_geometry_list, False

    # 不在A区, 尝试惯性推断出发点
    # 如果够近, 也可能是星星尾，return
    start_a_zone = _guess_target_a_zone_by_inertia(context.a_zone_endpoint, context.std_video_size, note_geometry_list[::-1])
    start_cx, start_cy = note_geometry_list[0].cx, note_geometry_list[0].cy
    if _is_close_to_A_zone_endpoint(context.a_zone_endpoint, context.std_video_size, start_cx, start_cy, start_a_zone):
        return None, note_geometry_list, False





    # 是否已分段
    # yes: 已分段, 还不满足条件, 说明数据异常, 丢弃, return
    # no:  还未分段, 继续尝试分段
    if is_segmented is True:
        return None, None, False

    # 是否到达A区
    # yes: 按第一个A区分割, 第一段视为星星头, 第二段视为星星尾, 递归
    # no:  可能是异常数据, 丢弃, return
    # 使用 Catmull-Rom 样条对轨迹中心点插值，再逐子段判定 A 区穿越，
    # 解决低帧率/稀疏追踪点下逐点线段漏判的问题
    num_samples = 4
    center_points = [(note.cx, note.cy) for note in note_geometry_list]
    interp = catmull_rom_spline(center_points, num_samples=num_samples)
    interp_pts = interp.reshape(-1, 2)

    for j in range(len(interp_pts) - 1):
        x1, y1 = float(interp_pts[j][0]), float(interp_pts[j][1])
        x2, y2 = float(interp_pts[j + 1][0]), float(interp_pts[j + 1][1])
        is_pass, _a_zone = is_line_pass_a_zone_endpoint(x1, y1, x2, y2, context)
        if not is_pass:
            continue
        # 映射回原始索引：每 num_samples 个插值子段对应一个原始段
        # j 是插值子段起点索引，原始段索引 = j // num_samples
        # 分割点在原始段的 curr 处，即 original_seg_idx + 1
        original_seg_idx = j // num_samples
        split_idx = min(original_seg_idx + 1, len(note_geometry_list) - 1)
        head_segment = note_geometry_list[:split_idx]
        tail_segment = note_geometry_list[split_idx:]
        # 递归处理头部和尾部
        head_result, _, _ = _classify_segment(context, head_segment, track_id, is_segmented=True)
        _, tail_result, _ = _classify_segment(context, tail_segment, track_id, is_segmented=True)
        return head_result, tail_result, True

    return None, None, False
