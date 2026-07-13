import math

from ..detect.note_definition import *




_WIFI_ENDPOINT_SEQ = {
    '1': '456',
    '2': '567',
    '3': '678',
    '4': '781',
    '5': '812',
    '6': '123',
    '7': '234',
    '8': '345',
}



def parse_note_info(key, value, timing_points,
                    base_denominator, duration_denominator
                   ) -> tuple[float, float, str, float] | None:
    
    (track_id, note_type, note_variant, cur_position), time = key, value

    raw_cur_note_time = _get_note_reach_time(time, track_id)
    if raw_cur_note_time is None: return None

    # 可能需要吸附
    cur_note_time = _snap_note_time_to_bpm_segment(raw_cur_note_time, timing_points, base_denominator)

    # 获取这个音符的 bpm
    cur_bpm = _get_bpm_by_note_time(cur_note_time, timing_points)
    one_beat_ms = calculate_one_beat_ms(cur_bpm)

    # 对于 slide, hold, touch_hold 可能存在 duration 信息
    # 更新 cur_position 添加时值文本
    if isinstance(time, tuple) and len(time) >= 2:
        if note_type == NoteType.SLIDE:
            # slide 可包含多个 duration
            cur_position = _append_slide_duration_syntax(
                cur_position, list(time[1:]), one_beat_ms,
                base_denominator, duration_denominator
            )
            # 特例：三段同头直线 slide 压缩为 w 语法
            cur_position = _try_compress_wifi_slide(cur_position)
        elif note_type == NoteType.HOLD and time[-1] == 0:
            # 特例: hold 时值为 0 时不添加时值文本
            pass
        else:
            duration_syntax = _parse_note_duration(one_beat_ms, note_type, time[-1],
                                                   base_denominator, duration_denominator)
            cur_position += duration_syntax

    return raw_cur_note_time, cur_note_time, cur_position, cur_bpm







def calculate_one_beat_ms(bpm):
    return 60 / bpm * 1000 * 4


def get_bpm_segment_idx(note_time: float, timing_points: list):
    """找到当前段索引（最后一个 start_ms <= note_time 的段）"""
    seg_idx = 0
    for i, tp in enumerate(timing_points):
        if tp[2] <= note_time:
            seg_idx = i
        else:
            break
    return seg_idx


def _get_bpm_by_note_time(note_time: float, timing_points: list) -> float:
    """返回起始时间最大且 <= note_time 的那段 BPM 数值"""
    seg_idx = get_bpm_segment_idx(note_time, timing_points)
    return timing_points[seg_idx][1]







def _snap_note_time_to_bpm_segment(note_time, timing_points,
                                   base_denominator) -> float:
    """
    双方向吸附：
    1. 前向：note_time 足够接近下一段起点 → 吸附到下一段
    2. 后向：note_time 足够接近当前段起点 → 吸附到当前段
       （第一段不后向吸附）

    判定标准：计算差值后用 get_fraction 判断是否返回 (0, 1, 0)。

    吸附判定:
        计算 note_time 到 BPM 段起始时间的差值,
        如果 get_fraction 返回 (0, 1, 0),
        说明此音符非常接近 bpm 段边界，执行吸附。

    返回:
        如果不用吸附，返回原始 note_time
        如果需要吸附，返回 BPM 段的起始时间，视为新的 note_time
    """

    from .maidata_generate import get_fraction  # 避免循环导入

    # 单段 BPM，无需吸附
    if len(timing_points) <= 1:
        return note_time

    seg_idx = get_bpm_segment_idx(note_time, timing_points)

    # 后向吸附：当前段起点
    if seg_idx > 0: # 第一段不吸
        current_start_ms = timing_points[seg_idx][2]
        diff_ms = note_time - current_start_ms
        current_bpm = timing_points[seg_idx][1]
        one_beat_ms = calculate_one_beat_ms(current_bpm)
        diff_beat = diff_ms / one_beat_ms
        numerator, denominator, one = get_fraction(diff_beat, base_denominator)
        if numerator == 0 and denominator == 1 and one == 0:
            return current_start_ms

    # 前向吸附：下一段起点
    if seg_idx < len(timing_points) - 1: # 如果位于最后一段，没有新段可供吸附，直接返回
        next_start_ms = timing_points[seg_idx + 1][2]
        diff_ms = next_start_ms - note_time
        current_bpm = timing_points[seg_idx][1]
        one_beat_ms = calculate_one_beat_ms(current_bpm)
        diff_beat = diff_ms / one_beat_ms
        numerator, denominator, one = get_fraction(diff_beat, base_denominator)
        if numerator == 0 and denominator == 1 and one == 0:
            return next_start_ms

    # 无需吸附
    return note_time






def _get_note_reach_time(time, track_id):

    if isinstance(time, (float, int)):
        # check time
        if math.isnan(time) or time < 0:
            print(f"get_note_reach_time: invalid time value for track_id {track_id}, time: {time}")
            return None
        # 赋值
        return time

    elif isinstance(time, tuple):
        # check time tuple
        if len(time) == 0:
            print(f"get_note_reach_time: empty time tuple for track_id {track_id}")
            return None
        valid = True
        for i, t in enumerate(time):
            if not (isinstance(t, (float, int)) and not math.isnan(t) and t >= 0):
                print(f"get_note_reach_time: invalid time tuple element at index {i} for track_id {track_id}, value: {t}")
                valid = False
                break
        if not valid:
            return None
        # 赋值
        return time[0]

    else:
        print(f"get_note_reach_time: invalid time format for track_id {track_id}, time: {time}")
        return None




def _parse_note_duration(one_beat_Msec, note_type, note_length, base_denominator, duration_denominator) -> str:

    from .maidata_generate import get_fraction  # 避免循环导入

    length_beat = note_length / one_beat_Msec

    # 分类处理
    if note_type == NoteType.TOUCH_HOLD or note_type == NoteType.SLIDE:
        # touch_hold / slide -> duration_denominator
        denominator_to_use = duration_denominator
    else:
        # hold -> base_denominator
        # 因为 hold 移动模式与 tap 相同，所以时值与 tap 一样用 base_denominator 处理
        denominator_to_use = base_denominator
    
    # 将 duration 变为分数形式
    numerator, denominator, one = get_fraction(
        length_beat, denominator_to_use, enable_12=False, enable_24=False, enable_48_1=False)
    # 将整数部分加入分子
    if one > 0:
        numerator = numerator + one * denominator
    # 异常情况默认变为1/1 (时值不能为0)
    if numerator == 0 and denominator == 1 and one == 0:
        numerator = 1
        denominator = 1

    duration_syntax = f'[{denominator}:{numerator}]'

    return duration_syntax




def _append_slide_duration_syntax(position: str,
                                  durations,
                                  one_beat_Msec,
                                  base_denominator,
                                  duration_denominator) -> str:
    """
    插入 slide 的时值文本
    - 单 slide: 1-2 -> 1-2[8:1]
    - 多 slide: 1-2*-5 -> 1-2[8:1]*-5[8:1]
    """
    if not durations:
        return position

    # 单星星: 直接在末尾添加时值
    if '*' not in position:
        return position + _parse_note_duration(
            one_beat_Msec,
            NoteType.SLIDE,
            durations[-1],
            base_denominator,
            duration_denominator,
        )

    # 多段链式语法：按 '*' 分段填充时值
    segments = position.split('*')
    if len(segments) != len(durations):
        print(
            f"generate_maidata: slide segment/duration mismatch, "
            f"segments={len(segments)}, durations={len(durations)}, position={position}"
        )
        # fallback: 如果分段数量与时值数量不匹配，直接在末尾添加时值
        return position + _parse_note_duration(
            one_beat_Msec,
            NoteType.SLIDE,
            durations[-1],
            base_denominator,
            duration_denominator,
        )

    output_segments = []
    for segment, duration in zip(segments, durations):
        duration_syntax = _parse_note_duration(
            one_beat_Msec,
            NoteType.SLIDE,
            duration,
            base_denominator,
            duration_denominator,
        )
        output_segments.append(segment + duration_syntax)

    return '*'.join(output_segments)




def _try_compress_wifi_slide(slide_position: str) -> str:
    """
    仅处理三段同头直线 slide 的特例：
    1-4[2:1]*-5[2:1]*-6[2:1] -> 1w5[2:1]

    约束：
    - 恰好 3 段（由 '*' 连接）
    - 三段都是 -x(varient) 直线段
    - 三段时值文本完全一致
    - 三段尾部变体完全一致
    - 三段终点集合命中起点硬编码映射（顺序可乱）
    - 同时保留头部与尾部变体
    """

    def check_varient(syntax) -> bool:
        if not syntax[0].isdigit():
            return False
        varient = syntax[1:] if len(syntax) > 1 else ''
        if varient not in ('', 'b', 'x', 'bx'):
            return False
        return True


    if '*' not in slide_position:
        return slide_position

    # 按 * 分割
    segments = slide_position.split('*')

    # 必须严格是三段
    if len(segments) != 3:
        return slide_position
    
    # 每个段有且仅有一个 "-"
    if not all(seg.count('-') == 1 for seg in segments):
        return slide_position
    
    duration = None
    start = None
    end_syntax = None
    end_pos_ids = None

    # 第一段结构: 起点(变体) "-" 终点(变体) 时值
    try:
        # 提取时值
        syntax, dur_part = segments[0].split('[')
        # 提取起点终点
        start, end = syntax.split('-')
        if not check_varient(start):
            return slide_position
        if not check_varient(end):
            return slide_position
        # 通过
        duration = '[' + dur_part # 补全括号
        end_syntax = end[1:] if len(end) > 1 else ''
        end_pos_ids = end[0]
    except Exception:
        return slide_position

    # 第二/三段结构: "-" 终点(变体) 时值
    for seg in segments[1:]:
        try:
            # 提取时值
            syntax, dur_part = seg.split('[')
            if '[' + dur_part != duration: # 时值一致性检查
                return slide_position
            # 提取终点
            if not syntax.startswith('-'):
                return slide_position
            end = syntax[1:]
            if not check_varient(end):
                return slide_position
            if end[1:] != end_syntax: # 变体一致性检查
                return slide_position
            end_pos_ids = end_pos_ids + end[0] # concat str
        except Exception:
            return slide_position

    seq = _WIFI_ENDPOINT_SEQ.get(start[0])
    if not seq:
        return slide_position
    
    if sorted(end_pos_ids) != sorted(seq):
        return slide_position
    
    return f"{start}w{seq[1]}{end_syntax}{duration}"
