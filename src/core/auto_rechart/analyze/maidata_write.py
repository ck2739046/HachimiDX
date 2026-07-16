# 排版引擎 (每小节独立 + 双层 DP, 2026-07-16 重构)
# 早期版本移植自 MuConvert 的 SimaiGenerator.cs, 已完全重写:
#   https://github.com/MuNET-OSS/MuConvert/blob/742355f50d7e53b5255cb951a1a16da8a4215b05/generator/mai/SimaiGenerator.cs

import os
from fractions import Fraction
from functools import reduce
import math

from .shared_context import *
from .maidata_generate import MaidataItem


# 分音策略常量
_MAX_DIV = 384   # 单段分音上限 (覆盖到 1/384, 保证 1/96 gap 的 4 倍对齐选项可用)


def _whole(f: Fraction) -> int:
    """小节数 (floor, 仅用于非负数)。"""
    return f.numerator // f.denominator


def _lcm_of_list(nums) -> int:
    return reduce(math.lcm, nums, 1)


def _single_segments(tau: int, R: int):
    """覆盖 tau ticks 的单段写法 (N, k): k 个逗号 @ 分音 N, k∈[1,4], N=k*R/tau 为整数, N≤_MAX_DIV。"""
    res = []
    for k in range(1, 5):
        if (k * R) % tau == 0:
            N = (k * R) // tau
            if N <= _MAX_DIV:
                res.append((N, k))
    return res


def _gap_configs(g: Fraction, R: int):
    """gap g 在分辨率 R 下的所有 Pareto-最优分段配置。

    返回 dict[(first_div, last_div)] = (switches, segments):
      segments = [(N, k), ...] 每 k∈[1,4], 连续 N 不同, sum(k/N) == g;
      switches = 段内 {N} 切换数 (首段不计, 由行首承担)。
    最简分子 p≤4: 直接给单段对齐分音 (0 内切换, 已最优); p≥5: 走 tick DP 求最小切换拆分。
    """
    tau = (g.numerator * R) // g.denominator
    if tau <= 0:
        return {}
    configs = {}
    for (N, k) in _single_segments(tau, R):
        configs[(N, N)] = (0, [(N, k)])
    if configs:                         # p≤4: 单段 0 内切换已最优, 跳过 DP
        return configs
    # p≥5: 多段 DP (atoms = 所有覆盖 <tau ticks 的单段)
    atoms = []
    for k in range(1, 5):
        for N in range(1, _MAX_DIV + 1):
            if (k * R) % N == 0:
                tk = (k * R) // N
                if 0 < tk < tau:
                    atoms.append((N, k, tk))
    dp = [dict() for _ in range(tau + 1)]
    dp[0][(None, None)] = (0, [])
    for t in range(tau):
        for (first, last), (sw, segs) in list(dp[t].items()):
            for (N, k, tk) in atoms:
                nt = t + tk
                if nt > tau:
                    continue
                if last is not None and last == N:
                    continue        # 禁止连续同 div: 否则合并成 >4 逗号串 (原则4)
                nsw = sw + (0 if last is None or last == N else 1)
                nfirst = N if first is None else first
                key = (nfirst, N)
                newsegs = segs + [(N, k)]
                cur = dp[nt].get(key)
                if cur is None or nsw < cur[0] or (nsw == cur[0] and len(newsegs) < len(cur[1])):
                    dp[nt][key] = (nsw, newsegs)
    for key, val in dp[tau].items():
        if key == (None, None):
            continue
        if key not in configs or val[0] < configs[key][0]:
            configs[key] = val
    return configs


class _LayoutEngine:
    """每小节独立排版引擎。

    六原则:
      1. 每小节完全独立, 不跨小节传递残余/cur_div;
      2. 放弃 _TH_DIRECT/_DIRECT_MINVAL 阈值;
      3. 每小节内部最小化 {N} 切换 (双层 DP);
      4. 连续逗号 ≤4, 超过必拆;
      5. 每小节行首强制写 {N};
      6. trailing gap 填满到小节线, 保证下小节从干净边界开始。
    """

    def layout(self, items: list[MaidataItem]) -> str:
        if not items:
            return "{1},,,E"
        bars = {}
        for it in items:
            t = Fraction(it.numerator, it.denominator)
            bars.setdefault(_whole(t), []).append((t, it))
        max_bar = max(bars)
        lines = []
        for b in range(0, max_bar + 1):
            its = bars.get(b)
            if not its:
                lines.append("{1},\n")
                continue
            its_sorted = sorted(its, key=lambda x: (x[0] - b, 0 if x[1].is_bpm else 1, x[1].content))
            events = []
            i = 0
            while i < len(its_sorted):
                t, _ = its_sorted[i]
                rel = t - b
                bpm_parts, note_parts = [], []
                while i < len(its_sorted) and (its_sorted[i][0] - b) == rel:
                    it2 = its_sorted[i][1]
                    (bpm_parts if it2.is_bpm else note_parts).append(it2.content)
                    i += 1
                content = "".join(bpm_parts) + "/".join(note_parts)
                events.append((rel, content))
            lines.append(self._layout_bar(events))
        return "".join(lines) + "{1},,,E"

    def _layout_bar(self, events) -> str:
        m = len(events)
        times = [Fraction(t) for t, _ in events]
        gaps = []
        prev = Fraction(0)
        for t in times:
            gaps.append(t - prev)
            prev = t
        gaps.append(Fraction(1) - prev)            # trailing 填满到小节线
        dens = [g.denominator for g in gaps if g > 0]
        R = _lcm_of_list(dens) if dens else 1
        cfgs = [_gap_configs(g, R) if g > 0 else None for g in gaps]
        active = [(idx, cfgs[idx]) for idx in range(len(gaps)) if cfgs[idx] is not None]
        # 外层 DP: 跨 gap 最小切换; 切换数相同时取总逗号数更少 (主键 switches, 次键 commas)
        first_idx, first_cfg = active[0]
        cur_layer = {}
        for (fd, ld), (sw, segs) in first_cfg.items():
            commas = sum(k for (_, k) in segs)
            cost = (sw, commas)
            if ld not in cur_layer or cost < cur_layer[ld][0]:
                cur_layer[ld] = (cost, [(first_idx, segs)])
        for a_idx in range(1, len(active)):
            gi, cfg = active[a_idx]
            next_layer = {}
            for (fd, ld), (sw, segs) in cfg.items():
                seg_commas = sum(k for (_, k) in segs)
                best = None
                for prev_ld, (prev_cost, prev_choices) in cur_layer.items():
                    tot = (prev_cost[0] + (0 if prev_ld == fd else 1) + sw,
                           prev_cost[1] + seg_commas)
                    if best is None or tot < best[0]:
                        best = (tot, prev_choices + [(gi, segs)])
                if ld not in next_layer or best[0] < next_layer[ld][0]:
                    next_layer[ld] = best
            cur_layer = next_layer
        chosen = min(cur_layer.values(), key=lambda v: v[0])[1]   # [(gap_idx, segments)]
        seg_map = {gi: segs for (gi, segs) in chosen}
        # 输出单行。布局规则: div 声明 {N} 永远紧跟在逗号之后或行首, 绝不直接跟在音符后,
        # 从而保证每个音符后至少有 1 个逗号 (避免 note{N} 形式)。
        # 实现: note[i] 的 trailing gap[i+1] 的首段 div 在 note[i] 之前声明 (落在前一 gap 的逗号后),
        #       其余段间 div 自然落在逗号后; 行首 {N} 由首个 emit_div 产生。
        out = []
        cur = None

        def emit_div(D):
            nonlocal cur
            if D != cur:
                out.append(f"{{{D}}}")
                cur = D

        # 行首 + leading gap[0] (首音符前的休止; 若存在则其首段 div 成为行首 {N})
        if gaps[0] > 0:
            for (N, k) in seg_map[0]:
                emit_div(N)
                out.append("," * k)
        # 各音符: 先声明 trailing gap 首段 div, 再出音符, 再出 trailing 逗号
        for i in range(m):
            tg = i + 1                              # trailing gap index
            has_trailing = tg < len(gaps) and gaps[tg] > 0
            if has_trailing:
                emit_div(seg_map[tg][0][0])         # 声明 div 在音符前 (避免 note{N})
            out.append(events[i][1])
            if has_trailing:
                for (N, k) in seg_map[tg]:
                    emit_div(N)
                    out.append("," * k)
        return "".join(out) + "\n"


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
