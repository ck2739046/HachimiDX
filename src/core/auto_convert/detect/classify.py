from ultralytics import YOLO
import cv2
import time
import numpy as np
from collections import defaultdict
from pathlib import Path

from ...schemas.op_result import OpResult, ok, err
from .note_definition import *
from .track import _save_track_results, _load_track_results


def main(std_video_path: Path,
         total_frames: int,
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
    """

    try:
        print("开始分类模块...")

        # 读取追踪结果
        track_results = _load_track_results(std_video_path.parent)

        start_time = time.time()

        cap = cv2.VideoCapture(std_video_path)

        # 构建采样计划，这样后续读取视频时，就知道当前帧要裁剪哪些图像
        sampling_plan, total_cls_quantity = _build_sampling_plan(track_results)
        if not sampling_plan:
            print("没有需要分类的轨迹")
            return None
        
        # 准备变量
        counter = 0
        last_counter = 0
        last_time = start_time

        cls_results_all = []
        images_batch_buffer = []

        cls_ex_model = YOLO(cls_ex_model_path, task="classify")
        cls_break_model = YOLO(cls_break_model_path, task="classify")
        imgsz = get_imgsz('cls')

        crop_border = round(cap.get(cv2.CAP_PROP_FRAME_WIDTH) * 0.003)

        # 按帧读取视频，提取图像并分类
        for frame_number in range(total_frames):
            # 读取当前帧
            ret, frame = cap.read()
            if not ret: break
            # 获取当前帧的采样计划
            if frame_number not in sampling_plan.keys():
                continue # skip
            this_frame_sample_plan = sampling_plan[frame_number]
            # 提取当前帧的所有采样图像
            cropped_images = _extract_note_images_in_frame(imgsz, frame, this_frame_sample_plan, frame_number, crop_border)
            if cropped_images is None:
                continue
            # 写入batch
            images_batch_buffer.extend(cropped_images)

            # 如果凑满一个batch，就进行分类
            while len(images_batch_buffer) >= batch_cls:
                # 从buffer中取出一个batch
                consumed_batch = images_batch_buffer[:batch_cls]
                images_batch_buffer = images_batch_buffer[batch_cls:]
                # 分类
                cls_results = _classify_image_batch(consumed_batch,
                                                    cls_ex_model, cls_break_model,
                                                    inference_device, imgsz)
                cls_results_all.extend(cls_results)
                # 打印进度
                counter += len(cls_results)
                last_time, last_counter = print_progress('分类', ' images/s', counter, total_cls_quantity, last_time, last_counter)

            # end of frame loop


        # 视频读取完毕后，batch buffer可能有剩余的未分类图像
        if images_batch_buffer:
            cls_results = _classify_image_batch(images_batch_buffer,
                                                cls_ex_model, cls_break_model,
                                                inference_device, imgsz)
            cls_results_all.extend(cls_results)

        # 根据分类结果，更新track_results
        track_results = _merge_cls_into_track_results(track_results, cls_results_all)

        # 结束
        finish_time = time.time()
        print(f"分类模块完成, 耗时{finish_time - start_time:.1f}s                       ")
        
        # 保存到文件
        _save_track_results(track_results, std_video_path.parent, call_fn="classify")
        return ok()
        
    except Exception as e:
        return err("Unexcepted error in auto_convert > detect > classify", e)
    
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
        # 对于普通矩形框，裁剪范围就是(x1, y1, x3, y3)
        if not is_obb(note_geometry.note_type):
            x1, y1, x2, y2 = note_geometry.x1, note_geometry.y1, note_geometry.x3, note_geometry.y3
            target_frame = frame
        else:
            # obb需要先将检测框和图像旋转为水平
            points = np.array([
                [note_geometry.x1, note_geometry.y1],
                [note_geometry.x2, note_geometry.y2],
                [note_geometry.x3, note_geometry.y3],
                [note_geometry.x4, note_geometry.y4]
            ], dtype=np.float32)
            angle = (note_geometry.r * 180 / np.pi) - 90
            rotation_matrix = cv2.getRotationMatrix2D((note_geometry.cx, note_geometry.cy), angle, 1.0)
            target_frame = cv2.warpAffine(frame, rotation_matrix, (frame.shape[1], frame.shape[0]))
            rotated_points = cv2.transform(points.reshape(1, -1, 2), rotation_matrix).reshape(-1, 2)
            x_coords = rotated_points[:, 0]
            y_coords = rotated_points[:, 1]
            x1, y1 = np.min(x_coords), np.min(y_coords)
            x2, y2 = np.max(x_coords), np.max(y_coords)

        # 稍微扩展一圈
        x1 -= crop_border
        y1 -= crop_border
        x2 += crop_border
        y2 += crop_border
        x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)
        x1 = max(0, x1)
        y1 = max(0, y1)
        x2 = min(target_frame.shape[1], x2)
        y2 = min(target_frame.shape[0], y2)
        if x1 >= x2 or y1 >= y2:
            return None
        cropped_image = target_frame[y1:y2, x1:x2]
        cropped_image = cv2.resize(cropped_image, (imgsz, imgsz))
        return cropped_image
    except Exception as e:
        print(f"裁剪音符图像时出错: {e}")
        return None



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
    crop_border = round(cap.get(cv2.CAP_PROP_FRAME_WIDTH) * 0.003)

    cls_results_all = []
    images_batch_buffer = []

    # 按帧遍历
    last_frame_number = -1
    sorted_frames = sorted(sampling_plan.keys())
    for frame_number in sorted_frames:
        # 速度优化，如果是连续帧，跳过 seek
        if frame_number - last_frame_number != 1:
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
        # 读取当前帧
        ret, frame = cap.read()
        if not ret: continue
        last_frame_number = frame_number

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
