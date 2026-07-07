from ultralytics import YOLO
import cv2
import time
import math
import threading
import queue
from collections import defaultdict
from pathlib import Path

from ...schemas.op_result import OpResult, ok, err
from .note_definition import *
from .track import _save_track_results, _load_track_results


SEEK_THRESHOLD = 200



def main(std_video_path: Path,
         batch_cls: int,
         inference_device: str,
         cls_ex_model_path: str,
         cls_break_model_path: str
        ) -> OpResult[None]:
    
    """
    输入:
    - std_video_path
    - batch_cls: yolo predict batch size
    - inference_device
    - cls_ex_model_path
    - cls_break_model_path

    架构: 生产者-消费者流水线
    - 生产者线程负责视频解码 + 图像裁剪
    - 消费者主线程负责 GPU 推理
    - 通过 queue.Queue(maxsize=2) 双缓冲实现 CPU/GPU 重叠执行
    """

    try:
        print("开始分类模块...")

        # 读取追踪结果
        track_results = _load_track_results(std_video_path.parent)

        start_time = time.time()

        # 构建采样计划，这样后续读取视频时，就知道当前帧要裁剪哪些图像
        sampling_plan, total_cls_quantity = _build_sampling_plan(track_results)
        if not sampling_plan:
            print("没有需要分类的轨迹")
            return ok()

        # 加载模型
        cls_ex_model = YOLO(cls_ex_model_path, task="classify")
        cls_break_model = YOLO(cls_break_model_path, task="classify")
        imgsz = get_imgsz('cls')

        # 创建双缓冲队列，启动生产者线程
        batch_queue = queue.Queue(maxsize=2)
        producer_thread = threading.Thread(
            target=_producer,
            args=(std_video_path, sampling_plan, imgsz, batch_cls, batch_queue),
            daemon=True
        )
        producer_thread.start()

        # 消费者循环：从队列取 batch，GPU 推理
        counter = 0
        last_counter = 0
        last_time = start_time
        cls_results_all = []

        while True:
            consumed_batch = batch_queue.get()
            if consumed_batch is None:
                break  # producer 结束

            cls_results = _classify_image_batch(consumed_batch,
                                                cls_ex_model, cls_break_model,
                                                inference_device, imgsz)
            if cls_results:
                cls_results_all.extend(cls_results)
                counter += len(cls_results)
                last_time, last_counter = print_progress('分类', ' images/s', counter, total_cls_quantity, last_time, last_counter)

        # producer 线程应该已经自行退出（daemon）
        # 此处防御性 join 兜底
        producer_thread.join(timeout=1.0)

        # 根据分类结果，更新track_results
        track_results = _merge_cls_into_track_results(track_results, cls_results_all)

        # 结束
        finish_time = time.time()
        print(f"分类模块完成, 耗时{finish_time - start_time:.1f}s                       ")

        # 保存到文件
        _save_track_results(track_results, std_video_path.parent, call_fn="classify")
        return ok()

    except Exception as e:
        return err("Unexcepted error in auto_rechart > detect > classify", e)
    







def _producer(std_video_path, sampling_plan,
              imgsz, batch_cls, batch_queue):
    """
    生产者线程：解码视频 + 裁剪音符图像，凑满一个 batch 就放入队列。
    结束后发送 None 作为 sentinel。
    """
    cap = cv2.VideoCapture(std_video_path)
    crop_border = round(cap.get(cv2.CAP_PROP_FRAME_WIDTH) * 0.005)  # 1080p下约5像素
    try:
        buffer = []
        sorted_frames_in_sampling_plan = sorted(sampling_plan.keys())
        last_frame_number = -1

        for frame_number in sorted_frames_in_sampling_plan:

            # 速度优化
            # cap.read() 读取下一帧 比 cap.set() 跳转到指定帧 更快
            # 如果目标帧和当前帧差距不大, 循环推进到目标帧以减少 seek 调用
            gap = frame_number - last_frame_number
            # 如果目标帧就是下一帧，直接读取
            if gap == 1:
                pass
            # 如果目标帧不远，循环 grab 跳过中间帧
            elif gap <= SEEK_THRESHOLD:
                for _ in range(gap - 1):
                    cap.grab()
            # 如果目标帧较远，使用 seek 跳转
            else:
                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)

            # 读取当前帧
            ret, frame = cap.read()
            if not ret: continue
            last_frame_number = frame_number

            # 获取当前帧的采样计划
            this_frame_sample_plan = sampling_plan[frame_number]
            # 提取当前帧的所有采样图像
            cropped_images = _extract_note_images_in_frame(imgsz, frame, this_frame_sample_plan, frame_number, crop_border)
            if cropped_images is None:
                continue
            # 写入本地 buffer
            buffer.extend(cropped_images)

            # 凑满一个 batch 就发送到队列
            while len(buffer) >= batch_cls:
                batch_queue.put(buffer[:batch_cls])
                buffer = buffer[batch_cls:]

        # 发送剩余的图像
        if buffer:
            batch_queue.put(buffer)

        # 发送结束信号
        batch_queue.put(None)

    finally:
        cap.release()








def _build_sampling_plan(track_results):
    """
    返回dict: frame_number -> list of dict
    inner_dict: track_id, sample_position, note_geometry
    """

    sampling_plan = defaultdict(list)
    counter = 0
    
    for key, value in track_results.items():
        track_id, note_type = key
        note_geometry_list = value
        
        # 跳过不需要分类的音符
        if len(note_geometry_list) <= 0: continue
        if not need_cls(note_type): continue

        # 从一个音符的轨迹中选取采样点
        path_length = len(note_geometry_list)
        if note_type == NoteType.HOLD:
            # 尽量选择早期的点，避免在后续长条hold时被闪烁特效干扰
            # 间距不同，防止周期性闪烁全部采样到同一位置
            sample_positions = [10, 13, 24, 29, 37]
        else:
            sample_positions = [20, 31, 50, 65, 77]

        for sample_position in sample_positions:
            sample_idx = int(path_length * sample_position / 100.0)
            if sample_idx >= path_length:
                continue
            # 获取采样点信息
            note = note_geometry_list[sample_idx]
            frame_number = note.frame
            # 写入采样计划
            sampling_plan[frame_number].append({
                'track_id': track_id,
                'sample_position': sample_position,
                'note_geometry': note,
            })
            counter += 1
    
    return sampling_plan, counter



def _crop_single_note_image(imgsz, frame, note_geometry, crop_border):
    
    """
    从视频帧中裁剪单个音符图像。
    
    输入:
        imgsz: 目标图像尺寸
        frame: 视频帧 (numpy array)
        note_geometry: Note_Geometry 对象
        crop_border: 裁剪边界扩展像素数
    
    返回:
        cropped_image: 裁剪并resize后的图像 (numpy array)
        或 None (裁剪失败)
    """
    
    try:
        if not is_obb(note_geometry.note_type):
            # 对于普通矩形框，裁剪范围就是(x1, y1, x3, y3)
            x1, y1, x2, y2 = note_geometry.x1, note_geometry.y1, note_geometry.x3, note_geometry.y3
            
            # 稍微扩展一圈
            x1 -= crop_border
            y1 -= crop_border
            x2 += crop_border
            y2 += crop_border

            # clamp到帧边界
            x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)
            x1 = max(0, x1)
            y1 = max(0, y1)
            x2 = min(frame.shape[1], x2)
            y2 = min(frame.shape[0], y2)
            if x1 >= x2 or y1 >= y2:
                return None
            
            # 裁剪并resize
            cropped_image = frame[y1:y2, x1:x2]
            cropped_image = cv2.resize(cropped_image, (imgsz, imgsz))
            return cropped_image
        
        else:
            # OBB: 精确裁剪后再旋转（避免对全帧 warpAffine）
            r = note_geometry.r
            w = note_geometry.w
            h = note_geometry.h

            # 1. 用 sin/cos 计算旋转矩形在原始帧中的精确 AABB
            sin_r = math.sin(r)
            cos_r = math.cos(r)
            half_ext_w = abs(w / 2 * cos_r) + abs(h / 2 * sin_r)
            half_ext_h = abs(w / 2 * sin_r) + abs(h / 2 * cos_r)

            aabb_x1 = note_geometry.cx - half_ext_w
            aabb_y1 = note_geometry.cy - half_ext_h
            aabb_x2 = note_geometry.cx + half_ext_w
            aabb_y2 = note_geometry.cy + half_ext_h

            # 2. 计算 ROI 坐标
            #    稍微扩展一圈 + clamp到帧边界
            roi_x1 = max(0, int(aabb_x1 - crop_border))
            roi_y1 = max(0, int(aabb_y1 - crop_border))
            roi_x2 = min(frame.shape[1], int(aabb_x2 + crop_border))
            roi_y2 = min(frame.shape[0], int(aabb_y2 + crop_border))

            if roi_x1 >= roi_x2 or roi_y1 >= roi_y2:
                return None

            # 3. 从原帧裁剪 ROI
            roi = frame[roi_y1:roi_y2, roi_x1:roi_x2]

            # 4. 旋转中心在 ROI 空间中的偏移
            roi_cx = note_geometry.cx - roi_x1
            roi_cy = note_geometry.cy - roi_y1

            # 5. 对 ROI 做逆旋转，使得 OBB 变为水平矩形
            angle_deg = r * 180 / math.pi
            rotation_matrix = cv2.getRotationMatrix2D((roi_cx, roi_cy), angle_deg, 1.0)
            target_frame = cv2.warpAffine(roi, rotation_matrix, (roi.shape[1], roi.shape[0]))

            # 6. 从 warp 后的 ROI 中提取有效内容区域
            content_x1 = max(0, roi_cx - w / 2)
            content_y1 = max(0, roi_cy - h / 2)
            content_x2 = min(target_frame.shape[1], roi_cx + w / 2)
            content_y2 = min(target_frame.shape[0], roi_cy + h / 2)

            content_x1 = int(content_x1); content_y1 = int(content_y1)
            content_x2 = int(content_x2); content_y2 = int(content_y2)

            if content_x1 >= content_x2 or content_y1 >= content_y2:
                return None
            
            # 7. 裁剪并resize
            cropped_image = target_frame[content_y1:content_y2, content_x1:content_x2]
            cropped_image = cv2.resize(cropped_image, (imgsz, imgsz))

            # 8. 若原始 OBB 是横着的 (w > h)，旋转 90° 使其竖过来
            #    因为 cls 训练时所有 hold 都是竖着的
            if w > h:
                cropped_image = cv2.rotate(cropped_image, cv2.ROTATE_90_CLOCKWISE)

            # _save_obb_debug_image(cropped_image) # debug

            return cropped_image
        
    except Exception as e:
        print(f"裁剪音符图像时出错: {e}")
        return None


_obb_debug_counter = 0
_obb_debug_folder_name = time.strftime("%Y%m%d_%H%M%S")

def _save_obb_debug_image(image):
    """DEBUG: 将 OBB 裁剪结果保存到硬盘"""
    global _obb_debug_counter
    try:
        folder = Path(f"C:/Users/ck273/Desktop/test/{_obb_debug_folder_name}")
        folder.mkdir(parents=True, exist_ok=True)
        filepath = folder / f"{_obb_debug_counter}.png"
        cv2.imwrite(str(filepath), image)
        _obb_debug_counter += 1
    except Exception:
        pass  # 静默失败，不影响主流程



def _extract_note_images_in_frame(imgsz, frame, this_frame_sample_plan, frame_number, crop_border):
    
    """
    根据 sample_plan 裁剪出一帧内的所有音符的图像
    返回 list of dict: frame, track_id, sample_position, note_type, cropped_image
    """
    
    try:
        cropped_images = []

        for sample_data in this_frame_sample_plan:

            track_id = sample_data['track_id']
            sample_position = sample_data['sample_position']
            note = sample_data['note_geometry']

            cropped_image = _crop_single_note_image(imgsz, frame, note, crop_border)
            if cropped_image is None:
                continue

            cropped_data = {
                'frame': frame_number,
                'track_id': track_id,
                'sample_position': sample_position,
                'note_type': note.note_type,
                'cropped_image': cropped_image
            }
            cropped_images.append(cropped_data)

        return cropped_images

    except Exception as e:
        print(f"提取第{frame_number}帧的图像时出错: {e}")
        return None
    


def _classify_image_batch(consumed_batch, cls_ex_model, cls_break_model, inference_device, imgsz):

    """
    调用yolo分类模型，推理传入的音符图片
    返回 list of dict: track_id, is_ex, is_break, frame, sample_position, note_type
    """

    try:
        # extract images and info
        images = [item['cropped_image'] for item in consumed_batch]
        images_info = [(item['frame'], item['track_id'], item['sample_position'], item['note_type']) for item in consumed_batch]

        # 模型推理
        ex_results = cls_ex_model.predict(
            task='classify',
            source=images,
            conf=0.5,
            verbose=False,
            device=inference_device,
            imgsz=imgsz,
            half=True
        )
        break_results = cls_break_model.predict(
            task='classify',
            source=images,
            conf=0.5,
            verbose=False,
            device=inference_device,
            imgsz=imgsz,
            half=True
        )

        # 解析yolo结果
        ex_flags = []
        for res in ex_results:
            is_ex = False
            if hasattr(res, 'probs') and res.probs is not None:
                ex_probs = res.probs.data.cpu().numpy()
                if len(ex_probs) >= 2: # 第一个是"no"，第二个是"yes"
                    is_ex = ex_probs[1] > ex_probs[0]
            ex_flags.append(bool(is_ex))

        break_flags = []
        for res in break_results:
            is_break = False
            if hasattr(res, 'probs') and res.probs is not None:
                break_probs = res.probs.data.cpu().numpy()
                if len(break_probs) >= 2: # 第一个是"no"，第二个是"yes"
                    is_break = break_probs[1] > break_probs[0]
            break_flags.append(bool(is_break))

        # reformat results
        final_cls_results = []
        for i, (frame_number, track_id, sample_position, note_type) in enumerate(images_info):
            data = {
                'track_id': track_id,
                'is_ex': ex_flags[i],
                'is_break': break_flags[i],
                'frame': frame_number,
                'sample_position': sample_position,
                'note_type': note_type
            }
            final_cls_results.append(data)

        return final_cls_results

    except Exception as e:
        print(f"批量分类错误: {e}")
        return None



def _merge_cls_into_track_results(track_results, cls_results_all):

    # 根据分类结果 is_ex, is_break 计算 note_variant，按 track_id 分组
    note_variant_by_track = defaultdict(list)
    for cls_result in cls_results_all:
        track_id = cls_result['track_id']
        is_ex = cls_result['is_ex']
        is_break = cls_result['is_break']
        note_type = cls_result['note_type']
        
        if is_break and is_ex:
            note_variant = NoteVariant.BREAK_EX
        elif is_ex and not is_break:
            note_variant = NoteVariant.EX
        elif not is_ex and is_break:
            note_variant = NoteVariant.BREAK
        else:
            note_variant = NoteVariant.NORMAL
        
        note_variant_by_track[track_id].append((note_variant, note_type))
    
    # 每个音符有多个候选点和分类结果，采用最多的类别作为最终结果
    for track_id, value in note_variant_by_track.items():
        note_variants = [v[0] for v in value]
        note_type = value[0][1] # 同一轨迹的note_type是一样的，取第一个就行了
        if len(note_variants) == 0:
            continue
        
        # 统计每个note_variant的出现次数
        counts = {}
        for note_variant in note_variants:
            counts[note_variant] = counts.get(note_variant, 0) + 1
        
        max_count = max(counts.values())
        most_common = [k for k, v in counts.items() if v == max_count]
        
        if len(most_common) == 1:
            # 有明确的一个最多数
            final_note_variant = most_common[0]
        else:
            # 没有明确的多数，默认 normal
            final_note_variant = NoteVariant.NORMAL
            print(f"警告: 轨迹 {track_id} 的采样点分类结果不一致，采用默认分类 {final_note_variant.name}")

        # 更新track_results的note_variant
        key = (track_id, note_type)
        if key not in track_results:
            continue
        note_geometry_list = track_results[key]
        for note_geometry in note_geometry_list:
            note_geometry.note_variant = final_note_variant

    return track_results




 # 此函数仅供外部调用
def classify_note_path(
    path_to_classify: list[Note_Geometry],
    std_video_path: Path,
    cls_ex_model, cls_break_model,
    inference_device: str, batch_cls: int,
) -> NoteVariant | None:
    """
    对单个音符路径进行分类，返回路径的 NoteVariant。

    输入:
        path_to_classify: list of Note_Geometry — 单个音符路径的所有检测框
        std_video_path: 标准视频路径
        cls_ex_model: YOLO EX 分类模型
        cls_break_model: YOLO BREAK 分类模型
        inference_device: 推理设备
        batch_cls: batch size

    返回:
        NoteVariant (或 None，若分类失败)
    """
    if not path_to_classify:
        return None

    imgsz = get_imgsz('cls')

    # 构建采样计划
    sampling_plan = defaultdict(list)
    path_length = len(path_to_classify)
    sample_positions = [20, 31, 50, 65, 77]
    for sp_idx, sample_position in enumerate(sample_positions):
        sample_idx = int(path_length * sample_position / 100.0)
        if sample_idx >= path_length:
            continue
        note = path_to_classify[sample_idx]
        sampling_plan[note.frame].append({
            'sample_position': sample_position,
            'note_geometry': note,
        })

    if not sampling_plan:
        return None

    # 打开视频
    cap = cv2.VideoCapture(str(std_video_path))
    crop_border = round(cap.get(cv2.CAP_PROP_FRAME_WIDTH) * 0.005)

    cls_results_all = []
    images_batch_buffer = []

    last_frame_number = -1
    sorted_frames = sorted(sampling_plan.keys())

    for frame_number in sorted_frames:

        # 速度优化
        # cap.read() 读取下一帧 比 cap.set() 跳转到指定帧 更快
        # 如果目标帧和当前帧差距不大, 循环推进到目标帧以减少 seek 调用
        gap = frame_number - last_frame_number
        # 如果目标帧就是下一帧，直接读取
        if gap == 1:
            pass
        # 如果目标帧不远，循环 grab 跳过中间帧
        elif gap <= SEEK_THRESHOLD:
            for _ in range(gap - 1):
                cap.grab()
        # 如果目标帧较远，使用 seek 跳转
        else:
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
        
        # 读取当前帧
        ret, frame = cap.read()
        if not ret: continue
        last_frame_number = frame_number

        # 根据采样计划裁剪图像并写入 batch
        for sample_data in sampling_plan[frame_number]:
            note = sample_data['note_geometry']
            cropped = _crop_single_note_image(imgsz, frame, note, crop_border)
            if cropped is None:
                continue
            images_batch_buffer.append({
                'track_id': 0,
                'frame': frame_number,
                'sample_position': sample_data['sample_position'],
                'note_type': note.note_type,
                'cropped_image': cropped,
            })

            while len(images_batch_buffer) >= batch_cls:
                consumed = images_batch_buffer[:batch_cls]
                images_batch_buffer = images_batch_buffer[batch_cls:]
                batch_results = _classify_image_batch(
                    consumed, cls_ex_model, cls_break_model, inference_device, imgsz
                )
                if batch_results:
                    cls_results_all.extend(batch_results)

    # 处理剩余 buffer
    if images_batch_buffer:
        batch_results = _classify_image_batch(
            images_batch_buffer, cls_ex_model, cls_break_model, inference_device, imgsz
        )
        if batch_results:
            cls_results_all.extend(batch_results)

    cap.release()

    if not cls_results_all:
        return None

    # 投票决定 variant
    variant_counts = defaultdict(int)
    for result in cls_results_all:
        is_ex = result['is_ex']
        is_break = result['is_break']

        if is_break and is_ex:
            variant = NoteVariant.BREAK_EX
        elif is_ex and not is_break:
            variant = NoteVariant.EX
        elif not is_ex and is_break:
            variant = NoteVariant.BREAK
        else:
            variant = NoteVariant.NORMAL

        variant_counts[variant] += 1

    # 取多数
    if not variant_counts:
        return None

    max_count = max(variant_counts.values())
    most_common = [k for k, v in variant_counts.items() if v == max_count]
    if len(most_common) == 1:
        return most_common[0]
    else:
        print(f"警告: 路径分类结果不一致，采用默认分类 NORMAL")
        return NoteVariant.NORMAL
