import numpy as np
import os
import math
from pathlib import Path

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



def generate_maidata(shared_context: SharedContext, bpm, chart_lv,
                     base_denominator, duration_denominator, notes_info,
                     note_speed: float, touch_speed: float):


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
        f.write(f'&inote_{chart_lv}=({bpm})' + '{1},\n')
        # 打印流速信息
        note_speed_str = f"{note_speed:.2f}" if note_speed else "N/A"
        touch_speed_str = f"{touch_speed:.2f}" if touch_speed else "N/A"
        f.write(f"|| note speed: {note_speed_str}, touch speed: {touch_speed_str}")

    # 打印基础信息
    level_label = ['zero', 'easy', 'basic', 'advanced', 'expert', 'master', 'remaster', 'special']
    print(f"\n{video_name} - {level_label[chart_lv]}")
    one_beat_Msec = 60 / bpm * 1000 * 4
    base_resolution = one_beat_Msec / base_denominator
    print(f"bpm: {bpm}, one beat: {one_beat_Msec:.3f} ms, base resolution: {base_resolution:.3f} ms")






    # 计算最小公倍数分母用于累加 (兼容1/12)
    if base_denominator >= 16:
        lcm_denom = base_denominator * 12 // math.gcd(base_denominator, 12)
    else:
        lcm_denom = base_denominator


    init_time = None
    last_time = None
    base_numerator_counter = 0
    last_position = None
    last_denominator = 0
    time_deviations = []






    with open(txt_path, 'a', encoding='utf-8') as f:
        for (track_id, note_type, note_variant, position), time in notes_info:

            note_time = check_note_time(time, track_id)
            if note_time is None:
                continue
            
            # 对于 slide, hold, touch_hold 可能存在 duration 信息
            if isinstance(time, tuple) and len(time) >= 2:
                if note_type == NoteType.SLIDE:
                    # slide 可包含多个 duration
                    position = _append_slide_duration_syntax(
                        position, list(time[1:]), one_beat_Msec,
                        base_denominator, duration_denominator)
                    # 特例：三段同头直线 slide 压缩为 w 语法
                    position = _try_compress_wifi_special(position)
                elif note_type == NoteType.HOLD and time[-1] == 0:
                    # 特例: hold 时值为 0 时不添加时值文本
                    pass
                else:
                    duration_syntax = parse_note_duration(one_beat_Msec, note_type, time[-1],
                                                          base_denominator, duration_denominator)
                    position += duration_syntax





            if last_time is None:
                # 第一个音符
                init_time = note_time
                last_time = note_time
                last_position = position
                # 控制台打印
                print(f"first note appear at {note_time:.1f} ms")
                continue




            # 计算与上一个音符的时间差，转为分数形式
            diff_Msec = note_time - last_time
            diff_beat = diff_Msec / one_beat_Msec
            numerator, denominator, one = get_fraction(diff_beat, base_denominator, enable_12=True)

            # update base_numerator_counter
            # 使用最小公倍数分母进行累加 (为了兼容1/12)
            selected_total_numerator = one * denominator + numerator
            base_numerator = selected_total_numerator * (lcm_denom // denominator)
            base_numerator_counter += base_numerator

            # update last_time
            # 采用 init_time + 总 passed_beat
            # 这是精确的谱面播放到此处的时间点，避免了累加误差
            passed_beat = base_numerator_counter / lcm_denom
            passed_beat_Msec = passed_beat * one_beat_Msec
            last_time = passed_beat_Msec + init_time

            # 统计误差
            # note_time 是通过分析得到的音符实际时间
            # last_time 是通过分数化处理后计算得到的理论时间
            time_deviation = note_time - last_time
            time_deviations.append(time_deviation)





            if numerator == 0 and one == 0:
                # 零间隔，使用 '/' 与上一个音符连接 
                position = f'{last_position}/{position}'
                # 跳过后续的处理，直接 continue
                last_position = position
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
            last_position = position
            









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




def check_note_time(time, track_id):

    if isinstance(time, (float, int)):
        # check time
        if math.isnan(time) or time < 0:
            print(f"analyze_all_notes_info: invalid time value for track_id {track_id}, time: {time}")
            return None
        # 赋值
        return time

    elif isinstance(time, tuple):
        # check time tuple
        if len(time) == 0:
            print(f"analyze_all_notes_info: empty time tuple for track_id {track_id}")
            return None
        valid = True
        for i, t in enumerate(time):
            if not (isinstance(t, (float, int)) and not math.isnan(t) and t >= 0):
                print(f"analyze_all_notes_info: invalid time tuple element at index {i} for track_id {track_id}, value: {t}")
                valid = False
                break
        if not valid:
            return None
        # 赋值
        return time[0]

    else:
        print(f"analyze_all_notes_info: invalid time format for track_id {track_id}, time: {time}")
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
