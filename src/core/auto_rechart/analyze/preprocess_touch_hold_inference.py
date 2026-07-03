"""
Touch-Hold YOLO 推理模块（生产者-消费者流水线）

负责：
- 构建采样计划（从 track_data 中提取 TOUCH_HOLD 轨迹）
- 生产者线程：视频 seek + 裁剪样本图像
- 消费者线程：YOLO batch 推理 + 轻量解析
- 返回 list[LightResult] 供 preprocess_touch_hold.py 做 dist/percent 解析

参照 detect/classify.py 的生产者-消费者模式
"""

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
import threading
import queue

import cv2
import numpy as np
from ultralytics import YOLO

from ..detect.note_definition import NoteType, get_imgsz
from .tool import calculate_all_position
from .shared_context import SharedContext


SEEK_THRESHOLD = 200

TOUCH_HOLD_CLASS_TOUCH = 0
TOUCH_HOLD_CLASS_PROGRESS = 1


@dataclass(slots=True)
class LightResult:
    """YOLO 推理后的轻量化结果，供后续 dist/percent 解析使用。"""
    track_id: int
    frame: int
    position: str
    touch_w: float | None   # class 0 最高 conf 框的 w（裁剪图坐标系）
    touch_h: float | None   # class 0 最高 conf 框的 h（裁剪图坐标系）
    progress_points: list   # class 1 所有框的 (cx, cy)，已按 conf 降序排列；可为空列表


def run_touch_hold_inference(
    shared_context: SharedContext,
    inference_device,
    batch_touch_hold: int,
    touch_hold_model_path: Path,
) -> tuple[list[LightResult], dict]:
    """
    Touch-Hold YOLO 推理入口。

    Returns:
        (light_results, track_meta)
        - light_results: list[LightResult] — 每条样本的轻量 YOLO 检测结果
        - track_meta: dict[track_id, {"note_type", "note_variant"}] — 供轨迹级校验用
    """
    frame_plan, track_meta = _build_touch_hold_sampling_plan(shared_context)
    if not frame_plan:
        print("run_touch_hold_inference: no touch hold data")
        return [], {}

    crop_size = calc_touch_hold_crop_size(shared_context.std_video_size, shared_context.is_big_touch)
    total_samples = sum(len(v) for v in frame_plan.values())

    # 双缓冲队列
    batch_queue = queue.Queue(maxsize=2)
    all_light_results: list[LightResult] = []

    # 启动生产者线程（CPU：视频解码 + 裁剪图像）
    producer_thread = threading.Thread(
        target=_producer,
        args=(
            str(shared_context.std_video_path),
            frame_plan,
            crop_size,
            batch_touch_hold,
            batch_queue,
        ),
        daemon=True,
    )
    producer_thread.start()

    # 启动消费者线程（GPU：YOLO 推理 + 轻量解析）
    consumer_thread = threading.Thread(
        target=_consumer,
        args=(
            batch_queue,
            str(touch_hold_model_path),
            inference_device,
            all_light_results,
            total_samples,
        ),
        daemon=True,
    )
    consumer_thread.start()

    # 等待两个线程完成
    producer_thread.join()
    consumer_thread.join()

    print(f"run_touch_hold_inference: processed {total_samples}/{total_samples} samples... Done")
    return all_light_results, track_meta








def _producer(std_video_path, frame_plan, crop_size, batch_touch_hold, batch_queue):
    """
    生产者线程
    解码视频 + 裁剪音符图像
    凑满 batch 后放入队列
    结束后发送 None sentinel
    """
    cap = cv2.VideoCapture(std_video_path)
    try:
        buffer = []
        sorted_frames = sorted(frame_plan.keys())
        last_frame_number = -1

        for frame_number in sorted_frames:
            # seek 优化：小跳用 cap.grab() 仅推进指针（不解码），大跳用 cap.set()
            gap = frame_number - last_frame_number
            if gap == 1:
                pass
            elif gap <= SEEK_THRESHOLD:
                for _ in range(gap - 1):
                    cap.grab()
            else:
                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)

            ret, frame = cap.read()
            if not ret: continue
            last_frame_number = frame_number

            this_frame_plan = frame_plan[frame_number]
            for sample in this_frame_plan:
                cropped = _crop_with_black_padding(
                    frame,
                    sample["cx"],
                    sample["cy"],
                    crop_size,
                    crop_size,
                )
                buffer.append({
                    "track_id": sample["track_id"],
                    "frame": frame_number,
                    "position": sample["position"],
                    "cropped_image": cropped,
                })

            # 凑满 batch 就发送
            while len(buffer) >= batch_touch_hold:
                batch_queue.put(buffer[:batch_touch_hold])
                buffer = buffer[batch_touch_hold:]

        # 发送剩余样本
        if buffer:
            batch_queue.put(buffer)

        # 发送结束信号
        batch_queue.put(None)

    finally:
        cap.release()






def _consumer(batch_queue, model_path, inference_device, all_light_results, total_samples):
    """
    消费者线程
    从队列取 batch → YOLO 推理 → 轻量解析 → 收集结果。"""
    model = YOLO(model_path, task="detect")
    processed_samples = 0
    last_printed_samples = 0

    while True:
        consumed_batch = batch_queue.get()
        if consumed_batch is None:
            break

        images = [item["cropped_image"] for item in consumed_batch]

        try:
            yolo_results = model.predict(
                source=images,
                task="detect",
                verbose=False,
                device=inference_device,
                imgsz=get_imgsz("touch_hold"),
                half=True,
                batch=len(images),
            )
        except Exception as e:
            print(f"touch-hold yolo inference failed: {e}")
            # 跳过这批，但还是要计入进度
            processed_samples += len(consumed_batch)
            continue

        for i, sample in enumerate(consumed_batch):
            if i < len(yolo_results):
                light = _extract_light_result(yolo_results[i], sample)
                all_light_results.append(light)
            else:
                # 防御：YOLO 返回结果数不足
                all_light_results.append(LightResult(
                    track_id=sample["track_id"],
                    frame=sample["frame"],
                    position=sample["position"],
                    touch_w=None,
                    touch_h=None,
                    progress_points=[],
                ))

        processed_samples += len(consumed_batch)
        if processed_samples - last_printed_samples >= len(consumed_batch):
            last_printed_samples = processed_samples
            print(
                f"run_touch_hold_inference: processed {processed_samples}/{total_samples} samples...",
                end="\r",
                flush=True,
            )










def _extract_light_result(yolo_result, sample_meta: dict) -> LightResult:
    """
    从单张裁剪图的 YOLO detect 结果中提取轻量字段。

    - class 0 (touch 框): 取 conf 最高的框，记 (w, h)
    - class 1 (progress 点): 所有框按 conf 降序，记 (cx, cy) 列表
    """
    touch_w = None
    touch_h = None
    progress_points = []

    if yolo_result.boxes is None or len(yolo_result.boxes) == 0:
        return LightResult(
            track_id=sample_meta["track_id"],
            frame=sample_meta["frame"],
            position=sample_meta["position"],
            touch_w=None,
            touch_h=None,
            progress_points=[],
        )

    boxes = yolo_result.boxes.cpu().numpy()

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

    if progress_candidates:
        progress_candidates.sort(key=lambda x: x[0], reverse=True)
        progress_points = [(cx, cy) for _conf, cx, cy in progress_candidates]

    return LightResult(
        track_id=sample_meta["track_id"],
        frame=sample_meta["frame"],
        position=sample_meta["position"],
        touch_w=touch_w,
        touch_h=touch_h,
        progress_points=progress_points,
    )







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









def calc_touch_hold_crop_size(std_video_size: int, is_big_touch: bool) -> int:
    crop_size = std_video_size * 210 / 1080   # 与 label_notes.py 一致
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
