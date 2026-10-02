"""时值 → 分数 的转换工具。
"""

from __future__ import annotations

import math



def get_best_numerator_denominator(diff_bar, input_denominator, auto_12, auto_24, auto_48):
    """
    在输入分母与 12/24/48 中选择误差最小的分母

    auto_12 / auto_24 / auto_48:
        True  = 智能启用
        False = 始终禁用
    """

    # 如果输入的分母足够大，将 12/24/48 添加为候选分母
    candidates = [input_denominator]
    if input_denominator >= 12 and auto_12:
        candidates.append(12)
    if input_denominator >= 24 and auto_24:
        candidates.append(24)
    if input_denominator >= 48 and auto_48:
        candidates.append(48)

    # 选择误差最小的分母
    best_error = float("inf")
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


def get_fraction(diff_bar, input_denominator, auto_12=True, auto_24=True, auto_48=True):
    """
    将数字转为带分数形式
    返回格式：分子，分母，整数

    auto_12 / auto_24 / auto_48:
        True  = 智能启用
        False = 始终禁用

    48 分另有限制: 只有 N + 1/48 会被接受
    """

    # 0.5   =  1/2 + 0  =  1, 2, 0
    # 1.0   =  0/1 + 1  =  0, 1, 1
    # 2.25  =  1/4 + 2  =  1, 4, 2

    raw_numerator, raw_denominator = get_best_numerator_denominator(
        diff_bar, input_denominator, auto_12, auto_24, auto_48
    )

    # 有限度的支持 48 分音符: 仅限 1/48
    # 如果不是 N+1/48，禁用 48 并重新计算
    if auto_48 and raw_denominator == 48 and raw_numerator % 48 != 1:
        raw_numerator, raw_denominator = get_best_numerator_denominator(
            diff_bar, input_denominator, auto_12, auto_24, auto_48=False
        )

    if raw_numerator == 0:
        return 0, 1, 0  # 零间隔直接返回
    # 获取整数和余数部分
    one = raw_numerator // raw_denominator
    remainder = raw_numerator % raw_denominator
    # 是整数，直接返回，不需要约分余数
    if remainder == 0:
        return 0, 1, one
    # 是小数，约分余数部分
    gcd_num = math.gcd(remainder, raw_denominator)
    numerator = remainder // gcd_num
    denominator = raw_denominator // gcd_num

    return numerator, denominator, one
