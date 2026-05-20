import numpy as np

def analyze_slide_tail_start_end_time(shared_context, note_path, start_position, end_position):
    '''
    粗略计算持续时间

    根据每一帧之间的位移，计算音符的帧间移动速度，取中位数作为最终速度
    找到第一个离开起始A区的点，计算此时到A区中心的距离，配合速度计算时间
    这个时间就是音符从A区中心移动到此处所消耗的时间
    音符此时的帧时间 - 这个时间 = 反推出音符开始移动的时间
    同理，找到最后一个进入终点A区的点，计算得到音符停止移动的时间
    持续时间 = 停止时间 - 开始时间
    '''

    if len(note_path) < 5:
        return None, None
    positions = [x['position'] for x in note_path]
    if not positions or len(positions) < 5:
        return None, None
    
    # 起点
    point = shared_context.a_zone_endpoint.get(start_position, None)
    if point is None:
        return None, None
    start_cx, start_cy = point
    # 终点
    point = shared_context.a_zone_endpoint.get(end_position, None)
    if point is None:
        return None, None
    end_cx, end_cy = point

    # 计算帧间速度
    last_cx = None
    last_cy = None
    last_frame = None
    # 这个值应该比 analyze_slide_movement.is_line_pass_a_zone_endpoint() 的阈值要大一点点
    min_dist = shared_context.note_travel_dist * 0.131
    frame_speeds = []

    for point in note_path:
        frame_num = point['frame']
        cx = point['cx']
        cy = point['cy']

        # 过滤离起点/终点过近的
        dist_to_start = np.sqrt((cx - start_cx)**2 + (cy - start_cy)**2)
        dist_to_end = np.sqrt((cx - end_cx)**2 + (cy - end_cy)**2)
        if dist_to_start < min_dist or dist_to_end < min_dist:
            continue

        if last_cx is not None and last_cy is not None and last_frame is not None:
            dist = np.sqrt((cx - last_cx)**2 + (cy - last_cy)**2)
            if dist < min_dist:
                continue # 两点间距过短，不能可靠计算速度，跳过
            time_diff_msec = shared_context.frame_delta_msec(last_frame, frame_num)
            if time_diff_msec > 0:
                speed = dist / time_diff_msec
                frame_speeds.append(speed)

        last_cx = cx
        last_cy = cy
        last_frame = frame_num

    # 获取第60%的速度 (比中位数偏右一点)
    if not frame_speeds:
        return None, None
    sorted_speeds = sorted(frame_speeds)
    index = min(round(len(sorted_speeds) * 0.6), len(sorted_speeds) - 1)
    index = max(index, 0)
    note_speed = sorted_speeds[index]






    # 定义A区中心半径
    # 这个值应该比 analyze_slide_movement.is_line_pass_a_zone_endpoint() 的阈值要大一点
    # 也要比上面的 min_dist 大一点
    a_zone_radius = (shared_context.note_travel_dist) * 0.2

    # 找到第一个离开起始A区的点
    start_move_frame = None
    dist_to_start = 0
    for point in note_path:
        frame_num = point['frame']
        cx = point['cx']
        cy = point['cy']
        dist_to_start = np.sqrt((cx - start_cx)**2 + (cy - start_cy)**2)
        if dist_to_start > a_zone_radius:
            start_move_frame = frame_num
            break
    
    # 计算开始时间
    if start_move_frame is None:
        return None, None
    time_to_start_Msec = dist_to_start / note_speed
    note_start_time_Msec = shared_context.frame_to_msec(start_move_frame) - time_to_start_Msec

    # 找到最后一个进入终点A区的点
    end_move_frame = None
    dist_to_end = 0
    for i in range(len(note_path)-1, -1, -1): # 从后往前
        point = note_path[i]
        frame_num = point['frame']
        cx = point['cx']
        cy = point['cy']
        dist_to_end = np.sqrt((cx - end_cx)**2 + (cy - end_cy)**2)
        if dist_to_end > a_zone_radius:
            end_move_frame = frame_num
            break

    # 计算结束时间
    if end_move_frame is None:
        return None, None
    time_to_end_Msec = dist_to_end / note_speed
    note_end_time_Msec = shared_context.frame_to_msec(end_move_frame) + time_to_end_Msec

    return note_start_time_Msec, note_end_time_Msec

