import math
import numpy as np

from ..detect.note_definition import *
from .tool import *
from .shared_context import *



def preprocess_hold_data(shared_context: SharedContext):
    '''
    返回格式:
    dict{
        key: (track_id, note_type, note_variant, note_position),
        value: note path
        [
            {
                'frame': frame_num,
                'dist-head': dist_head,
                'dist-tail': dist_tail
            },
            ...
        ]
    }
    '''

    hold_data = {}

    # 此处hold中点tolerance相对于tap要减半
    end_tolerance = shared_context.note_travel_dist * 0.05
    start_tolerance = shared_context.note_travel_dist * 0.05
    valid_judgeline_start = shared_context.judgeline_start + start_tolerance
    valid_judgeline_end = shared_context.judgeline_end - end_tolerance

    # read track data
    for key, value in shared_context.track_data.items():

        track_id, note_type = key
        note_geometry_list = value

        if note_type != NoteType.HOLD: continue
        if len(note_geometry_list) < 5: continue


        # read note path
        valid_track_path = []
        for note in note_geometry_list:

            # 计算距离圆心的距离
            dist_to_center = np.sqrt(((note.cx - shared_context.std_video_cx)**2 + (note.cy - shared_context.std_video_cy)**2))
            # 计算方向(1-8)
            position = calculate_oct_position(shared_context.std_video_cx, shared_context.std_video_cy, note.cx, note.cy)
            # 过滤数据
            if dist_to_center < valid_judgeline_start:
                continue # 掐头
            elif dist_to_center > valid_judgeline_end:
                continue # 去尾
            # 计算头尾的坐标/距离
            x_head, y_head, x_tail, y_tail, dist_head, dist_tail = calculate_hold_head_tail(shared_context, note.x1, note.y1, note.x2, note.y2, note.x3, note.y3, note.x4, note.y4, note.note_variant, position)
            if any(v is None for v in [x_head, y_head, x_tail, y_tail, dist_head, dist_tail]):
                print(f"calculate_hold_head_tail failed for track_id {track_id} at frame {note.frame}, skip this point")
                continue
            # 添加轨迹点
            valid_track_path.append((note.frame, position, dist_head, dist_tail))


        # 检查轨迹存在
        if not valid_track_path:
            print(f"preprocess_hold_data: no valid_track_path for track_id {track_id}")
            continue

        # 检验长度
        if len(valid_track_path) < 5:
            print(f"preprocess_hold_data: valid_track_path too short for track_id {track_id}, length: {len(valid_track_path)}")
            continue

        # 检验方位一致
        positions = [x[1] for x in valid_track_path]
        if len(set(positions)) != 1:
            print(f"preprocess_hold_data: positions not consistent for track_id {track_id}")
            continue

        # 按frame排序
        valid_track_path.sort(key=lambda x: x[0]) 
        
        # 检查dist是否递增 (允许微小回退3倍tolerance)
        # 这里宽松一点，因为hold的识别不太稳定
        dists = [(x[2] + x[3]) / 2 for x in valid_track_path]
        if not all(later - earlier > - 3*start_tolerance for earlier, later in zip(dists, dists[1:])):
            print(f"preprocess_hold_data: dist not increasing for track_id {track_id}")
            continue

        # 检查头尾dist是否覆盖全程 (25%-60%)
        big_head = valid_judgeline_start + 1.5*start_tolerance
        big_tail = valid_judgeline_end - 3*end_tolerance
        if dists[0] > big_head or dists[-1] < big_tail:
            print(f"preprocess_hold_data: dist out of range for track_id {track_id}, start_dist: {dists[0]}, end_dist: {dists[-1]}. Allowed range: {big_head} - {big_tail}")
            continue
        
        # 检查通过，添加到hold_data
        note_variant = note_geometry_list[0].note_variant
        position = positions[0]
        key = (track_id, note_type, note_variant, position)

        path = []
        for frame_num, position, dist_head, dist_tail in valid_track_path:
            path.append({
                'frame': frame_num,
                'dist-head': dist_head,
                'dist-tail': dist_tail
            })

        hold_data[key] = path

    if not hold_data:
        print("preprocess_hold_data: no hold data")
        return {}

    return hold_data




def calculate_hold_head_tail(shared_context, x1, y1, x2, y2, x3, y3, x4, y4, note_variant, position):
    '''
    获取hold框与轨道线的两个交点，视为hold的两个端点
    然后两个端点往回缩一点就是head和tail的位置
    '''

    # 直线经过中心点 (std_video_cx, std_video_cy)
    # 输入直线的y轴下方与x轴正半轴的夹角 (0°-180°)
    def get_line(angle):
        # 计算斜率 a = tan(angle)
        a = math.tan(math.radians(angle)) # 角度转换为弧度
        # 将屏幕中心点代入 y=ax+b 求解 b
        b = shared_context.std_video_cy - a * shared_context.std_video_cx
        return (a, b)


    # 计算矩形与直线的交点，应该是会有两个
    def calculate_line_rectangle_intersections(a, b, x1, y1, x2, y2, x3, y3, x4, y4):        
        # 四条边
        edges = [(x1, y1, x2, y2), (x2, y2, x3, y3), (x3, y3, x4, y4), (x4, y4, x1, y1)]
        intersections = []
        for x_start, y_start, x_end, y_end in edges:
            # 特殊处理竖直边，防止除零错误
            if abs(x_end - x_start) < 1e-1:
                x_intersect = x_start
                y_intersect = a * x_intersect + b   
            # 普通情况
            else:
                # 计算边的斜率和截距
                edge_a = (y_end - y_start) / (x_end - x_start)
                edge_b = y_start - edge_a * x_start
                # 计算交点
                if abs(a - edge_a) < 1e-1: continue # 跳过平行边，防止除零错误
                x_intersect = (edge_b - b) / (a - edge_a)
                y_intersect = a * x_intersect + b
            # 检查交点是否在边的x范围内
            if ((min(x_start, x_end) <= x_intersect <= max(x_start, x_end)) and
                (min(y_start, y_end) <= y_intersect <= max(y_start, y_end))):
                intersections.append((x_intersect, y_intersect))
        return intersections
    

    # 根据到中心点的距离，在轨迹线上计算新的点
    def get_point_by_dist_to_center(a, b, x, y, dist):
        # 沿轨迹线获得距离为 dist 的两个点
        dx = dist / np.sqrt(1 + np.power(a, 2))
        dy = a * dx
        p1x = shared_context.std_video_cx + dx
        p1y = shared_context.std_video_cy + dy
        p2x = shared_context.std_video_cx - dx
        p2y = shared_context.std_video_cy - dy
        # 更接近原始点的就是新的点
        if abs(p1x - x) > abs(p2x - x):
            return p2x, p2y
        else:
            return p1x, p1y


    # 根据方向确定轨道直线
    if position == 1 or position == 5:
        a, b = get_line(112.5)
    elif position == 2 or position == 6:
        a, b = get_line(157.5)
    elif position == 3 or position == 7:
        a, b = get_line(22.5)
    elif position == 4 or position == 8:
        a, b = get_line(67.5)

    # 计算hold框的四条边与轨道直线的交点
    intersections = calculate_line_rectangle_intersections(a, b, x1, y1, x2, y2, x3, y3, x4, y4)
    
    if len(intersections) != 2:
        print(f"expect 2 intersections, but got {len(intersections)}, skip")
        return None, None, None, None, None, None
        
    # 根据距离圆心的远近区分head和tail
    dist1 = math.sqrt((intersections[0][0] - shared_context.std_video_cx)**2 + (intersections[0][1] - shared_context.std_video_cy)**2)
    dist2 = math.sqrt((intersections[1][0] - shared_context.std_video_cx)**2 + (intersections[1][1] - shared_context.std_video_cy)**2)
    # 更远的是 head, 更近的是 tail
    head_x, head_y = intersections[0] if dist1 > dist2 else intersections[1]
    tail_x, tail_y = intersections[1] if dist1 > dist2 else intersections[0]
    dist_head = dist1 if dist1 > dist2 else dist2
    dist_tail = dist2 if dist1 > dist2 else dist1
    # 根据 label_notes 定义，整个hold的一半宽度为 70x0.77 (1080p)
    # ex / break_ex 再 +5 因为外面有一圈光晕
    width = 70 * 0.77
    if note_variant == NoteVariant.EX or note_variant == NoteVariant.BREAK_EX:
        width += 5
    width = width * shared_context.std_video_size / 1080 # 按视频尺寸缩放
    # 那么正六边形的端点到中心的距离约为 x 2/√3
    offset = width * 2 / math.sqrt(3)
    # 从端点往回缩，定位到head和tail的中心位置
    new_dist_head = dist_head - offset
    new_dist_tail = dist_tail + offset
    # 防止越过起点和终点
    if dist_head > shared_context.judgeline_end:
        dist_head = shared_context.judgeline_end
    if dist_head < shared_context.judgeline_start:
        dist_head = shared_context.judgeline_start
    if dist_tail > shared_context.judgeline_end:
        dist_tail = shared_context.judgeline_end
    if dist_tail < shared_context.judgeline_start:
        dist_tail = shared_context.judgeline_start
    # 计算新的head和tail坐标
    new_head_x, new_head_y = get_point_by_dist_to_center(a, b, head_x, head_y, new_dist_head)
    new_tail_x, new_tail_y = get_point_by_dist_to_center(a, b, tail_x, tail_y, new_dist_tail)

    return new_head_x, new_head_y, new_tail_x, new_tail_y, new_dist_head, new_dist_tail

