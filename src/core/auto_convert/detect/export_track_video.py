import os
import cv2
import time
import math
import numpy as np
from collections import defaultdict
import subprocess
from pathlib import Path

from ...schemas.op_result import OpResult, ok, err
from .note_definition import *
from .track import _load_track_results
from ..analyze.tool import catmull_rom_spline
from .oc_sort import _KalmanBoxTracker




def main(std_video_path: Path,
     total_frames: int,
    ) -> OpResult[Path]:

    print("开始导出视频模块...")
    cap = None
    ffmpeg_process = None
    
    try:
        # 读取追踪结果
        track_results = _load_track_results(std_video_path.parent)

        # === Kalman 预测预计算：对每条 SLIDE 轨迹逐帧重跑 Kalman 滤波器 ===
        # kalman_predictions: frame -> [{track_id, note_variant, x1,y1,x2,y2}, ...]
        kalman_predictions: dict[int, list[dict]] = defaultdict(list)
        for (track_id, note_type), geo_list in track_results.items():
            if note_type != NoteType.SLIDE:
                continue
            if len(geo_list) == 0:
                continue
            geo_list_sorted = sorted(geo_list, key=lambda g: g.frame)
            frame_to_geo = {g.frame: g for g in geo_list_sorted}
            first_f = geo_list_sorted[0].frame
            last_f = geo_list_sorted[-1].frame
            note_variant = geo_list_sorted[0].note_variant
            first_geo = geo_list_sorted[0]
            init_bbox = np.array([
                first_geo.x1, first_geo.y1,
                first_geo.x3, first_geo.y3,
                first_geo.conf,
                float(map_note_type_to_class_id(note_type)),
                0.0,
            ], dtype=np.float64)
            tracker = _KalmanBoxTracker(init_bbox)
            # 首帧：predict 后写入预测结果，若有检测框则 update
            pred = tracker.predict()[0]
            kalman_predictions[first_f].append({
                'track_id': track_id,
                'note_variant': note_variant,
                'x1': float(pred[0]), 'y1': float(pred[1]),
                'x2': float(pred[2]), 'y2': float(pred[3]),
            })
            tracker.update(init_bbox)
            for f in range(first_f + 1, last_f + 1):
                pred = tracker.predict()[0]
                kalman_predictions[f].append({
                    'track_id': track_id,
                    'note_variant': note_variant,
                    'x1': float(pred[0]), 'y1': float(pred[1]),
                    'x2': float(pred[2]), 'y2': float(pred[3]),
                })
                geo = frame_to_geo.get(f)
                if geo is not None:
                    obs = np.array([
                        geo.x1, geo.y1,
                        geo.x3, geo.y3,
                        geo.conf,
                        float(map_note_type_to_class_id(note_type)),
                        0.0,
                    ], dtype=np.float64)
                    tracker.update(obs)
                else:
                    tracker.update(None)

        # 获取视频信息
        cap = cv2.VideoCapture(std_video_path)
        video_width = round(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        video_height = round(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS)
        
        # 输出视频设置
        output_dir = std_video_path.parent
        video_name = output_dir.name
        final_track_video_path = os.path.join(output_dir, f'{video_name}_tracked.mp4')
        if os.path.exists(final_track_video_path):
            os.remove(final_track_video_path)

        # 为不同ID生成不同颜色
        def get_color_for_id(track_id):
            color_palette = [
                (0, 0, 190),   # RED
                (190, 0, 0),   # BLUE
                (0, 170, 0),   # GREEN
                (0, 100, 200), # ORANGE
                (200, 0, 150), # PURPLE
                (180, 130, 0), # TEAL
                (160, 0, 210), # MAGENTA
                (0, 150, 160), # OLIVE
                (40, 80, 160)  # SIENNA
            ]
            # 使用track_id对颜色池长度取模来选择颜色
            color_index = track_id % len(color_palette)
            return color_palette[color_index]
        
        # 按帧号组织轨迹点
        frame_tracks = defaultdict(list)
        for key, value in track_results.items():
            track_id, note_type = key
            note_geometry_list = value
            if len(note_geometry_list) <= 0: continue
            for note in note_geometry_list:
                frame_tracks[note.frame].append({
                    'track_id': track_id,
                    'note_type': note_type,
                    'note_variant': note.note_variant,
                    'x1': note.x1,
                    'y1': note.y1,
                    'x2': note.x2,
                    'y2': note.y2,
                    'x3': note.x3,
                    'y3': note.y3,
                    'x4': note.x4,
                    'y4': note.y4
                })
        
        # 存储轨迹历史用于绘制轨迹线
        track_history = defaultdict(list)
        track_last_seen = defaultdict(int)  # 记录轨迹最后出现的帧号
        track_note_type: dict[int, NoteType] = {}  # 记录轨迹对应的音符类型，用于区分 SLIDE 样条绘制
        label_size_cache: dict[str, tuple[int, int]] = {}

        # 轨迹清理和绘制长度使用同一套 fps 计算，避免长视频后期轨迹过长拖慢绘制
        fps_for_calc = float(fps) if fps and fps > 0 else 30.0
        timeout_frames = max(1, int(round(fps_for_calc / 2.0)))
        max_track_history_len = min(512, max(64, timeout_frames * 4))

        # 使用 FFmpeg 管道直接编码视频并映射原视频音频，避免临时文件二次编码
        from src.services import PathManage
        ffmpeg_exe = str(PathManage.FFMPEG_EXE_PATH)
        ffmpeg_cmd = [
            ffmpeg_exe,
            '-y', '-hide_banner', '-loglevel', 'error',
            '-f', 'rawvideo',
            '-pix_fmt', 'bgr24',
            '-s', f'{video_width}x{video_height}',
            '-r', str(fps_for_calc),
            '-i', '-',
            '-i', str(std_video_path),
            '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23', '-pix_fmt', 'yuv420p',
            '-c:a', 'aac', '-b:a', '192k',
            '-map', '0:v:0',
            '-map', '1:a:0?',
            '-shortest',
            final_track_video_path,
        ]
        print("Running FFmpeg command:", " ".join(ffmpeg_cmd))

        ffmpeg_process = subprocess.Popen(
            ffmpeg_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        if ffmpeg_process.stdin is None:
            raise Exception("FFmpeg stdin pipe is unavailable")
        
        # 逐帧处理
        start_time = time.time()
        last_start_time = start_time
        last_frame_number = 0
        
        for frame_number in range(total_frames):
            ret, frame = cap.read()
            if not ret:
                break
            
            # 获取当前帧的轨迹点
            current_tracks = frame_tracks.get(frame_number, [])
            
            # 更新当前帧中存在的轨迹
            current_track_ids = set()

            # --- SLIDE 候选框 many-to-one 去重 ---
            # 同帧内坐标完全一致的 SLIDE 框合并为一个绘制单元，
            # 用 "/" 连接多个 track_id 显示。
            _box_key_precision = 2 # 如果坐标精确到2位小数相同，视为同一个框

            def _slide_box_key(t):
                """用全部 8 个坐标值生成去重键。"""
                return (
                    round(t['x1'], _box_key_precision), round(t['y1'], _box_key_precision),
                    round(t['x2'], _box_key_precision), round(t['y2'], _box_key_precision),
                    round(t['x3'], _box_key_precision), round(t['y3'], _box_key_precision),
                    round(t['x4'], _box_key_precision), round(t['y4'], _box_key_precision),
                )

            slide_tracks = [t for t in current_tracks if t['note_type'] == NoteType.SLIDE]
            other_tracks = [t for t in current_tracks if t['note_type'] != NoteType.SLIDE]

            slide_groups: dict[tuple, list] = {}
            for t in slide_tracks:
                slide_groups.setdefault(_slide_box_key(t), []).append(t)

            dedup_items: list = []
            for group_tracks in slide_groups.values():
                merged_ids = '/'.join(str(t['track_id']) for t in group_tracks)
                rep = dict(group_tracks[0])
                rep['_display_track_id'] = merged_ids
                rep['_group_track_ids'] = [t['track_id'] for t in group_tracks]
                # 使用第一个 track_id 作为颜色代表
                rep['_color_track_id'] = group_tracks[0]['track_id']
                dedup_items.append(rep)

            for t in other_tracks:
                t['_display_track_id'] = str(t['track_id'])
                t['_group_track_ids'] = [t['track_id']]
                t['_color_track_id'] = t['track_id']
                dedup_items.append(t)

            # 绘制当前帧的音符
            for track in dedup_items:
                track_id_display = track['_display_track_id']
                note_type = track['note_type']
                note_variant = track['note_variant']
                is_obb_note = is_obb(note_type)
                color = get_color_for_id(track['_color_track_id'])

                # 记录当前帧中存在的轨迹
                for tid in track['_group_track_ids']:
                    current_track_ids.add(tid)

                # 根据note_type绘制不同类型的音符
                if is_obb_note:
                    points = np.array([
                        [track['x1'], track['y1']],
                        [track['x2'], track['y2']],
                        [track['x3'], track['y3']],
                        [track['x4'], track['y4']]
                    ], dtype=np.int32)
                    cv2.polylines(frame, [points], True, color, 2)
                else:
                    x1, y1, x2, y2 = int(track['x1']), int(track['y1']), int(track['x3']), int(track['y3'])
                    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)

                # 绘制标签（SLIDE 去重后 track_id 用 "/" 连接）
                label = f'{note_type.name}.{note_variant.name} ID:{track_id_display}'
                label_size = label_size_cache.get(label)
                if label_size is None:
                    label_size = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 1)[0]
                    label_size_cache[label] = label_size
                
                if is_obb_note:
                    # 找到OBB四个点中最上方的点作为标签位置；若y相同则选择x最小
                    points = [
                        (int(track['x1']), int(track['y1'])),
                        (int(track['x2']), int(track['y2'])),
                        (int(track['x3']), int(track['y3'])),
                        (int(track['x4']), int(track['y4']))
                    ]
                    label_x, label_y = min(points, key=lambda p: (p[1], p[0])) # 先选y最小，再选x最小
                else:
                    label_x = x1
                    label_y = y1
                
                cv2.rectangle(frame, (label_x, label_y - label_size[1] - 10), 
                            (label_x + label_size[0], label_y), color, -1)
                
                cv2.putText(frame, label, (label_x, label_y - 5), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
                
                # 更新轨迹历史
                # 计算中心点：OBB 使用四点平均，其他类型使用矩形中心
                if is_obb_note:
                    center_x = int(round((track['x1'] + track['x2'] + track['x3'] + track['x4']) / 4.0))
                    center_y = int(round((track['y1'] + track['y2'] + track['y3'] + track['y4']) / 4.0))
                else:
                    center_x = int(round((track['x1'] + track['x3']) / 2.0))
                    center_y = int(round((track['y1'] + track['y3']) / 2.0))

                for tid in track['_group_track_ids']:
                    history_points = track_history[tid]
                    history_points.append((center_x, center_y))
                    track_last_seen[tid] = frame_number
                    track_note_type[tid] = note_type

                    if len(history_points) > max_track_history_len:
                        del history_points[:-max_track_history_len]

            # 绘制 Kalman 预测框（灰色，仅 SLIDE）
            kalman_grey = (160, 160, 160)
            for kp in kalman_predictions.get(frame_number, []):
                if math.isnan(kp['x1']) or math.isnan(kp['y1']):
                    continue
                kp_x1, kp_y1 = int(kp['x1']), int(kp['y1'])
                kp_x2, kp_y2 = int(kp['x2']), int(kp['y2'])
                cv2.rectangle(frame, (kp_x1, kp_y1), (kp_x2, kp_y2), kalman_grey, 1)
                kp_label = f'{NoteType.SLIDE.name}.{kp["note_variant"].name} ID:{kp["track_id"]}'
                kp_label_size = label_size_cache.get(kp_label)
                if kp_label_size is None:
                    kp_label_size = cv2.getTextSize(kp_label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 1)[0]
                    label_size_cache[kp_label] = kp_label_size
                cv2.rectangle(frame, (kp_x1, kp_y1 - kp_label_size[1] - 10),
                            (kp_x1 + kp_label_size[0], kp_y1), kalman_grey, -1)
                cv2.putText(frame, kp_label, (kp_x1, kp_y1 - 5),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
            
            # 清理过期的轨迹（超过0.5秒未出现）
            tracks_to_remove = []
            for track_id in list(track_history.keys()):
                if track_id not in current_track_ids:
                    frames_since_last_seen = frame_number - track_last_seen.get(track_id, frame_number)
                    if frames_since_last_seen > timeout_frames:  # 超过0.5秒未出现，清理轨迹
                        tracks_to_remove.append(track_id)
            
            for track_id in tracks_to_remove:
                if track_id in track_history:
                    del track_history[track_id]
                if track_id in track_last_seen:
                    del track_last_seen[track_id]
                if track_id in track_note_type:
                    del track_note_type[track_id]
            
            # 绘制轨迹线
            for track_id, points in track_history.items():
                if len(points) > 1:
                    color = get_color_for_id(track_id)
                    note_type_for_trail = track_note_type.get(track_id)
                    if note_type_for_trail is NoteType.SLIDE:
                        polyline_points = catmull_rom_spline(points)
                    else:
                        polyline_points = np.array(points, dtype=np.int32).reshape((-1, 1, 2))
                    cv2.polylines(frame, [polyline_points], False, color, 3)
                    
                    # 在轨迹起点绘制小圆点
                    cv2.circle(frame, points[0], 3, color, -1)
            
            # 写入输出视频（FFmpeg stdin rawvideo）
            frame_to_write = frame if frame.flags['C_CONTIGUOUS'] else np.ascontiguousarray(frame)
            ffmpeg_process.stdin.write(frame_to_write.tobytes())
            
            # 显示进度
            if frame_number % 30 == 0:
                progress = (frame_number / total_frames) * 100
                end_time = time.time()
                elapsed_time = end_time - last_start_time
                elapsed_frame = frame_number - last_frame_number
                last_start_time = end_time # 重置时间给下一轮
                last_frame_number = frame_number # 重置帧数给下一轮
                fps_rate = elapsed_frame / elapsed_time if elapsed_time > 0 else 0
                print(f"导出进度: {frame_number}/{total_frames} ({progress:.1f}%) {fps_rate:.1f}fps", end="\r", flush=True)
        
        if ffmpeg_process.stdin is not None:
            ffmpeg_process.stdin.close()

        ffmpeg_return_code = ffmpeg_process.wait()
        ffmpeg_stderr = ""
        if ffmpeg_process.stderr is not None:
            ffmpeg_stderr = ffmpeg_process.stderr.read().decode('utf-8', errors='ignore').strip()
            ffmpeg_process.stderr.close()

        if ffmpeg_return_code != 0:
            raise Exception(f"FFmpeg processing failed with code {ffmpeg_return_code}: {ffmpeg_stderr}")

        cap.release()
        cap = None
        ffmpeg_process = None

        elapsed_time = time.time() - start_time
        average_fps = total_frames / elapsed_time if elapsed_time > 0 else 0
        print(f"追踪视频导出完成，耗时{elapsed_time:.1f}s, 平均{average_fps:.2f}fps               ")
        print(f"追踪视频已保存到：{final_track_video_path}")

        return ok(Path(final_track_video_path))

    except Exception as e:
        if cap is not None:
            try:
                cap.release()
            except Exception:
                pass

        if ffmpeg_process is not None:
            try:
                if ffmpeg_process.stdin is not None:
                    ffmpeg_process.stdin.close()
            except Exception:
                pass

            try:
                if ffmpeg_process.poll() is None:
                    ffmpeg_process.kill()
            except Exception:
                pass

            if ffmpeg_process.stderr is not None:
                try:
                    ffmpeg_process.stderr.close()
                except Exception:
                    pass

        return err("Unexcepted error in auto_convert > detect > export_track_video", e)
