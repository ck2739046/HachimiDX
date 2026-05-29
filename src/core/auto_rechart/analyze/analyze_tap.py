import numpy as np

from .shared_context import *
from ..detect.note_definition import *



def get_suffix(note_variant: NoteVariant):

    if note_variant == NoteVariant.NORMAL:
        suffix = ''
    elif note_variant == NoteVariant.BREAK:
        suffix = 'b'
    elif note_variant == NoteVariant.EX:
        suffix = 'x'
    elif note_variant == NoteVariant.BREAK_EX:
        suffix = 'bx'
    else:
        suffix = '?'
    
    return suffix





def analyze_tap_time(shared_context, tap_data):
    """
    返回:
    dict{
        key: 同 preprocess_tap_data,
        value: time
    }
    """

    tap_info = {}
    for key, path in tap_data.items():

        times = []

        # 平均所有轨迹的到达时间
        for point in path:
            frame_num = point['frame']
            dist = point['dist']

            reach_end_Msec = predict_tap_reach_end_time(shared_context, dist, frame_num)
            times.append(reach_end_Msec)

        mean = np.mean(times)

        track_id, note_type, note_variant, position = key
        new_position = f"{position}{get_suffix(note_variant)}"
        new_key = (track_id, note_type, note_variant, new_position)

        tap_info[new_key] = mean

        
        # min = np.min(times)
        # max = np.max(times)
        # median = np.median(times)
        # std_dev = np.std(times)
        # if max - min > 4:
        #     print(f"Tap ID {track_id} Direction {direction}:")
        #     print(f"  Mean {mean:.3f}, Min {min:.3f}, Max {max:.3f}, Median {median:.3f}, Std Dev {std_dev:.3f}")


    return tap_info




def predict_tap_reach_end_time(shared_context, cur_dist, cur_frame):
    '''
    正向:
    [dist_offset] = -1/120 * 总距离 * (OptionNotespeed/150f -1)
    [time_offset] = (OptionNotespeed/150f -1) * (-0.5 / (OptionNotespeed/150f -1)) * 1.6 * 1000 / 60
    高速的dist和time偏移都是负值 (实测后取消应用 time_offset)

    时间进度 = (current_Msec - leave_start_Msec + time_offset) / [DefaultMsec]
    travelled_dist = 时间进度 * [total_dist]
    current_dist = [startPos] + travelled_dist + [dist_offset]

    逆向:
    已知 current_dist, [dist_offset], [startPos]
    -> travelled_dist = current_dist - startPos - dist_offset
    已知 travelled_dist, [total_dist]
    -> 时间进度 = travelled_dist / total_dist
    已知 时间进度, [DefaultMsec], current_Msec, [time_offset]
    -> leave_start_Msec = current_Msec - 时间进度 * DefaultMsec + time_offset
    -> reach_end_Msec = leave_start_Msec + DefaultMsec
    '''

    cur_time = shared_context.frame_to_msec(cur_frame)
    total_dist = shared_context.note_travel_dist
    dist_offset = -1/120 * total_dist * (shared_context.note_OptionNotespeed / 150 - 1)
    #time_offset = (shared_context.note_OptionNotespeed / 150 - 1) * (-0.5 / (shared_context.note_OptionNotespeed / 150 - 1)) * 1.6 * 1000 / 60
    start_pos = shared_context.judgeline_start

    travelled_dist = cur_dist - start_pos - dist_offset
    time_progress = travelled_dist / total_dist
    leave_start_Msec = cur_time - time_progress * shared_context.note_DefaultMsec # + time_offset
    reach_end_Msec = leave_start_Msec + shared_context.note_DefaultMsec

    return reach_end_Msec
