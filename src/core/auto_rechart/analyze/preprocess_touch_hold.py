from collections import defaultdict
from pathlib import Path
import numpy as np

from ...schemas.op_result import OpResult, err, ok
from .shared_context import *
from .preprocess_touch_hold_inference import run_touch_hold_inference, calc_touch_hold_crop_size


def preprocess_touch_hold_data(shared_context: SharedContext,
                               inference_device,
                               batch_touch_hold: int,
                               touch_hold_model_path: Path,
                               half: bool = False) -> OpResult[dict]:
    '''
    返回格式:
    dict{
        key: (track_id, note_type, note_variant, note_position),
        value: note path
        [
            {
                'frame': frame_num,
                'dist': dist_to_center,
                'percent': percent_of_hold
            },
            ...
        ]
    }
    '''

    touch_hold_data = {}

    # 1: YOLO 推理（生产者-消费者流水线，轻量解析）
    inference_r = run_touch_hold_inference(
        shared_context, inference_device, batch_touch_hold, touch_hold_model_path,
        half=half,
    )
    if not inference_r.is_ok:
        return err("[preprocess_touch_hold] inference failed", inner=inference_r)
    if inference_r.value is None:
        return err("[preprocess_touch_hold] inference returned no value")
    light_results, track_meta = inference_r.value
    if not light_results:
        print("preprocess_touch_hold_data: no touch hold data")
        return ok({})

    # 2: 解析 dist/percent
    observations_by_track = _resolve_dist_percent(light_results, shared_context)

    # 3: 常规预处理校验
    for track_id, meta in track_meta.items():
        valid_track_path = observations_by_track.get(track_id, [])

        # 检查轨迹存在
        if not valid_track_path:
            print(f"preprocess_touch_hold_data: no valid_track_path for track_id {track_id}")
            continue
        
        # 检验长度
        if len(valid_track_path) < 4:
            print(f"preprocess_touch_hold_data: path too short for track_id {track_id}, length: {len(valid_track_path)}")
            continue

        # 检验方位一致
        positions = [x[1] for x in valid_track_path]
        if len(set(positions)) != 1:
            print(f"preprocess_touch_hold_data: positions not consistent for track_id {track_id}")
            continue
        
        # 按frame排序
        valid_track_path.sort(key=lambda x: x[0])

        # 检查通过，添加到touch_hold_data
        key = (track_id, meta["note_type"], meta["note_variant"], positions[0])
        path = []
        for frame_num, position, dist, percent_of_hold in valid_track_path:
            path.append({
                'frame': frame_num,
                'dist': dist,
                'percent': percent_of_hold
            })
        touch_hold_data[key] = path

    if not touch_hold_data:
        print("preprocess_touch_hold_data: no touch hold data")
        touch_hold_data = {}

    return ok(touch_hold_data)












# dist/percent 解析
def _resolve_dist_percent(light_results, shared_context: SharedContext):
    """返回: observations_by_track — dict[track_id, list[(frame, position, dist, percent)]]"""

    dist_end_tolerance = shared_context.touch_hold_travel_dist * 0.25
    dist_start_tolerance = shared_context.touch_hold_travel_dist * 0.1
    valid_dist_end = 0 + dist_end_tolerance
    valid_dist_start = shared_context.touch_hold_travel_dist - dist_start_tolerance
    percent_end_tolerance = 0.03
    percent_start_tolerance = 0.03
    valid_percent_end = 1 - percent_end_tolerance
    valid_percent_start = percent_start_tolerance

    crop_size = calc_touch_hold_crop_size(shared_context.std_video_size, shared_context.is_big_touch)
    observations_by_track = defaultdict(list)

    for light in light_results:
        dist = -1
        percent_of_hold = -1

        # dist: 从 touch-hold size 反推
        if light.touch_w is not None and light.touch_h is not None:
            dist = _convert_touch_box_to_dist_to_center(
                light.touch_w, light.touch_h, shared_context.is_big_touch
            )
            if dist > valid_dist_start or dist < valid_dist_end:
                dist = -1

        # percent: 从 progress_points 反推
        if light.progress_points:
            valid_percents = []
            for px, py in light.progress_points:
                filtered_percent = _progress_point_to_percent_with_dist_filter(
                    px, py, crop_size, crop_size
                )
                if filtered_percent == -1:
                    continue
                if filtered_percent < valid_percent_start or filtered_percent > valid_percent_end:
                    continue
                valid_percents.append(filtered_percent)

            if valid_percents:
                percent_of_hold = min(valid_percents) # 如果有多个合法结果，取最小的，一般不会出现

        # 两者都无效则丢弃
        if dist == -1 and percent_of_hold == -1:
            continue

        observations_by_track[light.track_id].append(
            (light.frame, light.position, dist, percent_of_hold)
        )

    return observations_by_track













def _convert_touch_box_to_dist_to_center(touch_w: float, touch_h: float, is_big_touch: bool) -> float:
    # label_notes.py 实现:
    # size = dist_to_center + 68
    # touch_box_side = 2 * size
    # 反推 dist_to_center = touch_box_side / 2 - 68
    # 以上是正常情况, 如果 is_big_touch, 常量 68 要变 1.3x
    touch_size = (float(touch_w) + float(touch_h)) / 2.0
    scale = 1.3 if is_big_touch else 1.0
    dist_to_center = touch_size / 2.0 - 68.0 * scale

    if np.isfinite(dist_to_center):
        return float(dist_to_center)
    return -1





def _angle_to_progress(px: float, py: float, cx: float, cy: float) -> float:
    dx = float(px) - float(cx)
    dy = float(py) - float(cy)
    if abs(dx) < 1e-6 and abs(dy) < 1e-6:
        return -1

    # 12点方向为0，顺时针增长到1
    angle = np.arctan2(dy, dx)
    progress = ((angle + np.pi / 2.0) % (2.0 * np.pi)) / (2.0 * np.pi)

    if np.isfinite(progress):
        return float(progress)
    return -1




def _progress_point_to_percent_with_dist_filter(px: float, py: float, crop_w: int, crop_h: int) -> float:
    """
    先转为角度，再计算该角度的理论 dist_to_center
    与实际结果比较，如果小于误差才视为合法
    tolerance: crop_size ±5%
    """

    cx = float(crop_w) / 2.0
    cy = float(crop_h) / 2.0

    dx = float(px) - cx
    dy = float(py) - cy
    actual_dist_to_center = float(np.hypot(dx, dy))
    if not np.isfinite(actual_dist_to_center) or actual_dist_to_center < 1e-6:
        return -1

    angle = np.arctan2(dy, dx)
    crop_size = min(float(crop_w), float(crop_h))
    theoretical_dist_to_center = _calc_touch_hold_progress_theoretical_dist(angle, crop_size)
    if theoretical_dist_to_center == -1:
        return -1

    tolerance = crop_size * 0.05
    if abs(actual_dist_to_center - theoretical_dist_to_center) > tolerance:
        return -1

    return _angle_to_progress(px, py, cx, cy)




def _calc_touch_hold_progress_theoretical_dist(angle: float, crop_size: float) -> float:
    # 与 label_notes.py 的 parse_touch_hold 保持一致
    base_radius = float(crop_size) * 0.4
    shape_p = 1.3
    dir_x = np.cos(angle)
    dir_y = np.sin(angle)
    denom = (abs(dir_x) ** shape_p + abs(dir_y) ** shape_p) ** (1.0 / shape_p)
    if denom <= 1e-6:
        return -1

    dist_to_center = base_radius / denom
    if np.isfinite(dist_to_center):
        return float(dist_to_center)
    return -1
