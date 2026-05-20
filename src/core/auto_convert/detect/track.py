from ultralytics.trackers import BOTSORT
import os
import cv2
import time
import numpy as np
from collections import defaultdict
from types import SimpleNamespace
from ultralytics.engine.results import OBB
from pathlib import Path

from ...schemas.op_result import OpResult, ok, err
from ....services.path_manage import PathManage
from .note_definition import *
from .detect import _load_detect_results
from .oc_sort import OCSort


TRACKER_NOTE_TYPES = [
    NoteType.TAP,
    NoteType.SLIDE,
    NoteType.TOUCH,
    NoteType.HOLD,
    NoteType.TOUCH_HOLD,
]



def _build_botsort_tracker(fps: float, with_reid: bool = False) -> BOTSORT:
    tracker_args = SimpleNamespace(
        tracker_type='botsort',

        # 优先匹配的 conf 阈值
        # 置信度大于此值的检测框，会被用于匹配轨迹
        track_high_thresh=0.5,

        # 如果 low_thresh < conf < high_thresh 也会被匹配，但是优先级更低
        # 置信度大于此值的检测框，会被用于匹配轨迹
        track_low_thresh=0.25,

        # 如果一个框无法匹配，且其置信度 ≥ 此值，会被创建为新轨迹
        # 值越高，越不容易视为新 id
        new_track_thresh=0.5,

        # 当一个轨迹在连续若干帧未匹配到检测框时，不会立即删除，而是保留最多 track_buffer 帧
        # 值越高，越不容易视为新 id
        # real buffer frames = fps / 30 * track_buffer
        # 由于传入了视频 fps，此处固定等于 x/30 秒
        track_buffer=2, # 1/15s

        # 计算: 阈值 = 1-IOU
        # 值越高，越宽松，允许较大位移 (低iou) 也匹配上，越不容易视为新 id
        # 值越低, 越严格，仅允许较小位移 (高iou) 匹配上, 可能会被视为新 id
        match_thresh=0.8, # 默认

        # 融合阈值，默认开启
        fuse_score=True,

        # 画面稳定，不需要 gmc 全局运动补偿
        gmc_method='none',

        # 是否启用 ReID
        with_reid=with_reid,
        model=str(PathManage.REID_PT_PATH) if with_reid else 'HachimiDX',
        # 开启 reid 的最小 iou 阈值
        # 只有两个框的 iou ≥ proximity_thresh 时，才会启用 reid 特征进行匹配
        # 值越高，越不容易启用 reid
        # 值越低，越容易启用 reid，越不容易视为新 id
        proximity_thresh=0.4 if with_reid else 273,
        # 外观相似度
        # 值越低，外观就不需要那么相似也能匹配上，越不容易视为新 id
        appearance_thresh=0.8 if with_reid else 478,
    )
    return BOTSORT(tracker_args, frame_rate=fps)


def _build_ocsort_tracker(fps: float) -> OCSort:

    # 仅用于 SLIDE；参数按 OC-SORT 原生语义硬编码
    return OCSort(

        # 置信度低于此值的候选框会被丢弃
        det_thresh=0.5,

        # 轨迹在 x 帧没有新的匹配时被删除
        max_age=max(2, round(fps * 0.05)),   # 0.05s, at least 2

        # 轨迹至少需要 x 个匹配到的点才被保留
        min_hits=max(2, round(fps * 0.05)),  # 0.05s, at least 2

        # 候选框与卡尔曼预测的框的 diou 大于此值时，才会被匹配上
        # 1倍尺寸=0.4, 2倍尺寸=0.3, 3倍=0.235, 4倍=0.192
        iou_threshold=0.35,

        # 用于 vdc 的 angle_diff 计算
        # 向量 A (轨迹速度): ref_obs → 轨迹最新框
        # 向量 B (VDC 方向): ref_obs 的下一帧 → 候选框
        # ref_obs 为历史中首个中心距离 > pct*框尺寸 的观测（找不到时回退到最旧）
        delta_dist_pct=0.7,  # 有效位移阈值 = 70% 框尺寸

        # vdc 的权重
        # vdc = angle_diff * inertia * score(置信度)
        inertia=0.7,

        # DIoU 高于此值时禁用 VDC
        # 因为框已经够重合了，有时候 vdc 反而会误导
        # 尤其是 slide_head 刚出现时容易被 vdc 弄成 id switch
        vdc_disable_diou_thresh=0.85,

        # 尺寸变大门控：候选框 max(w,h) ≤ 轨迹最后一帧 × (1+ratio)
        # 如最后一帧 max=30，ratio=0.15 → 候选框 max 须 ≤ 34.5
        # 值越大越宽松，越小越严格
        max_size_increase_ratio=0.15,

        # 尺寸变小门控：候选框 max(w,h) ≥ 轨迹最后一帧 × (1-ratio)
        # 如最后一帧 max=30，ratio=0.15 → 候选框 max 须 ≥ 25.5
        # 值越大越严格，越小越宽松
        max_size_decrease_ratio=0.15,
    )





def _reverse_track_slide(track_geos, fps, detections_by_frame):
    """反向追踪：将slide轨道反转后重新走OC-SORT，逐帧向前搜索可匹配的 SLIDE 检测框。

    将整个track按帧降序喂入全新的OCSort实例（参数与正向追踪完全一致），重建Kalman运动状态，
    然后从首帧前一帧开始逐帧向前搜索，最多向前添加 max_reverse_frames 个点。
    同个候选框可被多条轨迹同时选中（many-to-one）。

    Args:
        track_geos: 正向追踪的slide轨道 Note_Geometry 列表（帧升序）
        fps: 视频帧率
        detections_by_frame: {frame: [Note_Geometry, ...]} 所有帧的全部检测结果

    Returns:
        匹配到的 Note_Geometry 列表（帧升序，从最早到最晚），可能为空
    """

    # 向前添加的最大帧数/点数
    max_reverse_frames = 1 if fps < 70 else 2

    if not track_geos or max_reverse_frames <= 0:
        return []

    tracker = _build_ocsort_tracker(fps)

    # 按帧降序排列，反向喂入（不填充间隙，避免 max_age 导致 track 被误删）
    sorted_geos = sorted(track_geos, key=lambda x: x.frame, reverse=True)
    for geo in sorted_geos:
        ocsort_input = _convert_detections_to_ocsort_format([geo])
        tracker.update(ocsort_input)

    first_frame = track_geos[0].frame
    matched_geos: list = []  # 帧降序收集

    for offset in range(1, max_reverse_frames + 1):
        check_frame = first_frame - offset
        if check_frame < 0:
            break

        all_dets = detections_by_frame.get(check_frame, [])
        # 候选框必须与当前 track 同类型（仅 SLIDE），避免跨类型误匹配
        # 因为允许多个轨迹选同一个框 (many-to-one)
        # 所以不需要排除已被匹配的框, 直接传入所有
        slide_candidates = [d for d in all_dets if d.note_type == NoteType.SLIDE]
        if not slide_candidates:
            break

        candidate_input = _convert_detections_to_ocsort_format(slide_candidates)
        result = tracker.update(candidate_input)

        if result is None or len(result) == 0:
            break

        # 在当前帧找到匹配的候选框
        found = None
        for row in result:
            if len(row) < 9:
                continue
            frame_offset = int(row[9]) if len(row) >= 10 else 0
            idx = int(row[8])
            if frame_offset == 0 and 0 <= idx < len(slide_candidates):
                found = slide_candidates[idx]
                break

        if found is None:
            break

        matched_geos.append(found)

    # 转为帧升序返回
    matched_geos.reverse()
    return matched_geos



def main(std_video_path: Path,
         total_frames: int,
         enable_reid: bool,
        ) -> OpResult[None]:
    try:
        # 读取检测结果
        detect_results = _load_detect_results(std_video_path.parent)

        # 获取视频信息（保持打开，后续逐帧读取用于 ReID）
        cap = cv2.VideoCapture(std_video_path)
        fps = cap.get(cv2.CAP_PROP_FPS)
        video_size = round(cap.get(cv2.CAP_PROP_FRAME_WIDTH))

        # 初始化5个独立tracker: 每个note_type一个实例
        # slide -> oc-sort
        # other -> bot-sort
        trackers_by_type = {}
        for note_type in TRACKER_NOTE_TYPES:
            if note_type == NoteType.SLIDE:
                trackers_by_type[note_type] = _build_ocsort_tracker(fps)
            elif note_type == NoteType.TAP or note_type == NoteType.HOLD:
                trackers_by_type[note_type] = _build_botsort_tracker(fps, with_reid=enable_reid)
            else:
                trackers_by_type[note_type] = _build_botsort_tracker(fps, with_reid=False)

        # 按帧号重新组织detect_results
        detections_by_frame = defaultdict(list)
        for detection in detect_results:
            detections_by_frame[detection.frame].append(detection)

        # 定义一些变量
        counter = 0
        last_counter = 0
        start_time = time.time()
        last_time = start_time
        # 维护 local tracker id 到全局连续 id 的映射
        local_to_global_id = {}
        next_global_id = [0]
        frame_shape = np.empty((video_size, video_size, 3), dtype=np.uint8)
        # final_tracked_results should be a dict
        # (track_id, note_type) -> list of note_geometry
        final_tracked_results = defaultdict(list)
        # 记录正向追踪中已被匹配的检测框 (用于反向追踪时筛选候选框)
        matched_note_ids = set()

        print("开始追踪模块...")

        # 遍历每一帧
        for frame_number in range(total_frames):

            # 读取当前视频帧（用于 ReID 特征提取）
            frame = None
            if enable_reid:
                ret, frame = cap.read()
                if not ret: frame = None

            # 获取当前帧的检测结果
            single_frame_detections = detections_by_frame.get(frame_number, [])

            # 按note_type分流到各自tracker
            detections_by_note_type = defaultdict(list)
            for note_geometry in single_frame_detections:
                detections_by_note_type[note_geometry.note_type].append(note_geometry)

            for note_type in TRACKER_NOTE_TYPES:
                type_detections = detections_by_note_type.get(note_type, [])
                # 转换为tracker需要的数据格式
                # 就算没有检测框，也要传个空对象给tracker以更新时间
                if note_type == NoteType.SLIDE:
                    tracker_input = _convert_detections_to_ocsort_format(type_detections)
                    track_result = trackers_by_type[note_type].update(tracker_input)
                else:
                    tracker_input = _convert_detections_to_botsort_format(type_detections, frame_shape)
                    track_result = trackers_by_type[note_type].update(tracker_input, img=frame)
                if track_result is None or len(track_result) == 0:
                    continue
                # 解析追踪结果
                parsed_track_results = _parse_track_results(
                    track_result,
                    type_detections,
                    note_type,
                    frame_number,
                    detections_by_frame,
                )
                # 写入最终结果
                for local_track_id, original_note_geometry in parsed_track_results:
                    global_track_id = _get_or_assign_global_track_id(
                        note_type,
                        local_track_id,
                        local_to_global_id,
                        next_global_id,
                    )
                    key = (global_track_id, original_note_geometry.note_type)
                    value = original_note_geometry
                    final_tracked_results[key].append(value)
                    matched_note_ids.add(id(original_note_geometry))
            
            # 打印进度
            counter += 1
            if counter % 200 == 0:
                last_time, last_counter = print_progress('追踪', 'fps', counter, total_frames, last_time, last_counter)   
                        
        # 结束
        if cap and cap.isOpened(): cap.release()
        finish_time = time.time()
        print(f"追踪模块完成, 耗时{finish_time - start_time:.1f}s, 平均{total_frames / (finish_time - start_time):.1f}fps          ")

        # === 反向追踪 slide tracks ===
        # 对每条 slide track 尝试反向追踪
        reverse_count = 0
        for key, track_geos in final_tracked_results.items():
            track_id, note_type = key
            if note_type != NoteType.SLIDE:
                continue

            # 按帧排序（防御性，通常已有序）
            track_geos.sort(key=lambda x: x.frame)

            matched_geos = _reverse_track_slide(track_geos, fps, detections_by_frame)
            if matched_geos:
                # matched_geos 已按帧升序，直接逐个插入 track 开头
                for geo in matched_geos:
                    track_geos.insert(0, geo)
                    matched_note_ids.add(id(geo))
                    reverse_count += 1

        if reverse_count > 0:
            print(f"反向追踪: 补充了 {reverse_count} 个点")

        # 保存到文件
        _save_track_results(final_tracked_results, std_video_path.parent, call_fn="track")
        return ok()

    except Exception as e:
        return err("Unexcepted error in auto_convert > detect > track", e)



def _convert_detections_to_botsort_format(detections, frame_shape):

    # 如果没有检测结果，返回空对象
    if not detections or len(detections) == 0:
        return OBB(np.empty((0, 7), dtype=np.float32), frame_shape)
    
    # 创建空白数据结构
    n = len(detections)
    data = np.zeros((n, 7), dtype=np.float32)

    # 填充数据: xywhr + conf + class_id(note_type to int)
    for i, note_geometry in enumerate(detections):
        cx = note_geometry.cx
        cy = note_geometry.cy
        w = note_geometry.w
        h = note_geometry.h
        r = note_geometry.r
        conf = note_geometry.conf
        class_id = map_note_type_to_class_id(note_geometry.note_type)
        # 填充数据
        data[i] = [cx, cy, w, h, r, conf, class_id]

    # 封装为OBB对象
    return OBB(data, frame_shape)



def _convert_detections_to_ocsort_format(detections):

    # 仅用于 slide：输入为普通 box 框，暂时不考虑 OBB
    if not detections or len(detections) == 0:
        return np.empty((0, 7), dtype=np.float32)

    data = np.zeros((len(detections), 7), dtype=np.float32)
    for i, note_geometry in enumerate(detections):
        data[i] = [
            note_geometry.x1,
            note_geometry.y1,
            note_geometry.x3,
            note_geometry.y3,
            note_geometry.conf,
            float(map_note_type_to_class_id(note_geometry.note_type)),
            float(i),
        ]
    return data



def _parse_track_results(track_result, detections, note_type, frame_number, detections_by_frame):
    parsed_track_results = []

    # 当前帧按 idx 快速回查
    current_idx_to_note = {i: note_geometry for i, note_geometry in enumerate(detections)}

    for result in track_result:
        # 兼容两种输出:
        # 1) 9列: [cx, cy, w, h, r, track_id, score, class_id, idx]
        # 2) 10列: 在末尾增加 frame_offset（head-padding 用）
        if len(result) < 9:
            continue

        track_id = int(result[5])
        idx = int(result[8])
        frame_offset = int(result[9]) if len(result) >= 10 else 0

        if frame_offset == 0:
            if idx in current_idx_to_note:
                parsed_track_results.append((track_id, current_idx_to_note[idx]))
            continue

        # head-padding: 回查历史帧对应 note_type 的检测列表
        src_frame = frame_number + frame_offset
        if src_frame < 0:
            continue

        src_detections = detections_by_frame.get(src_frame, [])
        src_type_detections = [d for d in src_detections if d.note_type == note_type]
        if 0 <= idx < len(src_type_detections):
            parsed_track_results.append((track_id, src_type_detections[idx]))

    return parsed_track_results



def _save_track_results(tracks, output_dir, call_fn=None):

    track_result_path = os.path.join(output_dir, "track_result.txt")
    
    with open(track_result_path, 'w', encoding='utf-8') as f:
        for key, value in tracks.items():
            track_id, note_type = key
            note_geometry_list = sorted(value, key=lambda x: x.frame) # 按帧号排序

            if len(note_geometry_list) > 0:
                # 写入轨迹头
                f.write(f"track_id: {track_id}, note_type: {note_type.value}\n")
                # 写入轨迹路径
                for note in note_geometry_list:
                    data = [
                        f"{note.frame}",
                        f"{note.note_type.value}",
                        f"{note.note_variant.value}",
                        f"{note.conf:.4f}",
                        f"{note.x1:.4f}", f"{note.y1:.4f}",
                        f"{note.x2:.4f}", f"{note.y2:.4f}",
                        f"{note.x3:.4f}", f"{note.y3:.4f}",
                        f"{note.x4:.4f}", f"{note.y4:.4f}",
                        f"{note.cx:.4f}", f"{note.cy:.4f}",
                        f"{note.w:.4f}", f"{note.h:.4f}",
                        f"{note.r:.4f}"
                    ]
                    f.write(', '.join(data) + '\n')

                f.write('\n')  # track_id 之间空行分隔
    
    prefix = f"[{call_fn}]: " if call_fn else ""
    print(f"{prefix}追踪结果已保存到 {track_result_path}")



def _load_track_results(output_dir):

    track_result_path = os.path.join(output_dir, "track_result.txt")
    tracks = defaultdict(list)
    
    with open(track_result_path, 'r', encoding='utf-8') as f:
        current_track_id = -1
        current_note_type = -1
        
        for line in f:
            line = line.strip()
            if not line:
                continue
            
            if line.startswith('track_id:'):
                # 解析轨迹头
                parts = line.split(',')
                if len(parts) == 2:
                    current_track_id = int(parts[0].split(':')[1].strip())
                    current_note_type = NoteType(parts[1].split(':')[1].strip())
                    key = (current_track_id, current_note_type)
                    if key not in tracks:
                        tracks[key] = []
            else:
                # 解析轨迹点数据
                parts = line.split(',')
                if len(parts) == 17:  # 有17个字段
                    point = Note_Geometry(
                        frame=int(parts[0].strip()),
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
                    tracks[(current_track_id, current_note_type)].append(point)
    
    return tracks



def _get_or_assign_global_track_id(note_type, local_track_id, id_mapping, next_id_holder):
    """将 (note_type, local_track_id) 映射为全局连续 ID"""
    key = (note_type, int(local_track_id))
    if key not in id_mapping:
        id_mapping[key] = next_id_holder[0]
        next_id_holder[0] += 1
    return id_mapping[key]
