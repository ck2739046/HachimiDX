from ultralytics import YOLO
import cv2
import os
import time
import traceback
import torch
import torch.utils.data
import torch.multiprocessing as tmp
from queue import Empty, Full
from pathlib import Path
import numpy as np
from collections import defaultdict
from dataclasses import dataclass, field

from ...schemas.op_result import OpResult, ok, err
from .note_definition import *
from .detect_decode import Decoder
from .detect_inference import create_inferencer




_PROGRESS_STALL_TIMEOUT = 60.0  # 如果 progress 连续一段时间无推进则报错



def main(std_video_path,
         total_frames,
         batch_detect, inference_device,
         detect_model_path, obb_model_path
        ) -> OpResult:
    """
    检测模块主入口

    流程: Decoder 共享解码 → Inferencer (detect/obb 双 worker) 推理
          → 边喂边收 → send_eof → 收尾 drain → 后处理 → 保存 detect_result.txt
    """
    decoder = None
    inferencer = None
    raw_results = []
    try:
        start_time = time.time()
        print("Start detection...")

        # 1. 前置计算: decode_imgsz + coord_scale
        #    decoder 会把帧 resize 到 decode_imgsz
        #    worker 解析时乘 coord_scale 还原到原始尺寸
        decode_imgsz = get_imgsz('detect')
        cap = cv2.VideoCapture(str(std_video_path))
        std_video_width = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
        cap.release()
        if not std_video_width or std_video_width <= 0:
            return err(f"[detect] 无法读取视频宽度: {std_video_path}")
        coord_scale = std_video_width / decode_imgsz

        # 2. 构造 Decoder
        decoder = Decoder(str(std_video_path), decode_imgsz, batch_detect)

        # 3. 构造 Inferencer
        create_r = create_inferencer(detect_model_path, obb_model_path,
                                     batch_detect, inference_device, coord_scale)
        if not create_r.is_ok:
            return err("[detect] create_inferencer 失败", inner=create_r)
        inferencer = create_r.value

        # 3. 构造 progress monitor (打印进度 + 停滞检测)
        monitor = _ProgressMonitor(total_frames)



        # 4. 主循环: 从 decoder 取帧, 给 inferencer 喂帧, 再从 inferencer 取结果
        while True:
            batch_r = decoder.get_next_batch()
            if not batch_r.is_ok:
                return err("[detect.main.loop1] decoder.get_next_batch 失败", inner=batch_r)
            if batch_r.value is None:
                break  # 解码 EOF

            put_r = inferencer.put_batch(batch_r.value)
            if not put_r.is_ok:
                return err("[detect.main.loop1] inferencer.put_batch 失败", inner=put_r)

            get_r = inferencer.get_results()
            if not get_r.is_ok:
                return err("[detect.main.loop1] inferencer.get_results 失败", inner=get_r)
            raw_results.extend(get_r.value)

            update_r = monitor.update(inferencer)
            if not update_r.is_ok:
                return err("[detect.main.loop1] progress monitor error", inner=update_r)

        # 解码完成, 通知 worker 不再有新输入
        eof_r = inferencer.send_eof()
        if not eof_r.is_ok:
            return err("[detect.main] inferencer.send_eof 失败", inner=eof_r)



        # 5. 收尾循环: 等待 inferencer 完成剩余的推理
        while not inferencer.is_done:
            get_r = inferencer.get_results()
            if not get_r.is_ok:
                return err("[detect.main.loop2] inferencer.get_results 失败", inner=get_r)
            raw_results.extend(get_r.value)

            update_r = monitor.update(inferencer)
            if not update_r.is_ok:
                return err("[detect.main.loop2] progress monitor error", inner=update_r)
            time.sleep(0.01)

        # 再排空一次残留
        get_r = inferencer.get_results()
        if get_r.is_ok:
            raw_results.extend(get_r.value)

        _ = monitor.update(inferencer)  # 最终刷新一次进度显示 (忽略结果)
        print()  # 换行跳出 \r 行



        # 6. 后处理 (prefilter + NMS) + 保存
        final_results = _postprocess_results(raw_results, std_video_path)
        _save_detect_results(final_results, std_video_path.parent)

        print(f"检测模块完成, 耗时{time.time() - start_time:.1f}s")
        return ok()

    except KeyboardInterrupt:
        print("\n[detect] 中断")
        return err("[detect.main] KeyboardInterrupt")
    except Exception as e:
        print(traceback.format_exc())
        return err("[detect.main] unexpected error", error_raw=e)
    finally:
        if inferencer is not None:
            inferencer.stop()
        if decoder is not None:
            decoder.close()



class _ProgressMonitor:
    """简易进度监控器: 进度打印 + 停滞检测"""

    def __init__(self, total_frames: int,
                 stall_timeout: float = _PROGRESS_STALL_TIMEOUT):
        self._total_frames = total_frames
        self._stall_timeout = stall_timeout

        self._last_progress = None                 # 上次进度的数值, 用于停滞检测
        self._last_change_time = time.monotonic()  # 上次进度变化的时刻, 用于停滞检测

    def update(self, inferencer) -> OpResult:
        # 1. 读取 progress
        try:
            pd, po = inferencer.progress
        except Exception as e:
            return err("Failed to get inferencer.progress", error_raw=e)
        progress = (pd, po)

        # 2. 停滞检测: progress 连续无变化超过 stall_timeout 即判定卡住
        if progress != self._last_progress:
            self._last_progress = progress
            self._last_change_time = time.monotonic()
        elif time.monotonic() - self._last_change_time > self._stall_timeout:
            return err(f"进度超过 {self._stall_timeout}s 无推进, 可能程序卡住了")

        # 3. 打印进度
        total = self._total_frames
        pct_d = min(pd / total * 100, 100.0) if total else 0.0
        pct_o = min(po / total * 100, 100.0) if total else 0.0
        print("\r"
              f"detect {pd}/{total} ({pct_d:.1f}%)"
              " | "
              f"obb {po}/{total} ({pct_o:.1f}%)",
              end="    ", flush=True)

        return ok()







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


def _dedup_detections(note_geometrys: list, model_name: str, iou_thresh: float) -> list:
    by_type = {}
    for g in note_geometrys:
        t = g.note_type
        if t not in by_type:
            by_type[t] = []
        by_type[t].append(g)
    note_geometrys_final = []
    for lst in by_type.values():
        note_geometrys_final.extend(_dedup_detections_single_type(lst, model_name, iou_thresh))
    return note_geometrys_final


def _dedup_detections_single_type(detections: list, model_name: str, iou_thresh: float) -> list:
    if len(detections) < 2:
        return detections

    # 按置信度降序排列，确保高置信度框优先保留
    detections = sorted(detections, key=lambda d: d.conf, reverse=True)

    if model_name == 'detect':
        iou = _compute_detect_iou_matrix(detections)
    else:  # obb
        iou = _compute_obb_iou_matrix(detections)

    # 只取上三角配对，跳过对角线
    rows, cols = np.where(np.triu(iou, k=1) >= iou_thresh)
    if len(rows) == 0:
        return detections

    removed = set()

    # i < j 总是成立（上三角），排序后 conf[i] >= conf[j]，删除低置信度的 j
    for i, j in zip(rows, cols):
        i, j = int(i), int(j)
        if i not in removed and j not in removed:
            removed.add(j)

    return [d for idx, d in enumerate(detections) if idx not in removed]


def _compute_detect_iou_matrix(detections: list) -> np.ndarray:
    """计算 detect 框的对称 IoU 矩阵"""
    boxes = np.array([[d.x1, d.y1, d.x3, d.y3] for d in detections], dtype=np.float32)
    area = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
    xx1 = np.maximum(boxes[:, 0, None], boxes[:, 0])
    yy1 = np.maximum(boxes[:, 1, None], boxes[:, 1])
    xx2 = np.minimum(boxes[:, 2, None], boxes[:, 2])
    yy2 = np.minimum(boxes[:, 3, None], boxes[:, 3])
    iw = np.maximum(0.0, xx2 - xx1)
    ih = np.maximum(0.0, yy2 - yy1)
    inter = iw * ih
    iou = inter / (area[:, None] + area[None, :] - inter + 1e-7)
    return iou


def _obb_iou_single(g1, g2) -> float:
    """计算两个 OBB 框之间的 IoU"""
    pixel_box1 = np.array([[g1.x1, g1.y1], [g1.x2, g1.y2], [g1.x3, g1.y3], [g1.x4, g1.y4]], dtype=np.float32)
    pixel_box2 = np.array([[g2.x1, g2.y1], [g2.x2, g2.y2], [g2.x3, g2.y3], [g2.x4, g2.y4]], dtype=np.float32)
    rect1 = cv2.minAreaRect(pixel_box1)
    rect2 = cv2.minAreaRect(pixel_box2)
    ret, intersection = cv2.rotatedRectangleIntersection(rect1, rect2)
    if ret == 0:
        return 0.0
    intersection_area = cv2.contourArea(intersection)
    area1 = rect1[1][0] * rect1[1][1]
    area2 = rect2[1][0] * rect2[1][1]
    union_area = area1 + area2 - intersection_area
    if union_area <= 0:
        return 0.0
    return intersection_area / union_area


def _compute_obb_iou_matrix(detections: list) -> np.ndarray:
    """计算 OBB 框的对称 IoU 矩阵"""
    n = len(detections)
    iou = np.zeros((n, n), dtype=np.float32)
    for i in range(n):
        for j in range(i + 1, n):
            val = _obb_iou_single(detections[i], detections[j])
            iou[i, j] = val
            iou[j, i] = val
    return iou









def _postprocess_results(raw_results: list, std_video_path: Path) -> list:
    """推理完成后统一执行 prefilter + NMS 后处理"""

    if not raw_results:
        return []
    
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
    
    by_frame: dict[int, dict] = defaultdict(lambda: {"detect": [], "obb": []})
    for ng, model_name in raw_results:
        by_frame[ng.frame][model_name].append(ng)

    final_results = []
    for frame in sorted(by_frame.keys()):
        for model_name in ('detect', 'obb'):
            geos = by_frame[frame][model_name]
            if not geos:
                continue
            geos = _prefilter_tap_hold_by_size(geos, size_thresh)
            geos = _dedup_detections(geos, model_name, iou_thresh=0.98)
            final_results.extend(geos)

    return final_results









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
