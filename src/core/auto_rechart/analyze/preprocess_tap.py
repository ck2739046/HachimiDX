import numpy as np

from ..detect.note_definition import *
from .tool import *
from .shared_context import *



def preprocess_tap_data(shared_context: SharedContext):
    '''
    返回格式:
    dict{
        key: (track_id, note_type, note_variant, note_position),
        value: note path
        [
            {
                'frame': frame_num,
                'dist': dist_to_center
            },
            ...
        ]
    }
    '''

    tap_data = {}

    end_tolerance = shared_context.note_travel_dist * 0.1
    start_tolerance = shared_context.note_travel_dist * 0.1
    valid_judgeline_start = shared_context.judgeline_start + start_tolerance
    valid_judgeline_end = shared_context.judgeline_end - end_tolerance

    # read track data
    for key, value in shared_context.track_data.items():

        track_id, note_type = key
        note_geometry_list = value

        if note_type != NoteType.TAP: continue
        if len(note_geometry_list) < 5: continue

        # read note path
        valid_path = []
        for note in note_geometry_list:

            # 计算距离圆心的距离
            dist_to_center = np.sqrt(((note.cx - shared_context.std_video_cx)**2 + (note.cy - shared_context.std_video_cy)**2))
            # 计算方向(1-8)
            position = calculate_oct_position(shared_context.std_video_cx, shared_context.std_video_cy, note.cx, note.cy)
            # 过滤10%-90%距离的数据
            if dist_to_center < valid_judgeline_start:
                continue # 掐头
            elif dist_to_center > valid_judgeline_end:
                continue # 去尾
            # 添加轨迹点
            valid_path.append((note.frame, dist_to_center, position))



        # 检查轨迹存在
        if not valid_path:
            print(f"preprocess_tap_data: no valid_path for track_id {track_id}")
            continue

        # 检验长度
        if len(valid_path) < 5:
            print(f"preprocess_tap_data: valid_path too short for track_id {track_id}, length: {len(valid_path)}")
            continue

        # 检验方位一致
        positions = [x[2] for x in valid_path]
        if len(set(positions)) != 1:
            print(f"preprocess_tap_data: positions not consistent for track_id {track_id}")
            continue

        # 按frame排序
        valid_path.sort(key=lambda x: x[0])

        # 检查dist是否递增 (允许微小回退5%总距离)
        dists = [x[1] for x in valid_path]
        if not all(later - earlier > - 0.05 * shared_context.note_travel_dist for earlier, later in zip(dists, dists[1:])):
            print(f"preprocess_tap_data: dist not increasing for track_id {track_id}")
            continue

        # 检查头尾dist是否覆盖全程 (25%-60%)
        big_head = valid_judgeline_start + 1.5*start_tolerance
        big_tail = valid_judgeline_end - 3*end_tolerance
        if dists[0] > big_head or dists[-1] < big_tail:
            print(f"preprocess_tap_data: dist out of range for track_id {track_id}, start_dist: {dists[0]}, end_dist: {dists[-1]}. Allowed range: {big_head} - {big_tail}")
            continue

        # 检查通过，添加到tap_data
        note_variant = note_geometry_list[0].note_variant
        position = positions[0]
        key = (track_id, note_type, note_variant, position)

        value = []
        for frame_num, dist_to_center, position in valid_path:
            value.append({
                'frame': frame_num,
                'dist': dist_to_center
            })
        
        tap_data[key] = value

    if not tap_data:
        print("preprocess_tap_data: no tap data")
        return {}

    return tap_data
