import numpy as np
import math
from dataclasses import dataclass
from fractions import Fraction

from .shared_context import *
from ..detect.note_definition import *
from .maidata_parse import parse_note_info, calculate_one_bar_ms



@dataclass
class MaidataItem:
    """
    restructurer 的最小工作单元，对应 SimaiGenerator.cs 的 SimaiNote。

    time:        音符总小节位置，分数
    content:     音符语法文本
    is_bpm:      是否为 BPM 变化点
    each_group:  each 分组索引，因不支持伪 each, 所以始终为 0

    relative_time: 音符在小节内的相对位置 (0~1), 由 time 派生, 分数
    """
    time: Fraction
    content: str
    is_bpm: bool = False
    each_group: int = 0

    @property
    def relative_time(self) -> Fraction:
        return self.time - self.time.numerator // self.time.denominator





class PassedBarTracker:
    """
    追踪理论播放时间

    仅追踪最新 BPM 段的数据，过往的 BPM 段直接视为已通过

    内部保存两个状态:
      - current_bpm_segment_index:      当前所处的 BPM 段索引
      - current_bpm_segment_passed_bar: 当前段内已通过的 bar 分子 (基于384分母)
    """

    def __init__(self, timing_points: list):
        # 常量
        self.lcm_denom = 384
        self._timing_points = self.convert_timing_points(timing_points, self.lcm_denom)
        # 变量
        self.current_bpm_segment_index = 0
        self.current_bpm_segment_passed_bar = 0  # 仅分子，基于 384
        self.cur_note_track_id = -1  # 用于报错输出


    @staticmethod
    def convert_timing_points(timing_points: list, lcm_denom: int) -> dict[int, tuple[int, float]]:
        """
        将 timing_points 转换为字典形式，方便按段索引访问
        key   = 段序号 (0, 1, 2, ...)
        value = tuple[ bar_index(基于384的分子), bpm ]
        """
        converted = {}
        for i, (beat_index, bpm, start_ms) in enumerate(timing_points):
            bar_index = round(beat_index * 0.25 * lcm_denom)  # 将 beat 转为 bar
            converted[i] = (bar_index, bpm)
        return converted
    

    def update_track_id(self, new_track_id: int) -> None:
        self.cur_note_track_id = new_track_id


    def add(self, current_bpm_segment_index: int,
                  numerator: int, denominator: int, one: int) -> None:
        # 如果输入的段索引更大，说明已经跨段了，直接更新索引并清空 passed_bar
        if current_bpm_segment_index > self.current_bpm_segment_index:
            self.current_bpm_segment_index = current_bpm_segment_index
            self.current_bpm_segment_passed_bar = 0
        # 如果输入的段索引更小，说明尝试添加到之前的 BPM 段，直接报错
        elif current_bpm_segment_index < self.current_bpm_segment_index:
            raise ValueError(f"Cannot add note {self.cur_note_track_id} to a previous BPM segment: index {current_bpm_segment_index} < {self.current_bpm_segment_index}")

        # 将分数统一转为 lcm_denom 为分母的形式
        # 假设分母不为 0, 并且是 lcm_denom 的因数
        total_numerator = one * denominator + numerator
        scaled_numerator = total_numerator * (self.lcm_denom // denominator)
        self.current_bpm_segment_passed_bar += scaled_numerator


    def get_total_elapsed_ms(self) -> float:
        """理论总播放时间（毫秒）"""
        
        total_ms = 0.0
        idx = self.current_bpm_segment_index

        # 过往段: 使用该段的总时间
        for i in range(idx):
            start_bar, cur_bpm = self._timing_points[i]
            next_bar, _ = self._timing_points[i + 1]
            cur_total_bar = (next_bar - start_bar) / self.lcm_denom
            total_ms += cur_total_bar * calculate_one_bar_ms(cur_bpm)

        # 当前段: passed_bar * one_bar_ms
        start_bar, cur_bpm = self._timing_points[idx]
        actual_passed_bar = self.current_bpm_segment_passed_bar / self.lcm_denom
        # 检查: passed_bar 是否超过当前段理论总 bar，如果超过则截断
        if idx + 1 in self._timing_points:
            next_bar, _ = self._timing_points[idx + 1]
            theory_total_bar = (next_bar - start_bar) / self.lcm_denom
            if actual_passed_bar > theory_total_bar:
                print(f"get_total_elapsed_ms: Warning: note {self.cur_note_track_id}: actual_passed_bar {actual_passed_bar:.3f} exceeds theory_total_bar {theory_total_bar:.3f} for BPM segment {idx} {cur_bpm}, truncating to theory total.")
                actual_passed_bar = theory_total_bar  # 截断

        total_ms += actual_passed_bar * calculate_one_bar_ms(cur_bpm)

        return total_ms


    def get_total_elapsed_bar(self) -> Fraction:
        """理论总播放时间 (小节位置)"""

        total_bars = 0
        idx = self.current_bpm_segment_index

        # 过往段：使用该段的总 bar
        for i in range(idx):
            start_bar, _ = self._timing_points[i]
            next_bar, _ = self._timing_points[i + 1]
            total_bars += next_bar - start_bar

        # 当前段：使用 passed_bar
        actual_passed_bar = self.current_bpm_segment_passed_bar
        # 检查: passed_bar 是否超过当前段理论总 bar，如果超过则截断
        if idx + 1 in self._timing_points:
            start_bar, _ = self._timing_points[idx]
            next_bar, _ = self._timing_points[idx + 1]
            theory_total_bar = next_bar - start_bar
            if actual_passed_bar > theory_total_bar:
                print(f"get_total_elapsed_bar: Warning: note {self.cur_note_track_id}: actual_passed_bar {actual_passed_bar} exceeds theory_total_bar {theory_total_bar} for BPM segment {idx}, truncating to theory total.")
                actual_passed_bar = theory_total_bar  # 截断
        total_bars += actual_passed_bar

        return Fraction(total_bars, self.lcm_denom)







def _generate_bpm_items(passed_bar_tracker: PassedBarTracker, timing_points: list) -> list[MaidataItem]:
    """
    为每个 BPM 段生成一个 BPM 变化点 item
    位置 = 该段起点相对首段起点的小节位置
    """
    init_bar_index = passed_bar_tracker._timing_points[0][0]  # 首段起点 bar_index
    bpm_items = []
    for i in range(len(timing_points)):
        start_bar_index, bpm = passed_bar_tracker._timing_points[i]
        relative_bar_index = start_bar_index - init_bar_index
        time = Fraction(relative_bar_index, passed_bar_tracker.lcm_denom)
        item = MaidataItem(time, f"({bpm:g})", is_bpm=True)
        bpm_items.append(item)
    return bpm_items









def generate_maidata(notes_info, timing_points,
                     base_denominator, duration_denominator,
                    ) -> list[MaidataItem]:
    
    # timing_points = [(beat_index, bpm, start_ms), ...]

    items: list[MaidataItem] = []

    # 追踪理论时间
    init_time = None
    passed_bar_tracker = PassedBarTracker(timing_points)
    last_theory_time = None
    last_bpm_seg_index = None

    is_single_bpm = len(timing_points) <= 1
    
    # 仅用于统计音符约分偏差
    time_deviations = []
    # 仅用于统计吸附到 bpm 段的差值
    snap_deltas = []



    for key, value in notes_info:

        # 解析音符信息
        result = parse_note_info(key, value, timing_points,
                                 base_denominator, duration_denominator)
        if result is None: continue
        raw_cur_note_time, cur_note_time, cur_position, cur_bpm_seg_index, cur_note_track_id = result
        
        # 统计吸附到 bpm 段的差值
        if cur_note_time != raw_cur_note_time:
            snap_deltas.append(raw_cur_note_time - cur_note_time)

        # 处理第一个音符
        if last_theory_time is None:
            if is_single_bpm:
                # 单 BPM 谱面: init_time = 首音符时间，不计入 tracker
                init_time = cur_note_time
                last_theory_time = cur_note_time
                last_bpm_seg_index = cur_bpm_seg_index
            else:
                # 多 BPM: init_time = 首 BPM 段起点时间，首音符计入 tracker
                init_time = timing_points[0][2]
                passed_bar_tracker.update_track_id(cur_note_track_id)
                bar_diff = calculate_bar_diff(0.0, cur_note_time,
                                              -1, cur_bpm_seg_index,
                                              timing_points, base_denominator)
                passed_bar_tracker.add(*bar_diff)
                cur_theory_time = init_time + passed_bar_tracker.get_total_elapsed_ms()
                last_theory_time = cur_theory_time
                last_bpm_seg_index = cur_bpm_seg_index
            # 音符 item
            time = passed_bar_tracker.get_total_elapsed_bar()
            items.append(MaidataItem(time, cur_position))
            # 控制台打印
            print(f"first note appear at {cur_note_time:.1f} ms")
            continue

        # 计算当前音符的时间差
        bar_diff = calculate_bar_diff(last_theory_time, cur_note_time,
                                      last_bpm_seg_index, cur_bpm_seg_index,
                                      timing_points, base_denominator)
        # 更新 tracker
        passed_bar_tracker.update_track_id(cur_note_track_id)
        passed_bar_tracker.add(*bar_diff)

        # 得到当前音符的理论时间
        # 采用 init_time + 总 passed_bar
        # 这是精确的谱面播放到此处的时间点，避免了累加误差
        cur_theory_time = init_time + passed_bar_tracker.get_total_elapsed_ms()

        # 音符 item
        time = passed_bar_tracker.get_total_elapsed_bar()
        items.append(MaidataItem(time, cur_position))

        # 统计音符约分误差
        # note_time   是音符原始到达时间
        # theory_time 是分数化处理后的理论时间
        time_deviation = raw_cur_note_time - cur_theory_time
        time_deviations.append(time_deviation)

        # update status
        last_theory_time = cur_theory_time
        last_bpm_seg_index = cur_bpm_seg_index





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

    # 创建 BPM 变化点 item
    bpm_items = _generate_bpm_items(passed_bar_tracker, timing_points)
    # 与音符 item 合并
    all_items = items + bpm_items
    # 三重排序:
    #   1. numerator 升序 (时间顺序)
    #   2. is_bpm 项排在音符项之前 (同位置 BPM 先于音符)
    #   3. content 升序 (按字母顺序对并行音符排序)
    all_items.sort(key=lambda item: (item.time, 0 if item.is_bpm else 1, item.content))

    return all_items








def get_best_numerator_denominator(diff_bar, input_denominator,
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
        total_numerator = round(diff_bar * denom)
        # 零间隔
        if total_numerator == 0:
            error = abs(diff_bar)
            if error < best_error:
                best_error = error
                best_total_numerator = 0
                best_denominator = 1
            continue
        # 计算误差
        fraction_value = total_numerator / denom
        error = abs(diff_bar - fraction_value)
        if error < best_error:
            best_error = error
            best_total_numerator = total_numerator
            best_denominator = denom

    return best_total_numerator, best_denominator




def get_fraction(diff_bar, input_denominator,
                 enable_12=True, enable_24=True, enable_48_1=True):
        
        # 将数字转为带分数形式
        # 返回格式：分子，分母，整数
        
        # 0.5   =  1/2 + 0  =  1, 2, 0
        # 1.0   =  0/1 + 1  =  0, 1, 1
        # 2.25  =  1/4 + 2  =  1, 4, 2
        
        raw_numerator, raw_denominator = get_best_numerator_denominator(
            diff_bar, input_denominator, enable_12, enable_24, enable_48_1)
        
        # 有限度的支持 48 分音符: 仅限 1/48
        # 如果不是 N+1/48，禁用 48 并重新计算
        if enable_48_1 and raw_denominator == 48 and raw_numerator % 48 != 1:
            raw_numerator, raw_denominator = get_best_numerator_denominator(
                diff_bar, input_denominator, enable_12, enable_24, enable_48_1=False)
        
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




def calculate_bar_diff(last_note_time: float,
                       cur_note_time: float,
                       last_bpm_seg_index: int,
                       cur_bpm_seg_index: int,
                       timing_points: list,
                       base_denominator: int,
                      ) -> tuple[int, int, int, int]:
    """
    如果当前音符和旧音符位于相同 bpm 段，起点用 last_note_time
    如果当前音符和旧音符位于不同 bpm 段，起点用该段的起点时间

    计算当前音符时间与起点的时间差，转为分数

    return: tuple[cur_bpm_segment_index, numerator, denominator, one]
    """

    # 根据 bpm 段决定起点时间
    if cur_bpm_seg_index == last_bpm_seg_index:
        # 同一段，起点时间为上一个音符的理论时间
        start_time = last_note_time
    else:
        # 不同段，起点时间为该段的起点时间
        start_time = timing_points[cur_bpm_seg_index][2]  # start_ms

    # 计算时间差 bar
    time_diff_ms = cur_note_time - start_time
    cur_bpm = timing_points[cur_bpm_seg_index][1]  # bpm
    one_bar_ms = calculate_one_bar_ms(cur_bpm)
    diff_bar = time_diff_ms / one_bar_ms

    # 约分
    numerator, denominator, one = get_fraction(diff_bar, base_denominator)

    return cur_bpm_seg_index, numerator, denominator, one
