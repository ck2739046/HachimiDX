import numpy as np

from .shared_context import *
from .analyze_tap import predict_tap_reach_end_time
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





def analyze_hold_time(shared_context, hold_data):
    """
    返回：
    dict{
        key: 同 preprocess_hold_data,
        value: (time, duration)
    }
    """

    hold_info = {}

    end_tolerance = shared_context.note_travel_dist * 0.1
    start_tolerance = shared_context.note_travel_dist * 0.1
    valid_judgeline_start = shared_context.judgeline_start + start_tolerance
    valid_judgeline_end = shared_context.judgeline_end - end_tolerance

    for key, path in hold_data.items():

        head_times = []
        tail_times = []

        # 平均所有轨迹的到达时间
        for point in path:
            frame_num = point['frame']
            dist_head = point['dist-head']
            dist_tail = point['dist-tail']

            # 再次过滤 head 和 tail (10%-90%)
            if valid_judgeline_start <= dist_head <= valid_judgeline_end:
                reach_end_Msec_head = predict_tap_reach_end_time(shared_context, dist_head, frame_num)
                head_times.append(reach_end_Msec_head)

            if valid_judgeline_start <= dist_tail <= valid_judgeline_end:
                reach_end_Msec_tail = predict_tap_reach_end_time(shared_context, dist_tail, frame_num)
                tail_times.append(reach_end_Msec_tail)
        
        # 计算平均时间
        mean_head = np.mean(head_times)
        mean_tail = np.mean(tail_times)

        duration = max(0, mean_tail - mean_head)
        
        track_id, note_type, note_variant, position = key
        new_position = f"{position}{get_suffix(note_variant)}"
        new_key = (track_id, note_type, note_variant, new_position)

        hold_info[new_key] = (mean_head, duration)

        # print(f"Hold ID {track_id} Direction {direction}:")
        # min1 = np.min(head_times)
        # max1 = np.max(head_times)
        # median1 = np.median(head_times)
        # std_dev1 = np.std(head_times)
        # print(f"  head - Mean {mean_head:.3f}, Min {min1:.3f}, Max {max1:.3f}, Median {median1:.3f}, Std Dev {std_dev1:.3f}")

        # min2 = np.min(tail_times)
        # max2 = np.max(tail_times)
        # median2 = np.median(tail_times)
        # std_dev2 = np.std(tail_times)
        # print(f"  tail - Mean {mean_tail:.3f}, Min {min2:.3f}, Max {max2:.3f}, Median {median2:.3f}, Std Dev {std_dev2:.3f}")

    return hold_info
