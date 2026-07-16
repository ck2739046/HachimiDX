# 排版引擎移植自 MuConvert 的 SimaiGenerator.cs (C# → Python)
# 来源: https://github.com/MuNET-OSS/MuConvert/blob/742355f50d7e53b5255cb951a1a16da8a4215b05/generator/mai/SimaiGenerator.cs

import os
from fractions import Fraction
from functools import reduce
import math

from .shared_context import *
from .maidata_generate import MaidataItem


# 分音策略常量 (移植自 SimaiGenerator.cs)
_TH_DIRECT = 16      # base 分音上限；超过此值的分音不参与 base 计算
_DIRECT_MINVAL = 4   # 当存在 exotic 分音时，base 分音不得低于此值


def _whole(f: Fraction) -> int:
    """对应 C# Rational.WholePart (仅用于非负数)"""
    return f.numerator // f.denominator


def _frac(f: Fraction) -> Fraction:
    """对应 C# Rational.FractionPart"""
    return f - _whole(f)


def _lcm_of_list(nums) -> int:
    return reduce(math.lcm, nums, 1)


class _LayoutEngine:
    """
    SimaiGenerator.cs 排版引擎的 Python 移植。

    以 write_ptr (Fraction, 单位=小节) 与 cur_div (当前分音) 为唯一状态，
    在 list[MaidataItem] 之间填充逗号、跨小节线自动换行、最小化 {N} 切换。
    三层分音智能:
      1. 小节级 CalculateBaseDiv: 为本小节挑一个主力分音
      2. 间隔级 WriteBlank: 优先用 base_div 表示, 把 exotic 分音局部化
      3. 逗号级 WriteComma: 复用 cur_div 省切换
    """

    def __init__(self):
        self.result = ""
        self.write_ptr = Fraction(0)
        self.cur_div = 0   # 与 SimaiGenerator 初值一致; 首次 WriteComma 触发 ChangeDiv 插入 {div}
        self.base_div = 1
        self.base_div_bar = -1
        self.buf = []

    # ---- 移植自 ChangeDiv: 回溯插入 {div} ----
    def _change_div(self, div: int):
        result = self.result
        i = len(result) - 1
        e = -1
        while i >= 0:
            c = result[i]
            if c in (',', ')', '{', '\n'):
                if c == '{':
                    i -= 1
                break
            elif c == '}':
                e = i
            i -= 1
        if e == -1:
            e = i
        self.result = result[:i + 1] + f"{{{div}}}" + result[e + 1:]
        self.cur_div = div

    # ---- 移植自 WriteComma ----
    def _write_comma(self, length, force_as_is=False, auto_new_line=True, break_on_new_line=False):
        # 对应 C# WriteComma: force_as_is 时保留原始 (numer, div) 不约分
        # (Rationals 构造不自动约分, 而 Fraction 必约分; 故 force_as_is 路径改用裸数元组绕过约分,
        #  以匹配 C# WriteBlank 快路径 value=new(numer, baseDiv) 传入非约分形式的语义)
        if force_as_is and isinstance(length, tuple):
            numer, div = length
            if numer == 0:
                return
        else:
            if length == 0:
                return
            length = Fraction(length)   # Fraction 构造即自动最简 (CanonicalForm)
            div = length.denominator
            numer = length.numerator

            if not force_as_is:
                direct_count = length * self.cur_div
                # 若能用现有 cur_div 整除表示, 且逗号数不多 (或 cur_div 本身不大), 则复用 cur_div 省切换
                if self.cur_div > 0 and direct_count.denominator == 1 and (direct_count <= 4 or self.cur_div <= 16):
                    div = self.cur_div
                    numer = direct_count.numerator

        if div != self.cur_div:
            self._change_div(div)
        for _ in range(numer):
            before = self.write_ptr
            self.result += ','
            self.write_ptr += Fraction(1, div)
            # 跨过小节线则换行
            if auto_new_line and _whole(self.write_ptr) != _whole(before):
                self.result += '\n'
                # 强制清空 cur_div, 即便新小节分音与上一小节相同, 也固定在行首写一次 {n}
                self.cur_div = 0
                if break_on_new_line:
                    break

    # ---- 移植自 WriteBlank: 递归填充空白, 优先用 base_div ----
    def _write_blank(self, blank, base_div: int):
        blank = Fraction(blank)
        t = Fraction(base_div, blank.denominator)
        if t >= 1 and t.denominator == 1:
            # 空白能用 base_div 整除表示 -> 按 base_div 粒度写 (传裸数元组保留非约分形式, 与 C# WriteBlank 一致)
            self._write_comma((blank.numerator * _whole(t), base_div), force_as_is=True)
            return

        # 不能整除: 拆成 零头(remain) + 大块(whole_aims), 零头先行容忍一次切换, 大块递归回 base_div
        cur_aim = max(blank.denominator // 4, base_div)
        whole_aims = Fraction(_whole(blank * cur_aim), cur_aim)
        remain = blank - whole_aims
        self._write_comma(remain)
        self._write_blank(whole_aims, base_div)

    # ---- 移植自 LCM: 返回 (全分母 LCM, 仅<=TH_DIRECT 分母 LCM) ----
    def _lcm(self, gaps) -> tuple:
        data = [Fraction(g).denominator for g in gaps if g > 0]
        lcm_1 = _lcm_of_list(data) if data else 1
        data2 = [d for d in data if d <= _TH_DIRECT]
        lcm_2 = _lcm_of_list(data2) if data2 else 1
        if lcm_1 > _TH_DIRECT and lcm_2 < _DIRECT_MINVAL:
            lcm_2 = _DIRECT_MINVAL
        return lcm_1, lcm_2

    # ---- 移植自 CalculateBaseDiv: 为本小节挑最优 base 分音 ----
    def _calculate_base_div(self, note_idx: int):
        bar = _whole(self.buf[note_idx]['time'])
        gaps = [self.buf[note_idx]['time'] - bar]
        i = note_idx + 1
        while i < len(self.buf) and _whole(self.buf[i]['time']) <= bar:
            gaps.append(self.buf[i]['time'] - self.buf[i - 1]['time'])
            i += 1

        lcm_1, lcm_2 = self._lcm(gaps)
        result_div = lcm_2
        should_fill_last_bar_first = True

        # 假设不补满上一小节, 把"上一小节剩余空间"并入首 gap 重算; 若 LCM 更小则更优
        remain_time = bar - self.write_ptr
        if remain_time > 0:
            gaps[0] += remain_time
            lcm_n_1, lcm_n_2 = self._lcm(gaps)
            if lcm_n_1 < lcm_1:
                result_div = lcm_n_2
                should_fill_last_bar_first = False

        return result_div, should_fill_last_bar_first

    # ---- 移植自 Generate 第二阶段主循环 ----
    def layout(self, items: list[MaidataItem]) -> str:
        # 转换为内部视图 (time 为 Fraction, 单位=小节)
        self.buf = [
            {
                'time': Fraction(it.numerator, it.denominator),
                'content': it.content,
                'is_bpm': it.is_bpm,
                'each_group': it.each_group,
            }
            for it in items
        ]

        for i in range(len(self.buf)):
            note = self.buf[i]

            # 处理多押: 与上一音符同时刻且上一音符非 BPM -> 用 `/` (真 each) 或 `` ` `` (伪 each) 连接
            if i > 0 and note['time'] == self.buf[i - 1]['time'] and not self.buf[i - 1]['is_bpm']:
                is_false_each = note['each_group'] > self.buf[i - 1]['each_group']
                self.result += ('`' if is_false_each else '/') + note['content']
                continue

            # 仅在每小节第一个音符时执行
            should_fill_last_bar_first = None
            if _whole(note['time']) > self.base_div_bar:
                self.base_div_bar = _whole(note['time'])
                self.base_div, should_fill_last_bar_first = self._calculate_base_div(i)

            if should_fill_last_bar_first is not None:
                if should_fill_last_bar_first:
                    # 策略 A: 先把上一小节补满
                    to_fill = _frac(self.base_div_bar - self.write_ptr)
                    self._write_comma(to_fill)
                elif _frac(self.write_ptr) != 0:
                    # 策略 B: 让间隔自然跨过小节线, 跨线即停
                    self._write_comma(note['time'] - self.write_ptr, break_on_new_line=True)
                # 补完整的空小节 (只有最后一个加换行)
                whole_bar_to_fill = _whole(note['time'] - self.write_ptr)
                for j in range(whole_bar_to_fill):
                    # 第 3 参数 auto_new_line 对应 C# WriteComma(1, true, j==wholeBarToFill-1):
                    # 仅最后一个空小节在跨小节线时加换行, 其余同行; break_on_new_line 因 numer=1 不生效
                    self._write_comma(Fraction(1), force_as_is=True, auto_new_line=(j == whole_bar_to_fill - 1))

            # 音符前空白 + 音符本体
            blank = note['time'] - self.write_ptr
            self._write_blank(blank, self.base_div)
            self.result += note['content']

        # 结尾: 3 小节延迟 + E (沿用旧版约定)
        self.result += ",\n{1},,,E"
        return self.result








def write_maidata(shared_context, items: list[MaidataItem],
                  chart_lv: int, app_version: str,
                  note_speed, touch_speed):
    """
    主入口

    消费 generate_maidata 产出的 list[MaidataItem], 排版后写入 maidata.txt
    """

    # 准备输出文件
    output_dir = shared_context.std_video_path.parent
    txt_path = output_dir / "maidata.txt"
    if os.path.exists(txt_path):
        os.remove(txt_path)

    video_name = output_dir.name
    level_label = ['zero', 'easy', 'basic', 'advanced', 'expert', 'master', 'remaster', 'special']
    print(f"\n{video_name} - {level_label[chart_lv]}")

    # 排版引擎生成谱面正文
    engine = _LayoutEngine()
    body = engine.layout(items)
    # 从正文剥离出第一个 bpm 文本
    first_bpm = items[0].content if items and items[0].is_bpm else ""
    if first_bpm and body.startswith(first_bpm):
        body = body[len(first_bpm):].lstrip('\n')

    # 写入文件: 元信息头 + 流速注释 + &inote 谱面正文
    note_speed_str = f"{note_speed:.2f}" if note_speed else "N/A"
    touch_speed_str = f"{touch_speed:.2f}" if touch_speed else "N/A"

    with open(txt_path, 'w', encoding='utf-8') as f:
        f.write(f'&title={video_name}\n')
        f.write(f'&artist=default\n')
        f.write(f'&first=0\n')
        f.write(f'&des=Generated by HachimiDX v{app_version}\n\n')

        f.write(f'&des_{chart_lv}=default\n')
        f.write(f'&lv_{chart_lv}=15\n\n')

        f.write(f'&inote_{chart_lv}={first_bpm}\n')
        f.write(f'|| note speed: {note_speed_str}, touch speed: {touch_speed_str}\n')
        f.write(body)

    print(f"generate maidata.txt at {txt_path}\n")
