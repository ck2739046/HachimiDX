import numpy as np

from .shared_context import *
from .analyze_touch import predict_touch_reach_end_time
from ..detect.note_definition import *



def get_suffix(note_variant: NoteVariant):

    if note_variant == NoteVariant.NORMAL:
        suffix = 'h'
    elif note_variant == NoteVariant.BREAK:
        suffix = 'bh'
    elif note_variant == NoteVariant.EX:
        suffix = 'xh'
    elif note_variant == NoteVariant.BREAK_EX:
        suffix = 'bxh'
    else:
        suffix = '?'
    
    return suffix




def analyze_touch_hold_time(shared_context, touch_hold_data):
    """
    返回：
    dict{
        key: 同 preprocess_touch_hold_data,
        value: (time, duration)
    }
    """

    touch_hold_info = {}
    
    for key, path in touch_hold_data.items():

        dist_times = []
        percent_data = []

        for point in path:
            frame_num = point['frame']
            dist = point['dist']
            percent = point['percent']

            # 将 percent 数据单独处理
            if percent != -1:
                cur_time = shared_context.frame_to_msec(point['frame'])
                percent_data.append((cur_time, percent))

            # 将 dist 数据视为 touch note 处理
            if dist != -1:
                reach_end_Msec = predict_touch_reach_end_time(shared_context, dist, frame_num, shared_context.touch_hold_travel_dist)
                if reach_end_Msec != 0 and np.isfinite(reach_end_Msec):
                    dist_times.append(reach_end_Msec)

        if not dist_times:
            print(f"analyze_touch_hold_time: no valid dist data for track_id {key[0]}")
            continue

        percent_times, percent_speeds = predict_touch_hold_percent_reach_end_time(percent_data)
        if not percent_times:
            print(f"analyze_touch_hold_time: no valid percent data for track_id {key[0]}")
            continue

        # 计算平均值
        mean_dist = float(np.mean(dist_times))
        # 有极端值，使用中位数更稳定
        median_percent = float(np.median(percent_times))

        if not np.isfinite(mean_dist) or not np.isfinite(median_percent):
            print(f"analyze_touch_hold_time: invalid computed time for track_id {key[0]}")
            continue

        duration = median_percent - mean_dist
        if not np.isfinite(duration):
            print(f"analyze_touch_hold_time: invalid duration for track_id {key[0]}")
            continue
        
        track_id, note_type, note_variant, position = key
        new_position = f"{position}{get_suffix(note_variant)}"
        new_key = (track_id, note_type, note_variant, new_position)

        touch_hold_info[new_key] = (mean_dist, duration)

        # print(f"Touch Hold ID {track_id} Position {position}:")

        # mean = np.mean(percent_speeds)
        # min = np.min(percent_speeds)
        # max = np.max(percent_speeds)
        # median = np.median(percent_speeds)
        # std_dev = np.std(percent_speeds)
        # print(f"  speed Median {median:.3f}, Min {min:.3f}, Max {max:.3f}, Mean {mean:.3f}, Std Dev {std_dev:.3f}")

        # min_dist = np.min(dist_times)
        # max_dist = np.max(dist_times)
        # median_dist = np.median(dist_times)
        # std_dev_dist = np.std(dist_times)
        # print(f"  dist Mean {mean_dist:.3f}, Min {min_dist:.3f}, Max {max_dist:.3f}, Median {median_dist:.3f}, Std Dev {std_dev_dist:.3f}")

        # min_percent = np.min(percent_times)
        # max_percent = np.max(percent_times)
        # median_percent = np.median(percent_times)
        # std_dev_percent = np.std(percent_times)
        # print(f"  percent Mean {mean_percent:.3f}, Min {min_percent:.3f}, Max {max_percent:.3f}, Median {median_percent:.3f}, Std Dev {std_dev_percent:.3f}")

    return touch_hold_info






def predict_touch_hold_percent_reach_end_time(percent_data):

    # 点配对并计算 speed
    speeds = []
    if len(percent_data) < 2:
        return [], []

    percent_data.sort(key=lambda x: x[1]) # 按 percent 排序
    for i in range(len(percent_data)):
        for j in range(i + 1, len(percent_data)):
            time1, progress1 = percent_data[i]
            time2, progress2 = percent_data[j]
            if abs(progress1 - progress2) < 0.05:
                continue # 忽略相近的 progress 减少误差 (5%) 
            speed = abs(time1 - time2) / abs(progress1 - progress2)
            if np.isfinite(speed):
                speeds.append(speed)

    if not speeds:
        return [], []

    final_speed = float(np.median(speeds))
    if not np.isfinite(final_speed):
        return [], []

    # 预测到达时间
    reach_end_times = []
    for time, progress in percent_data:
        remaining_progress = 1 - progress
        reach_end_time = time + remaining_progress * final_speed
        if np.isfinite(reach_end_time):
            reach_end_times.append(reach_end_time)

    return reach_end_times, speeds
