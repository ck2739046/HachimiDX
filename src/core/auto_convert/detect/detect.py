from ultralytics import YOLO
import cv2
import os
import time
from pathlib import Path
import numpy as np

from ...schemas.op_result import OpResult, ok, err
from .note_definition import *


def main(std_video_path: Path,
         total_frames: int,
         batch_detect: int,
         inference_device: str,
         detect_model_path: str,
         obb_model_path: str
        ) -> OpResult[None]:
    
    """
    输入:
    - std_video_path
    - batch_detect: yolo predict batch size
    - inference_device
    - detect_model_path
    - obb_model_path

    返回:
    - OpResult[None]
    """

    try:
        final_results = []
        print("Start detection...")

        # 计算 tap/hold 尺寸预过滤的阈值
        try:
            cap = cv2.VideoCapture(str(std_video_path))
            video_width = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
            cap.release()
            # 标准尺寸: tap 105px, hold 108px
            # 这里保守一点取 90px 作为最小尺寸阈值
            size_thresh = video_width / 1080.0 * 90
        except Exception as e:
            print(f"Failed to get video width. Error: {e}")
            size_thresh = -1 # 不过滤

        for model_path, name in [(detect_model_path, 'detect'), (obb_model_path, 'obb')]:
            counter = 0
            last_counter = 0
            start_time = time.time()
            last_time = start_time

            # 模型推理
            model = YOLO(model_path, task=name)
            imgsz = get_imgsz(name)
            yolo_results_generator = model.predict(
                source=std_video_path,
                stream=True,
                batch=batch_detect,
                device=inference_device,
                imgsz=imgsz,
                max_det=50,
                verbose=False,
                half=True
            )

            # 流式输出后处理
            for result in yolo_results_generator:
                # 转换数据格式并保存
                note_geometrys = _parse_detections_to_note_geometrys(result, counter, name)
                # 预过滤：对 tap/hold 去除宽或高过小的误检框
                note_geometrys = _prefilter_tap_hold_by_size(note_geometrys, size_thresh)
                # 按 note_type 分组做 NMS 去重
                if name == 'detect':
                    note_geometrys = _dedup_detections_by_note_type(note_geometrys, iou_thresh=0.95)
                final_results.extend(note_geometrys)
                # 打印进度
                counter += 1
                if counter % 40 == 0:
                    last_time, last_counter = print_progress(name, 'fps', counter, total_frames, last_time, last_counter)
            
            # 结束
            finish_time = time.time()
            processed_frames = max(counter, 1)
            print(f"{name} done, time: {finish_time - start_time:.1f}s, average: {processed_frames / (finish_time - start_time):.1f}fps          ")

        # 保存到文件
        _save_detect_results(final_results, std_video_path.parent)
        return ok()

    except Exception as e:
        return err("Unexcepted error in auto_convert > detect > detect", e)



def _parse_detections_to_note_geometrys(result, frame_number, model_name):
    if model_name == 'detect':
        # 转换detect模型结果
        if result.boxes is None or len(result.boxes) == 0:
            return []
        # 转换为numpy批量获取数据
        boxes = result.boxes.cpu().numpy()
        xyxy = boxes.xyxy    # shape: (N, 4)
        xywh = boxes.xywh    # shape: (N, 4)
        conf = boxes.conf    # shape: (N, 1)
        raw_cls = boxes.cls  # shape: (N, 1)
        # 批量构建字典列表

        note_geometry_list = [
            Note_Geometry(
                frame=frame_number,
                note_type=map_model_class_to_note_type(model_name, int(raw_cls[i])),
                note_variant=NoteVariant.NORMAL, # 默认 normal
                conf=float(conf[i]),
                x1=float(xyxy[i, 0]),  # 左上角x
                y1=float(xyxy[i, 1]),  # 左上角y
                x2=float(xyxy[i, 2]),  # 右上角x
                y2=float(xyxy[i, 1]),  # 右上角y
                x3=float(xyxy[i, 2]),  # 右下角x
                y3=float(xyxy[i, 3]),  # 右下角y
                x4=float(xyxy[i, 0]),  # 左下角x
                y4=float(xyxy[i, 3]),  # 左下角y
                cx=float(xywh[i, 0]),
                cy=float(xywh[i, 1]),
                w=float(xywh[i, 2]),
                h=float(xywh[i, 3]),
                r=0.0
            )
            for i in range(len(boxes))
        ]
        return note_geometry_list
    else:
        # 转换obb模型结果
        if result.obb is None or len(result.obb) == 0:
            return [] 
        # 转换为numpy批量获取数据
        obb = result.obb.cpu().numpy()
        xyxyxyxy = obb.xyxyxyxy  # (N, 4, 2) -> N个框，每个框4个点，每个点(x,y)
        xywhr = obb.xywhr        # (N, 5)    -> N个框，每个框(x_center, y_center, w, h, r)
        conf = obb.conf          # (N, 1)
        raw_cls = obb.cls        # (N, 1)
        # 批量构建字典列表
        note_geometry_list = [
            Note_Geometry(
                frame=frame_number,
                note_type=map_model_class_to_note_type(model_name, int(raw_cls[i])),
                note_variant=NoteVariant.NORMAL, # 默认 normal
                conf=float(conf[i]),
                x1=float(xyxyxyxy[i, 0, 0]),  # 第1个点的x坐标
                y1=float(xyxyxyxy[i, 0, 1]),  # 第1个点的y坐标
                x2=float(xyxyxyxy[i, 1, 0]),  # 第2个点的x坐标
                y2=float(xyxyxyxy[i, 1, 1]),  # 第2个点的y坐标
                x3=float(xyxyxyxy[i, 2, 0]),  # 第3个点的x坐标
                y3=float(xyxyxyxy[i, 2, 1]),  # 第3个点的y坐标
                x4=float(xyxyxyxy[i, 3, 0]),  # 第4个点的x坐标
                y4=float(xyxyxyxy[i, 3, 1]),  # 第4个点的y坐标
                cx=float(xywhr[i, 0]),
                cy=float(xywhr[i, 1]),
                w=float(xywhr[i, 2]),
                h=float(xywhr[i, 3]),
                r=float(xywhr[i, 4]),         # rotation
            )
            for i in range(len(obb))
        ]
        return note_geometry_list










def _prefilter_tap_hold_by_size(note_geometrys: list, size_thresh: float) -> list:
    """预过滤：删除 TAP/HOLD 中宽或高小于阈值的检测框"""
    if size_thresh <= 0:
        return note_geometrys
    if not note_geometrys:
        return []
    _TARGET_TYPES = (NoteType.TAP, NoteType.HOLD)
    return [g for g in note_geometrys
            if g.note_type not in _TARGET_TYPES              # 如果不是目标类型, 直接保留
            or (g.w >= size_thresh and g.h >= size_thresh)]  # 如果是类型，应用尺寸过滤













def _save_detect_results(detections, output_dir):

    detections = sorted(detections, key=lambda x: x.frame) # 按帧号排序
    detect_result_path = os.path.join(output_dir, "detect_result.txt")
    
    with open(detect_result_path, 'w', encoding='utf-8') as f:
        current_frame = -1
        for detection in detections:
            # 写入新的帧号
            if detection.frame != current_frame:
                f.write(f"frame: {detection.frame}\n")
                current_frame = detection.frame
            # 写入音符数据
            data = [
                f"{detection.frame}",
                f"{detection.note_type.value}",
                f"{detection.note_variant.value}",
                f"{detection.conf:.4f}",
                f"{detection.x1:.4f}", f"{detection.y1:.4f}",
                f"{detection.x2:.4f}", f"{detection.y2:.4f}",
                f"{detection.x3:.4f}", f"{detection.y3:.4f}",
                f"{detection.x4:.4f}", f"{detection.y4:.4f}",
                f"{detection.cx:.4f}", f"{detection.cy:.4f}",
                f"{detection.w:.4f}", f"{detection.h:.4f}",
                f"{detection.r:.4f}"
            ]
            f.write(', '.join(data) + '\n')

    print(f"检测结果已保存到: {detect_result_path}")




    

def _iou_batch(bboxes1: np.ndarray, bboxes2: np.ndarray, eps: float = 1e-7) -> np.ndarray:
    area1 = (bboxes1[:, 2] - bboxes1[:, 0]) * (bboxes1[:, 3] - bboxes1[:, 1])
    area2 = (bboxes2[:, 2] - bboxes2[:, 0]) * (bboxes2[:, 3] - bboxes2[:, 1])
    bboxes2 = np.expand_dims(bboxes2, 0)
    bboxes1 = np.expand_dims(bboxes1, 1)
    xx1 = np.maximum(bboxes1[..., 0], bboxes2[..., 0])
    yy1 = np.maximum(bboxes1[..., 1], bboxes2[..., 1])
    xx2 = np.minimum(bboxes1[..., 2], bboxes2[..., 2])
    yy2 = np.minimum(bboxes1[..., 3], bboxes2[..., 3])
    w = np.maximum(0.0, xx2 - xx1)
    h = np.maximum(0.0, yy2 - yy1)
    inter = w * h
    return inter / (area1[:, np.newaxis] + area2[np.newaxis, :] - inter + eps)


def _dedup_detections_by_note_type(note_geometrys: list, iou_thresh: float) -> list:
    by_type = {}
    for g in note_geometrys:
        t = g.note_type
        if t not in by_type:
            by_type[t] = []
        by_type[t].append(g)
    note_geometrys_final = []
    for lst in by_type.values():
        note_geometrys_final.extend(_dedup_detections(lst, iou_thresh))
    return note_geometrys_final


def _dedup_detections(detections: list, iou_thresh: float) -> list:
    """同一帧内检测框去重：两两 IoU ≥ iou_thresh 时固定删除第二个。"""
    if len(detections) < 2:
        return detections

    # 提取 xyxy 坐标
    boxes = np.array([[d.x1, d.y1, d.x3, d.y3] for d in detections], dtype=np.float64)
    iou = _iou_batch(boxes, boxes)

    # 上三角索引，找出超过阈值的配对
    n = len(detections)
    i_upper, j_upper = np.triu_indices(n, k=1)
    dup_mask = iou[i_upper, j_upper] >= iou_thresh

    if not np.any(dup_mask):
        return detections

    removed = set()

    # 对每个重复对，固定删除第二个
    for i, j in zip(i_upper[dup_mask], j_upper[dup_mask]):
        if i not in removed and j not in removed:
            removed.add(j)

    return [d for idx, d in enumerate(detections) if idx not in removed]





def _load_detect_results(output_dir):

    detections = []
    detect_result_path = os.path.join(output_dir, "detect_result.txt")
    if not os.path.exists(detect_result_path):
        raise FileNotFoundError(f"文件不存在: {detect_result_path}")
    
    with open(detect_result_path, 'r', encoding='utf-8') as f:
        current_frame = -1
        for line in f:
            line = line.strip()
            if not line: continue
            
            if line.startswith('frame:'):
                current_frame = int(line.split(':')[1].strip())
            else:
                # 解析音符数据
                parts = line.split(',')
                if len(parts) == 17:  # 有17个字段
                    detection = Note_Geometry(
                        frame=current_frame,
                        note_type=NoteType(parts[1].strip()),
                        note_variant=NoteVariant(parts[2].strip()),
                        conf=float(parts[3].strip()),
                        x1=float(parts[4].strip()),
                        y1=float(parts[5].strip()),
                        x2=float(parts[6].strip()),
                        y2=float(parts[7].strip()),
                        x3=float(parts[8].strip()),
                        y3=float(parts[9].strip()),
                        x4=float(parts[10].strip()),
                        y4=float(parts[11].strip()),
                        cx=float(parts[12].strip()),
                        cy=float(parts[13].strip()),
                        w=float(parts[14].strip()),
                        h=float(parts[15].strip()),
                        r=float(parts[16].strip())
                    )
                    detections.append(detection)
    
    return detections

