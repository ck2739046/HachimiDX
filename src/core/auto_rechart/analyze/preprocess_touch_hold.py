from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np
from ultralytics import YOLO

from ..detect.note_definition import *
from .tool import *
from .shared_context import *


TOUCH_HOLD_CLASS_TOUCH = 0
TOUCH_HOLD_CLASS_PROGRESS = 1




def preprocess_touch_hold_data(shared_context: SharedContext,
                               inference_device,
                               batch_touch_hold: int,
                               touch_hold_model_path: Path):
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

    frame_plan, track_meta = _build_touch_hold_sampling_plan(shared_context)
    if not frame_plan:
        print("preprocess_touch_hold_data: no touch hold data")
        return {}

    dist_end_tolerance = shared_context.touch_hold_travel_dist * 0.25
    dist_start_tolerance = shared_context.touch_hold_travel_dist * 0.1
    valid_dist_end = 0 + dist_end_tolerance
    valid_dist_start = shared_context.touch_hold_travel_dist - dist_start_tolerance
    percent_end_tolerance = 0.03
    percent_start_tolerance = 0.03
    valid_percent_end = 1 - percent_end_tolerance
    valid_percent_start = percent_start_tolerance

    crop_size = _calc_touch_hold_crop_size(shared_context.std_video_size, shared_context.is_big_touch)
    total_samples = sum(len(v) for v in frame_plan.values())

    model = YOLO(str(touch_hold_model_path), task="detect")
    cap = cv2.VideoCapture(str(shared_context.std_video_path))
    if not cap.isOpened():
        print(f"preprocess_touch_hold_data: failed to open video: {shared_context.std_video_path}")
        return {}

    last_printed_samples = 0
    processed_samples = 0
    sample_buffer = []
    observations_by_track = defaultdict(list)

    try:
        total_frames = len(shared_context.frame_timestamps_msec)
        for frame_num in range(total_frames):
            ret, frame = cap.read()
            if not ret:
                break

            this_frame_plan = frame_plan.get(frame_num)
            if not this_frame_plan:
                continue

            for sample in this_frame_plan:
                cropped = _crop_with_black_padding(
                    frame,
                    sample["cx"],
                    sample["cy"],
                    crop_size,
                    crop_size,
                )
                sample_buffer.append({
                    "track_id": sample["track_id"],
                    "frame": frame_num,
                    "position": sample["position"],
                    "cropped_image": cropped,
                })

            while len(sample_buffer) >= batch_touch_hold:
                consumed_batch = sample_buffer[:batch_touch_hold]
                sample_buffer = sample_buffer[batch_touch_hold:]
                _consume_touch_hold_batch(
                    consumed_batch,
                    model,
                    inference_device,
                    shared_context.is_big_touch,
                    observations_by_track,
                    valid_dist_start,
                    valid_dist_end,
                    valid_percent_start,
                    valid_percent_end,
                )
                processed_samples += len(consumed_batch)

                if processed_samples - last_printed_samples >= batch_touch_hold:
                    last_printed_samples = processed_samples
                    print(
                        f"preprocess_touch_hold_data: processed {processed_samples}/{total_samples} samples...",
                        end="\r",
                        flush=True,
                    )


        if sample_buffer:
            _consume_touch_hold_batch(
                sample_buffer,
                model,
                inference_device,
                shared_context.is_big_touch,
                observations_by_track,
                valid_dist_start,
                valid_dist_end,
                valid_percent_start,
                valid_percent_end,
            )
            processed_samples += len(sample_buffer)

        print(f"preprocess_touch_hold_data: processed {total_samples}/{total_samples} samples... Done")

    finally:
        cap.release()

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

    print(f"{' '*70}", end='\r', flush=True) # 清除行
    return touch_hold_data







def _build_touch_hold_sampling_plan(shared_context: SharedContext):
    frame_plan = defaultdict(list)
    track_meta = {}

    for key, value in shared_context.track_data.items():
        track_id, note_type = key
        note_geometry_list = value

        if note_type != NoteType.TOUCH_HOLD:
            continue
        if len(note_geometry_list) < 10:
            continue

        track_meta[track_id] = {
            "note_type": note_type,
            "note_variant": note_geometry_list[0].note_variant,
        }

        for note in note_geometry_list:
            frame_num = int(note.frame)
            position = calculate_all_position(shared_context.touch_areas, note.cx, note.cy)
            frame_plan[frame_num].append({
                "track_id": track_id,
                "cx": float(note.cx),
                "cy": float(note.cy),
                "position": position,
            })

    return frame_plan, track_meta







def _consume_touch_hold_batch(consumed_batch,
                              model,
                              inference_device,
                              is_big_touch: bool,
                              observations_by_track,
                              valid_dist_start: float,
                              valid_dist_end: float,
                              valid_percent_start: float,
                              valid_percent_end: float):
    observations = _run_touch_hold_batch(consumed_batch, model, inference_device, is_big_touch)

    for sample, (dist, percent_of_hold) in zip(consumed_batch, observations):
        if dist != -1:
            if dist > valid_dist_start or dist < valid_dist_end:
                dist = -1

        if percent_of_hold != -1:
            if percent_of_hold < valid_percent_start or percent_of_hold > valid_percent_end:
                percent_of_hold = -1

        if dist == -1 and percent_of_hold == -1:
            continue

        observations_by_track[sample["track_id"]].append(
            (sample["frame"], sample["position"], dist, percent_of_hold)
        )






def _run_touch_hold_batch(consumed_batch, model, inference_device, is_big_touch: bool):
    images = [item["cropped_image"] for item in consumed_batch]

    try:
        yolo_results = model.predict(
            task="detect",
            source=images,
            verbose=False,
            device=inference_device,
            imgsz=get_imgsz("touch_hold"),
            half=True,
            batch=len(images),
        )
    except Exception as e:
        print(f"preprocess_touch_hold_data: touch-hold yolo inference failed: {e}")
        return [(-1, -1)] * len(consumed_batch)

    observations = []
    for i in range(len(consumed_batch)):
        if i >= len(yolo_results):
            observations.append((-1, -1))
            continue
        image = images[i]
        h, w = image.shape[:2]
        observations.append(_extract_touch_hold_observation(yolo_results[i], w, h, is_big_touch))

    return observations





def _extract_touch_hold_observation(result, crop_w: int, crop_h: int, is_big_touch: bool):
    dist = -1
    percent_of_hold = -1

    if result.boxes is None or len(result.boxes) == 0:
        return dist, percent_of_hold

    boxes = result.boxes.cpu().numpy()

    touch_candidate = None
    progress_candidates = []
    for i in range(len(boxes)):
        cls_id = int(boxes.cls[i])
        conf = float(boxes.conf[i])
        cx, cy, w, h = boxes.xywh[i]

        if cls_id == TOUCH_HOLD_CLASS_TOUCH:
            if touch_candidate is None or conf > touch_candidate[0]:
                touch_candidate = (conf, float(w), float(h))
        elif cls_id == TOUCH_HOLD_CLASS_PROGRESS:
            progress_candidates.append((conf, float(cx), float(cy)))

    if touch_candidate is not None:
        _conf, touch_w, touch_h = touch_candidate
        dist = _convert_touch_box_to_dist_to_center(touch_w, touch_h, is_big_touch)

    if progress_candidates:
        # 按置信度从高到低选择第一个合法的进度点
        progress_candidates.sort(key=lambda x: x[0], reverse=True)
        for _conf, px, py in progress_candidates:
            filtered_percent = _progress_point_to_percent_with_dist_filter(px, py, crop_w, crop_h)
            if filtered_percent != -1:
                percent_of_hold = filtered_percent
                break

    return dist, percent_of_hold





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






def _calc_touch_hold_crop_size(std_video_size: int, is_big_touch: bool) -> int:
    crop_size = std_video_size * 210 / 1080 # 与 label_notes.py 一致
    if is_big_touch:
        crop_size *= 1.3
    return max(1, int(round(crop_size)))





def _crop_with_black_padding(frame, center_x, center_y, crop_width, crop_height):
    frame_height, frame_width = frame.shape[:2]

    center_x = float(center_x)
    center_y = float(center_y)
    crop_width = max(1, int(crop_width))
    crop_height = max(1, int(crop_height))

    x1 = int(round(center_x - crop_width / 2))
    y1 = int(round(center_y - crop_height / 2))
    x2 = x1 + crop_width
    y2 = y1 + crop_height

    src_x1 = max(0, x1)
    src_y1 = max(0, y1)
    src_x2 = min(frame_width, x2)
    src_y2 = min(frame_height, y2)

    cropped = np.zeros((crop_height, crop_width, 3), dtype=frame.dtype)
    if src_x1 >= src_x2 or src_y1 >= src_y2:
        return cropped

    dst_x1 = src_x1 - x1
    dst_y1 = src_y1 - y1
    dst_x2 = dst_x1 + (src_x2 - src_x1)
    dst_y2 = dst_y1 + (src_y2 - src_y1)

    cropped[dst_y1:dst_y2, dst_x1:dst_x2] = frame[src_y1:src_y2, src_x1:src_x2]
    return cropped

