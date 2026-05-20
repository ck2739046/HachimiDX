import numpy as np

from ..detect.note_definition import *
from .tool import *
from .shared_context import *


def preprocess_slide_data(shared_context: SharedContext):
    
    # 此处仅作基础的分类
    # 具体预处理交给底下的函数
    candidate_slide_head_data = {}
    candidate_slide_tail_data = {}

    for key, value in shared_context.track_data.items():

        track_id, note_type = key
        note_geometry_list = value

        if note_type != NoteType.SLIDE: continue
        if len(note_geometry_list) < 5: continue

        note_geometry_list.sort(key=lambda x: x.frame) # 按帧排序

        segment_type = _classify_segment(shared_context, note_geometry_list)

        if segment_type is None:
            print(f"preprocess_slide_data: track_id {track_id} could not be classified as head or tail")
            continue

        if segment_type == 'head':
            candidate_slide_head_data[key] = note_geometry_list
        elif segment_type == 'tail':
            candidate_slide_tail_data[key] = note_geometry_list


    
    # 交给下层函数进行更细致的检查和处理
    slide_head_data = preprocess_slide_head_data(shared_context, candidate_slide_head_data)
    slide_tail_data = preprocess_slide_tail_data(shared_context, candidate_slide_tail_data)

    return slide_head_data, slide_tail_data






def _classify_segment(shared_context: SharedContext, note_geometry_list) -> str | None:

    # 合法的星星头
    # 1. position一致
    # 2. 距离圆心递增
    # 3. 所有 dist 不在危险区 (judgeline_start * 0.85)

    # 合法的星星尾
    # 1. 开头在A区或者离A区判定点够近
    # 2. 结尾在A区或者离A区判定点够近
    # 离A区判定点够近的定义: note_travel_dist * 0.45
    # 选 45 是为了适配同头或者同尾星星，在A区附近会有重叠
    # 一般在移动了 30% 后才会分开，被识别成两个星星

    # 段长度不足, 丢弃, return
    if len(note_geometry_list) < 5:
        return None

    # 判断所有 pos 是否一致, 因为星星尾是从一个A区移动到另一个A区的, 所以 pos 一定不一致
    # yes: 可能是星星头, 进一步检查, return
    # no:  进一步分类
    oct_positions = [calculate_oct_position(
                     shared_context.std_video_cx,
                     shared_context.std_video_cy,
                     note.cx, note.cy
                    ) for note in note_geometry_list]
    if len(set(oct_positions)) == 1:
        return 'head'

    # 如果开头在A区, 可能是星星尾
    all_positions = [calculate_all_position(
                     shared_context.touch_areas,
                     note.cx, note.cy
                    ) for note in note_geometry_list]
    if all_positions[0].startswith('A'):
        return 'tail'

    # 不在A区, 尝试惯性推断出发点
    # 如果够近, 也可能是星星尾
    start_A_zone = _guess_target_a_zone_by_inertia(shared_context.a_zone_endpoint, shared_context.std_video_size, note_geometry_list[::-1])
    start_cx, start_cy = note_geometry_list[0].cx, note_geometry_list[0].cy
    if _is_close_to_A_zone_endpoint(shared_context.a_zone_endpoint, shared_context.std_video_size, start_cx, start_cy, start_A_zone):
        return 'tail'

    return 'head' # fallback 星星头






def _is_close_to_A_zone_endpoint(a_zone_endpoint: dict, std_video_size: int, cx: int, cy: int, target_a_zone: str) -> bool:
    '''
    判断一个点是否接近指定的A区判定点
    接近的定义: 距离小于 std_video_size * 0.24
    '''
    if target_a_zone is None:
        return False
    if target_a_zone not in a_zone_endpoint:
        return False
    ex, ey = a_zone_endpoint[target_a_zone]
    dist = np.sqrt((cx - ex)**2 + (cy - ey)**2)
    return dist < std_video_size * 0.24 # 1080p下约为240像素








def preprocess_slide_head_data(shared_context: SharedContext, candidate_slide_head_data: dict):
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

    slide_data = {}

    end_tolerance = shared_context.note_travel_dist * 0.1
    start_tolerance = shared_context.note_travel_dist * 0.1
    valid_judgeline_start = shared_context.judgeline_start + start_tolerance
    valid_judgeline_end = shared_context.judgeline_end - end_tolerance
    danger_dist = shared_context.judgeline_start * 0.85

    # read track data
    for key, value in candidate_slide_head_data.items():

        track_id, note_type = key
        note_geometry_list = value

        if note_type != NoteType.SLIDE: continue
        if len(note_geometry_list) < 5: continue


        # read track path
        valid_track_path = []
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
            valid_track_path.append((note.frame, position, dist_to_center))


        # 检查轨迹存在
        if not valid_track_path:
            print(f"preprocess_slide_head_data: no valid_track_path for track_id {track_id}")
            continue

        # 检验长度
        if len(valid_track_path) < 5:
            print(f"preprocess_slide_head_data: valid_track_path too short for track_id {track_id}, length: {len(valid_track_path)}")
            continue

        # 检验方位一致
        positions = [x[1] for x in valid_track_path]
        if len(set(positions)) != 1:
            print(f"preprocess_slide_head_data: positions not consistent for track_id {track_id}")
            continue

        # 按frame排序
        valid_track_path.sort(key=lambda x: x[0])

        dists = [x[2] for x in valid_track_path]
        
        # 检查 danger dist
        if any(dist < danger_dist for dist in dists):
            print(f"preprocess_slide_head_data: dist in danger zone for track_id {track_id}, dist: {dists}")
            continue

        # 检查dist是否递增 (允许微小回退 -0.5* start_tolerance)
        if not all(later - earlier > -0.5 * start_tolerance for earlier, later in zip(dists, dists[1:])):
            print(f"preprocess_slide_head_data: dist not increasing for track_id {track_id}")
            continue

        # 检查头尾dist是否覆盖全程 (25%-60%)
        big_head = valid_judgeline_start + 1.5*start_tolerance
        big_tail = valid_judgeline_end - 3*end_tolerance
        if dists[0] > big_head or dists[-1] < big_tail:
            print(f"preprocess_slide_head_data: dist out of range for track_id {track_id}, start_dist: {dists[0]}, end_dist: {dists[-1]}. Allowed range: {big_head} - {big_tail}")
            continue

        # 检查通过，添加到slide_data
        note_variant = note_geometry_list[0].note_variant
        position = positions[0]
        key = (track_id, note_type, note_variant, position)

        path = []
        for frame_num, position, dist_to_center in valid_track_path:
            path.append({
                'frame': frame_num,
                'dist': dist_to_center
            })

        slide_data[key] = path

    if not slide_data:
        print("preprocess_slide_head_data: no slide head data")
        return {}

    return slide_data




def preprocess_slide_tail_data(shared_context: SharedContext, candidate_slide_tail_data: dict):
    '''
    对所有轨迹点进行方位计算，形成移动路径
    只分离出移动阶段的星星，忽略星星头
    分离方法: 仅接受轨迹开头和结尾都在A区的音符

    返回格式:
    dict{
        key: (track_id, note_type, note_variant, start_position, end_position),
        value: note path
        [
            {
                'frame': frame_num,
                'cx': cx,
                'cy': cy,
                'dist': dist_to_center,
                'position': position
            },
            ...
        ]
    }
    '''

    slide_data = {}

    # read track data
    for key, value in candidate_slide_tail_data.items():

        track_id, note_type = key
        note_geometry_list = value

        if note_type != NoteType.SLIDE: continue
        if len(note_geometry_list) < 5: continue


        # 开头在分类时已经检查过，此处仅检查结尾
        all_postions = [calculate_all_position(
                        shared_context.touch_areas,
                        note.cx, note.cy
                       ) for note in note_geometry_list]
        if not all_postions[-1].startswith('A'):
            end_A_zone = _guess_target_a_zone_by_inertia(shared_context.a_zone_endpoint, shared_context.std_video_size, note_geometry_list)
            end_cx, end_cy = note_geometry_list[-1].cx, note_geometry_list[-1].cy
            if not _is_close_to_A_zone_endpoint(shared_context.a_zone_endpoint, shared_context.std_video_size, end_cx, end_cy, end_A_zone):
                print(f"preprocess_slide_tail_data: end point not close to A zone for track_id {track_id}")
                continue



        # read track path
        valid_track_path = []
        for note in note_geometry_list:

            # 计算距离圆心的距离
            dist_to_center = np.sqrt(((note.cx - shared_context.std_video_cx)**2 + (note.cy - shared_context.std_video_cy)**2))
            # 允许音符略微超出判定线范围(5%)，但更远的就忽略了
            if dist_to_center > shared_context.judgeline_end * 1.05: # 105%
                continue
            # 计算方位
            position = calculate_all_position(shared_context.touch_areas, note.cx, note.cy)
            # 添加轨迹点
            valid_track_path.append((note.frame, note.cx, note.cy, position, dist_to_center))


        # 检查轨迹存在
        if not valid_track_path:
            print(f"preprocess_slide_tail_data: no valid_track_path for track_id {track_id}")
            continue

        # 检验长度
        if len(valid_track_path) < 5:
            print(f"preprocess_slide_tail_data: valid_track_path too short for track_id {track_id}, length: {len(valid_track_path)}")
            continue

        # 按frame排序
        valid_track_path.sort(key=lambda x: x[0])
        
        positions = [x[3] for x in valid_track_path]
        if not positions or len(positions[0]) < 2:
            continue

        # 前面分类时可能允许起点不是 A 区，这里要重新计算起点
        start_pos = positions[0]
        if not start_pos.startswith('A'):
            # 构建一个虚拟 note_geometry_list
            temp_list = []
            for frame_num, cx, cy, position, dist_to_center in valid_track_path:
                temp_note = type('Note', (object,), {})() # 创建一个空对象
                temp_note.cx = cx
                temp_note.cy = cy
                temp_list.append(temp_note)
            # 通过惯性推断起点A区
            start_pos = _guess_target_a_zone_by_inertia(shared_context.a_zone_endpoint, shared_context.std_video_size, temp_list[::-1])
        
        # 计算终点
        end_pos = positions[-1]
        if not end_pos.startswith('A'):
            # 构建一个虚拟 note_geometry_list
            temp_list = []
            for frame_num, cx, cy, position, dist_to_center in valid_track_path:
                temp_note = type('Note', (object,), {})() # 创建一个空对象
                temp_note.cx = cx
                temp_note.cy = cy
                temp_list.append(temp_note)
            # 通过惯性推断终点A区
            end_pos = _guess_target_a_zone_by_inertia(shared_context.a_zone_endpoint, shared_context.std_video_size, temp_list)
        
        # 检查通过，添加到slide_data
        note_variant = note_geometry_list[0].note_variant
        key = (track_id, note_type, note_variant, start_pos[1], end_pos[1]) # A1 -> 1

        path = []
        for frame_num, cx, cy, position, dist_to_center in valid_track_path:
            path.append({
                'frame': frame_num,
                'cx': cx,
                'cy': cy,
                'dist': dist_to_center,
                'position': position
            })
        
        slide_data[key] = path

    if not slide_data:
        print("preprocess_slide_tail_data: no slide tail data")
        return {}

    return slide_data






def _guess_target_a_zone_by_inertia(a_zone_endpoint: dict, std_video_size: int, note_path):
    '''
    根据运动惯性，预测最终可能进入的A区。
    '''
    if len(note_path) < 2:
        return None

    # 寻找倒序最后一点 (点A)
    last_note = note_path[-1]
    A_cx = last_note.cx
    A_cy = last_note.cy

    # 倒序遍历寻找距离大于阈值的点 (点B)
    B_cx, B_cy = None, None
    min_dist = std_video_size * 0.02 # 1080p下约为20像素

    for note in reversed(note_path[:-1]):
        cx = note.cx
        cy = note.cy
        dist = np.sqrt((cx - A_cx)**2 + (cy - A_cy)**2)
        if dist > min_dist:
            B_cx, B_cy = cx, cy
            break
        
    if B_cx is None or B_cy is None:
        return None
    
    # 运动向量 BA (从B指向A)
    BA_x = A_cx - B_cx
    BA_y = A_cy - B_cy
    BA_length = np.sqrt(BA_x**2 + BA_y**2)
    if BA_length == 0: return None # 理论上不会发生AB重合
    
    # 过滤并找出距离射线最近的点
    best_zone = None
    min_distance_to_line = 999999

    for zone_id in range(1, 9):
        zone_key = f'A{zone_id}'
        P_cx, P_cy = a_zone_endpoint[zone_key]
    
        # 目标向量 AP (从A指向P)
        AP_x = P_cx - A_cx
        AP_y = P_cy - A_cy
    
        # 1. 筛选排查：利用点乘 (Dot Product) 判断是否在相反方向
        dot_product = BA_x * AP_x + BA_y * AP_y
        if dot_product < 0:
            continue  # 夹角 > 90度，说明目标点在跑过来的“背后”，排除
        
        # 2. 计算点到射线的距离：利用叉乘的绝对值 (Cross Product Area) / 底边长
        cross_product = abs(BA_x * AP_y - BA_y * AP_x)
        distance_to_line = cross_product / BA_length
    
        if distance_to_line < min_distance_to_line:
            min_distance_to_line = distance_to_line
            best_zone = zone_key
        
    return best_zone
