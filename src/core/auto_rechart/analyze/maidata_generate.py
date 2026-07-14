import numpy as np
import os
import math

from .shared_context import *
from ..detect.note_definition import *
from .maidata_parse import parse_note_info, get_bpm_segment_idx, calculate_one_beat_ms




class PassedBeatTracker:
    """
    追踪理论播放时间

    仅追踪最新 BPM 段的数据，过往的 BPM 段直接视为已通过

    内部保存两个状态:
      - current_bpm_segment_index:       当前所处的 BPM 段索引
      - current_bpm_segment_passed_beat: 当前段内已通过的 beat fraction
    """

    def __init__(self, timing_points: list):
        # 常量
        self.lcm_denom = 384
        self._timing_points = self.convert_timing_points(timing_points, self.lcm_denom)
        # 变量
        self.current_bpm_segment_index = 0
        self.current_bpm_segment_passed_beat = 0  # 仅分子，基于 384


    @staticmethod
    def convert_timing_points(timing_points: list, lcm_denom: int) -> dict[int, tuple[int, float]]:
        """
        将 timing_points 转换为字典形式，方便按段索引访问
        key   = 段序号 (0, 1, 2, ...)
        value = tuple[ beat_index(基于384的分子), bpm ]
        """
        converted = {}
        for i, (beat_index, bpm, start_ms) in enumerate(timing_points):
            converted[i] = (round(beat_index * lcm_denom), bpm)
        return converted


    def add(self, current_bpm_segment_index: int,
                  numerator: int, denominator: int, one: int = 0) -> None:
        # 如果输入的段索引更大，说明已经跨段了，直接更新索引并清空 passed_beat
        if current_bpm_segment_index > self.current_bpm_segment_index:
            self.current_bpm_segment_index = current_bpm_segment_index
            self.current_bpm_segment_passed_beat = 0
        # 如果输入的段索引更小，说明尝试添加到之前的 BPM 段，直接报错
        elif current_bpm_segment_index < self.current_bpm_segment_index:
            raise ValueError(f"Cannot add to a previous BPM segment: index {current_bpm_segment_index} < {self.current_bpm_segment_index}")

        # 将分数统一转为 lcm_denom 为分母的形式
        # 假设分母不为 0, 并且是 lcm_denom 的因数
        total_numerator = one * denominator + numerator
        scaled_numerator = total_numerator * (self.lcm_denom // denominator)
        self.current_bpm_segment_passed_beat += scaled_numerator


    def get_total_elapsed_ms(self) -> float:
        """理论总播放时间（毫秒）"""
        total_ms = 0.0
        idx = self.current_bpm_segment_index
        # 过往段: 使用该段的总时间
        for i in range(idx):
            start_beat, cur_bpm = self._timing_points[i]
            next_beat, _ = self._timing_points[i + 1]
            cur_total_beat = (next_beat - start_beat) / self.lcm_denom
            total_ms += cur_total_beat * calculate_one_beat_ms(cur_bpm)
        # 当前段: passed_beat * one_beat_ms
        _, cur_bpm = self._timing_points[idx]
        cur_total_beat = self.current_bpm_segment_passed_beat / self.lcm_denom
        total_ms += cur_total_beat * calculate_one_beat_ms(cur_bpm)

        return total_ms









def generate_maidata(shared_context: SharedContext,
                     timing_points, chart_lv,
                     base_denominator, duration_denominator,
                     notes_info,
                     note_speed: float, touch_speed: float,
                     app_version: str):
    
    # timing_points = [(beat_index, bpm, start_ms), ...]




    # 追踪理论时间
    init_time = None
    passed_beat_tracker = PassedBeatTracker(timing_points)
    
    # 核心: 追踪音符状态
    last_note_time = None
    last_position = None
    last_denominator = None
    last_last_bpm = None
    last_bpm = None
    
    # 仅用于统计误差
    time_deviations = []
    # 仅用于统计吸附到 bpm 段的差值
    snap_deltas = []




        for key, value in notes_info:

            # 解析音符信息
            result = parse_note_info(key, value, timing_points,
                                     base_denominator, duration_denominator)
            if result is None: continue
            raw_cur_note_time, cur_note_time, cur_position, cur_bpm_seg_index = result
            
            # 统计吸附到 bpm 段的差值
            if cur_note_time != raw_cur_note_time:
                snap_deltas.append(raw_cur_note_time - cur_note_time)




            if last_note_time is None:
                # 第一个音符
                init_time = cur_note_time
                last_note_time = cur_note_time
                last_position = cur_position
                last_bpm = cur_bpm
                # 控制台打印
                print(f"first note appear at {cur_note_time:.1f} ms")
                continue




            # 计算与上一个音符的时间差，转为分数形式
            beat_diffs = calculate_beat_diff(last_note_time, cur_note_time,
                                             timing_points, base_denominator)
            if not beat_diffs:
                print(f"Warning: empty beat_diffs between {last_note_time:.1f} and {cur_note_time:.1f}, skipping")
                continue

            # update last_note_time
            # 采用 init_time + 总 passed_beat
            # 这是精确的谱面播放到此处的时间点，避免了累加误差
            for beat_diff in beat_diffs:
                passed_beat_tracker.add(*beat_diff)
            last_note_time = init_time + passed_beat_tracker.get_total_elapsed_ms()
            
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

    # 打印吸附（snap）统计信息
    if snap_deltas:
        snap_count = len(snap_deltas)
        snap_mean = np.mean(snap_deltas)
        backward_count = sum(1 for d in snap_deltas if d > 0)  # 后向吸附：吸附到当前段起点
        forward_count = sum(1 for d in snap_deltas if d < 0)   # 前向吸附：吸附到下一段起点
        print(f"\nSnap deltas of {snap_count} notes (backward {backward_count} / forward {forward_count}): Mean {snap_mean:.3f}")





def get_best_numerator_denominator(diff_beat, input_denominator,
                                   enable_12, enable_24, enable_48_1):
    """在12/24和输入分母中选择误差最小的分母"""

    # 如果输入的分母 >=12，启用12作为备选分母
    # 如果输入的分母 >=24，启用24作为备选分母
    candidates = [input_denominator]
    if input_denominator >= 12 and enable_12:
        candidates.append(12)
    if input_denominator >= 24 and enable_24:
        candidates.append(24)
    if input_denominator >= 48 and enable_48_1:
        candidates.append(48)

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




def get_fraction(diff_beat, input_denominator,
                 enable_12=True, enable_24=True, enable_48_1=True):
        
        # 将数字转为带分数形式
        # 返回格式：分子，分母，整数
        
        # 0.5   =  1/2 + 0  =  1, 2, 0
        # 1.0   =  0/1 + 1  =  0, 1, 1
        # 2.25  =  1/4 + 2  =  1, 4, 2
        
        raw_numerator, raw_denominator = get_best_numerator_denominator(
            diff_beat, input_denominator, enable_12, enable_24, enable_48_1)
        
        # 有限度的支持 48 分音符: 仅限 1/48
        # 如果不是 N+1/48，禁用 48 并重新计算
        if enable_48_1 and raw_denominator == 48 and raw_numerator % 48 != 1:
            raw_numerator, raw_denominator = get_best_numerator_denominator(
                diff_beat, input_denominator, enable_12, enable_24, enable_48_1=False)
        
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
            numerator, denominator, one = get_fraction(diff_beat, base_denominator)
            result.append((bpm, numerator, denominator, one))
            break
        else:
            # 中间子段：seg_start → next_boundary
            diff_ms = next_boundary - seg_start
            one_beat_ms = calculate_one_beat_ms(bpm)
            diff_beat = diff_ms / one_beat_ms
            numerator, denominator, one = get_fraction(diff_beat, base_denominator)
            # 过滤零长度碎段
            # 产生的原因可能是 bpm config 的 global offset 没有精准对齐
            # 或者 bpm config 的起始时间 / last_not_time 有精度误差
            # 总之产生了到段边界有几 ms 的碎片
            if (numerator, denominator, one) != (0, 1, 0):
                result.append((bpm, numerator, denominator, one))
            # 推进到下一段
            seg_start = next_boundary
            seg_idx += 1

    return result
