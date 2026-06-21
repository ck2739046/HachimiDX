import numpy as np
import os
import math

from .shared_context import *
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




class PassedBeatTracker:
    """
    按加入顺序追踪每个 BPM 段下已通过的 beat 数。

    同一 BPM 可多次出现（视为不同段），每段的 passed_numerator 独立累加。
    内部使用最小公倍数分母 (lcm_denom) 统一分数，避免浮点数误差。
    """

    def __init__(self, base_denominator: int):
        self.lcm_denom = self.calculate_lcm_denom(base_denominator)
        self._entries: list[dict] = []  # list of dict {bpm, passed_numerator}

    @property
    def entries(self) -> list[dict]:
        return self._entries

    @staticmethod
    def calculate_lcm_denom(base_denominator: int) -> int:
        if base_denominator >= 16:
            return base_denominator * 12 // math.gcd(base_denominator, 12)
        else:
            return base_denominator

    def add(self, bpm: float, numerator: int, denominator: int, one: int = 0) -> None:
        # 将分数统一转为 lcm_denom 当分母
        # 假设分母不为 0，并且是 lcm_denom 的因数
        total_numerator = one * denominator + numerator
        scaled_numerator = total_numerator * (self.lcm_denom // denominator)
        # 如果列表为空或最后一项的 BPM 不同，添加新段；否则累加到当前段
        if not self._entries or self._entries[-1]['bpm'] != bpm:
            self._entries.append({'bpm': bpm, 'passed_numerator': 0})
        # 始终累加到最新段
        self._entries[-1]['passed_numerator'] += scaled_numerator

    def total_elapsed_ms(self) -> float:
        total_ms = 0
        for entry in self._entries:
            one_beat_ms = calculate_one_beat_ms(entry['bpm'])
            segment_ms = one_beat_ms * entry['passed_numerator'] / self.lcm_denom
            total_ms += segment_ms
        return total_ms





def generate_maidata(shared_context: SharedContext,
                     timing_points, chart_lv,
                     base_denominator, duration_denominator,
                     notes_info,
                     note_speed: float, touch_speed: float):
    
    # timing_points = [[beat_index, bpm, start_ms], ...]

    # 准备输出txt文件
    output_dir = shared_context.std_video_path.parent
    txt_path = output_dir / "maidata.txt"
    if os.path.exists(txt_path):
        os.remove(txt_path)

    # 写入文件头
    video_name = output_dir.name
    with open(txt_path, 'w', encoding='utf-8') as f:
        f.write(f'&title={video_name}\n')
        f.write('&artist=default\n')
        f.write('&first=0\n')
        f.write(f'&des_{chart_lv}=default\n')
        f.write(f'&lv_{chart_lv}=15\n')
        f.write(f'&inote_{chart_lv}=({timing_points[0][1]})' + '{1},\n')
        # 打印流速信息
        note_speed_str = f"{note_speed:.2f}" if note_speed else "N/A"
        touch_speed_str = f"{touch_speed:.2f}" if touch_speed else "N/A"
        f.write(f"|| note speed: {note_speed_str}, touch speed: {touch_speed_str}")

    # 打印基础信息
    level_label = ['zero', 'easy', 'basic', 'advanced', 'expert', 'master', 'remaster', 'special']
    print(f"\n{video_name} - {level_label[chart_lv]}")




    # 追踪理论时间
    init_time = None
    passed_beat_tracker = PassedBeatTracker(base_denominator)
    
    # 核心: 追踪音符状态
    last_note_time = None
    last_position = None
    last_denominator = None
    
    # 仅用于统计误差
    time_deviations = []





    # 开始生成
    with open(txt_path, 'a', encoding='utf-8') as f:
        for (track_id, note_type, note_variant, cur_position), time in notes_info:

            raw_cur_note_time = get_note_reach_time(time, track_id)
            if raw_cur_note_time is None: continue

            # 可能需要吸附
            cur_note_time = snap_note_time_to_bpm_segment(raw_cur_note_time, timing_points, base_denominator)
            
            # 获取这个音符的 bpm
            cur_bpm = get_bpm_by_note_time(cur_note_time, timing_points)
            one_beat_ms = calculate_one_beat_ms(cur_bpm)

            # 对于 slide, hold, touch_hold 可能存在 duration 信息
            if isinstance(time, tuple) and len(time) >= 2:
                if note_type == NoteType.SLIDE:
                    # slide 可包含多个 duration
                    cur_position = _append_slide_duration_syntax(
                        cur_position, list(time[1:]), one_beat_ms,
                        base_denominator, duration_denominator)
                    # 特例：三段同头直线 slide 压缩为 w 语法
                    cur_position = _try_compress_wifi_special(cur_position)
                elif note_type == NoteType.HOLD and time[-1] == 0:
                    # 特例: hold 时值为 0 时不添加时值文本
                    pass
                else:
                    duration_syntax = parse_note_duration(one_beat_ms, note_type, time[-1],
                                                          base_denominator, duration_denominator)
                    cur_position += duration_syntax





            if last_note_time is None:
                # 第一个音符
                init_time = cur_note_time
                last_note_time = cur_note_time
                last_position = cur_position
                # 控制台打印
                print(f"first note appear at {cur_note_time:.1f} ms")
                continue




            # 计算与上一个音符的时间差，转为分数形式
            beat_diffs = calculate_beat_diff(last_note_time, cur_note_time,
                                             timing_points, base_denominator)

            # update last_note_time
            # 采用 init_time + 总 passed_beat
            # 这是精确的谱面播放到此处的时间点，避免了累加误差
            for beat_diff in beat_diffs:
                passed_beat_tracker.add(*beat_diff)
            last_note_time = init_time + passed_beat_tracker.total_elapsed_ms
            
            # 统计误差
            # note_time 是通过分析得到的音符实际时间
            # last_time 是通过分数化处理后计算得到的理论时间
            time_deviation = raw_cur_note_time - last_note_time
            time_deviations.append(time_deviation)





            
            # 提前处理零间隔并行音符
            if len(beat_diffs) == 1:
                (bpm, numerator, denominator, one) = beat_diffs[0]
                if numerator == 0 and one == 0:
                    # 零间隔，使用 '/' 与上一个音符连接 
                    cur_position = f'{last_position}/{cur_position}'
                    # 跳过后续的处理，直接 continue
                    last_position = cur_position
                    continue




            

            # 生成逗号部分
            if numerator == 0 and denominator == 1 and one > 0:
                # 特殊情况2：时间间隔是整数
                # 逗号数量等于整数部分
                commas = f'{"," * one}'
            elif one > 0:
                # 特殊情况1：时间间隔是小数，但是 > 1
                # 比如 11/4，正常来说是 {4},,,,,,,,,,, (x11)
                # 现在简写成 {4},,,{1},,
                # 使用带分数
                commas = f'{"," * numerator}' + '{1}' + f'{"," * one}'
            else:
                # 普通情况: 时间间隔是小数，并且 < 1
                commas = f'{"," * numerator}'

            # 将当前音符写入txt
            if denominator != last_denominator:
                f.write('\n{' + f'{denominator}' + '}' + f'{last_position}{commas}')
            else:
                f.write(f'{last_position}{commas}')

            # 上面使用了带分数，所以现在是 1
            if one > 0: denominator = 1

            last_denominator = denominator
            last_position = cur_position
            









    # 添加结尾E
    with open(txt_path, 'a', encoding='utf-8') as f:
        f.write(f'{last_position},\n' + '{1},,,E\n') # 结尾默认 3 拍延迟

    # 打印offset统计信息（至少需要多个音符才有偏差数据）
    if len(time_deviations) > 10:
        length = len(time_deviations)
        mean = np.mean(time_deviations)
        min = np.min(time_deviations)
        max = np.max(time_deviations)
        median = np.median(time_deviations)
        std_dev = np.std(time_deviations)
        print(f"\nTime deviations of {length} notes: Median {median:.3f}, Min {min:.3f}, Max {max:.3f}, Mean {mean:.3f}, Std Dev {std_dev:.3f}")
    else:
        print(f"\nNot enough notes detected, no time deviation statistics available.")

    # 打印生成的 maidata.txt 路径
    print(f"\nmaidata.txt: {txt_path}")




def get_best_numerator_denominator(diff_beat, input_denominator, enable_12):
    """在12和输入分母中选择误差最小的分母"""

    # 如果输入的分母 >=16，启用12作为备选分母
    candidates = [input_denominator]
    if input_denominator >= 16 and enable_12:
        candidates.append(12)
    
    # 选择误差最小的分母
    best_error = float('inf')
    best_total_numerator = 0
    best_denominator = input_denominator

    for denom in candidates:
        total_numerator = round(diff_beat * denom)
        # 零间隔
        if total_numerator == 0:
            error = abs(diff_beat)
            if error < best_error:
                best_error = error
                best_total_numerator = 0
                best_denominator = 1
            continue
        # 计算误差
        fraction_value = total_numerator / denom
        error = abs(diff_beat - fraction_value)
        if error < best_error:
            best_error = error
            best_total_numerator = total_numerator
            best_denominator = denom

    return best_total_numerator, best_denominator




def get_fraction(diff_beat, input_denominator, enable_12=True):
        
        # 将数字转为带分数形式
        # 返回格式：分子，分母，整数
        
        # 0.5   =  1/2 + 0  =  1, 2, 0
        # 1.0   =  0/1 + 1  =  0, 1, 1
        # 2.25  =  1/4 + 2  =  1, 4, 2
        
        raw_numerator, raw_denominator = get_best_numerator_denominator(diff_beat, input_denominator, enable_12)
        if raw_numerator == 0: return 0, 1, 0 # 零间隔直接返回
        # 获取整数和余数部分
        one = raw_numerator // raw_denominator
        remainder = raw_numerator % raw_denominator
        # 是整数，直接返回，不需要约分余数
        if remainder == 0: return 0, 1, one
        # 是小数，约分余数部分
        gcd_num = math.gcd(remainder, raw_denominator)
        numerator = remainder // gcd_num
        denominator = raw_denominator // gcd_num

        return numerator, denominator, one




def get_note_reach_time(time, track_id):

    if isinstance(time, (float, int)):
        # check time
        if math.isnan(time) or time < 0:
            print(f"analyze_all_notes_info: get_note_reach_time: invalid time value for track_id {track_id}, time: {time}")
            return None
        # 赋值
        return time

    elif isinstance(time, tuple):
        # check time tuple
        if len(time) == 0:
            print(f"analyze_all_notes_info: get_note_reach_time: empty time tuple for track_id {track_id}")
            return None
        valid = True
        for i, t in enumerate(time):
            if not (isinstance(t, (float, int)) and not math.isnan(t) and t >= 0):
                print(f"analyze_all_notes_info: get_note_reach_time: invalid time tuple element at index {i} for track_id {track_id}, value: {t}")
                valid = False
                break
        if not valid:
            return None
        # 赋值
        return time[0]

    else:
        print(f"analyze_all_notes_info: get_note_reach_time: invalid time format for track_id {track_id}, time: {time}")
        return None




def parse_note_duration(one_beat_Msec, note_type, note_length, base_denominator, duration_denominator) -> str:

    length_beat = note_length / one_beat_Msec

    # 分类处理
    if note_type == NoteType.TOUCH_HOLD or note_type == NoteType.SLIDE:
        # touch_hold / slide -> duration_denominator
        denominator_to_use = duration_denominator
    else:
        # hold -> base_denominator
        # 因为 hold 头尾视为两个 tap，所以时值按照 base_denominator 处理
        denominator_to_use = base_denominator
    
    # 将 duration 变为分数形式
    numerator, denominator, one = get_fraction(length_beat, denominator_to_use, enable_12=False)
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
        return position + parse_note_duration(
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
        return position + parse_note_duration(
            one_beat_Msec,
            NoteType.SLIDE,
            durations[-1],
            base_denominator,
            duration_denominator,
        )

    output_segments = []
    for segment, duration in zip(segments, durations):
        duration_syntax = parse_note_duration(
            one_beat_Msec,
            NoteType.SLIDE,
            duration,
            base_denominator,
            duration_denominator,
        )
        output_segments.append(segment + duration_syntax)

    return '*'.join(output_segments)









def _try_compress_wifi_special(slide_position: str) -> str:
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


def get_bpm_by_note_time(note_time: float, timing_points: list) -> float:
    """返回起始时间最大且 <= note_time 的那段 BPM 数值"""
    seg_idx = get_bpm_segment_idx(note_time, timing_points)
    return timing_points[seg_idx][1]


def snap_note_time_to_bpm_segment(note_time, timing_points,
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
        numerator, denominator, one = get_fraction(diff_beat, base_denominator, enable_12=True)
        if numerator == 0 and denominator == 1 and one == 0:
            return current_start_ms

    # 前向吸附：下一段起点
    if seg_idx < len(timing_points) - 1: # 如果位于最后一段，没有新段可供吸附，直接返回
        next_start_ms = timing_points[seg_idx + 1][2]
        diff_ms = next_start_ms - note_time
        current_bpm = timing_points[seg_idx][1]
        one_beat_ms = calculate_one_beat_ms(current_bpm)
        diff_beat = diff_ms / one_beat_ms
        numerator, denominator, one = get_fraction(diff_beat, base_denominator, enable_12=True)
        if numerator == 0 and denominator == 1 and one == 0:
            return next_start_ms

    # 无需吸附
    return note_time








def calculate_beat_diff(last_note_time: float,
                        cur_note_time: float,
                        timing_points: list,
                        base_denominator: int,
                       ) -> list[tuple[float, int, int, int]]:
    """
    同时适配 非跨段 和 跨段
    将 last_note_time → cur_note_time 按 BPM 段边界拆分。
    跨越多个 BPM 段时，中间用段起始时间作为切分点。

    返回列表: 每个子段的 (bpm, numerator, denominator, one)。
    """
    result: list[tuple[float, int, int, int]] = []

    # 初始起点 = last_note_time
    seg_start = last_note_time
    # 初始起点段索引
    seg_idx = get_bpm_segment_idx(seg_start, timing_points)

    while True:
        bpm = timing_points[seg_idx][1]

        # 下一个 BPM 段起点
        if seg_idx + 1 < len(timing_points):
            next_boundary = timing_points[seg_idx + 1][2]
        else:
            next_boundary = float('inf')

        if next_boundary >= cur_note_time:
            # 最后一个子段：seg_start → cur_note_time
            diff_ms = cur_note_time - seg_start
            one_beat_ms = calculate_one_beat_ms(bpm)
            diff_beat = diff_ms / one_beat_ms
            numerator, denominator, one = get_fraction(diff_beat, base_denominator, enable_12=True)
            result.append((bpm, numerator, denominator, one))
            break
        else:
            # 中间子段：seg_start → next_boundary
            diff_ms = next_boundary - seg_start
            one_beat_ms = calculate_one_beat_ms(bpm)
            diff_beat = diff_ms / one_beat_ms
            numerator, denominator, one = get_fraction(diff_beat, base_denominator, enable_12=True)
            result.append((bpm, numerator, denominator, one))
            # 推进到下一段
            seg_start = next_boundary
            seg_idx += 1

    return result
