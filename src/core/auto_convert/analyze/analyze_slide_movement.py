import numpy as np

from .tool import catmull_rom_spline, calculate_all_position

shared_context = None
track_id = None


def analyze_slide_tail_movement_syntax(input_shared_context, note_path, start_pos, end_pos, tail_track_id):
    '''
    分析运动模式
    '''

    global shared_context
    shared_context = input_shared_context
    global track_id
    track_id = tail_track_id

    if len(note_path) < 5:
        return None
    positions = [x['position'] for x in note_path]
    if not positions or len(positions) < 5:
        return None
    
    classified_segments = get_syntax(note_path, start_pos, end_pos)

    if not classified_segments:
        return None

    merged_tokens = []
    pending_arc = None

    def _flush_pending_arc():
        nonlocal pending_arc
        if pending_arc is None:
            return
        merged_tokens.append(
            _get_arc_syntax(
                pending_arc['start_id'],
                pending_arc['next_id'],
                pending_arc['end_id']
            )
        )
        pending_arc = None

    for start_A_zone, end_A_zone, syntax in classified_segments:

        start_id = int(start_A_zone[1])
        end_id = int(end_A_zone[1])

        # arc 段：连续且同向时折叠成更长 arc
        if syntax in ('<', '>'):
            is_consec, direction = _is_consecutive(start_id, end_id)
            if not is_consec:
                _flush_pending_arc()
                merged_tokens.append(f"{syntax}{end_id}")
                continue

            if pending_arc is None:
                pending_arc = {
                    'start_id': start_id,
                    'next_id': end_id,
                    'end_id': end_id,
                    'direction': direction,
                }
                continue

            if pending_arc['end_id'] == start_id and pending_arc['direction'] == direction:
                pending_arc['end_id'] = end_id
                continue

            _flush_pending_arc()
            pending_arc = {
                'start_id': start_id,
                'next_id': end_id,
                'end_id': end_id,
                'direction': direction,
            }
            continue

        _flush_pending_arc()
        merged_tokens.append(f"{syntax}{end_id}")

    _flush_pending_arc()

    if not merged_tokens:
        return None

    movement_syntax = ''.join(merged_tokens)

    return movement_syntax


  
    





def get_syntax(note_path, start_pos, end_pos):
    
    note_path_segments = _divide_path_by_A_zone(note_path, start_pos, end_pos)
    if not note_path_segments:
        print(f"get_syntax: no valid segments after dividing by A zones for track {track_id}")
        return None
    
    classified_segments = []
    for note_path_segment, start_A_zone, end_A_zone in note_path_segments:

        start_A_zone_id = int(start_A_zone[1])
        end_A_zone_id = int(end_A_zone[1])

        # 对一个 segemnt, 只有几种情况:

        #   -  : straight
        #  > < : arc
        #   v  : center_reflection
        #  p q : inner loop
        #  z s : zigzag
        # pp qq: outer loop

        #   V  : a-zone-reflection 经过多个A区，会被拆分，忽略

        is_straight1, syntax = is_straight(note_path_segment, start_A_zone_id, end_A_zone_id)
        if is_straight1:
            classified_segments.append((start_A_zone, end_A_zone, syntax))
            continue

        is_arc1, syntax = is_arc(note_path_segment, start_A_zone_id, end_A_zone_id)
        if is_arc1:
            classified_segments.append((start_A_zone, end_A_zone, syntax))
            continue

        is_center_reflection1, syntax = is_center_reflection(note_path_segment, start_A_zone_id, end_A_zone_id)
        if is_center_reflection1:
            classified_segments.append((start_A_zone, end_A_zone, syntax))
            continue

        is_inner_loop1, syntax = is_inner_loop(note_path_segment, start_A_zone_id, end_A_zone_id)
        if is_inner_loop1:
            classified_segments.append((start_A_zone, end_A_zone, syntax))
            continue

        is_zigzag1, syntax = is_zigzag(note_path_segment, start_A_zone_id, end_A_zone_id)
        if is_zigzag1:
            classified_segments.append((start_A_zone, end_A_zone, syntax))
            continue

        is_outer_loop1, syntax = is_outer_loop(note_path_segment, start_A_zone_id, end_A_zone_id)
        if is_outer_loop1:
            classified_segments.append((start_A_zone, end_A_zone, syntax))
            continue

        # 无法识别, syntax fallback to straight
        classified_segments.append((start_A_zone, end_A_zone, '?'))
        print(f"get_syntax: unrecognized movement pattern for segment in track {track_id}, default to '?' syntax:")
        print(f"start_A_zone: {start_A_zone}, end_A_zone: {end_A_zone}")
        
        deduped: list[str] = []
        last_pos = None
        for note in note_path_segment:
            if note['position'] != last_pos:
                deduped.append(note['position'])
                last_pos = note['position']
        print(" -> ".join(deduped))


    return classified_segments










def is_straight(note_path: list, start_A_zone_id: int, end_A_zone_id: int) -> tuple[bool, str]:

    pos_diff = _get_pos_diff(start_A_zone_id, end_A_zone_id)
    
    if pos_diff == 0:
        # 直线不可能起点和终点相同
        return False, None
    if pos_diff == 1:
        # 直线不可能是相邻的A区
        return False, None
    
    positions = [x['position'] for x in note_path]
    positions.insert(0, f'A{start_A_zone_id}')
    positions.append(f'A{end_A_zone_id}')
    required = []
    optional = []
    banned = []

    # 必须激活起点/终点
    required.append(f'A{start_A_zone_id}')
    required.append(f'A{end_A_zone_id}')
    
    if pos_diff == 2:
        # 可选激活之间的 AB 区
        between_AB_zones_id = _get_between_AB_zones(start_A_zone_id, end_A_zone_id)
        for id in between_AB_zones_id:
            optional.append(f'A{id}')
            optional.append(f'B{id}')
        # 可选激活之间的 DE 区
        between_DE_zones_id = _get_between_DE_zones(start_A_zone_id, end_A_zone_id)
        for id in between_DE_zones_id:
            optional.append(f'D{id}')
            optional.append(f'E{id}')
        
    if pos_diff == 3:
        # 必须激活之间的 B 区
        between_AB_zones_id = _get_between_AB_zones(start_A_zone_id, end_A_zone_id)
        for id in between_AB_zones_id:
            required.append(f'B{id}')
        # 可选激活之间的 E 区 (排除中间)
        between_DE_zones_id = _get_between_DE_zones(start_A_zone_id, end_A_zone_id)
        optional.append(f'E{between_DE_zones_id[0]}')
        optional.append(f'E{between_DE_zones_id[-1]}')
        
    if pos_diff == 4:
        # 必须激活 C 区
        required.append(f'C1')
        # 必须激活 B 区
        required.append(f'B{start_A_zone_id}')
        required.append(f'B{end_A_zone_id}')
        # 可选起点/终点附近的 E 区
        optional.append(f'E{_prev_DE_zone_id(start_A_zone_id)}')
        optional.append(f'E{_next_DE_zone_id(start_A_zone_id)}')
        optional.append(f'E{_prev_DE_zone_id(end_A_zone_id)}')
        optional.append(f'E{_next_DE_zone_id(end_A_zone_id)}')

    # 检查
    if _ckeck_zones(positions, required, optional, banned):
        return True, '-'
    
    return False, None



        


def is_arc(note_path: list, start_A_zone_id: int, end_A_zone_id: int) -> tuple[bool, str]:

    pos_diff = _get_pos_diff(start_A_zone_id, end_A_zone_id)

    if pos_diff != 1:
        # 圆弧必须是相邻的A区
        return False, None
    
    positions = [x['position'] for x in note_path]
    positions.insert(0, f'A{start_A_zone_id}')
    positions.append(f'A{end_A_zone_id}')
    required = []
    optional = []
    banned = []

    # 必须激活起点/终点
    required.append(f'A{start_A_zone_id}')
    required.append(f'A{end_A_zone_id}')

    # 可选激活 D 区
    optional.append(f'D{_prev_DE_zone_id(start_A_zone_id)}')
    optional.append(f'D{_next_DE_zone_id(start_A_zone_id)}')
    optional.append(f'D{_prev_DE_zone_id(end_A_zone_id)}')
    optional.append(f'D{_next_DE_zone_id(end_A_zone_id)}')

    # 检查
    if _ckeck_zones(positions, required, optional, banned):
        syntax = _get_arc_syntax(start_A_zone_id, end_A_zone_id, end_A_zone_id)
        return True, syntax[0] # 只取箭头
    
    return False, None







def is_center_reflection(note_path: list, start_A_zone_id: int, end_A_zone_id: int) -> tuple[bool, str]:

    pos_diff = _get_pos_diff(start_A_zone_id, end_A_zone_id)

    if pos_diff == 0:
        # 不可能起点和终点相同
        return False, None
    if pos_diff == 4:
        # 不可能是相对的A区
        return False, None
    
    positions = [x['position'] for x in note_path]
    positions.insert(0, f'A{start_A_zone_id}')
    positions.append(f'A{end_A_zone_id}')
    required = []
    optional = []
    banned = []

    # 必须激活起点/终点
    required.append(f'A{start_A_zone_id}')
    required.append(f'A{end_A_zone_id}')

    # 必须激活 C 区
    required.append(f'C1')
    
    # 必须激活 B 区
    required.append(f'B{start_A_zone_id}')
    required.append(f'B{end_A_zone_id}')

    # 检查
    if _ckeck_zones(positions, required, optional, banned):
        return True, 'v'
    
    return False, None
    






def is_inner_loop(note_path: list, start_A_zone_id: int, end_A_zone_id: int) -> tuple[bool, str]:

    is_q, syntax_q = is_inner_loop_q_clockwise(note_path, start_A_zone_id, end_A_zone_id)
    is_p, syntax_p = is_inner_loop_p_counterclockwise(note_path, start_A_zone_id, end_A_zone_id)

    if is_q:
        return True, syntax_q
    elif is_p:
        return True, syntax_p
    else:
        return False, None




def is_inner_loop_q_clockwise(note_path: list, start_A_zone_id: int, end_A_zone_id: int) -> tuple[bool, str]:

    pos_diff = _get_pos_diff(start_A_zone_id, end_A_zone_id, clockwise=True)

    positions = [x['position'] for x in note_path]
    positions.insert(0, f'A{start_A_zone_id}')
    positions.append(f'A{end_A_zone_id}')
    required = []
    optional = []
    banned = []
    required_sort = False

    # 必须激活起点/终点
    required.append(f'A{start_A_zone_id}')
    if pos_diff != 0:
        required.append(f'A{end_A_zone_id}')

    if pos_diff == 0:
        # 可选激活相邻 E 区
        optional.append(f'E{_prev_DE_zone_id(start_A_zone_id)}')
        optional.append(f'E{_next_DE_zone_id(start_A_zone_id)}')
        # 必须按顺序激活其他 B 区 (排除起点)
        next_A_zone_id = _next_AB_zone_id(start_A_zone_id)
        last_A_zone_id = _prev_AB_zone_id(start_A_zone_id)
        between_AB_zones_id = _get_between_AB_zones(next_A_zone_id, last_A_zone_id, clockwise=True)
        required.append(f'B{next_A_zone_id}')
        for id in between_AB_zones_id:
            required.append(f'B{id}')
        required.append(f'B{last_A_zone_id}')
        required_sort = True


    if pos_diff == 1:
        # 可选之间的 E 区
        between_DE_zones_id = _get_between_DE_zones(start_A_zone_id, end_A_zone_id)
        for id in between_DE_zones_id:
            optional.append(f'E{id}')
        # 必须激活所有 B 区
        for id in [1, 2, 3, 4, 5, 6, 7, 8]:
            required.append(f'B{id}')

    if pos_diff == 2 or pos_diff == 3:
        # 可选起点下一个 E 区
        optional.append(f'E{_next_DE_zone_id(start_A_zone_id)}')
        # 可选终点上一个 E 区
        optional.append(f'E{_prev_DE_zone_id(end_A_zone_id)}')
        # 必须激活所有 B 区
        for id in [1, 2, 3, 4, 5, 6, 7, 8]:
            required.append(f'B{id}')

    if pos_diff in [4, 5, 6, 7]:
        # 可选起点下一个 E 区
        optional.append(f'E{_next_DE_zone_id(start_A_zone_id)}')
        # 可选终点上一个 E 区
        optional.append(f'E{_prev_DE_zone_id(end_A_zone_id)}')
        # 必须激活之间的 B 区
        between_AB_zones_id = _get_between_AB_zones(start_A_zone_id, end_A_zone_id, clockwise=True)
        for id in between_AB_zones_id:
            required.append(f'B{id}')

    # 检查
    if _ckeck_zones(positions, required, optional, banned, required_sort):
        return True, 'q'
    
    return False, None




def is_inner_loop_p_counterclockwise(note_path: list, start_A_zone_id: int, end_A_zone_id: int) -> tuple[bool, str]:

    pos_diff = _get_pos_diff(start_A_zone_id, end_A_zone_id, counterclockwise=True)

    positions = [x['position'] for x in note_path]
    positions.insert(0, f'A{start_A_zone_id}')
    positions.append(f'A{end_A_zone_id}')
    required = []
    optional = []
    banned = []
    required_sort = False

    # 必须激活起点/终点
    required.append(f'A{start_A_zone_id}')
    if pos_diff != 0:
        required.append(f'A{end_A_zone_id}')

    if pos_diff == 0:
        # 可选激活相邻 E 区
        optional.append(f'E{_prev_DE_zone_id(start_A_zone_id)}')
        optional.append(f'E{_next_DE_zone_id(start_A_zone_id)}')
        # 必须按顺序激活其他 B 区 (排除起点)
        next_A_zone_id = _next_AB_zone_id(start_A_zone_id)
        last_A_zone_id = _prev_AB_zone_id(start_A_zone_id)
        between_AB_zones_id = _get_between_AB_zones(last_A_zone_id, next_A_zone_id, counterclockwise=True)
        required.append(f'B{last_A_zone_id}')
        for id in between_AB_zones_id:
            required.append(f'B{id}')
        required.append(f'B{next_A_zone_id}')
        required_sort = True

    if pos_diff == 1:
        # 可选之间的 E 区
        between_DE_zones_id = _get_between_DE_zones(start_A_zone_id, end_A_zone_id)
        for id in between_DE_zones_id:
            optional.append(f'E{id}')
        # 必须激活所有 B 区
        for id in [1, 2, 3, 4, 5, 6, 7, 8]:
            required.append(f'B{id}')

    if pos_diff == 2 or pos_diff == 3:
        # 可选起点上一个 E 区
        optional.append(f'E{_prev_DE_zone_id(start_A_zone_id)}')
        # 可选终点下一个 E 区
        optional.append(f'E{_next_DE_zone_id(end_A_zone_id)}')
        # 必须激活所有 B 区
        for id in [1, 2, 3, 4, 5, 6, 7, 8]:
            required.append(f'B{id}')

    if pos_diff in [4, 5, 6, 7]:
        # 可选起点上一个 E 区
        optional.append(f'E{_prev_DE_zone_id(start_A_zone_id)}')
        # 可选终点下一个 E 区
        optional.append(f'E{_next_DE_zone_id(end_A_zone_id)}')
        # 必须激活之间的 B 区
        between_AB_zones_id = _get_between_AB_zones(start_A_zone_id, end_A_zone_id, counterclockwise=True)
        for id in between_AB_zones_id:
            required.append(f'B{id}')

    # 检查
    if _ckeck_zones(positions, required, optional, banned, required_sort):
        return True, 'p'
    
    return False, None









def is_zigzag(note_path: list, start_A_zone_id: int, end_A_zone_id: int) -> tuple[bool, str]:

    pos_diff = _get_pos_diff(start_A_zone_id, end_A_zone_id)

    if pos_diff != 4:
        # 必须是4
        return False, None
    
    is_s, syntax_s = is_zigzag_s(note_path, start_A_zone_id, end_A_zone_id)
    is_z, syntax_z = is_zigzag_z(note_path, start_A_zone_id, end_A_zone_id)

    if is_s:
        return True, syntax_s
    elif is_z:
        return True, syntax_z
    else:
        return False, None




def is_zigzag_s(note_path: list, start_A_zone_id: int, end_A_zone_id: int) -> tuple[bool, str]:

    positions = [x['position'] for x in note_path]
    positions.insert(0, f'A{start_A_zone_id}')
    positions.append(f'A{end_A_zone_id}')
    required = []
    optional = []
    banned = []

    # 必须激活起点/终点
    required.append(f'A{start_A_zone_id}')
    required.append(f'A{end_A_zone_id}')

    # 必须激活 C 区
    required.append(f'C1')

    # 必须激活转折处的 B 区: 通用
    B_zone_id = _next_AB_zone_id(_next_AB_zone_id(start_A_zone_id))
    required.append(f'B{B_zone_id}')
    B_zone_id = _prev_AB_zone_id(_prev_AB_zone_id(start_A_zone_id))
    required.append(f'B{B_zone_id}')

    # 必须激活转折处的 B 区: s
    B_zone_id = _prev_AB_zone_id(start_A_zone_id)
    required.append(f'B{B_zone_id}')
    B_zone_id = _prev_AB_zone_id(end_A_zone_id)
    required.append(f'B{B_zone_id}')
    # 可选激活转折处的 E 区: s
    E_zone_id = _prev_DE_zone_id(start_A_zone_id)
    optional.append(f'E{E_zone_id}')
    E_zone_id = _prev_DE_zone_id(end_A_zone_id)
    optional.append(f'E{E_zone_id}')
    # 可选起点/终点的 B 区: s
    # 参考 galaxy blaster 开头的两个 s/z 交叉造成的意外波动
    optional.append(f'B{start_A_zone_id}')
    optional.append(f'B{end_A_zone_id}')

    # 检查
    if _ckeck_zones(positions, required, optional, banned):
        return True, 's'
    
    return False, None




def is_zigzag_z(note_path: list, start_A_zone_id: int, end_A_zone_id: int) -> tuple[bool, str]:

    positions = [x['position'] for x in note_path]
    positions.insert(0, f'A{start_A_zone_id}')
    positions.append(f'A{end_A_zone_id}')
    required = []
    optional = []
    banned = []

    # 必须激活起点/终点
    required.append(f'A{start_A_zone_id}')
    required.append(f'A{end_A_zone_id}')

    # 必须激活 C 区
    required.append(f'C1')

    # 必须激活转折处的 B 区: 通用
    B_zone_id = _next_AB_zone_id(_next_AB_zone_id(start_A_zone_id))
    required.append(f'B{B_zone_id}')
    B_zone_id = _prev_AB_zone_id(_prev_AB_zone_id(start_A_zone_id))
    required.append(f'B{B_zone_id}')

    # 必须激活转折处的 B 区: z
    B_zone_id = _next_AB_zone_id(start_A_zone_id)
    required.append(f'B{B_zone_id}')
    B_zone_id = _next_AB_zone_id(end_A_zone_id)
    required.append(f'B{B_zone_id}')
    # 可选激活转折处的 E 区: z
    E_zone_id = _next_DE_zone_id(start_A_zone_id)
    optional.append(f'E{E_zone_id}')
    E_zone_id = _next_DE_zone_id(end_A_zone_id)
    optional.append(f'E{E_zone_id}')
    # 可选起点/终点的 B 区: z
    # 参考 galaxy blaster 开头的两个 s/z 交叉造成的意外波动
    optional.append(f'B{start_A_zone_id}')
    optional.append(f'B{end_A_zone_id}')

    # 检查
    if _ckeck_zones(positions, required, optional, banned):
        return True, 'z'
    
    return False, None











def is_outer_loop(note_path: list, start_A_zone_id: int, end_A_zone_id: int) -> tuple[bool, str]:

    is_qq, syntax_qq = is_outer_loop_qq_clockwise(note_path, start_A_zone_id, end_A_zone_id)
    is_pp, syntax_pp = is_outer_loop_pp_counterclockwise(note_path, start_A_zone_id, end_A_zone_id)

    if is_qq:
        return True, syntax_qq
    elif is_pp:
        return True, syntax_pp
    else:
        return False, None




def is_outer_loop_qq_clockwise(note_path: list, start_A_zone_id: int, end_A_zone_id: int) -> tuple[bool, str]:

    pos_diff = _get_pos_diff(start_A_zone_id, end_A_zone_id, clockwise=True)

    positions = [x['position'] for x in note_path]
    positions.insert(0, f'A{start_A_zone_id}')
    positions.append(f'A{end_A_zone_id}')
    required = []
    optional = []
    banned = []

    # 必须激活起点/终点
    required.append(f'A{start_A_zone_id}')
    if pos_diff != 0:
        required.append(f'A{end_A_zone_id}')

    # 通用
    # 必须激活 C 区
    required.append(f'C1')
    # 必须激活绕大圈经过的 B 区
    required.append(f'B{start_A_zone_id}')
    required.append(f'B{start_A_zone_id - 3 if start_A_zone_id > 3 else start_A_zone_id + 5}')
    # 必须激活绕大圈经过的 A 区
    A_zone_id2 = _prev_AB_zone_id(_prev_AB_zone_id(start_A_zone_id))
    required.append(f'A{A_zone_id2}')
    # 可选激活绕大圈经过的 E 区
    optional.append(f'E{_prev_DE_zone_id(A_zone_id2)}')
    # 可选激活绕大圈经过的 D 区
    optional.append(f'D{_prev_DE_zone_id(A_zone_id2)}')

    if pos_diff == 0:
        # 必须激活绕大圈回到终点经过的 A 区
        A_zone_id = _prev_AB_zone_id(start_A_zone_id)
        required.append(f'A{A_zone_id}')
        # 可选激活绕大圈回到终点经过的 D 区
        between_DE_zone_ids = _get_between_DE_zones(start_A_zone_id, A_zone_id2)
        for id in between_DE_zone_ids:
            optional.append(f'D{id}')

    if pos_diff == 1:
        # 必须激活绕大圈回到终点经过的 A 区
        A_zone_id = _prev_AB_zone_id(start_A_zone_id)
        required.append(f'A{A_zone_id}')
        # 可选激活绕大圈回到终点经过的 D 区
        between_DE_zone_ids = _get_between_DE_zones(end_A_zone_id, A_zone_id2)
        for id in between_DE_zone_ids:
            optional.append(f'D{id}')
        # 可选激活绕大圈回到终点经过的 E 区
        between_DE_zone_ids = _get_between_DE_zones(end_A_zone_id, A_zone_id)
        for id in between_DE_zone_ids:
            optional.append(f'E{id}')

    if pos_diff == 2:
        # 必须激活绕大圈回到终点经过的 A 区
        A_zone_id = _prev_AB_zone_id(start_A_zone_id)
        required.append(f'A{A_zone_id}')
        # 必须激活绕大圈回到终点经过的 B 区
        A_zone_id = _next_AB_zone_id(start_A_zone_id)
        required.append(f'B{A_zone_id}')
        # 可选激活绕大圈回到终点经过的 D 区
        between_DE_zone_ids = _get_between_DE_zones(start_A_zone_id, A_zone_id2)
        for id in between_DE_zone_ids:
            optional.append(f'D{id}')
        # 可选激活绕大圈回到终点经过的 E 区
        optional.append(f'E{_prev_DE_zone_id(start_A_zone_id)}')
        optional.append(f'E{_next_DE_zone_id(start_A_zone_id)}')
        optional.append(f'E{_prev_DE_zone_id(end_A_zone_id)}')

    if pos_diff == 3:
        # 必须激活绕大圈回到终点经过的 A 区
        A_zone_id = _prev_AB_zone_id(start_A_zone_id)
        required.append(f'A{A_zone_id}')
        # 必须激活绕大圈回到终点经过的 B 区
        required.append(f'B{end_A_zone_id}')
        # 可选激活绕大圈回到终点经过的 B 区
        between_AB_zone_ids = _get_between_AB_zones(start_A_zone_id, end_A_zone_id)
        for id in between_AB_zone_ids:
            optional.append(f'B{id}')
        # 可选激活绕大圈回到终点经过的 D 区
        between_DE_zone_ids = _get_between_DE_zones(start_A_zone_id, A_zone_id2)
        for id in between_DE_zone_ids:
            optional.append(f'D{id}')
        # 可选激活绕大圈回到终点经过的 E 区
        optional.append(f'E{_prev_DE_zone_id(start_A_zone_id)}')
        optional.append(f'E{_prev_DE_zone_id(end_A_zone_id)}')

    if pos_diff == 4:
        # 必须激活绕大圈回到终点经过的 A 区
        A_zone_id = _prev_AB_zone_id(start_A_zone_id)
        required.append(f'A{A_zone_id}')
        # 必须激活绕大圈回到终点经过的 B 区
        required.append(f'B{end_A_zone_id}')
        # 可选激活绕大圈回到终点经过的 D 区
        between_DE_zone_ids = _get_between_DE_zones(start_A_zone_id, A_zone_id2)
        for id in between_DE_zone_ids:
            optional.append(f'D{id}')
        # 可选激活绕大圈回到终点经过的 E 区
        optional.append(f'E{_prev_DE_zone_id(start_A_zone_id)}')

    if pos_diff == 5:
        # 必须激活绕大圈回到终点经过的 A 区
        A_zone_id = _prev_AB_zone_id(start_A_zone_id)
        required.append(f'A{A_zone_id}')
        # 可选激活绕大圈回到终点经过的 D 区
        between_DE_zone_ids = _get_between_DE_zones(start_A_zone_id, A_zone_id2)
        for id in between_DE_zone_ids:
            optional.append(f'D{id}')
        # 可选激活绕大圈回到终点经过的 E 区
        optional.append(f'E{_prev_DE_zone_id(start_A_zone_id)}')

    # if pos_diff == 6:
        # pass

    if pos_diff == 7:
        # 必须激活绕大圈回到终点经过的 A 区
        A_zone_id = _prev_AB_zone_id(start_A_zone_id)
        required.append(f'A{A_zone_id}')
        # 可选激活绕大圈回到终点经过的 D 区
        optional.append(f'D{_prev_DE_zone_id(A_zone_id)}')

    # 检查
    if _ckeck_zones(positions, required, optional, banned):
        return True, 'qq'
    
    return False, None




def is_outer_loop_pp_counterclockwise(note_path: list, start_A_zone_id: int, end_A_zone_id: int) -> tuple[bool, str]:

    pos_diff = _get_pos_diff(start_A_zone_id, end_A_zone_id, counterclockwise=True)

    positions = [x['position'] for x in note_path]
    positions.insert(0, f'A{start_A_zone_id}')
    positions.append(f'A{end_A_zone_id}')
    required = []
    optional = []
    banned = []

    # 必须激活起点/终点
    required.append(f'A{start_A_zone_id}')
    if pos_diff != 0:
        required.append(f'A{end_A_zone_id}')

    # 通用
    # 必须激活 C 区
    required.append(f'C1')
    # 必须激活绕大圈经过的 B 区
    required.append(f'B{start_A_zone_id}')
    required.append(f'B{start_A_zone_id + 3 if start_A_zone_id < 6 else start_A_zone_id - 5}')
    # 必须激活绕大圈经过的 A 区
    A_zone_id2 = _next_AB_zone_id(_next_AB_zone_id(start_A_zone_id))
    required.append(f'A{A_zone_id2}')
    # 可选激活绕大圈经过的 E 区
    optional.append(f'E{_next_DE_zone_id(A_zone_id2)}')
    # 可选激活绕大圈经过的 D 区
    optional.append(f'D{_next_DE_zone_id(A_zone_id2)}')

    if pos_diff == 0:
        # 必须激活绕大圈回到终点经过的 A 区
        A_zone_id = _next_AB_zone_id(start_A_zone_id)
        required.append(f'A{A_zone_id}')
        # 可选激活绕大圈回到终点经过的 D 区
        between_DE_zone_ids = _get_between_DE_zones(start_A_zone_id, A_zone_id2)
        for id in between_DE_zone_ids:
            optional.append(f'D{id}')

    if pos_diff == 1:
        # 必须激活绕大圈回到终点经过的 A 区
        A_zone_id = _next_AB_zone_id(start_A_zone_id)
        required.append(f'A{A_zone_id}')
        # 可选激活绕大圈回到终点经过的 D 区
        between_DE_zone_ids = _get_between_DE_zones(end_A_zone_id, A_zone_id2)
        for id in between_DE_zone_ids:
            optional.append(f'D{id}')
        # 可选激活绕大圈回到终点经过的 E 区
        between_DE_zone_ids = _get_between_DE_zones(end_A_zone_id, A_zone_id)
        for id in between_DE_zone_ids:
            optional.append(f'E{id}')

    if pos_diff == 2:
        # 必须激活绕大圈回到终点经过的 A 区
        A_zone_id = _next_AB_zone_id(start_A_zone_id)
        required.append(f'A{A_zone_id}')
        # 必须激活绕大圈回到终点经过的 B 区
        A_zone_id = _prev_AB_zone_id(start_A_zone_id)
        required.append(f'B{A_zone_id}')
        # 可选激活绕大圈回到终点经过的 D 区
        between_DE_zone_ids = _get_between_DE_zones(start_A_zone_id, A_zone_id2)
        for id in between_DE_zone_ids:
            optional.append(f'D{id}')
        # 可选激活绕大圈回到终点经过的 E 区
        optional.append(f'E{_prev_DE_zone_id(start_A_zone_id)}')
        optional.append(f'E{_next_DE_zone_id(start_A_zone_id)}')
        optional.append(f'E{_next_DE_zone_id(end_A_zone_id)}')

    if pos_diff == 3:
        # 必须激活绕大圈回到终点经过的 A 区
        A_zone_id = _next_AB_zone_id(start_A_zone_id)
        required.append(f'A{A_zone_id}')
        # 必须激活绕大圈回到终点经过的 B 区
        required.append(f'B{end_A_zone_id}')
        # 可选激活绕大圈回到终点经过的 B 区
        between_AB_zone_ids = _get_between_AB_zones(start_A_zone_id, end_A_zone_id)
        for id in between_AB_zone_ids:
            optional.append(f'B{id}')
        # 可选激活绕大圈回到终点经过的 D 区
        between_DE_zone_ids = _get_between_DE_zones(start_A_zone_id, A_zone_id2)
        for id in between_DE_zone_ids:
            optional.append(f'D{id}')
        # 可选激活绕大圈回到终点经过的 E 区
        optional.append(f'E{_next_DE_zone_id(start_A_zone_id)}')
        optional.append(f'E{_next_DE_zone_id(end_A_zone_id)}')

    if pos_diff == 4:
        # 必须激活绕大圈回到终点经过的 A 区
        A_zone_id = _next_AB_zone_id(start_A_zone_id)
        required.append(f'A{A_zone_id}')
        # 必须激活绕大圈回到终点经过的 B 区
        required.append(f'B{end_A_zone_id}')
        # 可选激活绕大圈回到终点经过的 D 区
        between_DE_zone_ids = _get_between_DE_zones(start_A_zone_id, A_zone_id2)
        for id in between_DE_zone_ids:
            optional.append(f'D{id}')
        # 可选激活绕大圈回到终点经过的 E 区
        optional.append(f'E{_next_DE_zone_id(start_A_zone_id)}')

    if pos_diff == 5:
        # 必须激活绕大圈回到终点经过的 A 区
        A_zone_id = _next_AB_zone_id(start_A_zone_id)
        required.append(f'A{A_zone_id}')
        # 可选激活绕大圈回到终点经过的 D 区
        between_DE_zone_ids = _get_between_DE_zones(start_A_zone_id, A_zone_id2)
        for id in between_DE_zone_ids:
            optional.append(f'D{id}')
        # 可选激活绕大圈回到终点经过的 E 区
        optional.append(f'E{_next_DE_zone_id(start_A_zone_id)}')

    # if pos_diff == 6:
        # pass

    if pos_diff == 7:
        # 必须激活绕大圈回到终点经过的 A 区
        A_zone_id = _next_AB_zone_id(start_A_zone_id)
        required.append(f'A{A_zone_id}')
        # 可选激活绕大圈回到终点经过的 D 区
        optional.append(f'D{_next_DE_zone_id(A_zone_id)}')

    # 检查
    if _ckeck_zones(positions, required, optional, banned):
        return True, 'pp'
    
    return False, None












# 此处上下指的是顺时针方向
# A1: next AB2, prev AB8
#     next DE2, prev DE1
def _prev_AB_zone_id(A_zone_id: int) -> int:
    return A_zone_id - 1 if A_zone_id > 1 else 8
def _next_AB_zone_id(A_zone_id: int) -> int:
    return A_zone_id + 1 if A_zone_id < 8 else 1
def _prev_DE_zone_id(A_zone_id: int) -> int:
    return A_zone_id
def _next_DE_zone_id(A_zone_id: int) -> int:
    return A_zone_id + 1 if A_zone_id < 8 else 1




def _ckeck_zones(note_positions: list[str],
                 required: list[str] = [],
                 optional: list[str] = [],
                 banned: list[str] = [],
                 required_sort: bool = False) -> bool:
    # banned
    for pos in note_positions:
        if pos in banned or (pos not in required and pos not in optional):
            return False
    # required
    for pos in required:
        if pos not in note_positions:
            return False
    # required_sort
    if required_sort:
        last_index = -1
        for pos in required:
            try:
                index = note_positions.index(pos)
            except ValueError:
                return False
            if index <= last_index:
                return False
            last_index = index
    return True




def _get_pos_diff(start_A_zone_id: int, end_A_zone_id: int, clockwise=False, counterclockwise=False) -> int:
    
    # 计算顺时针距离
    if start_A_zone_id <= end_A_zone_id:
        clockwise_distance = end_A_zone_id - start_A_zone_id
    else:
        clockwise_distance = (8 - start_A_zone_id) + end_A_zone_id
    # 计算逆时针距离
    if start_A_zone_id >= end_A_zone_id:
        counterclockwise_distance = start_A_zone_id - end_A_zone_id
    else:
        counterclockwise_distance = start_A_zone_id + (8 - end_A_zone_id)
    
    if clockwise:
        return clockwise_distance
    elif counterclockwise:
        return counterclockwise_distance
    else:
        return min(clockwise_distance, counterclockwise_distance)




def _is_clockwise(start_A_zone_id: int, end_A_zone_id: int) -> bool:

    clockwise_dist = _get_pos_diff(start_A_zone_id, end_A_zone_id, clockwise=True)
    counterclockwise_dist = _get_pos_diff(start_A_zone_id, end_A_zone_id, counterclockwise=True)
    # 如果顺时针距离更短，返回True
    # 特例, 如果两个A区相对 (差4), 无法判断, 默认逆时针
    return clockwise_dist < counterclockwise_dist




def _get_between_AB_zones(start_A_zone_id: int, end_A_zone_id: int,
                          clockwise=False, counterclockwise=False) -> list[int]:

    
    pos_diff = _get_pos_diff(start_A_zone_id, end_A_zone_id,
                             clockwise=clockwise, counterclockwise=counterclockwise)
    # 如果两个A区相同/相邻，无法判断
    if pos_diff in [0, 1]:
        return []
    # 如果两个A区相对，且没有指定方向，无法判断
    if pos_diff == 4 and not (clockwise or counterclockwise):
        return []

    # 顺时针方向
    between_zones_clockwise = []
    current = start_A_zone_id
    while True:
        current = current + 1 if current < 8 else 1
        if current == end_A_zone_id:
            break
        between_zones_clockwise.append(current)
    
    # 逆时针方向
    between_zones_counterclockwise = []
    current = start_A_zone_id
    while True:
        current = current - 1 if current > 1 else 8
        if current == end_A_zone_id:
            break
        between_zones_counterclockwise.append(current)

    if clockwise:
        return between_zones_clockwise
    elif counterclockwise:
        return between_zones_counterclockwise
    else:
        if _is_clockwise(start_A_zone_id, end_A_zone_id):
            return between_zones_clockwise
        else:
            return between_zones_counterclockwise




def _get_between_DE_zones(start_A_zone_id: int, end_A_zone_id: int,
                          clockwise=False, counterclockwise=False) -> list[int]:

    
    pos_diff = _get_pos_diff(start_A_zone_id, end_A_zone_id,
                             clockwise=clockwise, counterclockwise=counterclockwise)
    # 如果两个A区相同，无法判断
    if pos_diff in [0]:
        return []
    # 如果两个A区相对，且没有指定方向，无法判断
    if pos_diff == 4 and not (clockwise or counterclockwise):
        return []
    
    # 顺时针方向
    between_zones_clockwise = []
    current = start_A_zone_id
    while True:
        # 移动到下一个A区
        next_a = current + 1 if current < 8 else 1
        # 顺时针方向时，DE区编号等于next_a（因为next_a是较大的编号）
        de_zone = next_a
        between_zones_clockwise.append(de_zone)
        
        if next_a == end_A_zone_id:
            break
        current = next_a

    # 逆时针方向
    between_zones_counterclockwise = []
    current = start_A_zone_id
    while True:
        # 移动到下一个A区
        next_a = current - 1 if current > 1 else 8
        # 逆时针方向时，DE区编号等于current（因为current是较大的编号）
        de_zone = current
        between_zones_counterclockwise.append(de_zone)
        
        if next_a == end_A_zone_id:
            break
        current = next_a
    
    if clockwise:
        return between_zones_clockwise
    elif counterclockwise:
        return between_zones_counterclockwise
    else:
        if _is_clockwise(start_A_zone_id, end_A_zone_id):
            return between_zones_clockwise
        else:
            return between_zones_counterclockwise









    


def is_line_pass_a_zone_endpoint(x1, y1, x2, y2, input_shared_context) -> tuple[bool, str]:
    """
    判断线段 (x1,y1)→(x2,y2) 是否经过 A 区判定点附近。
    用点到线段的垂直距离代替点到点的距离，解决低帧率下逐帧点漏判的问题。
    """
    max_dist = input_shared_context.note_travel_dist * 0.13

    dx = x2 - x1
    dy = y2 - y1
    seg_len_sq = dx*dx + dy*dy

    for label, (ex, ey) in input_shared_context.a_zone_endpoint.items():

        if seg_len_sq < 1e-6:
            # 线段退化（两点重合），fallback 到点到点距离
            dist = np.sqrt((x1 - ex)**2 + (y1 - ey)**2)
        else:
            # 点到线段的最短距离：投影法
            t = ((ex - x1) * dx + (ey - y1) * dy) / seg_len_sq
            t = max(0.0, min(1.0, t))  # clamp 到线段范围内
            proj_x = x1 + t * dx
            proj_y = y1 + t * dy
            dist = np.sqrt((ex - proj_x)**2 + (ey - proj_y)**2)

        if dist < max_dist:
            return True, label

    return False, ""


def _divide_path_by_A_zone(note_path, start_pos, end_pos) -> list:
    """
    将一整条分割成多个小段，分割点是经过了A区 (判定点)
    返回：list[tuple[note_path, start_A_zone_label, end_A_zone_label]]
    """

    note_path_segments = []
    current_segment = []
    current_segment_start_A_zone = None
    current_segment_end_A_zone = None
    leave_start_A_zone = False

    # 使用 Catmull-Rom 样条插值扩充 note_path
    # 每对相邻原始点之间插入 num_samples 个插值点，frame 同段起点
    num_samples = 4
    center_points = [(p['cx'], p['cy']) for p in note_path]
    interp = catmull_rom_spline(center_points, num_samples=num_samples)
    interp_pts = interp.reshape(-1, 2)

    enriched_path = []
    n = len(note_path)
    for i in range(n):
        enriched_path.append(note_path[i])
        if i < n - 1:
            seg_start = i * num_samples
            seg_end = seg_start + num_samples
            for k in range(seg_start, seg_end):
                cx = float(interp_pts[k][0])
                cy = float(interp_pts[k][1])
                interp_point = {
                    'cx': cx,
                    'cy': cy,
                    'position': calculate_all_position(shared_context.touch_areas, cx, cy),
                    'frame': note_path[i]['frame'],
                }
                enriched_path.append(interp_point)
    note_path = enriched_path

    for i, point in enumerate(note_path):

        # 特例：第一个点
        if i == 0:
            current_segment.append(point)
            current_segment_start_A_zone = start_pos
            continue

        # 特例：最后一个点
        if i == len(note_path) - 1:
            current_segment.append(point)
            current_segment_end_A_zone = end_pos
            if current_segment_start_A_zone != current_segment_end_A_zone:
                note_path_segments.append((current_segment,
                                           current_segment_start_A_zone,
                                           current_segment_end_A_zone))
            break

        # 普通：其他的轨迹点
        # 检查上一帧 -> 当前帧的连线是否经过 A 区判定点
        prev_point = note_path[i - 1]
        is_pass, a_zone = is_line_pass_a_zone_endpoint(
            prev_point['cx'], prev_point['cy'],
            point['cx'], point['cy'],
            shared_context
        )
        # 没经过A区，添加点到当前段
        if not is_pass:
            if point['position'] != current_segment_start_A_zone:
                leave_start_A_zone = True
            current_segment.append(point)
            continue
        # 经过A区，且是当前段的起点
        if current_segment_start_A_zone == a_zone:
            if not leave_start_A_zone:
                # 如果没离开, 添加到当前段
                current_segment.append(point)
                continue
            else:
                # 从 A 区离开又回到了 A 区，视为当前段已结束，开启新段
                pass
        else:
            # 经过A区，且不是当前段的起点，说明进入了下一个A区
            pass
        
        # 保存当前段
        current_segment.append(point)
        current_segment_end_A_zone = a_zone
        note_path_segments.append((current_segment,
                                   current_segment_start_A_zone,
                                   current_segment_end_A_zone))
        # 开启新段
        current_segment = [point]
        current_segment_start_A_zone = a_zone
        current_segment_end_A_zone = None
        leave_start_A_zone = False # reset


    return note_path_segments






def _get_arc_syntax(start_position: int, next_position: int, end_position: int) -> str:
    """
    Args: A zone id (1-8)
    Returns: movement syntax like '>5' or '<3'
    """

    # 判断起始点在顶部还是底部
    if start_position in [1,2,7,8]:
        start_side = 'up'
    else:
        start_side = 'down'

    # 判断旋转方向
    # > 代表从起点开始箭头向右, < 代表从起点开始箭头向左
    if start_side == 'up':
        # 处理1和8的特殊情况
        if start_position == 1:
            if next_position in [6, 7, 8]:
                next_position -= 8
        elif start_position == 8:
            if next_position in [1, 2, 3]:
                next_position += 8
        # 判断方向
        if next_position > start_position:
            movement_type = '>'
        else:
            movement_type = '<'
    else: # start_side == 'down'
        if next_position > start_position:
            movement_type = '<'
        else:
            movement_type = '>'

    # 组合语法
    movement_syntax = f"{movement_type}{end_position}"
    return movement_syntax







def _is_consecutive(id1, id2):
    # 检查两个A区ID是否连续（考虑环形结构）
    # 顺时针：1->2, 2->3, ..., 7->8, 8->1
    if (id2 - id1) == 1 or (id1 == 8 and id2 == 1):
        return True, 'clockwise'
    # 逆时针：1->8, 8->7, ..., 2->1
    if (id1 - id2) == 1 or (id1 == 1 and id2 == 8):
        return True, 'counterclockwise'
    return False, None

