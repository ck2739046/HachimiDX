from ultralytics import YOLO
import cv2
import os
import time
import multiprocessing
from queue import Empty, Full
from pathlib import Path
import numpy as np
from collections import defaultdict
from dataclasses import dataclass, field

from ...schemas.op_result import OpResult, ok, err
from .note_definition import *

# --- 共享解码流水线参数 ---
_FRAME_QUEUE_CAP = 20        # 每条帧队列上限（detect/obb 各一条）
_DECODE_EOF = None           # 帧队列 EOF 哨兵
_PUT_TIMEOUT = 0.5           # 解码进程 put 的单次超时（用于周期检查 stop_event）
_DECODE_JOIN_TIMEOUT = 10.0  # 解码进程 join 超时
_DECODE_DEAD_GRACE = 3       # decode 死亡判据连续成立的轮数（×0.3s 主循环 timeout）
                             # 滤掉 EOF 已消费、worker 仍在 flush 尾批的正常窗口


def _decode_worker(std_video_path, q_detect, q_obb,
                   stop_event, decode_imgsz):
    """
    独立解码进程：
    - 单次 cap.read() 解码
    - cv2.resize 到 decode_imgsz
    - 每帧分别 put 进 detect/obb 两条 bounded Queue
    """
    cap = cv2.VideoCapture(std_video_path)
    try:
        while not stop_event.is_set():
            ret, frame = cap.read()
            if not ret:
                break
            # 解码时提前一次 resize
            # 避免 detect/obb 两个模型各自 resize
            # 推理结果基于 decode_imgsz, 后续解析需要还原到视频原始尺寸
            frame = cv2.resize(frame, (decode_imgsz, decode_imgsz),
                               interpolation=cv2.INTER_LINEAR)
            # 先 detect 再 obb
            # 任一队列满则阻塞 (detect/obb 速度差不多影响不大)
            # stop_event 触发则放弃
            if not _put_or_stop(q_detect, frame, stop_event):
                return
            if not _put_or_stop(q_obb, frame, stop_event):
                return
    except Exception:
        pass
    finally:
        cap.release()
        _send_eof(q_detect, stop_event)
        _send_eof(q_obb, stop_event)


def _put_or_stop(q, item, stop_event, timeout=_PUT_TIMEOUT):
    """带超时的 put：队列满则周期重试并检查 stop_event；返回 False 表示已被要求终止"""
    while True:
        if stop_event.is_set():
            return False
        try:
            q.put(item, block=True, timeout=timeout)
            return True
        except Full:
            continue


def _drain_queue(q):
    """排空队列，返回所有移除项（调用方可丢弃）。get_nowait 跑空即止。"""
    items = []
    while True:
        try:
            items.append(q.get_nowait())
        except Empty:
            break
    return items


def _send_eof(q, stop_event, timeout=_PUT_TIMEOUT):
    """尽力向队列送达 EOF；stop 触发时（消费者大概率已死）先排空再塞入，避免永久阻塞"""
    deadline = time.monotonic() + 5.0
    while True:
        if stop_event.is_set():
            _drain_queue(q)
        try:
            q.put(_DECODE_EOF, block=True, timeout=timeout)
            return
        except Full:
            if time.monotonic() > deadline:
                return











def _inference_worker(model_path, task_name,
                      frame_queue, batch_detect, inference_device,
                      results_queue, progress_val, coord_scale):
    """
    模型推理进程（消费共享解码队列）：
    - 从 frame_queue 攒 batch_detect → predict
    - 按绝对帧号解析为 Note_Geometrys（帧序由 next_frame_idx 显式维护）
    - 通过 multiprocessing.Queue 发送 (note_geometry, task_name)
    - 通过 multiprocessing.Value 更新进度计数器
    """
    start_time = time.time()
    model = YOLO(model_path, task=task_name)
    imgsz_val = get_imgsz(task_name)
    buffer = []
    next_frame_idx = 0

    while True:
        frame = frame_queue.get()
        if frame is _DECODE_EOF:
            break
        buffer.append(frame)
        if len(buffer) >= batch_detect:
            _run_batch(model, task_name, imgsz_val, buffer, next_frame_idx,
                       batch_detect, inference_device, results_queue, progress_val,
                       coord_scale)
            next_frame_idx += len(buffer)
            buffer.clear()

    # flush 残余
    if buffer:
        _run_batch(model, task_name, imgsz_val, buffer, next_frame_idx,
                   batch_detect, inference_device, results_queue, progress_val,
                   coord_scale)
        next_frame_idx += len(buffer)
        buffer.clear()

    elapsed_s = time.time() - start_time
    results_queue.put(("__done__", task_name, elapsed_s))


def _run_batch(model, task_name, imgsz_val, frames, start_idx,
               batch_detect, inference_device, results_queue, progress_val,
               coord_scale):
    """对一个 batch 的帧跑 predict 并解析结果；results 与 frames 输入顺序一一对应"""
    results = model.predict(
        source=frames,
        batch=batch_detect,
        device=inference_device,
        imgsz=imgsz_val,
        max_det=50,
        verbose=False,
        half=True,
    )
    for i, result in enumerate(results):
        frame_number = start_idx + i
        note_geometrys = _parse_detections_to_note_geometrys(result, frame_number, task_name, coord_scale)
        if note_geometrys:
            for ng in note_geometrys:
                results_queue.put((ng, task_name))
        progress_val.value = frame_number + 1










def _process_printer(progress_detect, progress_obb, total_frames, stop_event):
    """
    独立打印 progress 进程
    每 0.2s 轮询两个推理进度计数器，在同一行打印合并进度
    """
    while not stop_event.wait(timeout=0.2):
        d = progress_detect.value
        o = progress_obb.value
        if d >= total_frames and o >= total_frames:
            break
        pct_d = min(d / total_frames * 100, 100.0)
        pct_o = min(o / total_frames * 100, 100.0)
        print(f"detect: {d}/{total_frames} ({pct_d:.1f}%) | obb: {o}/{total_frames} ({pct_o:.1f}%)  ", end="\r", flush=True)
    # 最后一次刷新
    d = progress_detect.value
    o = progress_obb.value
    pct_d = min(d / total_frames * 100, 100.0)
    pct_o = min(o / total_frames * 100, 100.0)
    print(f"detect: {d}/{total_frames} ({pct_d:.1f}%) | obb: {o}/{total_frames} ({pct_o:.1f}%)  ", end="\r", flush=True)












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
        print("Start detection...")

        # 共享解码的 imgsz：detect/obb 必须一致
        decode_imgsz = get_imgsz('detect')
        if get_imgsz('obb') != decode_imgsz:
            return err("detect/obb imgsz 不一致，共享解码需相同 imgsz", None)
        if decode_imgsz <= 0:
            return err("detect/obb imgsz 非正整数", None)
        
        # 坐标空间还原系数：解码时缩放到 decode_imgsz，解析时乘此系数还原到视频原始尺寸
        cap = cv2.VideoCapture(str(std_video_path))
        std_video_size = round(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        cap.release()
        coord_scale = std_video_size / decode_imgsz

        # 跨进程共享对象（主进程创建，传递给子进程）
        progress_detect = multiprocessing.Value('i', 0)
        progress_obb    = multiprocessing.Value('i', 0)
        results_queue   = multiprocessing.Queue()
        q_detect        = multiprocessing.Queue(maxsize=_FRAME_QUEUE_CAP)
        q_obb           = multiprocessing.Queue(maxsize=_FRAME_QUEUE_CAP)
        stop_event      = multiprocessing.Event()  # worker 崩溃时解除解码进程阻塞
        stop_printer    = multiprocessing.Event()

        # 启动解码进程（单次解码，喂两条队列）
        decode_p = multiprocessing.Process(
            target=_decode_worker,
            args=(str(std_video_path), q_detect, q_obb, stop_event, decode_imgsz),
            daemon=True,
        )
        decode_p.start()

        # 启动 printer 进程
        printer_p = multiprocessing.Process(
            target=_process_printer,
            args=(progress_detect, progress_obb, total_frames, stop_printer),
            daemon=True
        )
        printer_p.start()

        # 启动两个模型推理进程（各自从自己的帧队列消费）
        p_detect = multiprocessing.Process(
            target=_inference_worker,
            args=(detect_model_path, 'detect', q_detect,
                  batch_detect, inference_device,
                  results_queue, progress_detect, coord_scale)
        )
        p_obb = multiprocessing.Process(
            target=_inference_worker,
            args=(obb_model_path, 'obb', q_obb,
                  batch_detect, inference_device,
                  results_queue, progress_obb, coord_scale)
        )
        p_detect.start()
        p_obb.start()

        workers = (('detect', p_detect), ('obb', p_obb))
        state = _PipelineState()

        # 主进程：消费 results_queue，三个退出路径（collect done / decode dead / worker died）
        while state.workers_alive > 0:
            try:
                item = results_queue.get(timeout=0.3)
                _collect_one(state, item)
            except Empty:
                if _check_decode_dead(state, decode_p, q_detect, q_obb):
                    break
                if _check_worker_exits(state, workers, results_queue):
                    break

        # 排空队列中可能残留的结果
        for item in _drain_queue(results_queue):
            _collect_one(state, item)

        _cleanup_pipeline(decode_p, workers, printer_p,
                          stop_event, stop_printer, force_terminate=state.worker_died)

        if state.worker_died:
            print()
            return err("Unexpected error in auto_rechart > detect > detect (worker died)", None)

        print()  # 跳过 \r 所在行

        # 打印各模型汇总
        for name in ('detect', 'obb'):
            if name in state.worker_times and state.worker_times[name] is not None:
                elapsed = state.worker_times[name]
                frames_done = progress_detect.value if name == 'detect' else progress_obb.value
                fps = frames_done / elapsed if elapsed > 0 else 0
                print(f"{name} done, time: {elapsed:.1f}s, average: {fps:.1f}fps")

        # 后处理（prefilter + NMS）
        final_results = _postprocess_results(state.all_raw_results, std_video_path)

        # 保存到文件
        _save_detect_results(final_results, std_video_path.parent)
        return ok()

    except Exception as e:
        return err("Unexpected error in auto_rechart > detect > detect", e)






# 管道控制辅助
@dataclass
class _PipelineState:
    """主消费循环的可变状态（被多个辅助函数原地修改，避免多返回值签名爆炸）"""
    workers_alive: int = 2
    worker_died: bool = False
    decode_dead_rounds: int = 0                             # decode 死亡判据连续成立的轮数（宽限过滤）
    worker_times: dict = field(default_factory=dict)        # {task_name: elapsed_seconds}
    all_raw_results: list = field(default_factory=list)     # list[tuple[Note_Geometry, str]]


def _collect_one(state, item):
    """处理一个 results_queue item：__done__ 信号 → 记录耗时并递减未完成计数；否则 append 结果"""
    if isinstance(item, tuple) and len(item) == 3 and item[0] == "__done__":
        _, name, elapsed = item
        state.worker_times[name] = elapsed
        state.workers_alive -= 1
    else:
        state.all_raw_results.append(item)


def _check_decode_dead(state, decode_p, q_detect, q_obb):
    """
    decode 存活兜底：解码进程段错误/被杀时 finally 不执行，EOF 不会送达，
    推理 worker 会永久阻塞在 frame_queue.get() 上 → 死锁。
    判据：decode 已死 + 两条帧队列都空 + 仍有 worker 未完成，连续 _DECODE_DEAD_GRACE 轮成立。
    返回 True 表示判定 decode 死锁（外层 break 走清理）。
    """
    if (not decode_p.is_alive()
            and q_detect.empty() and q_obb.empty()
            and state.workers_alive > 0):
        state.decode_dead_rounds += 1
        if state.decode_dead_rounds >= _DECODE_DEAD_GRACE:
            print("\n[decode] worker died unexpectedly (no EOF delivered)")
            state.worker_died = True
            return True
    else:
        state.decode_dead_rounds = 0
    return False


def _check_worker_exits(state, workers, results_queue):
    """
    崩溃兜底：worker 已退出但未发 __done__。
    再等一小段排除 mp.Queue 管道尚未刷新的正常退出竞态；仍取不到才判异常死亡。
    返回 True 表示判定 worker 异常死亡（外层 break 走清理）。
    """
    for name, p in workers:
        if name in state.worker_times or p.is_alive():
            continue
        time.sleep(0.2)
        try:
            late = results_queue.get(timeout=0.5)
            _collect_one(state, late)  # done 信号会自动递减 workers_alive
            return False               # 回主循环顶部继续 get（等价于原 break for 回 while）
        except Empty:
            state.worker_times[name] = None
            state.workers_alive -= 1
            state.worker_died = True
            print(f"\n[{name}] worker died unexpectedly")
            return True
    return False


def _cleanup_pipeline(decode_p, workers, printer_p,
                      stop_event, stop_printer, force_terminate):
    """
    统一清理：force_terminate=True（worker_died）先 stop 解阻塞 + terminate 存活 worker，
    各 join 带超时；False（正常）则无限 join 两个 worker（已发 __done__）。
    公共尾巴：通知 printer 退出并 join。
    """
    if force_terminate:
        stop_event.set()  # 解除解码进程 put 阻塞
        for _, p in workers:
            if p.is_alive():
                p.terminate()
        decode_p.join(timeout=_DECODE_JOIN_TIMEOUT)
        for _, p in workers:
            p.join(timeout=2.0)
    else:
        for _, p in workers:
            p.join()  # 正常退出，无限等待
        stop_event.set()  # 保险：若解码进程仍在，解除其 put 阻塞
        decode_p.join(timeout=_DECODE_JOIN_TIMEOUT)
    stop_printer.set()
    printer_p.join(timeout=1.0)









def _parse_detections_to_note_geometrys(result, frame_number, model_name, coord_scale):
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

        # 坐标从 decode_imgsz 空间还原到 _STD_VIDEO_SIZE 空间
        xyxy = xyxy * coord_scale
        xywh = xywh * coord_scale

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

        # 坐标从 decode_imgsz 空间还原到 _STD_VIDEO_SIZE 空间
        xyxyxyxy = xyxyxyxy * coord_scale
        xywhr[:, :4] = xywhr[:, :4] * coord_scale  # 旋转角 r 不缩放

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
    """
    推理完成后统一执行 prefilter + NMS 后处理。
    """
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

