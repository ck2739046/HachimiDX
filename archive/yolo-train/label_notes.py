import os
import cv2
import numpy as np
import shutil
import random
import re
from bisect import bisect_right
from pathlib import Path



# 解决 imread/imwrite 无法正确处理中文路径
def cv_imread(filepath):
    cv_imr = cv2.imdecode(np.fromfile(filepath,dtype=np.uint8),cv2.IMREAD_COLOR)
    return cv_imr

def cv_imwrite(filepath,img):
    parent = Path(filepath).parent
    if not parent.exists():
        parent.mkdir(parents=True, exist_ok=True)
    cv_imw = cv2.imencode('.jpg',img)[1].tofile(filepath)
    return




class Note:
    def __init__(self, frameTime=None, type=None, index=None, posX=None, posY=None, 
                 local_posX=None, local_posY=None, status=None, 
                 appearMsec=None, isEX=None, touchDecor=None, touchAlpha=None, touchHoldProgress=None,
                 tapScale=None, holdScale=None, holdSize=None, starScale=None, starAlpha=None):
        
        self.frameTime = frameTime
        self.type = type
        self.index = index
        self.posX = posX
        self.posY = posY
        self.local_posX = local_posX
        self.local_posY = local_posY
        self.status = status
        self.appearMsec = appearMsec
        self.isEX = isEX
        self.touchDecor = touchDecor
        self.touchAlpha = touchAlpha
        self.touchHoldProgress = touchHoldProgress
        self.tapScale = tapScale
        self.holdScale = holdScale
        self.holdSize = holdSize
        self.starScale = starScale
        self.starAlpha = starAlpha
    
    

star_skin = 0 # 0 圆头星星，1 尖头星星
note_speed = 0
is_big_touch = False
filter_touch_alpha = 0
STRICT_ALIGN_FPS = 30.0


def prepare_align_diff(align_diff):
    """
    统一处理 align_diff 输入。

    返回:
        base_align_diff: float，常量时间偏移（仅当 align_diff 为数字时有效）
        align_schedule: list[(frame, diff)] 或 None
        schedule_frames: 排序后的 frame 列表或 None
    """
    if isinstance(align_diff, (int, float)):
        return float(align_diff), None, None

    if isinstance(align_diff, list):
        schedule = []
        for item in align_diff:
            if not isinstance(item, (tuple, list)) or len(item) != 2:
                raise ValueError("align_diff list item must be tuple(int, float)")

            frame_no, diff = item
            frame_no = int(frame_no)
            if frame_no < 0:
                raise ValueError("align_diff frame must be >= 0")

            schedule.append((frame_no, float(diff)))

        if len(schedule) == 0:
            raise ValueError("align_diff list cannot be empty")

        schedule.sort(key=lambda x: x[0])

        # 相同帧号只保留最后一个配置
        dedup_schedule = []
        for frame_no, diff in schedule:
            if dedup_schedule and dedup_schedule[-1][0] == frame_no:
                dedup_schedule[-1] = (frame_no, diff)
            else:
                dedup_schedule.append((frame_no, diff))

        schedule_frames = [frame_no for frame_no, _ in dedup_schedule]
        return None, dedup_schedule, schedule_frames

    raise TypeError("align_diff must be float/int or list of tuple(int, float)")


def resolve_align_diff(frame_number, base_align_diff, align_schedule=None, schedule_frames=None):
    """
    根据当前帧号获取生效的时间偏移。
    """
    if align_schedule is None:
        return float(base_align_diff)

    idx = bisect_right(schedule_frames, frame_number) - 1
    if idx < 0:
        idx = 0
    return align_schedule[idx][1]



def parse_txt(txt_path, strict_align=False):
    """
    解析txt文件，返回一个按时间组织的notes字典
    键为时间戳(毫秒)，值为该时间点的notes列表

    参数:
        strict_align: 为True时，忽略txt中的Time数值，按Time行序号映射到固定30fps
    """
    if not os.path.exists(txt_path):
        return {}
    
    time_notes = {}  # 存储按时间组织的notes字典
    
    with open(txt_path, 'r', encoding='utf-8') as file:
        lines = file.readlines()
    
    current_time = None
    strict_time_index = 0
    
    for line in lines:
        line = line.strip()
        
        # 跳过空行和头部信息
        if (not line or
            line.startswith('Note Dump') or
            line.startswith('Music Info') or
            line.startswith('Format') or
            line.startswith('=') or
            line.startswith('Touch:') or
            line.startswith('Star(1st):')):
            continue
        
        # 检查是否是Time行
        if line.startswith('Time:'):
            if strict_align:
                current_time = frame_to_time(strict_time_index, STRICT_ALIGN_FPS)
                strict_time_index += 1
            else:
                # 解析时间信息
                time_parts = line.split('|')
                time_str = time_parts[0].replace('Time:', '')
                current_time = float(time_str)
            
            # 初始化这个时间点的notes列表
            if current_time not in time_notes:
                time_notes[current_time] = []
            continue
        
        # 解析note行
        if current_time is not None:
            note = parse_note_line(line, current_time)
            if note:
                time_notes[current_time].append(note)
    
    return time_notes


def find_closest_notes(time_notes, sorted_times, target_time, max_time_diff):
    """
    根据目标时间查找最接近的notes数据
    
    参数:
        time_notes: 按时间组织的notes字典 {时间戳: [notes列表]}
        sorted_times: 已排序的时间戳列表
        target_time: 目标时间(毫秒)
        
    返回:
        最接近目标时间的notes列表
    """
    if not time_notes:
        return []

    # 如果目标时间小于等于第一个时间戳，返回第一个时间戳的notes
    if target_time <= sorted_times[0]:
        return time_notes[sorted_times[0]]
    
    # 如果目标时间大于等于最后一个时间戳，返回最后一个时间戳的notes
    if target_time >= sorted_times[-1]:
        return time_notes[sorted_times[-1]]
    
    # 找到目标时间前后最近的时间戳
    left_time = None
    right_time = None
    
    for i in range(len(sorted_times) - 1):
        if sorted_times[i] <= target_time <= sorted_times[i + 1]:
            left_time = sorted_times[i]
            right_time = sorted_times[i + 1]
            break
    
    if left_time is None or right_time is None:
        return []
    
    # 计算目标时间与左右时间戳的距离
    left_diff = target_time - left_time
    right_diff = right_time - target_time

    # 如果时间差距太大也要忽略
    if left_diff > max_time_diff and right_diff > max_time_diff:
        return []
    
    # 返回距离更近的时间戳的notes
    if left_diff <= right_diff:
        return time_notes[left_time]
    else:
        return time_notes[right_time]


def frame_to_time(frame_number, fps):
    """
    将帧号转换为时间(毫秒)
    
    参数:
        frame_number: 帧号
        fps: 视频帧率
        
    返回:
        对应的时间(毫秒)
    """
    return (frame_number / fps) * 1000


def build_frame_timestamps(cap, total_video_frames, strict_align=False, progress_step=100):
    """
    获取每一帧的时间戳。
    - strict_align=False: 逐帧读取视频真实时间戳（兼容VFR）
    - strict_align=True: 按固定30fps推导
    """
    if strict_align:
        print(f"strict_align=True，按固定 {STRICT_ALIGN_FPS:.2f}fps 生成帧时间戳...")
        return [frame_to_time(frame_number, STRICT_ALIGN_FPS) for frame_number in range(total_video_frames)]

    print("正在读取视频帧时间戳...")
    frame_timestamps = []
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    i = 0
    while i < total_video_frames and cap.grab():
        timestamp = cap.get(cv2.CAP_PROP_POS_MSEC)
        frame_timestamps.append(timestamp)
        i += 1
        if i % progress_step == 0 or i == total_video_frames:
            print(f"\r进度: {i}/{total_video_frames} 帧", end="", flush=True)
    print("\r时间戳读取完成！            ")
    return frame_timestamps


def resolve_max_time_diff(cap, strict_align=False, fallback_fps=None):
    """
    计算 find_closest_notes 的最大时间匹配窗口。
    """
    if strict_align:
        return (1000 / STRICT_ALIGN_FPS) - 0.1

    fps = cap.get(cv2.CAP_PROP_FPS)
    if fallback_fps is not None and fps <= 0:
        print(f"警告: 视频 FPS 无效，回退到 {fallback_fps}")
        fps = float(fallback_fps)
    return (1000 / fps) - 0.1


def parse_note_line(line, frame_time):
    """
    解析单个note行，返回Note对象
    """
    try:
        # NA 表示当前时间点明确没有音符，返回占位对象供时间匹配命中。
        if line.strip().upper() == 'NA':
            return Note(
                frameTime=frame_time,
                type='NA',
                index=-1,
                status='NA',
                isEX=False
            )


        # 分割主要部分
        parts = line.split(' | ')
        if len(parts) < 6:
            return None
        
        # 解析type和index
        type_index = parts[0].strip()
        if "-Move" in type_index:
            type_name, move, index = type_index.split('-')
            type_name = f"{type_name}-Move"
            index = int(index)
        else:
            type_name, index = type_index.split('-')
            index = int(index)
        
        # 解析位置信息
        pos_parts = parts[1].split(', ')
        posX = float(pos_parts[0])
        posY = float(pos_parts[1])
        
        local_pos_parts = parts[2].split(', ')
        local_posX = float(local_pos_parts[0])
        local_posY = float(local_pos_parts[1])
        
        # 解析状态
        status = parts[3].strip()
        
        # 解析出现时间
        appear_msec = float(parts[4].strip())

        # 解析是否为EX
        isEX_str = parts[5].strip().lower()
        isEX = True if isEX_str == 'ex:y' else False
        
        # 创建Note对象
        note = Note(
            frameTime=frame_time,
            type=type_name,
            index=index,
            posX=posX,
            posY=posY,
            local_posX=local_posX,
            local_posY=local_posY,
            status=status,
            appearMsec=appear_msec,
            isEX=isEX
        )
        
        # 处理额外数据
        extra_data = parts[6].strip().lower() if len(parts) >= 7 else ""
        extra_data2 = parts[7].strip().lower() if len(parts) >= 8 else ""
        extra_data3 = parts[8].strip().lower() if len(parts) >= 9 else ""

        #print(f"Parsing note: {type_name}-{index} at {frame_time}ms with extra data: '{extra_data}' and '{extra_data2}'")
        
        # 处理Touch/Touch-Hold类型的TouchDecor数据
        if 'touch' in type_name.lower():
            if 'touchdecorposition' in extra_data and 'alpha' in extra_data2:
                touch_decor = float(extra_data.split('touchdecorposition:')[1].strip())
                note.touchDecor = touch_decor
                touch_alpha = float(extra_data2.split('alpha:')[1].strip())
                note.touchAlpha = touch_alpha

        # 处理Touch-Hold类型的TouchHoldProgress数据
        if 'touchhold' in type_name.lower():
            if 'touchholdprogress' in extra_data3:
                touch_hold_progress = float(extra_data3.split('touchholdprogress:')[1].strip())
                note.touchHoldProgress = touch_hold_progress

        # 处理Hold类型的HoldScale和HoldSize数据
        elif 'hold' in type_name.lower():
            if 'holdscale' in extra_data and 'holdbodysize' in extra_data2:
                hold_scale_str = extra_data.split('holdscale:')[1].strip()
                hold_scale1 = float(hold_scale_str.split(',')[0].strip())
                hold_scale2 = float(hold_scale_str.split(',')[1].strip())
                note.holdScale = (hold_scale1, hold_scale2)
                hold_size = float(extra_data2.split('holdbodysize:')[1].strip())
                note.holdSize = hold_size

        # 处理Star类型的StarScale数据
        elif 'star' in type_name.lower():
            if 'starscale' in extra_data:
                star_scale_str = extra_data.split('starscale:')[1].strip()
                star_scale1 = float(star_scale_str.split(',')[0].strip())
                star_scale2 = float(star_scale_str.split(',')[1].strip())
                note.starScale = (star_scale1, star_scale2)
            if 'alpha' in extra_data2:
                star_alpha = float(extra_data2.split('alpha:')[1].strip())
                note.starAlpha = star_alpha

        # 处理Tap类型的TapScale数据
        elif 'tap' in type_name.lower() or 'break' in type_name.lower():
            if 'tapscale' in extra_data:
                tap_scale_str = extra_data.split('tapscale:')[1].strip()
                tap_scale1 = float(tap_scale_str.split(',')[0].strip())
                tap_scale2 = float(tap_scale_str.split(',')[1].strip())
                note.tapScale = (tap_scale1, tap_scale2)
        
        return note

    except Exception as e:
        print(f"Error in parse_note_line(): {e}: {line}")
        return None




def manual_align(video_path, txt_path, time_notes, align_diff=0, jumps_to=0, strict_align=False):
    """
    手动对齐视频帧和时间戳音符数据
    
    操作说明：
    - 空格：播放/暂停
    - 模式1（对齐模式）：音符保持不变
    - 按'c'键切换到模式2
    - 模式2（验证模式）：视频和音符同步（时间差固定）
    - 左/右箭头：暂停并前进/后退一帧
    - 按'q'退出
    
    返回：时间偏移量(毫秒)
    """
    
    last_video_frame_counter = -1  # 上一次的视频帧计数器
    is_playing = False  # 播放状态

    base_align_diff, align_schedule, schedule_frames = prepare_align_diff(align_diff)
    is_scheduled_align = align_schedule is not None

    if is_scheduled_align:
        time_offset = resolve_align_diff(0, base_align_diff, align_schedule, schedule_frames)
        mode = 2
    elif base_align_diff == 0:
        time_offset = 0.0  # notes与video的时间差(ms)
        mode = 1  # 1=对齐模式, 2=验证模式
    else:
        time_offset = base_align_diff
        mode = 2

    cap = cv2.VideoCapture(video_path)
    total_video_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    
    if not time_notes:
        print("没有找到音符数据！")
        cap.release()
        return 0

    # 预先读取所有帧的时间戳（strict_align 时按固定 30fps 推导）
    frame_timestamps = build_frame_timestamps(
        cap,
        total_video_frames,
        strict_align=strict_align,
        progress_step=10
    )

    max_time_diff = resolve_max_time_diff(cap, strict_align=strict_align) # 最大时间差，1帧时间

    if jumps_to == 0:
        # 重置视频到第一帧
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        video_frame_counter = 0  # 视频当前帧计数
    else:
        cap.set(cv2.CAP_PROP_POS_FRAMES, jumps_to)
        video_frame_counter = jumps_to

    # 获取所有时间戳并排序
    sorted_times = sorted(time_notes.keys())    
    window_name = 'Label Notes Alignment Tool'
    cv2.namedWindow(window_name, cv2.WINDOW_AUTOSIZE)

    while True:
        # 设置视频到指定帧
        if video_frame_counter - last_video_frame_counter != 1: # 不是下一帧
            cap.set(cv2.CAP_PROP_POS_FRAMES, video_frame_counter)

        last_video_frame_counter = video_frame_counter
        ret, raw_frame = cap.read()
        
        if not ret:
            video_frame_counter = min(video_frame_counter, total_video_frames - 1)
            is_playing = False
            continue
        
        # 从预先缓存的时间戳列表中获取当前帧的真实时间戳
        current_video_timestamp = frame_timestamps[video_frame_counter]

        if is_scheduled_align and mode == 2:
            time_offset = resolve_align_diff(video_frame_counter, base_align_diff, align_schedule, schedule_frames)
        
        # 计算notes虚拟时间 = 视频真实时间戳 + 时间差
        notes_virtual_time = current_video_timestamp + time_offset
        
        # 根据notes虚拟时间查找最接近的音符
        current_notes = find_closest_notes(time_notes, sorted_times, notes_virtual_time, max_time_diff)
        
        # 绘制音符
        result_frame = draw_all_notes(raw_frame, current_notes, notes_virtual_time)
        
        # 显示信息
        play_status = "[PLAYING]" if is_playing else "[PAUSED]"
        mode_text = f"{play_status} Mode 1: Alignment" if mode == 1 else f"{play_status} Mode 2: Sync"
        mode_color = (0, 255, 255) if mode == 1 else (0, 255, 0)
        
        cv2.putText(result_frame, mode_text,
                    (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, mode_color, 2)
        cv2.putText(result_frame, f"Video: {video_frame_counter}/{total_video_frames} frame ({current_video_timestamp:.2f}ms)",
                    (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        cv2.putText(result_frame, f"Notes: {notes_virtual_time:.2f}ms",
                    (10, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        cv2.putText(result_frame, f"Diff: {time_offset:.2f}ms",
                    (10, 120), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 0), 2)
        cv2.putText(result_frame, "Q:Quit | C:Mode",
                    (10, result_frame.shape[0] - 80), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)
        cv2.putText(result_frame, "Space: Play/Pause",
                    (10, result_frame.shape[0] - 50), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)
        cv2.putText(result_frame, "Arrow: Last frame",
                    (10, result_frame.shape[0] - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)
        
        cv2.imshow(window_name, result_frame)

        # 等待按键
        key = cv2.waitKey(5) & 0xFF
        
        if key == ord('q') or key == ord('Q'):  # 退出
            print(f"对齐完成！")
            print(f"Time Offset: {time_offset:.2f}ms")
            break
            
        elif key == ord('c') or key == ord('C'):  # 切换模式
            is_playing = False
            mode = 2 if mode == 1 else 1
        
        elif key == 32:  # 空格：播放/暂停
            is_playing = not is_playing
                
        elif key == 0:  # 四个箭头键 (四个键都是0，不知道怎么区分)
            is_playing = False  # 箭头操作时暂停
            if mode == 1:
                # 模式1：视频后退一帧，同时调整时间差以保持notes虚拟时间不变
                new_video_frame_counter = max(video_frame_counter - 1, 0)
                if new_video_frame_counter != video_frame_counter:
                    # 从缓存中获取新帧的时间戳
                    new_video_timestamp = frame_timestamps[new_video_frame_counter]
                    # 调整时间差：让notes虚拟时间保持不变
                    # notes_virtual_time = new_video_timestamp + new_time_offset
                    # 由于notes_virtual_time不变，所以：
                    time_offset += (current_video_timestamp - new_video_timestamp)
                    video_frame_counter = new_video_frame_counter
            else:
                # 模式2：视频后退一帧，时间差不变（notes会同步后退）
                video_frame_counter = max(video_frame_counter - 1, 0)
        
        # 如果正在播放，自动前进
        if is_playing:
            if mode == 1:
                # 模式1：视频前进，同时调整时间差以保持notes虚拟时间不变
                new_video_frame_counter = video_frame_counter + 1
                if new_video_frame_counter >= total_video_frames:
                    video_frame_counter = total_video_frames - 1
                    is_playing = False
                else:
                    # 获取下一帧的时间戳
                    next_video_timestamp = frame_timestamps[new_video_frame_counter]
                    # 调整时间差：让notes虚拟时间保持不变
                    # notes_virtual_time = next_video_timestamp + new_time_offset
                    # 由于notes_virtual_time不变，所以：
                    time_offset += (current_video_timestamp - next_video_timestamp)
                    video_frame_counter = new_video_frame_counter
            else:
                # 模式2：视频前进，时间差不变（notes会同步前进）
                video_frame_counter += 1
                if video_frame_counter >= total_video_frames:
                    video_frame_counter = total_video_frames - 1
                    is_playing = False
    
    cap.release()
    cv2.destroyWindow(window_name)

    return time_offset



def draw_tap_note(note, target_time):
    """
    绘制单个Tap音符
    """

    if note.status.lower() == "init": return None, None

    center_x = 1080 + note.posX
    center_y = 120 - note.posY
    ox = 540
    oy = 540

    if note.status.lower() == "scale":
        index = note.tapScale[0]
        if index < 0.5: return None, None # 忽略过小的音符
        if note.isEX:
            size = 1080 * 0.055 * index
        else:
            size = 1080 * 0.049 * index
        # 不需要位置补偿，直接使用center计角点
        return [
            (center_x - size, center_y - size),  # 左上
            (center_x + size, center_y - size),  # 右上
            (center_x + size, center_y + size),  # 右下
            (center_x - size, center_y + size),  # 左下
        ], (center_x, center_y)


    # 对于 move 状态的音符，需要根据时间差进行位置补偿
    if note.isEX:
        size = 1080 * 0.055
    else:
        size = 1080 * 0.049

    # 假设速度 7.50
    # OptionNotespeed = 850
    # DefaultMsec = 1000 / (850 / 60) * 4 = 282.35294
    # 说明音符走完全程要 282ms
    # 在标准 1080p 下，起点 120 终点 480 全程 360 像素
    # 所以此时移动速度为 360 / 282 像素/毫秒
    defaultMsec = 100 * note_speed + 100
    speed = 360 / (1000 / defaultMsec * 60 * 4)
    time_diff = target_time - note.frameTime
    new_distance_to_o = note.local_posY + speed * time_diff
    # local_posY就是到屏幕中心的距离

    # 以 O (屏幕中心) 为中心，沿直线获得距离为 new_distance_to_o 的两个点
    a = (center_y - oy) / (center_x - ox)
    dx = new_distance_to_o / np.sqrt(1 + np.power(a, 2))
    dy = a * dx
    p1x = ox + dx
    p1y = oy + dy
    p2x = ox - dx
    p2y = oy - dy

    # 更接近 center 的点就是新的中心点
    if abs(p1x - center_x) > abs(p2x - center_x):
        new_center_x = p2x
        new_center_y = p2y
    else:
        new_center_x = p1x
        new_center_y = p1y

    # 返回4个角点（左上、右上、右下、左下）和中心点
    points = [
        (new_center_x - size, new_center_y - size),  # 左上
        (new_center_x + size, new_center_y - size),  # 右上
        (new_center_x + size, new_center_y + size),  # 右下
        (new_center_x - size, new_center_y + size),  # 左下
    ]

    return points, (round(new_center_x), round(new_center_y))


def draw_hold_note(note, target_time):
    """
    绘制单个Hold音符
    """

    if note.status.lower() == "init": return None, None, None

    if note.status.lower() == "scale":
        index = note.holdScale[0]
        if index < 0.5: return None, None, None # 忽略过小的音符
    else:
        index = 1

    ex_extend = 5 # 如果是 ex 音符，外扩 5 像素来包住保护套光晕
    if not note.isEX:
        box_width = 140 * 0.5 * 0.77 * index
        box_length = (note.holdSize-20) * 0.5 * index
    else:
        box_width = (ex_extend + 140 * 0.5 * 0.77) * index
        box_length = (ex_extend + (note.holdSize-20) * 0.5) * index

    center_x = 1080 + note.posX
    center_y = 120 - note.posY
    ox = 540
    oy = 540
    head_x, head_y = None, None


    # 对于 move 状态的音符，需要根据时间差进行位置补偿
    # 但是排除中点位于中间的情况，这时候头尾都占满轨道了不需要移动
    if note.status.lower() == "move" and note.local_posY != 300:
        # 假设速度 7.50
        # 由于是中点，移动速度减半
        defaultMsec = 100 * note_speed + 100
        speed = 360 / (1000 / defaultMsec * 60 * 4) * 0.5
        time_diff = target_time - note.frameTime
        new_distance_to_o = note.local_posY + speed * time_diff
        # 以 O (屏幕中心) 为中心，沿直线获得距离为 new_distance_to_o 的两个点
        a = (center_y - oy) / (center_x - ox)
        dx = new_distance_to_o / np.sqrt(1 + np.power(a, 2))
        dy = a * dx
        p1x = ox + dx
        p1y = oy + dy
        p2x = ox - dx
        p2y = oy - dy
        # 更接近 center 的点就是新的中心点
        if abs(p1x - center_x) > abs(p2x - center_x):
            center_x = p2x
            center_y = p2y
        else:
            center_x = p1x
            center_y = p1y


    # y = ax + b
    a = (center_y - oy) / (center_x - ox)
    
    # 对于 move 阶段，根据中心点计算出头部追踪点
    # 140 的时候 head 与中点重合了，所以要等 160 以后才显示
    if note.status.lower() == "move" and note.holdSize > 160:
        # 以 center xy 为中心，沿直线获得距离为 box_length - c 的两个点
        c = 60 + ex_extend if note.isEX else 60
        dx = (box_length - c) / np.sqrt(1 + np.power(a, 2))
        dy = a * dx
        p1x = center_x + dx
        p1y = center_y + dy
        p2x = center_x - dx
        p2y = center_y - dy
        # 更远离屏幕中心的点就是头部追踪点
        if abs(p1x - ox) < abs(p2x - ox):
            head_x = p2x
            head_y = p2y
        else:
            head_x = p1x
            head_y = p1y


    # 根据中心点和边长计算出四个角点（带角度的）
    # 以 center xy 为中心，沿直线获得距离为 box_length 的两个点
    # 这两个点是 hold 的头尾两条边的中点
    dx = box_length / np.sqrt(1 + np.power(a, 2))
    dy = a * dx
    mid1x = center_x - dx
    mid1y = center_y - dy
    mid2x = center_x + dx
    mid2y = center_y + dy

    # 现在根据头尾两条边的中点，计算出四个角点
    a_perpendicular = -1 / a

    dx1 = box_width / np.sqrt(1 + np.power(a_perpendicular, 2))
    dy1 = a_perpendicular * dx1
    p1 = (mid1x - dx1, mid1y - dy1)
    p2 = (mid1x + dx1, mid1y + dy1)

    dx2 = box_width / np.sqrt(1 + np.power(a_perpendicular, 2))
    dy2 = a_perpendicular * dx2
    p3 = (mid2x + dx2, mid2y + dy2)
    p4 = (mid2x - dx2, mid2y - dy2)

    return [
        (round(p1[0]), round(p1[1])),
        (round(p2[0]), round(p2[1])),
        (round(p3[0]), round(p3[1])),
        (round(p4[0]), round(p4[1])),
    ], (center_x, center_y), (head_x, head_y)



def draw_slide_note(note, target_time):
    """
    绘制单个Slide音符（星星头）
    """

    # 直接复制 tap 的代码
    if note.status.lower() == "init": return None, None

    center_x = 1080 + note.posX
    center_y = 120 - note.posY
    ox = 540
    oy = 540


    if "move" in note.type.lower():
        if note.starAlpha < 0.75: return None, None # 忽略过于透明的音符

        index = 0.88 if star_skin == 0 else 1   # 0 圆头星星，1 尖头星星
        size = 1080 * 0.055 * note.starScale[0] * index

        # 不需要位置补偿，直接使用center计角点
        return [
            (center_x - size, center_y - size),  # 左上
            (center_x + size, center_y - size),  # 右上
            (center_x + size, center_y + size),  # 右下
            (center_x - size, center_y + size),  # 左下
        ], (center_x, center_y)


    if note.status.lower() == "scale":
        index = note.starScale[0]
        if index < 0.5: return None, None # 忽略过小的音符
        
        if note.isEX:
            size = 1080 * 0.055 * index
        else:
            size = 1080 * 0.05 * index

        # 不需要位置补偿，直接使用center计角点
        return [
            (center_x - size, center_y - size),  # 左上
            (center_x + size, center_y - size),  # 右上
            (center_x + size, center_y + size),  # 右下
            (center_x - size, center_y + size),  # 左下
        ], (center_x, center_y)


    # 对于 move 状态的音符，需要根据时间差进行位置补偿
    if note.isEX:
        size = 1080 * 0.055
    else:
        size = 1080 * 0.049

    # 假设速度 7.50
    # OptionNotespeed = 850
    # DefaultMsec = 1000 / (850 / 60) * 4 = 282.35294
    # 说明音符走完全程要 282ms
    # 在标准 1080p 下，起点 120 终点 480 全程 360 像素
    # 所以此时移动速度为 360 / 282 像素/毫秒
    defaultMsec = 100 * note_speed + 100
    speed = 360 / (1000 / defaultMsec * 60 * 4)
    time_diff = target_time - note.frameTime
    new_distance_to_o = note.local_posY + speed * time_diff
    # local_posY就是到屏幕中心的距离

    # 以 O (屏幕中心) 为中心，沿直线获得距离为 new_distance_to_o 的两个点
    a = (center_y - oy) / (center_x - ox)
    dx = new_distance_to_o / np.sqrt(1 + np.power(a, 2))
    dy = a * dx
    p1x = ox + dx
    p1y = oy + dy
    p2x = ox - dx
    p2y = oy - dy

    # 更接近 center 的点就是新的中心点
    if abs(p1x - center_x) > abs(p2x - center_x):
        new_center_x = p2x
        new_center_y = p2y
    else:
        new_center_x = p1x
        new_center_y = p1y

    # 返回4个角点（左上、右上、右下、左下）和中心点
    points = [
        (new_center_x - size, new_center_y - size),  # 左上
        (new_center_x + size, new_center_y - size),  # 右上
        (new_center_x + size, new_center_y + size),  # 右下
        (new_center_x - size, new_center_y + size),  # 左下
    ]

    return points, (round(new_center_x), round(new_center_y))


def draw_touch_note(note, target_time):
    """
    绘制单个Touch音符
    """

    center_x = 1080 + note.posX
    center_y = 120 - note.posY
    size = note.touchDecor + 54
    if is_big_touch:
        size = round(size * 1.3)

    if filter_touch_alpha > 1:
        # 由于未知原因，当 touch_speed = 1.0 时
        # touchDecor = 34 时音符还是隐形的
        # 直到开始缩小了才真的逐渐浮现出来
        if note.touchDecor > 32.7:
            return None, None
    else:
        # 普通情况
        if note.touchAlpha < filter_touch_alpha: return None, None # 忽略过于透明的音符

    # touch 音符的公式有点复杂，就不补偿了
    # 反正最后识别尺寸也是靠查找轮廓，不需要画框很精准
    return [
        (center_x - size, center_y - size),  # 左上
        (center_x + size, center_y - size),  # 右上
        (center_x + size, center_y + size),  # 右下
        (center_x - size, center_y + size),  # 左下
    ], (center_x, center_y)


def draw_touch_hold_note(note, target_time):
    """
    绘制单个Touch-Hold音符
    """

    center_x = 1080 + note.posX
    center_y = 120 - note.posY

    note_alpha = note.touchAlpha if note.touchAlpha is not None else -1
    if filter_touch_alpha > 1:
        # 与 draw_touch_note 对齐：在特殊过滤模式下按 touchDecor 判定
        if note.touchDecor > 32.7:
            return None, None
    else:
        if note_alpha < filter_touch_alpha: return None, None # 忽略过于透明的音符

    size = note.touchDecor + 68 # 缩放阶段
    if is_big_touch:
        size = round(size * 1.3)

    # 反正最后识别尺寸也是靠识别彩虹框，跟touch一样不做运动补偿了
    return [
        (center_x - size, center_y - size),  # 左上
        (center_x + size, center_y - size),  # 右上
        (center_x + size, center_y + size),  # 右下
        (center_x - size, center_y + size),  # 左下
    ], (center_x, center_y)


def draw_rotated_rect(frame, points, color, thickness=2):
    """
    在帧上绘制旋转矩形
    
    输入：
        frame: 图像帧
        points: 4个点的坐标列表 [(x1,y1), (x2,y2), (x3,y3), (x4,y4)]
        color: BGR颜色元组
        thickness: 线条粗细
        
    返回：
        frame: 绘制后的图像帧
    """
    
    # 转换为整数坐标
    pts = np.array(points, dtype=np.int32)
    
    # 绘制矩形（连接4个点）
    cv2.polylines(frame, [pts], isClosed=True, color=color, thickness=thickness)
    
    return frame


def draw_all_notes(frame, notes, target_time):
    """
    绘制所有类型的音符
    使用独立的绘制函数为每种音符类型生成矩形框
    """

    if not notes: return frame

    for note in notes:
        note_type = note.type.lower()
        if note_type == 'na':
            continue
        
        # 根据音符类型调用对应的绘制函数
        points = None
        center = None
        head = None
        color = (255, 255, 255)  # 默认白色
        label = ""
        
        # Tap音符：绿色
        if note_type == 'tapnote':
            points, center = draw_tap_note(note, target_time)
            color = (0, 255, 0)
            label = 'TAP'
        elif note_type == 'breaknote':
            points, center = draw_tap_note(note, target_time)
            color = (0, 255, 0)
            label = 'TAP-B'

        # Hold音符：蓝色
        elif note_type == 'holdnote':
            points, center, head = draw_hold_note(note, target_time)
            color = (255, 0, 0)
            label = 'HOLD'
        elif note_type == 'breakholdnote':
            points, center, head = draw_hold_note(note, target_time)
            color = (255, 0, 0)
            label = 'HOLD-B'
        
        # Slide音符：黄色
        elif note_type == 'starnote' or note_type == 'starnote-move':
            points, center = draw_slide_note(note, target_time)
            color = (0, 255, 255)
            label = 'SLIDE'
        elif note_type == 'breakstarnote' or note_type == 'breakstarnote-move':
            points, center = draw_slide_note(note, target_time)
            color = (0, 255, 255)
            label = 'SLIDE-B'
        
        # Touch-Hold音符：青色
        elif 'touchhold' in note_type:
            points, center = draw_touch_hold_note(note, target_time)
            color = (255, 255, 0)
            label = 'TOUCH-HOLD'
        
        # Touch音符：紫色
        elif 'touch' in note_type:
            points, center = draw_touch_note(note, target_time)
            color = (255, 0, 255)
            label = 'TOUCH'

        if note.isEX:
            if label.endswith('-B'):
                label += 'X'
            else:
                label += '-X'

        label += f' {note.index}'
            
        # 绘制矩形框
        if points:
            frame = draw_rotated_rect(frame, points, color, thickness=2)
            
            # 绘制中心点
            center_x, center_y = center
            center_x = int(round(center_x))
            center_y = int(round(center_y))
            cv2.circle(frame, (center_x, center_y), 2, (0, 0, 255), 3)

            # 显示音符类型标签
            org_x = int(round(points[0][0]))
            org_y = int(round(points[0][1])) - 5
            cv2.putText(frame, label, (org_x, org_y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
            
            # 如果是Hold音符，绘制头部追踪点
            if head:
                head_x, head_y = head
                if head_x and head_y:
                    head_x = int(round(head_x))
                    head_y = int(round(head_y))
                    cv2.circle(frame, (head_x, head_y), 2, (255, 0, 0), 3)
            
    return frame


def calculate_oct_position(circle_center_x, circle_center_y, note_x, note_y):
    x_diff = note_x - circle_center_x
    y_diff = note_y - circle_center_y
    if x_diff > 0 and y_diff < 0:
        # 1, 2
        if abs(x_diff) < abs(y_diff):
            return 1
        else:
            return 2
    elif x_diff > 0 and y_diff > 0:
        # 3, 4
        if abs(x_diff) > abs(y_diff):
            return 3
        else:
            return 4
    elif x_diff < 0 and y_diff > 0:
        # 5, 6
        if abs(x_diff) < abs(y_diff):
            return 5
        else:
            return 6
    elif x_diff < 0 and y_diff < 0:
        # 7, 8
        if abs(x_diff) > abs(y_diff):
            return 7
        else:
            return 8
    else:
        return 0


def export_dataset(video_path, txt_path, output_dir, time_offset, video_name=None, export_half_frame=False,
                   strict_align=False):
    """
    导出YOLO训练数据集
    
    输出文件结构:
        output_dir/
        ├── images/          # 所有图像文件 (detect和obb共用)
        ├── labels_detect/   # detect格式标签 (bbox: class_id x_center y_center width height)
        └── labels_obb/      # obb格式标签 (oriented bbox: class_id x1 y1 x2 y2 x3 y3 x4 y4)
    
    参数:
        video_path: 视频路径
        txt_path: 音符数据txt路径
        output_dir: 输出目录
        time_offset: 时间偏移量(毫秒)，支持 float 或 list[(frame, diff)]
        video_name: 视频名称（用于文件命名），如果为None则从video_path提取
        export_half_frame: 是否隔一帧导出（True时仅导出偶数帧）
        strict_align: 为True时，视频与txt时间都按固定30fps处理
    """

    base_align_diff, align_schedule, schedule_frames = prepare_align_diff(time_offset)
    
    # 解析txt文件
    time_notes = parse_txt(txt_path, strict_align=strict_align)
    
    if not time_notes:
        print("错误：没有找到任何音符数据！")
        return
    
    # 获取视频名称
    if video_name is None:
        video_name = os.path.splitext(os.path.basename(video_path))[0]
    
    # 创建输出目录结构：三个并列文件夹
    images_dir = os.path.join(output_dir, 'images')
    detect_labels_dir = os.path.join(output_dir, 'labels_detect')
    obb_labels_dir = os.path.join(output_dir, 'labels_obb')
    
    # 如果已存在则删除再创建
    for d in (images_dir, detect_labels_dir, obb_labels_dir):
        if os.path.exists(d):
            try:
                if os.path.isfile(d):
                    os.remove(d)
                else:
                    shutil.rmtree(d)
            except Exception as e:
                print(f"Warning: failed to remove {d}: {e}")
        os.makedirs(d, exist_ok=True)
    
    # 打开视频
    cap = cv2.VideoCapture(video_path)
    total_video_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    
    # 预先读取所有帧的时间戳（strict_align 时按固定 30fps 推导）
    frame_timestamps = build_frame_timestamps(
        cap,
        total_video_frames,
        strict_align=strict_align,
        progress_step=100
    )

    max_time_diff = resolve_max_time_diff(cap, strict_align=strict_align)
    
    # 重置视频到第一帧
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    
    # 获取所有时间戳并排序
    sorted_times = sorted(time_notes.keys())
    
    # 获取帧尺寸
    frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    
    detect_count = 0
    obb_count = 0
    
    print(f"\n开始导出数据集...")
    print(f"视频尺寸: {frame_width}x{frame_height}")
    print(f"导出模式: {'隔帧导出(1/2帧)' if export_half_frame else '全帧导出'}")
    print(f"输出目录:")
    print(f"  Images: {images_dir}")
    print(f"  Detect labels: {detect_labels_dir}")
    print(f"  OBB labels: {obb_labels_dir}")
    
    # 测试写入权限
    test_file = os.path.join(images_dir, "test.txt")
    try:
        with open(test_file, 'w') as f:
            f.write("test")
        os.remove(test_file)
    except Exception as e:
        print(f"错误: 目录写入测试失败: {e}")
        return
    
    # 遍历所有帧（可选隔帧导出）
    frame_step = 2 if export_half_frame else 1
    for frame_number in range(0, total_video_frames, frame_step):
        # 读取帧
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
        ret, frame = cap.read()
        
        if not ret:
            continue
        
        # 获取当前帧的时间戳
        current_video_timestamp = frame_timestamps[frame_number]
        
        # 计算notes虚拟时间
        current_align_diff = resolve_align_diff(frame_number, base_align_diff, align_schedule, schedule_frames)
        notes_virtual_time = current_video_timestamp + current_align_diff
        
        # 查找最接近的音符
        current_notes = find_closest_notes(time_notes, sorted_times, notes_virtual_time, max_time_diff)
        
        # 处理detect格式的音符
        detect_labels = []
        if current_notes:
            for note in current_notes:
                note_type = note.type.lower()
                if note_type == 'na':
                    continue
                class_id = -1
                points = None
                center = None
                
                # Tap音符 (class_id = 0)
                if note_type in ['tapnote', 'breaknote']:
                    points, center = draw_tap_note(note, notes_virtual_time)
                    class_id = 0
                
                # Slide音符 (class_id = 1)
                elif note_type in ['starnote', 'starnote-move', 'breakstarnote', 'breakstarnote-move']:
                    points, center = draw_slide_note(note, notes_virtual_time)
                    class_id = 1
                
                # Touch音符 (class_id = 2)
                elif 'touch' in note_type and 'touchhold' not in note_type:
                    points, center = draw_touch_note(note, notes_virtual_time)
                    class_id = 2
                
                # TouchHold音符 (class_id = 3)
                elif 'touchhold' in note_type:
                    points, center = draw_touch_hold_note(note, notes_virtual_time)
                    class_id = 3
                
                # 如果成功获取了角点数据
                if points is not None and center is not None and class_id >= 0:
                    # 从4个角点计算宽度和高度
                    x_coords = [p[0] for p in points]
                    y_coords = [p[1] for p in points]
                    
                    min_x = min(x_coords)
                    max_x = max(x_coords)
                    min_y = min(y_coords)
                    max_y = max(y_coords)
                    
                    width = max_x - min_x
                    height = max_y - min_y
                    
                    # 按半径过滤
                    dist_to_center = np.sqrt((center[0] - frame_width/2) ** 2 + (center[1] - frame_height/2) ** 2)
                    threshold = frame_width * 520/1080 # 1080p下不超过520像素
                    if dist_to_center <= threshold:
                        # 归一化
                        x_center_norm = center[0] / frame_width
                        y_center_norm = center[1] / frame_height
                        width_norm = width / frame_width
                        height_norm = height / frame_height
                        # 确保归一化后的数据不超过 0-1
                        x_center_norm = max(0, min(1, x_center_norm))
                        y_center_norm = max(0, min(1, y_center_norm))
                        width_norm = max(0, min(1, width_norm))
                        height_norm = max(0, min(1, height_norm))
                        # 添加到标签列表
                        detect_labels.append(f"{class_id} {x_center_norm} {y_center_norm} {width_norm} {height_norm}")
        
        # 保存图像和标签（即使标签为空也保存）
        image_filename = f"{video_name}_{frame_number}.jpg"
        label_filename = f"{video_name}_{frame_number}.txt"
        
        # 保存图像（只保存一次，detect和obb共用）
        image_path = os.path.join(images_dir, image_filename)
        cv_imwrite(image_path, frame)

        # 保存detect标签文件（空标签也保存）
        with open(os.path.join(detect_labels_dir, label_filename), 'w') as f:
            if detect_labels:
                f.write('\n'.join(detect_labels))
                detect_count += 1
        
        # 处理obb格式的音符
        obb_labels = []
        if current_notes:
            for note in current_notes:
                note_type = note.type.lower()
                if note_type == 'na':
                    continue
                class_id = -1
                points = None
                
                # Hold音符 (class_id = 0)
                if note_type in ['holdnote', 'breakholdnote']:
                    points, _, _ = draw_hold_note(note, notes_virtual_time)
                    class_id = 0
                
                # 如果成功获取了角点数据
                if points is not None and class_id >= 0:
                    # 重新排序四个点：点1（最上方），点2（最右边），点3（最下方），点4（最左边）
                    reordered_points = reorder_obb_points(points)

                    # 归一化4个角点
                    normalized_points = []
                    for p in reordered_points:
                        x_norm = p[0] / frame_width
                        y_norm = p[1] / frame_height
                        # 确保归一化后的数据不超过 0-1
                        x_norm = max(0, min(1, x_norm))
                        y_norm = max(0, min(1, y_norm))
                        # 保存坐标
                        normalized_points.extend([x_norm, y_norm])
                    
                    # 添加到标签列表
                    label_str = f"{class_id}"
                    for coord in normalized_points:
                        label_str += f" {coord}"
                    obb_labels.append(label_str)
        
        # 保存obb标签文件（即使标签为空也保存，图像已在上面保存过了）
        label_filename = f"{video_name}_{frame_number}.txt"
        
        # 保存obb标签文件（空标签也保存）
        with open(os.path.join(obb_labels_dir, label_filename), 'w') as f:
            if obb_labels:
                f.write('\n'.join(obb_labels))
                obb_count += 1
        
        # 显示进度
        if (frame_number + 1) % 10 <= 1 or frame_number == total_video_frames - 1:
            print(f"\r处理进度: {frame_number + 1}/{total_video_frames} 帧 | Detect: {detect_count} 帧 | OBB: {obb_count} 帧", end="", flush=True)
    
    print(f"\n\n导出完成！")
    print(f"Detect数据集: {detect_count} 帧")
    print(f"OBB数据集: {obb_count} 帧")
    print(f"输出目录: {output_dir}")
    
    cap.release()


def crop_with_black_padding(frame, center_x, center_y, crop_width, crop_height):
    """
    按中心点裁剪固定大小区域，超出边界的部分使用黑色填充。
    """
    frame_height, frame_width = frame.shape[:2]
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


def parse_touch_hold(cropped_frame, touch_hold_note, crop_origin_x, crop_origin_y):
    """
    接收裁剪后的帧与 touch-hold 音符信息，生成 YOLO detect 标签。

    参数:
        cropped_frame: 裁剪后的图像
        touch_hold_note: touch-hold 音符对象
        crop_origin_x: 裁剪框左上角在原图中的 x
        crop_origin_y: 裁剪框左上角在原图中的 y

    返回:
        YOLO detect 标签行列表
        - class 0: touch 框
        - class 1: 进度点框（若进度有效）
    """
    if cropped_frame is None:
        return []

    frame_h, frame_w = cropped_frame.shape[:2]
    note_alpha = touch_hold_note.touchAlpha if touch_hold_note.touchAlpha is not None else -1
    if filter_touch_alpha > 1:
        # 与 draw_touch_hold_note 对齐：在特殊过滤模式下按 touchDecor 判定
        if touch_hold_note.touchDecor > 32.7:
            return []
    else:
        if note_alpha < filter_touch_alpha:  # 忽略过于透明的音符
            return []

    labels = []

    def append_bbox(class_id, x1, y1, x2, y2):
        x1 = max(0.0, min(float(frame_w), float(x1)))
        y1 = max(0.0, min(float(frame_h), float(y1)))
        x2 = max(0.0, min(float(frame_w), float(x2)))
        y2 = max(0.0, min(float(frame_h), float(y2)))
        box_w = x2 - x1
        box_h = y2 - y1
        if box_w <= 0 or box_h <= 0:
            return
        x_center = (x1 + x2) * 0.5 / frame_w
        y_center = (y1 + y2) * 0.5 / frame_h
        width = box_w / frame_w
        height = box_h / frame_h

        # 强制归一化结果在 [0, 1]
        x_center = max(0.0, min(1.0, x_center))
        y_center = max(0.0, min(1.0, y_center))
        width = max(0.0, min(1.0, width))
        height = max(0.0, min(1.0, height))
        labels.append(f"{class_id} {x_center:.6f} {y_center:.6f} {width:.6f} {height:.6f}")




    # 绘制 touch 框
    # 魔改 draw_touch_hold_note() 的计算逻辑，并把四点映射到裁剪图坐标系
    center_x = 1080 + touch_hold_note.posX
    center_y = 120 - touch_hold_note.posY

    size = touch_hold_note.touchDecor + 68
    if is_big_touch:
        size = round(size * 1.3)

    points_on_full = [
        (center_x - size, center_y - size),  # 左上
        (center_x + size, center_y - size),  # 右上
        (center_x + size, center_y + size),  # 右下
        (center_x - size, center_y + size),  # 左下
    ]

    points_on_crop = []
    for px, py in points_on_full:
        mx = int(round(px - crop_origin_x))
        my = int(round(py - crop_origin_y))
        points_on_crop.append((mx, my))

    x_coords = [p[0] for p in points_on_crop]
    y_coords = [p[1] for p in points_on_crop]
    append_bbox(0, min(x_coords), min(y_coords), max(x_coords), max(y_coords))




    center_on_crop = (
        int(round(center_x - crop_origin_x)),
        int(round(center_y - crop_origin_y)),
    )




    # 绘制进度点：0/1 在 12 点，顺时针增加
    hold_progress = touch_hold_note.touchHoldProgress
    if hold_progress is not None and hold_progress >= 0.02:  # 忽略前2%
        # 根据进度计算角度
        progress = max(0.0, min(1.0, float(hold_progress)))
        base_radius = frame_w * 0.4
        angle = -np.pi / 2 + progress * 2 * np.pi
        # 圆角菱形轨迹：p=1 是菱形，p=2 是圆
        shape_p = 1.3
        dir_x = np.cos(angle)
        dir_y = np.sin(angle)
        denom = (abs(dir_x) ** shape_p + abs(dir_y) ** shape_p) ** (1.0 / shape_p)
        adjusted_radius = base_radius if denom <= 1e-6 else (base_radius / denom)
        # 计算进度点在裁剪图中的坐标
        progress_x = float(center_on_crop[0] + adjusted_radius * dir_x)
        progress_y = float(center_on_crop[1] + adjusted_radius * dir_y)

        # class 1: 进度点框，边长为 round(width * 0.1)
        dot_side = max(1, int(round(frame_w * 0.1)))
        half_side = dot_side * 0.5
        append_bbox(1,
                    progress_x - half_side,
                    progress_y - half_side,
                    progress_x + half_side,
                    progress_y + half_side)

    return labels


def export_dataset_touch_hold(all_configs, dataset_root):
    """
    批量导出 touch-hold 裁剪数据集。

    规则:
    - all_configs 由调用方传入
    - dataset_root 由调用方传入
    - 每首歌单独读取 strict_align，默认 True，除非显式指定为 False
    - 先从 output_dir/images 文件名解析目标帧号
    - 按目标帧号定位视频帧时间，再到 txt 匹配当帧音符
    - 仅保留 touch-hold 音符，排除其他类型
    - 输出裁剪图和 YOLO detect 标签（class 0: touch框, class 1: 进度点框）
    """
    global is_big_touch
    global filter_touch_alpha

    if not isinstance(all_configs, list) or len(all_configs) == 0:
        print("错误: all_configs 不能为空，且必须为配置列表")
        return

    if not isinstance(dataset_root, str) or dataset_root.strip() == "":
        print("错误: dataset_root 不能为空")
        return

    dataset_root = dataset_root.strip()
    train_images_dir = os.path.join(dataset_root, 'train', 'images')
    train_labels_dir = os.path.join(dataset_root, 'train', 'labels')
    valid_images_dir = os.path.join(dataset_root, 'valid', 'images')
    valid_labels_dir = os.path.join(dataset_root, 'valid', 'labels')

    if os.path.exists(dataset_root):
        try:
            if os.path.isfile(dataset_root):
                os.remove(dataset_root)
            else:
                shutil.rmtree(dataset_root)
        except Exception as e:
            print(f"错误: 无法清理旧输出目录: {dataset_root}: {e}")
            return

    for d in (train_images_dir, train_labels_dir, valid_images_dir, valid_labels_dir):
        os.makedirs(d, exist_ok=True)

    old_is_big_touch = is_big_touch
    old_filter_touch_alpha = filter_touch_alpha
    train_stats = {'target_frames': 0, 'hit_frames': 0, 'exported': 0, 'class0': 0, 'class1': 0}
    moved_stats = {'exported': 0, 'class0': 0, 'class1': 0}

    print("=" * 70)
    print("批量导出 Touch-Hold 裁剪数据集")
    print("=" * 70)
    print(f"固定输出目录: {dataset_root}")
    print(f"标签类别: class 0 = touch框, class 1 = 进度点框")
    print("导出策略: 先全部导出到 train，再从 train 随机抽取 20% 移动到 valid")

    print(f"\n\n{'=' * 70}")
    print("开始处理全部配置（统一导出到 TRAIN）")
    print(f"配置数量: {len(all_configs)}")
    print(f"TRAIN 图像目录: {train_images_dir}")
    print(f"TRAIN 标签目录: {train_labels_dir}")
    print(f"VALID 图像目录: {valid_images_dir}")
    print(f"VALID 标签目录: {valid_labels_dir}")
    print(f"{'=' * 70}")

    for cfg_idx, config in enumerate(all_configs, 1):
        video_path = config['video_path']
        txt_path = config['txt_path']
        source_output_dir = config['output_dir']
        source_images_dir = os.path.join(source_output_dir, 'images')
        align_diff = config['align_diff']
        current_strict_align = config.get('strict_align', True)
        current_strict_align = False if current_strict_align is False else True
        current_is_big_touch = bool(config.get('is_big_touch', False))
        current_touch_alpha = config.get('touch_alpha', 0.4)
        try:
            current_touch_alpha = float(current_touch_alpha)
        except (TypeError, ValueError):
            print(f"警告: touch_alpha 无效({current_touch_alpha})，已回退到 0.4")
            current_touch_alpha = 0.4

        video_name = os.path.splitext(os.path.basename(video_path))[0]
        print(f"\n[ALL] {cfg_idx}/{len(all_configs)}: {video_name}")
        print(f"source images: {source_images_dir}")
        print(f"strict_align: {current_strict_align}")
        print(f"is_big_touch: {current_is_big_touch}")
        print(f"touch_alpha: {current_touch_alpha}")

        if not os.path.exists(video_path):
            print(f"错误: 视频文件不存在，跳过: {video_path}")
            continue
        if not os.path.exists(txt_path):
            print(f"错误: 文本文件不存在，跳过: {txt_path}")
            continue
        if not os.path.isdir(source_images_dir):
            print(f"错误: 未找到 source images 目录，跳过: {source_images_dir}")
            continue

        try:
            base_align_diff, align_schedule, schedule_frames = prepare_align_diff(align_diff)
        except Exception as e:
            print(f"错误: align_diff 配置无效，跳过: {e}")
            continue

        target_frame_numbers = extract_frame_numbers_from_images(source_images_dir)
        if len(target_frame_numbers) == 0:
            print("警告: source images 未解析到帧号，跳过")
            continue

        time_notes = parse_txt(txt_path, strict_align=current_strict_align)
        if len(time_notes) == 0:
            print("警告: txt 无有效音符数据，跳过")
            continue

        cap = cv2.VideoCapture(video_path)
        total_video_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total_video_frames <= 0:
            print("错误: 视频无可用帧，跳过")
            cap.release()
            continue

        frame_timestamps = build_frame_timestamps(
            cap,
            total_video_frames,
            strict_align=current_strict_align,
            progress_step=100
        )

        available_video_frames = len(frame_timestamps)
        if available_video_frames == 0:
            print("错误: 无法读取视频时间戳，跳过")
            cap.release()
            continue

        out_of_range_count = sum(1 for f in target_frame_numbers if f >= available_video_frames)
        target_frame_numbers = [f for f in target_frame_numbers if 0 <= f < available_video_frames]
        if out_of_range_count > 0:
            print(f"警告: {out_of_range_count} 个目标帧越界，已忽略")
        if len(target_frame_numbers) == 0:
            print("警告: 过滤后无可处理目标帧，跳过")
            cap.release()
            continue

        sorted_times = sorted(time_notes.keys())
        max_time_diff = resolve_max_time_diff(cap, strict_align=current_strict_align, fallback_fps=60.0)

        frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        crop_size = frame_width * 210 / 1080
        if current_is_big_touch:
            crop_size *= 1.3
        crop_size = max(1, int(round(crop_size)))

        is_big_touch = current_is_big_touch
        filter_touch_alpha = current_touch_alpha

        train_stats['target_frames'] += len(target_frame_numbers)
        config_hit_frames = 0
        exported_before = train_stats['exported']

        print(f"目标帧数: {len(target_frame_numbers)}")
        print(f"裁剪尺寸: {crop_size}x{crop_size}")

        for idx, frame_number in enumerate(target_frame_numbers, 1):
            
            current_video_timestamp = frame_timestamps[frame_number]
            current_align_diff = resolve_align_diff(frame_number, base_align_diff, align_schedule, schedule_frames)
            notes_virtual_time = current_video_timestamp + current_align_diff
            current_notes = find_closest_notes(time_notes, sorted_times, notes_virtual_time, max_time_diff)

            if len(current_notes) == 0:
                continue

            touch_hold_notes = [n for n in current_notes if n.type and 'touchhold' in n.type.lower()]
            if len(touch_hold_notes) == 0:
                continue

            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
            ret, frame = cap.read()
            if not ret:
                continue

            frame_has_export = False
            for note in touch_hold_notes:
                center_x = 1080 + note.posX
                center_y = 120 - note.posY
                crop_origin_x = int(round(center_x - crop_size / 2))
                crop_origin_y = int(round(center_y - crop_size / 2))
                cropped = crop_with_black_padding(frame, center_x, center_y, crop_size, crop_size)

                labels = parse_touch_hold(cropped, note, crop_origin_x, crop_origin_y)
                if len(labels) == 0:
                    continue

                sample_index = train_stats['exported']
                image_filename = f"{video_name}_f{frame_number:06d}_n{sample_index:07d}.jpg"
                label_filename = f"{video_name}_f{frame_number:06d}_n{sample_index:07d}.txt"

                cv_imwrite(os.path.join(train_images_dir, image_filename), cropped)
                with open(os.path.join(train_labels_dir, label_filename), 'w', encoding='utf-8') as f:
                    f.write('\n'.join(labels))

                train_stats['exported'] += 1
                frame_has_export = True

                for line in labels:
                    if line.startswith("0 "):
                        train_stats['class0'] += 1
                    elif line.startswith("1 "):
                        train_stats['class1'] += 1

            if frame_has_export:
                config_hit_frames += 1

            if idx % 10 <= 1 or idx == len(target_frame_numbers):
                print(
                    f"\r处理进度: {idx}/{len(target_frame_numbers)} 目标帧 |"
                    f" 命中帧: {config_hit_frames} | 已导出: {train_stats['exported']}",
                    end="",
                    flush=True,
                )

        cap.release()
        train_stats['hit_frames'] += config_hit_frames

        print("\n配置完成:")
        print(f"  新增样本: {train_stats['exported'] - exported_before}")
        print(f"  命中帧: {config_hit_frames}/{len(target_frame_numbers)}")

    print("\n开始从 TRAIN 随机抽取 20% 移动到 VALID...")
    train_image_files = [
        f for f in os.listdir(train_images_dir)
        if f.lower().endswith(('.jpg', '.jpeg', '.png', '.bmp', '.webp'))
    ]
    total_train_exported = len(train_image_files)
    valid_target_count = int(total_train_exported * 0.2)

    if valid_target_count > 0:
        move_candidates = random.sample(train_image_files, valid_target_count)
        for idx, image_filename in enumerate(move_candidates, 1):
            image_src = os.path.join(train_images_dir, image_filename)
            image_dst = os.path.join(valid_images_dir, image_filename)
            label_filename = os.path.splitext(image_filename)[0] + '.txt'
            label_src = os.path.join(train_labels_dir, label_filename)
            label_dst = os.path.join(valid_labels_dir, label_filename)

            if os.path.exists(label_src):
                with open(label_src, 'r', encoding='utf-8') as f:
                    for line in f:
                        if line.startswith("0 "):
                            moved_stats['class0'] += 1
                        elif line.startswith("1 "):
                            moved_stats['class1'] += 1

            shutil.move(image_src, image_dst)
            if os.path.exists(label_src):
                shutil.move(label_src, label_dst)
            moved_stats['exported'] += 1

            if idx % 100 == 0 or idx == valid_target_count:
                print(f"\r移动进度: {idx}/{valid_target_count}", end="", flush=True)
        print()
    else:
        print("样本数量不足，未抽取到 valid 样本。")

    print(f"\n[TRAIN] 汇总:")
    print(f"  目标帧: {train_stats['target_frames']}")
    print(f"  命中帧: {train_stats['hit_frames']}")
    print(f"  导出样本(移动前): {train_stats['exported']}")
    print(f"  最终样本(移动后): {train_stats['exported'] - moved_stats['exported']}")
    print(f"  class 0 (touch框): {train_stats['class0'] - moved_stats['class0']}")
    print(f"  class 1 (进度点框): {train_stats['class1'] - moved_stats['class1']}")

    print(f"\n[VALID] 汇总:")
    print(f"  抽样比例: 20%")
    print(f"  导出样本: {moved_stats['exported']}")
    print(f"  class 0 (touch框): {moved_stats['class0']}")
    print(f"  class 1 (进度点框): {moved_stats['class1']}")

    is_big_touch = old_is_big_touch
    filter_touch_alpha = old_filter_touch_alpha

    total_target_frames = train_stats['target_frames']
    total_hit_frames = train_stats['hit_frames']
    total_exported = train_stats['exported']
    total_class0 = train_stats['class0']
    total_class1 = train_stats['class1']

    print(f"\n\n{'=' * 70}")
    print("Touch-Hold 数据集导出完成")
    print(f"输出目录: {dataset_root}")
    print(f"总目标帧: {total_target_frames}")
    print(f"总命中帧: {total_hit_frames}")
    print(f"总导出样本(移动前): {total_exported}")
    print(f"总导出样本(移动后): train={total_exported - moved_stats['exported']}, valid={moved_stats['exported']}")
    print(f"class 0 (touch框): total={total_class0}, train={total_class0 - moved_stats['class0']}, valid={moved_stats['class0']}")
    print(f"class 1 (进度点框): total={total_class1}, train={total_class1 - moved_stats['class1']}, valid={moved_stats['class1']}")
    print(f"{'=' * 70}")


def verify_dataset(output_dir):
    """
    验证并可视化导出的数据集
    
    文件结构要求:
        output_dir/
        ├── images/          # 所有图像文件
        ├── labels_detect/   # detect格式标签
        └── labels_obb/      # obb格式标签
    
    参数:
        output_dir: 数据集根目录
    """
    
    image_exts = ('.jpg', '.png', '.jpeg', '.bmp', '.webp')

    # 标准 detect/obb 结构
    images_dir = os.path.join(output_dir, 'images')
    detect_labels_dir = os.path.join(output_dir, 'labels_detect')
    obb_labels_dir = os.path.join(output_dir, 'labels_obb')

    # touch-hold 结构: train + valid
    train_images_dir = os.path.join(output_dir, 'train', 'images')
    train_labels_dir = os.path.join(output_dir, 'train', 'labels')
    valid_images_dir = os.path.join(output_dir, 'valid', 'images')
    valid_labels_dir = os.path.join(output_dir, 'valid', 'labels')

    has_standard_layout = os.path.isdir(images_dir)
    has_touch_hold_layout = os.path.isdir(train_images_dir) and os.path.isdir(valid_images_dir)

    if not has_standard_layout and not has_touch_hold_layout:
        print("错误：未识别到支持的数据集结构！")
        print(f"标准结构期望: {images_dir}")
        print(f"touch-hold结构期望: {train_images_dir} 与 {valid_images_dir}")
        return

    # 收集所有帧的信息
    all_frames = {}  # {frame_key: {'img': path, 'detect_label': path, 'obb_label': path, ...}}
    dataset_mode = 'standard'

    if has_touch_hold_layout:
        dataset_mode = 'touch_hold'

        split_sources = [
            ('train', train_images_dir, train_labels_dir),
            ('valid', valid_images_dir, valid_labels_dir),
        ]

        for split_name, split_images_dir, split_labels_dir in split_sources:
            if not os.path.isdir(split_images_dir):
                print(f"警告：未找到 {split_name} images 目录: {split_images_dir}")
                continue
            if not os.path.isdir(split_labels_dir):
                print(f"警告：未找到 {split_name} labels 目录: {split_labels_dir}")

            for img_file in os.listdir(split_images_dir):
                if not img_file.lower().endswith(image_exts):
                    continue

                frame_key = os.path.splitext(img_file)[0]
                label_file = frame_key + '.txt'
                unique_frame_key = f"{split_name}:{frame_key}"

                all_frames[unique_frame_key] = {
                    'img': os.path.join(split_images_dir, img_file),
                    'split': split_name,
                    'display_key': frame_key,
                }

                detect_label_path = os.path.join(split_labels_dir, label_file)
                if os.path.exists(detect_label_path):
                    all_frames[unique_frame_key]['detect_label'] = detect_label_path
    else:
        if not os.path.exists(detect_labels_dir):
            print(f"警告：未找到 labels_detect 目录！")
            print(f"期望路径: {detect_labels_dir}")

        if not os.path.exists(obb_labels_dir):
            print(f"警告：未找到 labels_obb 目录！")
            print(f"期望路径: {obb_labels_dir}")

        for img_file in os.listdir(images_dir):
            if not img_file.lower().endswith(image_exts):
                continue

            frame_key = os.path.splitext(img_file)[0]
            label_file = frame_key + '.txt'

            all_frames[frame_key] = {
                'img': os.path.join(images_dir, img_file),
                'display_key': frame_key,
            }

            detect_label_path = os.path.join(detect_labels_dir, label_file)
            if os.path.exists(detect_label_path):
                all_frames[frame_key]['detect_label'] = detect_label_path

            obb_label_path = os.path.join(obb_labels_dir, label_file)
            if os.path.exists(obb_label_path):
                all_frames[frame_key]['obb_label'] = obb_label_path

    if not all_frames:
        print("错误：未找到任何图像文件！")
        return

    def build_frame_sort_key(frame_key):
        frame_info = all_frames[frame_key]
        display_key = frame_info.get('display_key', frame_key)

        # touch-hold 导出名: xxx_f000123_n0000001
        match_f_n = re.search(r'_f(\d+)(?:_n(\d+))?$', display_key)
        if match_f_n:
            frame_no = int(match_f_n.group(1))
            sample_no = int(match_f_n.group(2)) if match_f_n.group(2) is not None else -1
            split_order = 0 if frame_info.get('split') == 'train' else 1
            return (0, frame_no, sample_no, split_order, display_key.lower())

        match_tail_num = re.search(r'(\d+)$', display_key)
        if match_tail_num:
            return (1, int(match_tail_num.group(1)), 0, 0, display_key.lower())

        return (2, 0, 0, 0, display_key.lower())

    sorted_frame_keys = sorted(all_frames.keys(), key=build_frame_sort_key)
    
    print(f"\n找到 {len(sorted_frame_keys)} 帧数据")
    if dataset_mode == 'touch_hold':
        print("检测到 touch-hold 数据集结构: train + valid")
    else:
        print("检测到标准 detect/obb 数据集结构")
    print(f"空格播放/暂停，左右箭头切换帧，D删除选中框，R恢复删除框，Q退出")
    print(f"支持鼠标点击选中/拖动已有框，松开后立即保存到对应txt（仅平移，不改尺寸）\n")

    current_frame_idx = 0
    playback = {'is_playing': False}
    window_name = 'Dataset Verification'
    cv2.namedWindow(window_name, cv2.WINDOW_AUTOSIZE)

    if dataset_mode == 'touch_hold':
        detect_class_names = ['TOUCH_BOX', 'PROGRESS_POINT']
        obb_class_names = ['HOLD']
    else:
        detect_class_names = ['TAP', 'SLIDE', 'TOUCH', 'TOUCH-HOLD']
        obb_class_names = ['HOLD']

    editor_state = {
        'frame_key': None,
        'frame_width': 0,
        'frame_height': 0,
        'frame_info': None,
        'detect_label_path': None,
        'obb_label_path': None,
        'detect_lines': [],
        'obb_lines': [],
        'detect_has_trailing_newline': False,
        'obb_has_trailing_newline': False,
        'detect_items': [],
        'obb_items': [],
        'dragging': False,
        'drag_type': None,
        'drag_idx': -1,
        'offset_x': 0.0,
        'offset_y': 0.0,
        'drag_moved': False,
        'selected_type': None,
        'selected_idx': -1,
        'deleted_stack': [],
    }

    def clamp(value, min_value, max_value):
        if min_value > max_value:
            return (min_value + max_value) * 0.5
        return max(min_value, min(max_value, value))

    def get_obb_center(points):
        if not points:
            return 0.0, 0.0
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        return float(sum(xs)) / len(xs), float(sum(ys)) / len(ys)

    def load_label_file_lines(label_path):
        if not label_path or not os.path.exists(label_path):
            return [], False
        with open(label_path, 'r', encoding='utf-8') as f:
            raw_text = f.read()
        return raw_text.splitlines(), raw_text.endswith('\n')

    def parse_detect_items(lines, frame_width, frame_height):
        items = []
        for line_idx, line in enumerate(lines):
            parts = line.strip().split()
            if len(parts) < 5:
                continue
            try:
                class_id = int(parts[0])
                x_center_norm = float(parts[1])
                y_center_norm = float(parts[2])
                width_norm = float(parts[3])
                height_norm = float(parts[4])
            except ValueError:
                continue

            items.append({
                'line_idx': line_idx,
                'class_id': class_id,
                'x_center': x_center_norm * frame_width,
                'y_center': y_center_norm * frame_height,
                'width': max(1.0, width_norm * frame_width),
                'height': max(1.0, height_norm * frame_height),
            })
        return items

    def parse_obb_items(lines, frame_width, frame_height):
        items = []
        for line_idx, line in enumerate(lines):
            parts = line.strip().split()
            if len(parts) < 9:
                continue
            try:
                class_id = int(parts[0])
                points = []
                for i in range(4):
                    x_norm = float(parts[1 + i * 2])
                    y_norm = float(parts[2 + i * 2])
                    points.append((x_norm * frame_width, y_norm * frame_height))
            except ValueError:
                continue

            items.append({
                'line_idx': line_idx,
                'class_id': class_id,
                'points': points,
            })
        return items

    def save_detect_labels():
        label_path = editor_state['detect_label_path']
        if not label_path or not os.path.exists(label_path):
            return False

        lines = list(editor_state['detect_lines'])
        frame_width = float(editor_state['frame_width'])
        frame_height = float(editor_state['frame_height'])
        if frame_width <= 0 or frame_height <= 0:
            return False

        for item in editor_state['detect_items']:
            line_idx = item['line_idx']
            if line_idx < 0 or line_idx >= len(lines):
                continue
            x_center_norm = clamp(item['x_center'] / frame_width, 0.0, 1.0)
            y_center_norm = clamp(item['y_center'] / frame_height, 0.0, 1.0)
            width_norm = clamp(item['width'] / frame_width, 0.0, 1.0)
            height_norm = clamp(item['height'] / frame_height, 0.0, 1.0)
            lines[line_idx] = (
                f"{item['class_id']} {x_center_norm:.6f} {y_center_norm:.6f} "
                f"{width_norm:.6f} {height_norm:.6f}"
            )

        try:
            text = '\n'.join(lines)
            if editor_state['detect_has_trailing_newline']:
                text += '\n'
            with open(label_path, 'w', encoding='utf-8') as f:
                f.write(text)
            editor_state['detect_lines'] = lines
            return True
        except Exception as e:
            print(f"错误：保存 detect 标签失败: {e}")
            return False

    def save_obb_labels():
        label_path = editor_state['obb_label_path']
        if not label_path or not os.path.exists(label_path):
            return False

        lines = list(editor_state['obb_lines'])
        frame_width = float(editor_state['frame_width'])
        frame_height = float(editor_state['frame_height'])
        if frame_width <= 0 or frame_height <= 0:
            return False

        for item in editor_state['obb_items']:
            line_idx = item['line_idx']
            if line_idx < 0 or line_idx >= len(lines):
                continue

            coords = []
            for px, py in item['points']:
                x_norm = clamp(px / frame_width, 0.0, 1.0)
                y_norm = clamp(py / frame_height, 0.0, 1.0)
                coords.append(f"{x_norm:.6f}")
                coords.append(f"{y_norm:.6f}")
            lines[line_idx] = f"{item['class_id']} {' '.join(coords)}"

        try:
            text = '\n'.join(lines)
            if editor_state['obb_has_trailing_newline']:
                text += '\n'
            with open(label_path, 'w', encoding='utf-8') as f:
                f.write(text)
            editor_state['obb_lines'] = lines
            return True
        except Exception as e:
            print(f"错误：保存 obb 标签失败: {e}")
            return False

    def load_frame_labels(frame_key, frame_info, frame_width, frame_height, reset_deleted_stack=True):
        detect_lines, detect_has_trailing_newline = load_label_file_lines(frame_info.get('detect_label'))
        obb_lines, obb_has_trailing_newline = load_label_file_lines(frame_info.get('obb_label'))

        editor_state['frame_key'] = frame_key
        editor_state['frame_info'] = frame_info
        editor_state['frame_width'] = frame_width
        editor_state['frame_height'] = frame_height
        editor_state['detect_label_path'] = frame_info.get('detect_label')
        editor_state['obb_label_path'] = frame_info.get('obb_label')
        editor_state['detect_lines'] = detect_lines
        editor_state['obb_lines'] = obb_lines
        editor_state['detect_has_trailing_newline'] = detect_has_trailing_newline
        editor_state['obb_has_trailing_newline'] = obb_has_trailing_newline
        editor_state['detect_items'] = parse_detect_items(detect_lines, frame_width, frame_height)
        editor_state['obb_items'] = parse_obb_items(obb_lines, frame_width, frame_height)

        editor_state['dragging'] = False
        editor_state['drag_type'] = None
        editor_state['drag_idx'] = -1
        editor_state['offset_x'] = 0.0
        editor_state['offset_y'] = 0.0
        editor_state['drag_moved'] = False
        editor_state['selected_type'] = None
        editor_state['selected_idx'] = -1
        if reset_deleted_stack:
            editor_state['deleted_stack'] = []

    def find_hit_item(x, y):
        candidates = []

        for idx, item in enumerate(editor_state['detect_items']):
            half_w = item['width'] * 0.5
            half_h = item['height'] * 0.5
            x1 = item['x_center'] - half_w
            y1 = item['y_center'] - half_h
            x2 = item['x_center'] + half_w
            y2 = item['y_center'] + half_h
            if x1 <= x <= x2 and y1 <= y <= y2:
                dx = item['x_center'] - x
                dy = item['y_center'] - y
                candidates.append((dx * dx + dy * dy, 'detect', idx))

        for idx, item in enumerate(editor_state['obb_items']):
            pts = np.array(item['points'], dtype=np.float32).reshape((-1, 1, 2))
            if cv2.pointPolygonTest(pts, (float(x), float(y)), False) >= 0:
                center_x, center_y = get_obb_center(item['points'])
                dx = center_x - x
                dy = center_y - y
                candidates.append((dx * dx + dy * dy, 'obb', idx))

        if not candidates:
            return None, -1

        candidates.sort(key=lambda it: it[0])
        return candidates[0][1], candidates[0][2]

    def move_detect_item(item_idx, target_center_x, target_center_y):
        if item_idx < 0 or item_idx >= len(editor_state['detect_items']):
            return False

        item = editor_state['detect_items'][item_idx]
        frame_width = float(editor_state['frame_width'])
        frame_height = float(editor_state['frame_height'])
        half_w = min(item['width'] * 0.5, max(0.0, (frame_width - 1.0) * 0.5))
        half_h = min(item['height'] * 0.5, max(0.0, (frame_height - 1.0) * 0.5))

        new_x = clamp(target_center_x, half_w, frame_width - 1.0 - half_w)
        new_y = clamp(target_center_y, half_h, frame_height - 1.0 - half_h)

        if abs(new_x - item['x_center']) < 1e-4 and abs(new_y - item['y_center']) < 1e-4:
            return False

        item['x_center'] = new_x
        item['y_center'] = new_y
        return True

    def move_obb_item(item_idx, target_center_x, target_center_y):
        if item_idx < 0 or item_idx >= len(editor_state['obb_items']):
            return False

        item = editor_state['obb_items'][item_idx]
        points = item['points']
        if not points:
            return False

        current_center_x, current_center_y = get_obb_center(points)
        dx = target_center_x - current_center_x
        dy = target_center_y - current_center_y

        frame_width = float(editor_state['frame_width'])
        frame_height = float(editor_state['frame_height'])
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        min_x = min(xs)
        max_x = max(xs)
        min_y = min(ys)
        max_y = max(ys)

        dx = clamp(dx, -min_x, (frame_width - 1.0) - max_x)
        dy = clamp(dy, -min_y, (frame_height - 1.0) - max_y)

        if abs(dx) < 1e-4 and abs(dy) < 1e-4:
            return False

        item['points'] = [(px + dx, py + dy) for px, py in points]
        return True

    def save_line_list(label_path, lines, has_trailing_newline):
        if not label_path:
            return False
        try:
            text = '\n'.join(lines)
            if has_trailing_newline:
                text += '\n'
            with open(label_path, 'w', encoding='utf-8') as f:
                f.write(text)
            return True
        except Exception as e:
            print(f"错误：保存标签失败: {e}")
            return False

    def delete_selected_item():
        selected_type = editor_state['selected_type']
        selected_idx = editor_state['selected_idx']

        if selected_type == 'detect':
            if selected_idx < 0 or selected_idx >= len(editor_state['detect_items']):
                editor_state['selected_type'] = None
                editor_state['selected_idx'] = -1
                return False

            item = editor_state['detect_items'][selected_idx]
            line_idx = item['line_idx']
            lines = list(editor_state['detect_lines'])
            if line_idx < 0 or line_idx >= len(lines):
                return False

            removed_line = lines.pop(line_idx)
            if not save_line_list(editor_state['detect_label_path'], lines, editor_state['detect_has_trailing_newline']):
                return False

            editor_state['deleted_stack'].append({
                'type': 'detect',
                'line_idx': line_idx,
                'line_text': removed_line,
            })

            load_frame_labels(
                editor_state['frame_key'],
                editor_state['frame_info'],
                editor_state['frame_width'],
                editor_state['frame_height'],
                reset_deleted_stack=False,
            )
            print(f"已删除: {editor_state['frame_key']} | detect | line={line_idx}")
            return True

        if selected_type == 'obb':
            if selected_idx < 0 or selected_idx >= len(editor_state['obb_items']):
                editor_state['selected_type'] = None
                editor_state['selected_idx'] = -1
                return False

            item = editor_state['obb_items'][selected_idx]
            line_idx = item['line_idx']
            lines = list(editor_state['obb_lines'])
            if line_idx < 0 or line_idx >= len(lines):
                return False

            removed_line = lines.pop(line_idx)
            if not save_line_list(editor_state['obb_label_path'], lines, editor_state['obb_has_trailing_newline']):
                return False

            editor_state['deleted_stack'].append({
                'type': 'obb',
                'line_idx': line_idx,
                'line_text': removed_line,
            })

            load_frame_labels(
                editor_state['frame_key'],
                editor_state['frame_info'],
                editor_state['frame_width'],
                editor_state['frame_height'],
                reset_deleted_stack=False,
            )
            print(f"已删除: {editor_state['frame_key']} | obb | line={line_idx}")
            return True

        return False

    def restore_last_deleted_item():
        if not editor_state['deleted_stack']:
            print("当前帧没有可恢复的删除记录")
            return False

        restore_item = editor_state['deleted_stack'][-1]
        item_type = restore_item.get('type')
        line_idx = int(restore_item.get('line_idx', 0))
        line_text = restore_item.get('line_text', '')

        if item_type == 'detect':
            lines = list(editor_state['detect_lines'])
            insert_idx = max(0, min(len(lines), line_idx))
            lines.insert(insert_idx, line_text)
            if not save_line_list(editor_state['detect_label_path'], lines, editor_state['detect_has_trailing_newline']):
                return False

            editor_state['deleted_stack'].pop()
            load_frame_labels(
                editor_state['frame_key'],
                editor_state['frame_info'],
                editor_state['frame_width'],
                editor_state['frame_height'],
                reset_deleted_stack=False,
            )

            for idx, item in enumerate(editor_state['detect_items']):
                if item['line_idx'] == insert_idx:
                    editor_state['selected_type'] = 'detect'
                    editor_state['selected_idx'] = idx
                    break

            print(f"已恢复: {editor_state['frame_key']} | detect | line={insert_idx}")
            return True

        if item_type == 'obb':
            lines = list(editor_state['obb_lines'])
            insert_idx = max(0, min(len(lines), line_idx))
            lines.insert(insert_idx, line_text)
            if not save_line_list(editor_state['obb_label_path'], lines, editor_state['obb_has_trailing_newline']):
                return False

            editor_state['deleted_stack'].pop()
            load_frame_labels(
                editor_state['frame_key'],
                editor_state['frame_info'],
                editor_state['frame_width'],
                editor_state['frame_height'],
                reset_deleted_stack=False,
            )

            for idx, item in enumerate(editor_state['obb_items']):
                if item['line_idx'] == insert_idx:
                    editor_state['selected_type'] = 'obb'
                    editor_state['selected_idx'] = idx
                    break

            print(f"已恢复: {editor_state['frame_key']} | obb | line={insert_idx}")
            return True

        return False

    def on_mouse(event, x, y, flags, param):
        if editor_state['frame_key'] is None:
            return

        if event == cv2.EVENT_LBUTTONDOWN:
            hit_type, hit_idx = find_hit_item(x, y)
            if hit_idx < 0:
                editor_state['selected_type'] = None
                editor_state['selected_idx'] = -1
                return

            playback['is_playing'] = False
            editor_state['selected_type'] = hit_type
            editor_state['selected_idx'] = hit_idx
            editor_state['dragging'] = True
            editor_state['drag_type'] = hit_type
            editor_state['drag_idx'] = hit_idx
            editor_state['drag_moved'] = False

            if hit_type == 'detect':
                item = editor_state['detect_items'][hit_idx]
                center_x, center_y = item['x_center'], item['y_center']
            else:
                item = editor_state['obb_items'][hit_idx]
                center_x, center_y = get_obb_center(item['points'])

            editor_state['offset_x'] = float(x) - center_x
            editor_state['offset_y'] = float(y) - center_y

        elif event == cv2.EVENT_MOUSEMOVE and editor_state['dragging']:
            playback['is_playing'] = False
            target_center_x = float(x) - editor_state['offset_x']
            target_center_y = float(y) - editor_state['offset_y']

            if editor_state['drag_type'] == 'detect':
                moved = move_detect_item(editor_state['drag_idx'], target_center_x, target_center_y)
            else:
                moved = move_obb_item(editor_state['drag_idx'], target_center_x, target_center_y)

            if moved:
                editor_state['drag_moved'] = True

        elif event == cv2.EVENT_LBUTTONUP and editor_state['dragging']:
            moved = editor_state['drag_moved']
            drag_type = editor_state['drag_type']
            drag_idx = editor_state['drag_idx']
            frame_key = editor_state['frame_key']

            editor_state['dragging'] = False
            editor_state['drag_type'] = None
            editor_state['drag_idx'] = -1
            editor_state['offset_x'] = 0.0
            editor_state['offset_y'] = 0.0
            editor_state['drag_moved'] = False

            if not moved:
                return

            if drag_type == 'detect':
                saved = save_detect_labels()
            else:
                saved = save_obb_labels()

            if saved:
                print(f"已保存: {frame_key} | {drag_type} | index={drag_idx}")

    cv2.setMouseCallback(window_name, on_mouse)

    while True:
        frame_key = sorted_frame_keys[current_frame_idx]
        frame_info = all_frames[frame_key]

        # 获取图像路径
        img_path = frame_info.get('img')

        if not img_path or not os.path.exists(img_path):
            print(f"警告：无法找到帧 {frame_key} 的图像")
            current_frame_idx = (current_frame_idx + 1) % len(sorted_frame_keys)
            continue

        # 读取图像
        frame = cv_imread(img_path)
        if frame is None:
            print(f"警告：无法读取图像 {img_path}")
            current_frame_idx = (current_frame_idx + 1) % len(sorted_frame_keys)
            continue

        frame_height, frame_width = frame.shape[:2]

        # 切换帧时重新加载标签缓存，确保不会跨帧拖拽
        if editor_state['frame_key'] != frame_key:
            load_frame_labels(frame_key, frame_info, frame_width, frame_height)

        # 绘制detect标签（绿色框）
        detect_count = 0
        for idx, item in enumerate(editor_state['detect_items']):
            half_w = item['width'] * 0.5
            half_h = item['height'] * 0.5
            x1 = int(round(item['x_center'] - half_w))
            y1 = int(round(item['y_center'] - half_h))
            x2 = int(round(item['x_center'] + half_w))
            y2 = int(round(item['y_center'] + half_h))

            is_selected = (
                (editor_state['dragging']
                 and editor_state['drag_type'] == 'detect'
                 and editor_state['drag_idx'] == idx)
                or
                (not editor_state['dragging']
                 and editor_state['selected_type'] == 'detect'
                 and editor_state['selected_idx'] == idx)
            )
            # touch-hold 数据集下，class 1(PROGRESS_POINT) 使用蓝色
            if dataset_mode == 'touch_hold' and item['class_id'] == 1:
                color = (0, 255, 255) if is_selected else (255, 0, 0)
            else:
                color = (0, 255, 255) if is_selected else (0, 255, 0)
            thickness = 3 if is_selected else 2

            cv2.rectangle(frame, (x1, y1), (x2, y2), color, thickness)

            class_id = item['class_id']
            label = detect_class_names[class_id] if 0 <= class_id < len(detect_class_names) else str(class_id)
            cv2.putText(frame, label, (x1, y1 - 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
            detect_count += 1

        # 绘制obb标签（红色框）
        obb_count = 0
        for idx, item in enumerate(editor_state['obb_items']):
            points = item['points']
            if len(points) != 4:
                continue

            int_points = [(int(round(px)), int(round(py))) for px, py in points]
            pts = np.array(int_points, dtype=np.int32)

            is_selected = (
                (editor_state['dragging']
                 and editor_state['drag_type'] == 'obb'
                 and editor_state['drag_idx'] == idx)
                or
                (not editor_state['dragging']
                 and editor_state['selected_type'] == 'obb'
                 and editor_state['selected_idx'] == idx)
            )
            color = (0, 165, 255) if is_selected else (0, 0, 255)
            thickness = 3 if is_selected else 2
            cv2.polylines(frame, [pts], isClosed=True, color=color, thickness=thickness)

            class_id = item['class_id']
            label = obb_class_names[class_id] if 0 <= class_id < len(obb_class_names) else str(class_id)
            cv2.putText(frame, label, (int_points[0][0], int_points[0][1] - 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
            obb_count += 1

        # 显示信息
        play_status = "[PLAYING]" if playback['is_playing'] else "[PAUSED]"
        if dataset_mode != 'touch_hold':
            cv2.putText(frame, f"{play_status} Frame: {current_frame_idx + 1}/{len(sorted_frame_keys)} ({frame_key})",
                        (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
            cv2.putText(frame, f"Detect: {detect_count} notes | OBB: {obb_count} notes",
                        (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

        if editor_state['dragging']:
            cv2.putText(frame, "DRAGGING: release mouse to save", (10, 90),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
        elif editor_state['selected_idx'] >= 0:
            cv2.putText(frame, f"SELECTED: {editor_state['selected_type']} #{editor_state['selected_idx']} | D delete | R restore",
                        (10, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)

        if dataset_mode != 'touch_hold':
            cv2.putText(frame, "Mouse: Drag existing box only (auto save on release)",
                        (10, frame_height - 50), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)
            cv2.putText(frame, "Space: Play/Pause | Arrow: Last frame | D: Delete | R: Restore | Q: Quit",
                        (10, frame_height - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)

        cv2.imshow(window_name, frame)

        # 等待按键
        key = cv2.waitKey(15 if playback['is_playing'] else 1) & 0xFF

        if key == ord('q') or key == ord('Q'):  # 退出
            break
        elif key == 32:  # 空格：播放/暂停
            if not editor_state['dragging']:
                playback['is_playing'] = not playback['is_playing']
        elif key == ord('d') or key == ord('D'):  # 删除当前选中框
            if not editor_state['dragging']:
                playback['is_playing'] = False
                delete_selected_item()
        elif key == ord('r') or key == ord('R'):  # 恢复当前帧最近删除框
            if not editor_state['dragging']:
                playback['is_playing'] = False
                restore_last_deleted_item()
        elif key == 0:  # 箭头: 上一帧
            playback['is_playing'] = False
            current_frame_idx = (current_frame_idx - 1) % len(sorted_frame_keys)

        # 如果正在播放，自动前进
        if playback['is_playing'] and not editor_state['dragging']:
            current_frame_idx = (current_frame_idx + 1) % len(sorted_frame_keys)

    cv2.destroyWindow(window_name)
    print("\n验证完成！")


def count_dataset_statistics(output_dir):
    """
    统计数据集类别分布
    
    遍历labels目录，统计每个类别总共有多少个数据，以及计算占所有类型的样本数量之和的百分比
    
    参数:
        output_dir: 数据集根目录
    """
    
    # 定义新文件结构的路径
    detect_labels_dir = os.path.join(output_dir, 'labels_detect')
    obb_labels_dir = os.path.join(output_dir, 'labels_obb')
    
    # 检查目录是否存在
    if not os.path.exists(detect_labels_dir) and not os.path.exists(obb_labels_dir):
        print("错误：未找到任何labels目录！")
        return
    
    # 初始化统计字典
    detect_stats = {}
    obb_stats = {}
    
    # 统计detect数据集
    if os.path.exists(detect_labels_dir):
        print("正在统计detect数据集...")
        detect_files = [f for f in os.listdir(detect_labels_dir) if f.endswith('.txt')]
        total_detect_files = len(detect_files)
        
        for i, label_file in enumerate(detect_files):
            label_path = os.path.join(detect_labels_dir, label_file)
            with open(label_path, 'r', encoding='utf-8') as f:
                for line in f:
                    parts = line.strip().split()
                    if len(parts) >= 5:
                        class_id = int(parts[0])
                        detect_stats[class_id] = detect_stats.get(class_id, 0) + 1
            
            # 显示进度
            if (i + 1) % 50 == 0 or i + 1 == total_detect_files:
                print(f"\rDetect进度: {i + 1}/{total_detect_files} 文件", end="", flush=True)

    # 统计obb数据集
    if os.path.exists(obb_labels_dir):
        print("正在统计obb数据集...   ")
        obb_files = [f for f in os.listdir(obb_labels_dir) if f.endswith('.txt')]
        total_obb_files = len(obb_files)
        
        for i, label_file in enumerate(obb_files):
            label_path = os.path.join(obb_labels_dir, label_file)
            with open(label_path, 'r', encoding='utf-8') as f:
                for line in f:
                    parts = line.strip().split()
                    if len(parts) >= 9:
                        class_id = int(parts[0])
                        obb_stats[class_id] = obb_stats.get(class_id, 0) + 1
            
            # 显示进度
            if (i + 1) % 50 == 0 or i + 1 == total_obb_files:
                print(f"\rOBB进度: {i + 1}/{total_obb_files} 文件", end="", flush=True)
    
    # 计算总数和百分比
    detect_total = sum(detect_stats.values())
    obb_total = sum(obb_stats.values())
    
    # 打印统计结果
    print("\n数据集统计结果:       ")
    
    # Detect数据集统计
    print("detect:")
    if detect_stats:
        for class_id in sorted(detect_stats.keys()):
            count = detect_stats[class_id]
            percentage = (count / detect_total * 100) if detect_total > 0 else 0
            print(f"  class {class_id}: {count} ({percentage:.2f}%)")
    else:
        print("  无数据")
    print(f"  总计: {detect_total}")
    
    print()
    
    # OBB数据集统计
    print("obb:")
    if obb_stats:
        for class_id in sorted(obb_stats.keys()):
            count = obb_stats[class_id]
            percentage = (count / obb_total * 100) if obb_total > 0 else 0
            print(f"  class {class_id}: {count} ({percentage:.2f}%)")
    else:
        print("  无数据")
    print(f"  总计: {obb_total}")
    
    print("=" * 50)


def extract_frame_numbers_from_images(images_dir):
    """
    从 images 目录文件名中解析帧号。

    规则:
    - 仅处理图片文件（jpg/png/jpeg/bmp/webp）
    - 使用“文件名最后一个下划线后的纯数字”作为帧号
      例如: xxx_123.jpg -> 123

    返回:
        升序且去重后的帧号列表
    """
    if not os.path.isdir(images_dir):
        return []

    image_exts = ('.jpg', '.png', '.jpeg', '.bmp', '.webp')
    frame_numbers = set()
    skipped_count = 0

    for filename in os.listdir(images_dir):
        if not filename.lower().endswith(image_exts):
            continue

        stem = os.path.splitext(filename)[0]
        if '_' not in stem:
            skipped_count += 1
            continue

        frame_part = stem.rsplit('_', 1)[-1]
        if frame_part.isdigit():
            frame_numbers.add(int(frame_part))
        else:
            skipped_count += 1

    sorted_frames = sorted(frame_numbers)
    if skipped_count > 0:
        print(f"警告: {images_dir} 中有 {skipped_count} 个文件名无法解析帧号，已忽略")

    return sorted_frames


def export_classification_dataset(video_path, txt_path, time_offset, break_cls_dir, ex_cls_dir,
                                  dataset_split='train', video_name=None, selected_frame_numbers=None,
                                  strict_align=False):
    """
    导出YOLO分类训练数据集
    
    导出两个分类数据集:
    1. Break分类: 判断是否为Break音符 (yes/no)
    2. EX分类: 判断是否为EX音符 (yes/no)
    
    仅包含: Tap, Slide, Hold 三类音符，排除 Touch 和 Touch-Hold
    
    参数:
        video_path: 视频路径
        txt_path: 音符数据txt路径
        time_offset: 时间偏移量(毫秒)，支持 float 或 list[(frame, diff)]
        break_cls_dir: Break分类数据集输出目录
        ex_cls_dir: EX分类数据集输出目录
        dataset_split: 数据集划分 ('train' 或 'valid')
        video_name: 视频名称（用于文件命名），如果为None则从video_path提取
        selected_frame_numbers: 仅处理这些帧号；为None时处理全部帧
        strict_align: 为True时，视频与txt时间都按固定30fps处理
    """

    base_align_diff, align_schedule, schedule_frames = prepare_align_diff(time_offset)
    
    # 解析txt文件
    time_notes = parse_txt(txt_path, strict_align=strict_align)
    
    if not time_notes:
        print("错误：没有找到任何音符数据！")
        return
    
    # 获取视频名称
    if video_name is None:
        video_name = os.path.splitext(os.path.basename(video_path))[0]
    
    # 创建输出目录结构 (根据dataset_split决定是train还是valid)
    # Break分类: train/yes, train/no 或 valid/yes, valid/no
    break_yes = os.path.join(break_cls_dir, dataset_split, 'yes')
    break_no = os.path.join(break_cls_dir, dataset_split, 'no')
    
    # EX分类: train/yes, train/no 或 valid/yes, valid/no
    ex_yes = os.path.join(ex_cls_dir, dataset_split, 'yes')
    ex_no = os.path.join(ex_cls_dir, dataset_split, 'no')
    
    # 创建所有目录
    for d in [break_yes, break_no, ex_yes, ex_no]:
        os.makedirs(d, exist_ok=True)
    
    # 打开视频
    cap = cv2.VideoCapture(video_path)
    total_video_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    
    # 预先读取所有帧的时间戳（strict_align 时按固定 30fps 推导）
    frame_timestamps = build_frame_timestamps(
        cap,
        total_video_frames,
        strict_align=strict_align,
        progress_step=100
    )

    available_video_frames = len(frame_timestamps)
    if available_video_frames == 0:
        print("错误：无法读取视频时间戳！")
        cap.release()
        return 0, {'yes': 0, 'no': 0}, {'yes': 0, 'no': 0}

    if selected_frame_numbers is None:
        target_frame_numbers = list(range(available_video_frames))
    else:
        parsed_target_frames = []
        invalid_target_count = 0
        for f in selected_frame_numbers:
            try:
                frame_no = int(f)
            except (TypeError, ValueError):
                invalid_target_count += 1
                continue
            if frame_no >= 0:
                parsed_target_frames.append(frame_no)

        target_frame_numbers = sorted(set(parsed_target_frames))
        if invalid_target_count > 0:
            print(f"警告: 目标帧中有 {invalid_target_count} 个非整数值，已忽略")
        out_of_range_count = sum(1 for f in target_frame_numbers if f >= available_video_frames)
        target_frame_numbers = [f for f in target_frame_numbers if f < available_video_frames]
        if out_of_range_count > 0:
            print(f"警告: 目标帧中有 {out_of_range_count} 个超出视频帧范围，已忽略")

    if len(target_frame_numbers) == 0:
        print("警告: 没有可处理的目标帧，跳过当前视频")
        cap.release()
        return 0, {'yes': 0, 'no': 0}, {'yes': 0, 'no': 0}
    
    max_time_diff = resolve_max_time_diff(cap, strict_align=strict_align)
    
    # 重置视频到第一帧
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    
    # 获取所有时间戳并排序
    sorted_times = sorted(time_notes.keys())
    
    # 获取帧尺寸
    frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    
    break_count = {'yes': 0, 'no': 0}
    ex_count = {'yes': 0, 'no': 0}
    note_counter = 0
    
    print(f"\n开始导出分类数据集 ({dataset_split})...")
    print(f"视频尺寸: {frame_width}x{frame_height}")
    print(f"Break分类输出: {break_cls_dir}")
    print(f"EX分类输出: {ex_cls_dir}")
    print(f"目标帧数: {len(target_frame_numbers)}")
    
    # 遍历目标帧
    for idx, frame_number in enumerate(target_frame_numbers, 1):
        # 读取帧
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
        ret, frame = cap.read()
        
        if not ret:
            continue
        
        # 获取当前帧的时间戳
        current_video_timestamp = frame_timestamps[frame_number]
        
        # 计算notes虚拟时间
        current_align_diff = resolve_align_diff(frame_number, base_align_diff, align_schedule, schedule_frames)
        notes_virtual_time = current_video_timestamp + current_align_diff
        
        # 查找最接近的音符
        current_notes = find_closest_notes(time_notes, sorted_times, notes_virtual_time, max_time_diff)
        
        if not current_notes:
            continue
        
        # 处理每个音符
        for note in current_notes:
            note_type = note.type.lower()
            if note_type == 'na':
                continue
            points = None
            center = None
            head = None
            
            # 仅处理 Tap, Slide, Hold 三类音符
            # 排除 Touch 和 Touch-Hold
            if note_type in ['tapnote', 'breaknote']:
                points, center = draw_tap_note(note, notes_virtual_time)
            elif note_type in ['starnote', 'starnote-move', 'breakstarnote', 'breakstarnote-move']:
                points, center = draw_slide_note(note, notes_virtual_time)
            elif note_type in ['holdnote', 'breakholdnote']:
                points, center, head = draw_hold_note(note, notes_virtual_time)
            else:
                # 跳过 Touch 和 Touch-Hold
                continue
            
            if points is None or center is None:
                continue
            
            # 裁剪并保存音符图像
            cropped_img = crop_and_rotate_note(frame, points)
            
            if cropped_img is None or cropped_img.size == 0:
                continue
            
            # 确定是否为Break音符
            is_break = 'break' in note_type
            break_label = 'yes' if is_break else 'no'
            
            # 确定是否为EX音符
            # Special case: starnote-move 一律视为 false (non-EX)
            if note_type in ['starnote-move', 'breakstarnote-move']:
                is_ex = False
            else:
                is_ex = note.isEX
            ex_label = 'yes' if is_ex else 'no'
            
            # 保存到Break分类数据集
            break_save_dir = break_yes if is_break else break_no
            break_filename = f"{video_name}_f{frame_number}_n{note_counter}_break_{break_label}.jpg"
            break_save_path = os.path.join(break_save_dir, break_filename)
            cv_imwrite(break_save_path, cropped_img)
            break_count[break_label] += 1
            
            # 保存到EX分类数据集
            ex_save_dir = ex_yes if is_ex else ex_no
            ex_filename = f"{video_name}_f{frame_number}_n{note_counter}_ex_{ex_label}.jpg"
            ex_save_path = os.path.join(ex_save_dir, ex_filename)
            cv_imwrite(ex_save_path, cropped_img)
            ex_count[ex_label] += 1
            
            note_counter += 1
        
        # 显示进度
        if idx % 10 <= 1 or idx == len(target_frame_numbers):
            print(f"\r处理进度: {idx}/{len(target_frame_numbers)} 目标帧 | 音符数: {note_counter} | Break(yes/no): {break_count['yes']}/{break_count['no']} | EX(yes/no): {ex_count['yes']}/{ex_count['no']}", end="", flush=True)
    
    print(f"\n\n导出完成！")
    print(f"总音符数: {note_counter}")
    print(f"Break分类 - Yes: {break_count['yes']}, No: {break_count['no']}")
    print(f"EX分类 - Yes: {ex_count['yes']}, No: {ex_count['no']}")
    
    cap.release()
    
    return note_counter, break_count, ex_count


def crop_and_rotate_note(frame, points):
    """
    根据四个角点裁剪音符图像
    对于旋转的矩形（如Hold和Touch-Hold），先旋转图像使其水平，然后裁剪
    
    参数:
        frame: 原始图像帧
        points: 4个角点的坐标列表 [(x1,y1), (x2,y2), (x3,y3), (x4,y4)]
        
    返回:
        cropped_img: 裁剪后的音符图像
    """
    
    if not points or len(points) != 4:
        return None
    
    # 转换为numpy数组
    pts = np.array(points, dtype=np.float32)
    
    # 计算边界框
    x_coords = [p[0] for p in points]
    y_coords = [p[1] for p in points]
    
    min_x = max(0, int(min(x_coords)))
    max_x = min(frame.shape[1], int(max(x_coords)))
    min_y = max(0, int(min(y_coords)))
    max_y = min(frame.shape[0], int(max(y_coords)))
    
    # 检查是否需要旋转（判断是否为旋转的矩形）
    # 计算两条边的长度
    width1 = np.linalg.norm(pts[1] - pts[0])
    width2 = np.linalg.norm(pts[3] - pts[2])
    height1 = np.linalg.norm(pts[2] - pts[1])
    height2 = np.linalg.norm(pts[3] - pts[0])
    
    # 取平均宽度和高度
    width = int((width1 + width2) / 2)
    height = int((height1 + height2) / 2)
    
    # 检查是否为旋转矩形（角点不是水平/垂直对齐）
    is_rotated = False
    for i in range(4):
        for j in range(i + 1, 4):
            dx = abs(pts[i][0] - pts[j][0])
            dy = abs(pts[i][1] - pts[j][1])
            # 如果有边既不水平也不垂直，则认为是旋转的
            if dx > 5 and dy > 5:
                is_rotated = True
                break
        if is_rotated:
            break
    
    if is_rotated and width > 0 and height > 0:
        # 对于旋转的矩形，使用透视变换
        # 定义目标矩形的四个角点（水平矩形）
        dst_pts = np.array([
            [0, 0],
            [width - 1, 0],
            [width - 1, height - 1],
            [0, height - 1]
        ], dtype=np.float32)
        
        # 计算透视变换矩阵
        M = cv2.getPerspectiveTransform(pts, dst_pts)
        
        # 应用透视变换
        cropped = cv2.warpPerspective(frame, M, (width, height))
        
        return cropped
    else:
        # 对于非旋转的矩形，直接裁剪
        if max_x > min_x and max_y > min_y:
            cropped = frame[min_y:max_y, min_x:max_x]
            return cropped
        else:
            return None


def reorder_obb_points(points):
    """
    重新排序OBB的四个点：
    点1是最上方的点，点2是最右边的点，点3是最下面的点，点4是最左边的点
    
    参数:
        points: 4个点的坐标列表 [(x1,y1), (x2,y2), (x3,y3), (x4,y4)]
        
    返回:
        重新排序后的4个点列表
    """
    if len(points) != 4:
        return points
    
    # 找到最上方的点（y坐标最小）
    top_point = min(points, key=lambda p: p[1])
    
    # 找到最下方的点（y坐标最大）
    bottom_point = max(points, key=lambda p: p[1])
    
    # 找到最右边的点（x坐标最大）
    right_point = max(points, key=lambda p: p[0])
    
    # 找到最左边的点（x坐标最小）
    left_point = min(points, key=lambda p: p[0])
    
    # 返回重新排序的点：点1（最上方），点2（最右边），点3（最下方），点4（最左边）
    return [top_point, right_point, bottom_point, left_point]


def main(video_path, txt_path, output_dir,
         align_diff=0, star_skinn=0, note_speedd=7.50,
         is_big_touchh=False, mode=None,
         jumps_to=0, export_half_frame=False, filter_touch_alphaa=0.4,
         strict_align=False, all_configs=None, dataset_root=None):
    """
    主函数
    """

    global star_skin
    global note_speed
    global is_big_touch
    global filter_touch_alpha
    star_skin = star_skinn
    note_speed = note_speedd
    is_big_touch = is_big_touchh
    filter_touch_alpha = filter_touch_alphaa


    if mode is None:
        # 询问用户选择操作模式
        print("\n请选择操作模式:")
        print("1. 手动对齐")
        print("2. 导出数据集")
        print("3. 验证数据集")
        print("4. 统计数据集")
        print("5. 导出分类数据集")
        print("6. 导出Touch-Hold数据集")
        choice = input("请输入选择 (1, 2, 3, 4, 5 或 6): ").strip()
    else:
        choice = mode

    if choice == '5':
        # 导出分类数据集模式 - 批量处理所有配置的视频
        confirm = input("\n是否继续? (y/n): ").strip().lower()
        if confirm != 'y':
            print("已取消导出")
            return
        
        # 直接调用批量导出函数
        export_all_classification_datasets(strict_align=strict_align)
        return

    elif choice == '6':
        # 解析 touch-hold 裁剪模式（批量）
        print("\n开始批量解析 Touch-Hold 裁剪...")
        if all_configs is None:
            print("错误: 模式6需要提供 all_configs 参数")
            return
        if dataset_root is None:
            print("错误: 模式6需要提供 dataset_root 参数")
            return
        export_dataset_touch_hold(all_configs=all_configs, dataset_root=dataset_root)
        return

    elif choice == '3' or choice == '4':
        # 验证/统计模式不依赖 video_path 和 txt_path
        target_output_dir = output_dir.strip() if isinstance(output_dir, str) else ""
        if not target_output_dir and isinstance(dataset_root, str):
            target_output_dir = dataset_root.strip()

        if not target_output_dir:
            print("错误: 模式3/4需要提供 output_dir 或 dataset_root")
            return

        if choice == '3':
            print(f"\n验证数据集: {target_output_dir}")
            verify_dataset(target_output_dir)
        else:
            print(f"\n统计数据集: {target_output_dir}")
            count_dataset_statistics(target_output_dir)
        return


    # check file exist
    if not os.path.exists(video_path):
        print(f"Video file not found: {video_path}")
        return

    if not os.path.exists(txt_path):
        print(f"Text file not found: {txt_path}")
        return

    # 解析txt文件
    time_notes = parse_txt(txt_path, strict_align=strict_align)
    
    if len(time_notes) == 0:
        print("错误：没有找到任何音符数据！")
        return
    
    if choice == '1':
        # 手动对齐模式
        time_offset = manual_align(video_path, txt_path, time_notes, align_diff, jumps_to,
                       strict_align=strict_align)
        return
    
    elif choice == '2':
        # 导出数据集模式
        if align_diff == 0 and strict_align == False:
            print("\n警告: 当前 align_diff = 0，可能未对齐！")
            confirm = input("是否继续导出? (y/n): ").strip().lower()
            if confirm != 'y':
                print("已取消导出")
                return

        if mode is None and export_half_frame is False:
            frame_switch = input("是否开启隔帧导出? (y/n, 默认n): ").strip().lower()
            export_half_frame = (frame_switch == 'y')
        
        print(f"\n使用时间偏移: {align_diff}ms")
        print(f"隔帧导出: {'开启' if export_half_frame else '关闭'}")
        print(f"输出目录: {output_dir}")
        
        # 从视频路径提取视频名称
        video_name = os.path.splitext(os.path.basename(video_path))[0]
        
        # 导出数据集
        export_dataset(video_path, txt_path, output_dir, align_diff, video_name, export_half_frame,
                   strict_align=strict_align)
        return
    
    else:
        print("无效的选择！")
        return None





def export_all_classification_datasets(strict_align=False):
    """
    批量导出分类数据集
    
    仅包含: Tap, Slide, Hold (排除 Touch 和 Touch-Hold)
    """
    
    global star_skin
    
    # 定义视频配置
    # Valid集视频
    valid_videos = [

        # dataset 1
        {
            # 11814 背景亮 autoplay:random 达成率递减 perfect/great/good/miss统计
            "video_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset1\source_data\11814\11814_std.mp4",
            "txt_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset1\source_data\11814\11814_2026-04-17_21-03-44.txt",
            "output_dir": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset1\seperate_data\11814",
            "align_diff": 891.34,
            "star_skin": 0 # 蓝色圆头星星
        },

        {
            # 11898 背景亮 autoplay:random 达成率递减 perfect/great/good/miss统计
            "video_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset1\source_data\11898\11898_std.mp4",
            "txt_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset1\source_data\11898\11898_2026-04-17_21-00-08.txt",
            "output_dir": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset1\seperate_data\11898",
            "align_diff": 433.33,
            "star_skin": 0 # 粉色圆头星星
        },

        {
            # 11820 背景暗 autoplay:critical combo数 达成率累加 带开头/结尾动画
            "video_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset1\source_data\11820\11820_std.mp4",
            "txt_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset1\source_data\11820\11820_2026-04-17_19-39-35.txt",
            "output_dir": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset1\seperate_data\11820",
            "align_diff": -7324.32,
            "star_skin": 1 # 粉色尖头星星
        },

        # dataset 2
        {
            "video_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset2\source_data\11898\7 Wonders.mp4",
            "txt_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset2\source_data\11898\11898_2026-04-16_20-29-47.txt",
            "output_dir": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset2\seperate_data\11898",
            "align_diff": [(0, 1833.0), (350, 1816.8), (513, 1833.0), (746, 1816.8), (2461, 1833.0), (2595, 1845), (2908, 1833.0)],
            "jumps_to": 1900,
            "touch_alpha": 0.6,
        },

        {
            "video_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset2\source_data\11986\AiAe.mp4",
            "txt_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset2\source_data\11986\11986_2026-04-16_20-23-20.txt",
            "output_dir": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset2\seperate_data\11986",
            "align_diff": [(0, -150), (231, -133.33), (350, -150), (2120, -160.0), (2340, -127), (2777, -133.33), (4037, -140)],
            "jumps_to": 4000,
            "touch_alpha": 0.7,
        },

        {
            "video_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset2\source_data\11929\11929_std.mp4",
            "txt_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset2\source_data\11929\11929_2026-04-16_20-14-53.txt",
            "output_dir": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset2\seperate_data\11929",
            "align_diff": [(0, 2561.8),(492, 2544.9),(1663, 2528.1),(3337, 2511.2),(4345, 2528.1)],
            "jumps_to": 2300,
            "touch_alpha": 0.2,
        },

    ]
    
    # Train集视频
    train_videos = [

        # dataset 1
        {
            # 11394 背景亮 autoplay:critical combo数 达成率累加 带开头/结尾动画
            "video_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset1\source_data\11394\11394_std.mp4",
            "txt_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset1\source_data\11394\11394_2026-04-17_17-55-13.txt",
            "output_dir": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset1\seperate_data\11394",
            "align_diff": -7208,
            "star_skin": 1, # 粉色尖头星星
        },

        {
            # 11741 背景暗 autoplay:random 达成率递减 perfect/great/good/miss统计
            "video_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset1\source_data\11741\11741_std.mp4",
            "txt_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset1\source_data\11741\11741_2026-04-17_21-07-33.txt",
            "output_dir": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset1\seperate_data\11741",
            "align_diff": 650,
            "star_skin": 0 # 粉色圆头星星
        },

        {
            # 11753 背景亮 autoplay:critical combo数 达成率累加
            "video_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset1\source_data\11753\11753_std.mp4",
            "txt_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset1\source_data\11753\11753_2026-04-17_20-15-41.txt",
            "output_dir": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset1\seperate_data\11753",
            "align_diff": 658.68,
            "star_skin": 0 # 蓝色圆头星星
        },

        {
            # 11818 背景暗 autoplay:random 达成率递减 达成率递减
            "video_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset1\source_data\11818\11818_std.mp4",
            "txt_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset1\source_data\11818\11818_2026-04-17_20-11-43.txt",
            "output_dir": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset1\seperate_data\11818",
            "align_diff": 558,
            "star_skin": 1 # 蓝色尖头星星
        },


        # dataset 2
        {
            "video_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset2\source_data\11905\Daredevil Glaive.mp4",
            "txt_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset2\source_data\11905\11905_2026-04-16_20-32-59.txt",
            "output_dir": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset2\seperate_data\11905",
            "align_diff": [(0, -5400+5), (1890, -5400-5), (2493, -5380), (3725, -5390)],
            "jumps_to": 3700,
            "touch_alpha": 0.5,
        },

        {
            "video_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset2\source_data\10622\バッド・ダンス・ホール.mp4",
            "txt_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset2\source_data\10622\10622_2026-04-16_20-18-39.txt",
            "output_dir": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset2\seperate_data\10622",
            "align_diff": [(0, 620), (960, 610), (2463, 633.3), (3611, 620), (3841, 633.3)],
            "jumps_to": 1800,
            "touch_alpha": 114514,
        },

        {
            "video_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset2\source_data\11969\TECHNOPOLICE 2085.mp4",
            "txt_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset2\source_data\11969\11969_2026-04-16_20-26-55.txt",
            "output_dir": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset2\seperate_data\11969",
            "align_diff": [(0, -133.33), (1243, -145), (2338, -120)],
            "jumps_to": 2300,
            "touch_alpha": 0.6,
        },



        {
            "video_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset2\source_data\11979\11979_std.mp4",
            "txt_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset2\source_data\11979\11979_2026-04-16_20-07-19.txt",
            "output_dir": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset2\seperate_data\11979",
            "align_diff": [(0, 910.11),(251, 893.3),(1546, 876.4),(3654, 859.6),(4353, 876.4)],
            "jumps_to": 2300,
            "touch_alpha": 0.5,
        },

        {
            "video_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset2\source_data\11981\11981_std.mp4",
            "txt_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset2\source_data\11981\11981_2026-04-16_20-10-46.txt",
            "output_dir": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset2\seperate_data\11981",
            "align_diff": [(0, 185.4),(1181, 168.5),(2748,151.7),(3865,134.9),(4345, 168.5)],
            "jumps_to": 2300,
            "touch_alpha": 0.5,
            "star_skin": 1, # 粉色尖头星星
        },

        {
            "video_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset2\source_data\11988\11988_std.mp4",
            "txt_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset2\source_data\11988\11988_2026-04-16_20-04-24.txt",
            "output_dir": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset2\seperate_data\11988",
            "align_diff": [(0, 0), (267, -33.71), (510, -50.6), (1970, -67.4), (2267, -33.7), (3544, -50.6)],
            "jumps_to": 1500,
            "touch_alpha": 0.5,
            "is_big_touch": False,
        },


        # dataset 3
        {
            "video_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset3\source_data\hold_plus\hold_plus_std.mp4",
            "txt_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset3\source_data\hold_plus\2026-04-16_16-18-10.txt",
            "output_dir": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset3\seperate_data\hold_plus",
            "align_diff": 100,
            "star_skin": 1 # 粉色尖头星星
        },

        {
            "video_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset3\source_data\touch_hold_plus\touch_hold_plus_std.mp4",
            "txt_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset3\source_data\touch_hold_plus\2026-04-16_19-18-39.txt",
            "output_dir": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset3\seperate_data\touch_hold_plus",
            "align_diff": -83.34,
            "star_skin": 1 # 粉色尖头星星
        },

        {
            "video_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset3\source_data\slide_plus\slide_plus_std.mp4",
            "txt_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset3\source_data\slide_plus\2026-04-16_19-16-44.txt",
            "output_dir": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset3\seperate_data\slide_plus",
            "align_diff": -16.67,
            "star_skin": 1 # 粉色尖头星星
        },
    ]
    
    # 分类数据集输出目录
    break_cls_dir = r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset_break_cls"
    ex_cls_dir = r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset_ex_cls"
    
    print("=" * 70)
    print("批量导出分类数据集")
    print("=" * 70)
    print(f"Break分类输出: {break_cls_dir}")
    print(f"EX分类输出: {ex_cls_dir}")
    print(f"仅包含音符类型: Tap, Slide, Hold")
    print(f"Valid集视频数: {len(valid_videos)}")
    print(f"Train集视频数: {len(train_videos)}")
    print("=" * 70)
    
    # 处理Valid集视频
    print(f"\n\n{'='*70}")
    print("开始处理 Valid 集")
    print(f"{'='*70}")
    
    for idx, config in enumerate(valid_videos, 1):
        star_skin = config.get('star_skin', 0)
        
        video_path = config['video_path']
        txt_path = config['txt_path']
        align_diff = config['align_diff']
        source_images_dir = os.path.join(config['output_dir'], 'images')
        
        # 检查文件是否存在
        if not os.path.exists(video_path):
            print(f"\n错误: 视频文件不存在: {video_path}")
            continue
        
        if not os.path.exists(txt_path):
            print(f"\n错误: 文本文件不存在: {txt_path}")
            continue

        if not os.path.isdir(source_images_dir):
            print(f"\n错误: 未找到源图片目录: {source_images_dir}")
            continue

        target_frame_numbers = extract_frame_numbers_from_images(source_images_dir)
        if len(target_frame_numbers) == 0:
            print(f"\n警告: 未从 {source_images_dir} 解析到可用帧号，跳过该视频")
            continue

        try:
            prepare_align_diff(align_diff)
        except Exception as e:
            print(f"\n错误: align_diff 配置无效，跳过该视频: {e}")
            continue
        
        video_name = os.path.splitext(os.path.basename(video_path))[0]
        
        print(f"\n\n{'='*70}")
        print(f"[Valid] 处理视频 {idx}/{len(valid_videos)}: {video_name}")
        print(f"时间偏移: {align_diff}ms")
        print(f"星星皮肤: {'圆头' if star_skin == 0 else '尖头'}")
        print(f"源图片目录: {source_images_dir}")
        print(f"解析帧数: {len(target_frame_numbers)}")
        print(f"{'='*70}")
        
        # 导出到valid集
        export_classification_dataset(video_path, txt_path, align_diff, break_cls_dir, ex_cls_dir, 
                         dataset_split='valid', video_name=video_name,
                         selected_frame_numbers=target_frame_numbers,
                         strict_align=strict_align)
    
    # 处理Train集视频
    print(f"\n\n{'='*70}")
    print("开始处理 Train 集")
    print(f"{'='*70}")
    
    for idx, config in enumerate(train_videos, 1):
        star_skin = config.get('star_skin', 0)
        
        video_path = config['video_path']
        txt_path = config['txt_path']
        align_diff = config['align_diff']
        source_images_dir = os.path.join(config['output_dir'], 'images')
        
        # 检查文件是否存在
        if not os.path.exists(video_path):
            print(f"\n错误: 视频文件不存在: {video_path}")
            continue
        
        if not os.path.exists(txt_path):
            print(f"\n错误: 文本文件不存在: {txt_path}")
            continue

        if not os.path.isdir(source_images_dir):
            print(f"\n错误: 未找到源图片目录: {source_images_dir}")
            continue

        target_frame_numbers = extract_frame_numbers_from_images(source_images_dir)
        if len(target_frame_numbers) == 0:
            print(f"\n警告: 未从 {source_images_dir} 解析到可用帧号，跳过该视频")
            continue

        try:
            prepare_align_diff(align_diff)
        except Exception as e:
            print(f"\n错误: align_diff 配置无效，跳过该视频: {e}")
            continue
        
        video_name = os.path.splitext(os.path.basename(video_path))[0]
        
        print(f"\n\n{'='*70}")
        print(f"[Train] 处理视频 {idx}/{len(train_videos)}: {video_name}")
        print(f"时间偏移: {align_diff}ms")
        print(f"星星皮肤: {'圆头' if star_skin == 0 else '尖头'}")
        print(f"源图片目录: {source_images_dir}")
        print(f"解析帧数: {len(target_frame_numbers)}")
        print(f"{'='*70}")
        
        # 导出到train集
        export_classification_dataset(video_path, txt_path, align_diff, break_cls_dir, ex_cls_dir,
                         dataset_split='train', video_name=video_name,
                         selected_frame_numbers=target_frame_numbers,
                         strict_align=strict_align)
    
    print(f"\n\n{'='*70}")
    print("所有视频处理完成！")
    print(f"{'='*70}")
    
    # 统计最终数据集
    print("\n最终数据集统计:")
    print("\nBreak分类数据集:")
    count_classification_samples(break_cls_dir)
    print("\nEX分类数据集:")
    count_classification_samples(ex_cls_dir)


def count_classification_samples(cls_dir):
    """
    统计分类数据集的样本数量
    """
    
    if not os.path.exists(cls_dir):
        print(f"目录不存在: {cls_dir}")
        return
    
    # 统计train和valid数据
    for split in ['train', 'valid']:
        split_dir = os.path.join(cls_dir, split)
        if not os.path.exists(split_dir):
            continue
        
        print(f"\n  {split}:")
        counts = {}
        total = 0
        
        for class_name in ['yes', 'no']:
            class_dir = os.path.join(split_dir, class_name)
            if os.path.exists(class_dir):
                count = len([f for f in os.listdir(class_dir) if f.endswith(('.jpg', '.png', '.jpeg'))])
                counts[class_name] = count
                total += count
            else:
                counts[class_name] = 0
        
        # 打印结果和百分比
        for class_name in ['yes', 'no']:
            count = counts[class_name]
            percentage = (count / total * 100) if total > 0 else 0
            print(f"    {class_name}: {count} ({percentage:.2f}%)")
        
        print(f"    总计: {total}")



if __name__ == "__main__":

    align_diff = 0
    # star_skin 0 圆头星星，1 尖头星星
    # detect: 0 Tap, 1 Slide, 2 Touch, 3 TouchHold
    # obb: 0 Hold

    all_configs = [

        # dataset 1
        {
            # 11394 背景亮 autoplay:critical combo数 达成率累加
            "video_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset1\source_data\11394_1\11394_2026-04-20_12-29-08.mp4",
            "txt_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset1\source_data\11394_1\11394_2026-04-20_12-29-08.txt",
            "output_dir": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset1\seperate_data\11394_1",
            "align_diff": 0,
        },

        {
            # 11741 背景暗 autoplay:random 达成率递减 perfect/great/good/miss统计
            "video_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset1\source_data\11741_1\11741_2026-04-20_12-53-39.mp4",
            "txt_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset1\source_data\11741_1\11741_2026-04-20_12-53-39.txt",
            "output_dir": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset1\seperate_data\11741_1",
            "align_diff": 0,
        },

        {
            # 11746 背景亮 autoplay:random 达成率递减 perfect/great/good/miss统计
            "video_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset1\source_data\11746_1\11746_2026-04-20_12-47-58.mp4",
            "txt_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset1\source_data\11746_1\11746_2026-04-20_12-47-58.txt",
            "output_dir": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset1\seperate_data\11746_1",
            "align_diff": 0,
        },

        {
            # 11753 背景亮 autoplay:critical combo数 达成率累加
            "video_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset1\source_data\11753_1\11753_2026-04-20_12-25-21.mp4",
            "txt_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset1\source_data\11753_1\11753_2026-04-20_12-25-21.txt",
            "output_dir": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset1\seperate_data\11753_1",
            "align_diff": 0,
        },

        {
            # 11818 背景暗 autoplay:random 达成率递减 达成率递减
            "video_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset1\source_data\11818_1\11818_2026-04-20_12-21-27.mp4",
            "txt_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset1\source_data\11818_1\11818_2026-04-20_12-21-27.txt",
            "output_dir": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset1\seperate_data\11818_1",
            "align_diff": 0,
        },

        {
            # 11814 背景亮 autoplay:random 达成率递减 perfect/great/good/miss统计
            "video_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset1\source_data\11814_1\11814_2026-04-20_12-36-58.mp4",
            "txt_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset1\source_data\11814_1\11814_2026-04-20_12-36-58.txt",
            "output_dir": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset1\seperate_data\11814_1",
            "align_diff": 0,
        },

        {
            # 11820 背景暗 autoplay:critical combo数 达成率累加 带开头/结尾动画
            "video_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset1\source_data\11820_1\11820_2026-04-20_12-15-19.mp4",
            "txt_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset1\source_data\11820_1\11820_2026-04-20_12-15-19.txt",
            "output_dir": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset1\seperate_data\11820_1",
            "align_diff": 0,
        },

        {
            # 11885 背景亮 autoplay:random 达成率递减 perfect/great/good/miss统计
            "video_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset1\source_data\11885_1\11885_2026-04-20_12-41-58.mp4",
            "txt_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset1\source_data\11885_1\11885_2026-04-20_12-41-58.txt",
            "output_dir": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset1\seperate_data\11885_1",
            "align_diff": 0,
        },

        {
            # 11898 背景亮 autoplay:random 达成率递减 perfect/great/good/miss统计
            "video_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset1\source_data\11898_1\11898_2026-04-20_12-33-28.mp4",
            "txt_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset1\source_data\11898_1\11898_2026-04-20_12-33-28.txt",
            "output_dir": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset1\seperate_data\11898_1",
            "align_diff": 0,
        },

        # dataset 2
        {
            "video_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset2\source_data\11905\Daredevil Glaive.mp4",
            "txt_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset2\source_data\11905\11905_2026-04-16_20-32-59.txt",
            "output_dir": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset2\seperate_data\11905",
            "align_diff": [(0, -5400+5), (1890, -5400-5), (2493, -5380), (3725, -5390)],
            "touch_alpha": 0.5,
            "strict_align": False,
            "is_big_touch": True,
        },

        {
            "video_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset2\source_data\11898\7 Wonders.mp4",
            "txt_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset2\source_data\11898\11898_2026-04-16_20-29-47.txt",
            "output_dir": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset2\seperate_data\11898",
            "align_diff": [(0, 1833.0), (350, 1816.8), (513, 1833.0), (746, 1816.8), (2461, 1833.0), (2595, 1845), (2908, 1833.0)],
            "touch_alpha": 0.6,
            "strict_align": False,
            "is_big_touch": True,
        },

        {
            "video_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset2\source_data\10622\バッド・ダンス・ホール.mp4",
            "txt_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset2\source_data\10622\10622_2026-04-16_20-18-39.txt",
            "output_dir": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset2\seperate_data\10622",
            "align_diff": [(0, 620), (960, 610), (2463, 633.3), (3611, 620), (3841, 633.3)],
            "touch_alpha": 114514,
            "strict_align": False,
            "is_big_touch": True,
        },

        {
            "video_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset2\source_data\11969\TECHNOPOLICE 2085.mp4",
            "txt_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset2\source_data\11969\11969_2026-04-16_20-26-55.txt",
            "output_dir": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset2\seperate_data\11969",
            "align_diff": [(0, -133.33), (1243, -145), (2338, -120)],
            "touch_alpha": 0.6,
            "strict_align": False,
            "is_big_touch": True,
        },

        {
            "video_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset2\source_data\11986\AiAe.mp4",
            "txt_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset2\source_data\11986\11986_2026-04-16_20-23-20.txt",
            "output_dir": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset2\seperate_data\11986",
            "align_diff": [(0, -150), (231, -133.33), (350, -150), (2120, -160.0), (2340, -127), (2777, -133.33), (4037, -140)],
            "touch_alpha": 0.7,
            "strict_align": False,
            "is_big_touch": True,
        },



        {
            "video_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset2\source_data\11929\11929_std.mp4",
            "txt_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset2\source_data\11929\11929_2026-04-16_20-14-53.txt",
            "output_dir": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset2\seperate_data\11929",
            "align_diff": [(0, 2561.8),(492, 2544.9),(1663, 2528.1),(3337, 2511.2),(4345, 2528.1)],
            "touch_alpha": 0.2,
            "strict_align": False,
            "is_big_touch": True,
        },

        {
            "video_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset2\source_data\11979\11979_std.mp4",
            "txt_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset2\source_data\11979\11979_2026-04-16_20-07-19.txt",
            "output_dir": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset2\seperate_data\11979",
            "align_diff": [(0, 910.11),(251, 893.3),(1546, 876.4),(3654, 859.6),(4353, 876.4)],
            "touch_alpha": 0.5,
            "strict_align": False,
            "is_big_touch": True,
        },

        {
            "video_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset2\source_data\11981\11981_std.mp4",
            "txt_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset2\source_data\11981\11981_2026-04-16_20-10-46.txt",
            "output_dir": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset2\seperate_data\11981",
            "align_diff": [(0, 185.4),(1181, 168.5),(2748,151.7),(3865,134.9),(4345, 168.5)],
            "touch_alpha": 0.5,
            "strict_align": False,
            "is_big_touch": True,
        },

        {
            "video_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset2\source_data\11988\11988_std.mp4",
            "txt_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset2\source_data\11988\11988_2026-04-16_20-04-24.txt",
            "output_dir": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset2\seperate_data\11988",
            "align_diff": [(0, 0), (267, -33.71), (510, -50.6), (1970, -67.4), (2267, -33.7), (3544, -50.6)],
            "touch_alpha": 0.5,
            "is_big_touch": False,
            "strict_align": False,
        },

        # dataset 3
        {
            "video_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset3\source_data\hold_plus\2026-04-19_17-09-28.mp4",
            "txt_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset3\source_data\hold_plus\2026-04-19_17-09-28.txt",
            "output_dir": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset3\seperate_data\hold_plus",
            "align_diff": 0,
        },

        {
            "video_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset3\source_data\touch_hold_plus\2026-04-20_12-10-40.mp4",
            "txt_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset3\source_data\touch_hold_plus\2026-04-20_12-10-40.txt",
            "output_dir": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset3\seperate_data\touch_hold_plus",
            "align_diff": 0,
        },

        {
            "video_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset3\source_data\slide_plus\2026-04-21_05-49-20.mp4",
            "txt_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset3\source_data\slide_plus\2026-04-21_05-49-20.txt",
            "output_dir": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset3\seperate_data\slide_plus",
            "align_diff": 0,
        },
    ]

    dataset_root = r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset_touch_hold"

    main("", "", "", all_configs=all_configs, dataset_root=dataset_root)


    # dataset1 = [
    #     {
    #         # 11394 背景亮 autoplay:critical combo数 达成率累加
    #         "video_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset1\source_data\11394_1\11394_2026-04-20_12-29-08.mp4",
    #         "txt_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset1\source_data\11394_1\11394_2026-04-20_12-29-08.txt",
    #         "output_dir": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset1\seperate_data\11394_1",
    #         "align_diff": 0,
    #         "star_skin": 1, # 粉色尖头星星
    #     },

    #     {
    #         # 11741 背景暗 autoplay:random 达成率递减 perfect/great/good/miss统计
    #         "video_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset1\source_data\11741_1\11741_2026-04-20_12-53-39.mp4",
    #         "txt_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset1\source_data\11741_1\11741_2026-04-20_12-53-39.txt",
    #         "output_dir": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset1\seperate_data\11741_1",
    #         "align_diff": 0,
    #         "star_skin": 0 # 粉色圆头星星
    #     },

    #     {
    #         # 11746 背景亮 autoplay:random 达成率递减 perfect/great/good/miss统计
    #         "video_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset1\source_data\11746_1\11746_2026-04-20_12-47-58.mp4",
    #         "txt_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset1\source_data\11746_1\11746_2026-04-20_12-47-58.txt",
    #         "output_dir": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset1\seperate_data\11746_1",
    #         "align_diff": 0,
    #         "star_skin": 1, # 粉色尖头星星
    #     },

    #     {
    #         # 11753 背景亮 autoplay:critical combo数 达成率累加
    #         "video_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset1\source_data\11753_1\11753_2026-04-20_12-25-21.mp4",
    #         "txt_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset1\source_data\11753_1\11753_2026-04-20_12-25-21.txt",
    #         "output_dir": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset1\seperate_data\11753_1",
    #         "align_diff": 0,
    #         "star_skin": 0 # 蓝色圆头星星
    #     },

    #     {
    #         # 11818 背景暗 autoplay:random 达成率递减 达成率递减
    #         "video_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset1\source_data\11818_1\11818_2026-04-20_12-21-27.mp4",
    #         "txt_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset1\source_data\11818_1\11818_2026-04-20_12-21-27.txt",
    #         "output_dir": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset1\seperate_data\11818_1",
    #         "align_diff": 0,
    #         "star_skin": 1 # 蓝色尖头星星
    #     },

    #     {
    #         # 11814 背景亮 autoplay:random 达成率递减 perfect/great/good/miss统计
    #         "video_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset1\source_data\11814_1\11814_2026-04-20_12-36-58.mp4",
    #         "txt_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset1\source_data\11814_1\11814_2026-04-20_12-36-58.txt",
    #         "output_dir": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset1\seperate_data\11814_1",
    #         "align_diff": 0,
    #         "star_skin": 0 # 蓝色圆头星星
    #     },

    #     {
    #         # 11820 背景暗 autoplay:critical combo数 达成率累加 带开头/结尾动画
    #         "video_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset1\source_data\11820_1\11820_2026-04-20_12-15-19.mp4",
    #         "txt_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset1\source_data\11820_1\11820_2026-04-20_12-15-19.txt",
    #         "output_dir": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset1\seperate_data\11820_1",
    #         "align_diff": 0,
    #         "star_skin": 1 # 粉色尖头星星
    #     },

    #     {
    #         # 11885 背景亮 autoplay:random 达成率递减 perfect/great/good/miss统计
    #         "video_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset1\source_data\11885_1\11885_2026-04-20_12-41-58.mp4",
    #         "txt_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset1\source_data\11885_1\11885_2026-04-20_12-41-58.txt",
    #         "output_dir": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset1\seperate_data\11885_1",
    #         "align_diff": 0,
    #         "star_skin": 1, # 粉色尖头星星
    #     },

    #     {
    #         # 11898 背景亮 autoplay:random 达成率递减 perfect/great/good/miss统计
    #         "video_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset1\source_data\11898_1\11898_2026-04-20_12-33-28.mp4",
    #         "txt_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset1\source_data\11898_1\11898_2026-04-20_12-33-28.txt",
    #         "output_dir": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset1\seperate_data\11898_1",
    #         "align_diff": 0,
    #         "star_skin": 0 # 粉色圆头星星
    #     },
    # ]

    # for song in dataset1:
    #     video_path = song["video_path"]
    #     txt_path = song["txt_path"]
    #     output_dir = song["output_dir"]
    #     align_diff = song["align_diff"]
    #     star_skin = song["star_skin"]
    #     main(video_path, txt_path, output_dir, align_diff, star_skin, mode="3", strict_align=True)








    # # dataset 2
    # dataset2 = [
    #     {
    #         "video_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset2\source_data\11905\Daredevil Glaive.mp4",
    #         "txt_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset2\source_data\11905\11905_2026-04-16_20-32-59.txt",
    #         "output_dir": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset2\seperate_data\11905",
    #         "align_diff": [(0, -5400+5), (1890, -5400-5), (2493, -5380), (3725, -5390)],
    #         "jumps_to": 3700,
    #         "touch_alpha": 0.5,
    #     },

    #     {
    #         "video_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset2\source_data\11898\7 Wonders.mp4",
    #         "txt_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset2\source_data\11898\11898_2026-04-16_20-29-47.txt",
    #         "output_dir": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset2\seperate_data\11898",
    #         "align_diff": [(0, 1833.0), (350, 1816.8), (513, 1833.0), (746, 1816.8), (2461, 1833.0), (2595, 1845), (2908, 1833.0)],
    #         "jumps_to": 1900,
    #         "touch_alpha": 0.6,
    #     },

    #     {
    #         "video_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset2\source_data\10622\バッド・ダンス・ホール.mp4",
    #         "txt_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset2\source_data\10622\10622_2026-04-16_20-18-39.txt",
    #         "output_dir": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset2\seperate_data\10622",
    #         "align_diff": [(0, 620), (960, 610), (2463, 633.3), (3611, 620), (3841, 633.3)],
    #         "jumps_to": 1800,
    #         "touch_alpha": 114514,
    #     },

    #     {
    #         "video_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset2\source_data\11969\TECHNOPOLICE 2085.mp4",
    #         "txt_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset2\source_data\11969\11969_2026-04-16_20-26-55.txt",
    #         "output_dir": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset2\seperate_data\11969",
    #         "align_diff": [(0, -133.33), (1243, -145), (2338, -120)],
    #         "jumps_to": 2300,
    #         "touch_alpha": 0.6,
    #     },

    #     {
    #         "video_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset2\source_data\11986\AiAe.mp4",
    #         "txt_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset2\source_data\11986\11986_2026-04-16_20-23-20.txt",
    #         "output_dir": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset2\seperate_data\11986",
    #         "align_diff": [(0, -150), (231, -133.33), (350, -150), (2120, -160.0), (2340, -127), (2777, -133.33), (4037, -140)],
    #         "jumps_to": 4000,
    #         "touch_alpha": 0.7,
    #     },



    #     {
    #         "video_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset2\source_data\11929\11929_std.mp4",
    #         "txt_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset2\source_data\11929\11929_2026-04-16_20-14-53.txt",
    #         "output_dir": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset2\seperate_data\11929",
    #         "align_diff": [(0, 2561.8),(492, 2544.9),(1663, 2528.1),(3337, 2511.2),(4345, 2528.1)],
    #         "jumps_to": 2300,
    #         "touch_alpha": 0.2,
    #     },

    #     {
    #         "video_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset2\source_data\11979\11979_std.mp4",
    #         "txt_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset2\source_data\11979\11979_2026-04-16_20-07-19.txt",
    #         "output_dir": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset2\seperate_data\11979",
    #         "align_diff": [(0, 910.11),(251, 893.3),(1546, 876.4),(3654, 859.6),(4353, 876.4)],
    #         "jumps_to": 2300,
    #         "touch_alpha": 0.5,
    #     },

    #     {
    #         "video_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset2\source_data\11981\11981_std.mp4",
    #         "txt_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset2\source_data\11981\11981_2026-04-16_20-10-46.txt",
    #         "output_dir": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset2\seperate_data\11981",
    #         "align_diff": [(0, 185.4),(1181, 168.5),(2748,151.7),(3865,134.9),(4345, 168.5)],
    #         "jumps_to": 2300,
    #         "touch_alpha": 0.5,
    #         "star_skin": 1, # 粉色尖头星星
    #     },

    #     {
    #         "video_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset2\source_data\11988\11988_std.mp4",
    #         "txt_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset2\source_data\11988\11988_2026-04-16_20-04-24.txt",
    #         "output_dir": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset2\seperate_data\11988",
    #         "align_diff": [(0, 0), (267, -33.71), (510, -50.6), (1970, -67.4), (2267, -33.7), (3544, -50.6)],
    #         "jumps_to": 1500,
    #         "touch_alpha": 0.5,
    #         "is_big_touch": False,
    #     },
    # ]
    # speed_2 = 3.0

    # for song in dataset2:
    #     video_path = song["video_path"]
    #     txt_path = song["txt_path"]
    #     output_dir = song["output_dir"]
    #     align_diff = song["align_diff"]
    #     filter_touch_alpha = song["touch_alpha"]
    #     star_skin = song.get("star_skin", 0) # 默认蓝色圆头星星
    #     is_big_touch = song.get("is_big_touch", True) # 默认大号 touch
    #     # jumps_to = song.get("jumps_to", 0)
    #     jumps_to = 0
        
    #     main(video_path, txt_path, output_dir, align_diff, star_skin, speed_2, mode="3",
    #          jumps_to=jumps_to, is_big_touchh=is_big_touch, filter_touch_alphaa=filter_touch_alpha)










    # # dataset 3
    # dataset3 = [
    #     {
    #         "video_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset3\source_data\hold_plus\2026-04-19_17-09-28.mp4",
    #         "txt_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset3\source_data\hold_plus\2026-04-19_17-09-28.txt",
    #         "output_dir": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset3\seperate_data\hold_plus",
    #         "align_diff": 0,
    #         "star_skin": 1 # 粉色尖头星星
    #     },

    #     {
    #         "video_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset3\source_data\touch_hold_plus\2026-04-20_12-10-40.mp4",
    #         "txt_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset3\source_data\touch_hold_plus\2026-04-20_12-10-40.txt",
    #         "output_dir": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset3\seperate_data\touch_hold_plus",
    #         "align_diff": 0,
    #         "star_skin": 1 # 粉色尖头星星
    #     },

    #     {
    #         "video_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset3\source_data\slide_plus\2026-04-21_05-49-20.mp4",
    #         "txt_path": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset3\source_data\slide_plus\2026-04-21_05-49-20.txt",
    #         "output_dir": r"C:\git\aaa-HachimiDX-Convert\archive\yolo-train\dataset3\seperate_data\slide_plus",
    #         "align_diff": 0,
    #         "star_skin": 1 # 粉色尖头星星
    #     },
    # ]
    # speed_3 = 4.0

    # for song in dataset3:
    #     video_path = song["video_path"]
    #     txt_path = song["txt_path"]
    #     output_dir = song["output_dir"]
    #     align_diff = song["align_diff"]
    #     star_skin = song["star_skin"]
    #     main(video_path, txt_path, output_dir, align_diff, star_skin, speed_3, mode="3", strict_align=True)
