# 参考了 MuConvert 的 SimaiGenerator.cs:
#   https://github.com/MuNET-OSS/MuConvert/blob/742355f50d7e53b5255cb951a1a16da8a4215b05/generator/mai/SimaiGenerator.cs
# 仅参考部分策略或思路，具体代码实现完全独立


import os
from fractions import Fraction
from functools import reduce
import math

from .shared_context import *
from .maidata_generate import MaidataItem


# 分音策略常量
_MAX_DIV = 384       # 分音的最大值
_SWITCH_WEIGHT = 4   # 1 次 {N} 切换相当于多少个逗号的代价 (用于在"少切换"与"少逗号"之间权衡)


def _whole(f: Fraction) -> int:
    """计算一个时间值落在第几小节 (向下取整)"""
    return f.numerator // f.denominator


def _lcm_of_list(nums) -> int:
    """求一组整数的最小公倍数"""
    return reduce(math.lcm, nums, 1)


def _single_segments(tau: int, R: int):
    """
    找一个间隔的所有"单段写法" (N, k)

    一个间隔在分辨率 R 下占 tau 个 tick。如果它恰好能用一个分音 {N} 的 k 个逗号表示
    (即 k 个 1/N 相加 = tau/R, 且 1 ≤ k ≤ 4), 就是一种合法的单段写法。
    返回所有这样的 (N, k)。
    """
    res = []
    for k in range(1, 5):
        if (k * R) % tau == 0:
            N = (k * R) // tau
            if N <= _MAX_DIV:
                res.append((N, k))
    return res


def _gap_configs(g: Fraction, R: int):
    """为一个间隔 g 求出所有"性价比最优"的写法。

    返回 dict[(首段分音, 末段分音)] = (段内切换次数, 分段列表):
      分段列表 = [(N, k), ...] 每个 k∈[1,4], 相邻两段分音不同, 全部相加正好等于 g;
      段内切换次数 = 这个间隔内部需要切 {N} 的次数 (第一段不计, 由行首或前一间隔承担)。

    策略:
      - 若 g 能用单段写完 (即它的最简分数分子 ≤ 4), 单段就一定最优 (0 内切换),
        直接返回所有单段候选, 跳过 DP;
      - 否则用 tick DP 找出"切换最少、其次逗号最少"的多段拆法。
    """
    tau = (g.numerator * R) // g.denominator
    if tau <= 0:
        return {}
    configs = {}
    for (N, k) in _single_segments(tau, R):
        configs[(N, N)] = (0, [(N, k)])
    if configs:                         # 能用单段写完: 单段 0 内切换已是理论最优, 不必再拆
        return configs
    # 不能用单段写完: 用 tick DP 求最优多段拆法
    # 先列出所有"占 tick 数少于 tau"的候选段, 作为 DP 的基本构件
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
                    continue        # 不允许相邻两段用同一分音: 否则逗号会连成一串, 超过 4 个
                nsw = sw + (0 if last is None or last == N else 1)
                nfirst = N if first is None else first
                key = (nfirst, N)
                newsegs = segs + [(N, k)]
                cur = dp[nt].get(key)
                new_commas = sum(k for _, _ in newsegs)
                if cur is None or nsw < cur[0] or (nsw == cur[0] and new_commas < sum(kk for _, kk in cur[1])):
                    dp[nt][key] = (nsw, newsegs)
    # 从 DP 终态收口: 对每个 (首段, 末段) 组合, 按"加权和"挑最优 (切换数优先, 逗号数次之)
    for key, val in dp[tau].items():
        if key == (None, None):
            continue
        val_commas = sum(kk for _, kk in val[1])
        if key not in configs:
            configs[key] = val
        else:
            cur_c = configs[key]
            cur_cost = cur_c[0] * _SWITCH_WEIGHT + sum(kk for _, kk in cur_c[1])
            new_cost = val[0] * _SWITCH_WEIGHT + val_commas
            if new_cost < cur_cost:
                configs[key] = val
    return configs


class _LayoutEngine:
    """simai 谱面排版引擎: 把一组音符 (带绝对小节位置) 转成谱面文本。

    设计要点:
      - 每个小节独立排版, 小节之间互不影响;
      - 每个小节内部尽量减少 {N} 切换次数 (用双层 DP 求最优);
      - 连续的逗号不超过 4 个, 超过就拆成多段;
      - 每个小节占一行, 行首固定写一次 {N};
      - 每个小节末尾用逗号填满到小节线, 保证下一小节从干净的位置开始。
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
                lines.append("{1},\n")          # 空小节: 一个逗号 = 整小节休止
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
                # 同一时刻的项合并成一个"事件": BPM 文本和音符文本分开存
                # (同时刻的多个音符用 / 连成 each; BPM 后续输出时单独处理)
                events.append((rel, "".join(bpm_parts), "/".join(note_parts)))
            lines.append(self._layout_bar(events))
        return "".join(lines) + "{1},,,E"

    def _layout_bar(self, events) -> str:
        """排版单个小节。每个事件是 (小节内位置, BPM文本, 音符文本)。返回一整行文本。"""
        m = len(events)
        times = [Fraction(t) for t, _, _ in events]
        gaps = []
        prev = Fraction(0)
        for t in times:
            gaps.append(t - prev)
            prev = t
        gaps.append(Fraction(1) - prev)            # 末尾间隔: 把小节填满到小节线
        # 取所有间隔分母的最小公倍数作为本小节的分辨率 R, 这样每个间隔都是整数个 tick
        dens = [g.denominator for g in gaps if g > 0]
        R = _lcm_of_list(dens) if dens else 1
        cfgs = [_gap_configs(g, R) if g > 0 else None for g in gaps]
        active = [(idx, cfgs[idx]) for idx in range(len(gaps)) if cfgs[idx] is not None]
        # 外层 DP: 跨所有间隔, 让"相邻间隔的衔接处"尽量用同一分音 (省一次切换)。
        # 总代价 = 切换次数*_SWITCH_WEIGHT + 逗号总数; 用加权和是为了让逗号数也能反过来
        # 抵消"为省一次切换而堆一大堆逗号"的情况。
        first_idx, first_cfg = active[0]
        cur_layer = {}
        for (fd, ld), (sw, segs) in first_cfg.items():
            commas = sum(k for (_, k) in segs)
            cost = sw * _SWITCH_WEIGHT + commas
            if ld not in cur_layer or cost < cur_layer[ld][0]:
                cur_layer[ld] = (cost, [(first_idx, segs)])
        for a_idx in range(1, len(active)):
            gi, cfg = active[a_idx]
            next_layer = {}
            for (fd, ld), (sw, segs) in cfg.items():
                seg_commas = sum(k for (_, k) in segs)
                best = None
                for prev_ld, (prev_cost, prev_choices) in cur_layer.items():
                    tot = prev_cost + (0 if prev_ld == fd else 1) * _SWITCH_WEIGHT + sw * _SWITCH_WEIGHT + seg_commas
                    if best is None or tot < best[0]:
                        best = (tot, prev_choices + [(gi, segs)])
                if ld not in next_layer or best[0] < next_layer[ld][0]:
                    next_layer[ld] = best
            cur_layer = next_layer
        chosen = min(cur_layer.values(), key=lambda v: v[0])[1]   # [(间隔序号, 分段列表)]
        seg_map = {gi: segs for (gi, segs) in chosen}

        # ---- 拼接这一行的文本 ----
        # 输出顺序的硬性规则: {N} 只能出现在"行首"或"逗号之后", 不能直接贴在音符后面。
        # 这样能保证每个音符后面都至少跟一个逗号 (不会出现 note{N} 这种音符后没逗号的情况)。
        # 做法: 每个音符 i 之后的间隔 i+1, 把它的第一段分音提到"音符 i 之前"来声明
        #       (正好落在前一个间隔的逗号后面)。
        out = []
        cur = None

        def emit_div(D):
            """必要时写一次 {D}; 只有 D 与当前分音不同时才写。"""
            nonlocal cur
            if D != cur:
                out.append(f"{{{D}}}")
                cur = D

        # 行首 + 第一个间隔 (第一个音符前的休止): 若存在, 它的第一段分音成为行首的 {N}
        if gaps[0] > 0:
            for (N, k) in seg_map[0]:
                emit_div(N)
                out.append("," * k)
        # 逐个音符输出: 先写 BPM, 再声明它后一个间隔的分音, 再写音符, 再写间隔的逗号
        for i in range(m):
            tg = i + 1                              # 该音符后面的间隔序号
            has_trailing = tg < len(gaps) and gaps[tg] > 0
            _, bpm, notes = events[i]
            if bpm:
                out.append(bpm)                     # BPM 写在 {N} 前面
                cur = None                          # 换过 BPM 后强制重新声明 {N}, 即使分音没变
            if has_trailing:
                emit_div(seg_map[tg][0][0])         # 先声明分音, 再出音符 (避免 note{N})
            if notes:
                out.append(notes)
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

    接收 generate_maidata 产出的音符列表, 排版成 simai 谱面, 写入 maidata.txt
    """

    # 准备输出文件
    output_dir = shared_context.std_video_path.parent
    txt_path = output_dir / "maidata.txt"
    if os.path.exists(txt_path):
        os.remove(txt_path)

    video_name = output_dir.name
    level_label = ['zero', 'easy', 'basic', 'advanced', 'expert', 'master', 'remaster', 'special']
    print(f"\n{video_name} - {level_label[chart_lv]}")

    # 用排版引擎生成谱面正文
    engine = _LayoutEngine()
    body = engine.layout(items)
    # 正文开头会带一个 BPM 文本 (如 "(120"), 它会单独写到 &inote 头部, 所以从正文里剥掉
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
