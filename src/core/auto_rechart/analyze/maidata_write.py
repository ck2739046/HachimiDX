# 参考了 MuConvert 的 SimaiGenerator.cs:
#   https://github.com/MuNET-OSS/MuConvert/blob/742355f50d7e53b5255cb951a1a16da8a4215b05/generator/mai/SimaiGenerator.cs
# 仅参考部分思路，具体代码实现完全独立


import os
from fractions import Fraction
from functools import reduce
from itertools import groupby, tee
import math

from .shared_context import *
from .maidata_generate import MaidataItem


# 分音策略常量
_MAX_DIV = 384     # 分音的分辨率，最小支持 1/384 小节
_MAX_COMMAS = 5    # 单段内最多连续逗号数



def _lcm_of_list(nums) -> int:
    """求一组整数的最小公倍数"""
    return reduce(math.lcm, nums, 1)


def _single_segments(numerator: int, denominator: int) -> list[tuple[int, int]]:
    """
    输入: 分子/分母 是这个单个间隔的长度 (以小节为单位)
    返回: 所有合法的 分子/分母 组合 (分子为1-4)

    例: 输入 2/8, 输出 [1/4, 2/8, 3/12, 4/16]

    若间隔无法用 1~4 分子表示 (例如 5/8), 返回空列表
    """
    res = []
    for new_numerator in range(1, _MAX_COMMAS + 1):
        if (new_numerator * denominator) % numerator == 0:
            new_denominator = (new_numerator * denominator) // numerator
            if new_denominator <= _MAX_DIV:
                res.append((new_numerator, new_denominator))
    return res


def _gap_configs(g: Fraction, R: int):
    """
    为一个间隔 g 求出所有"性价比最优"的写法

    输入:
        g: 分数, 本间隔的长度 (以小节为单位)
        R:i int, 本小节的所有间隔的分母的 lcm

    返回:
      dict[(首段分音, 末段分音)] = (段内切换次数, 分段列表):
        分段列表 = [(N, k), ...] 每个 k∈[1,4]
        段内切换次数 = 这个间隔内部需要切 {N} 的次数 (第一段不计, 由行首或前一间隔承担)

    策略:
      - 若 g 能用单段写完, 直接返回所有单段候选
      - 否则找出"切换最少、其次逗号最少"的多段拆法
    """

    # 将分子转为基于 R 的
    tau = (g.numerator * R) // g.denominator
    # 零间隔，直接返回
    if tau <= 0: return {}

    configs = {}

    # 单段就能写完，零次分音切换
    for (k, N) in _single_segments(tau, R):
        configs[(N, N)] = (0, [(N, k)])
    if configs:
        return configs
    
    # 不能用单段写完: 用 tick DP 求最优多段拆法

    # 1. 枚举后选段
    # 先列出所有"占 tick 数少于 tau"的候选段, 作为 DP 的基本构件
    atoms = []
    for k in range(1, _MAX_COMMAS + 1):
        for N in range(1, _MAX_DIV + 1):
            if (k * R) % N == 0:
                tk = (k * R) // N
                if 0 < tk < tau:
                    atoms.append((N, k, tk))

    # 2. DP 状态定义
    dp = [dict() for _ in range(tau + 1)]
    dp[0][(None, None)] = (0, [])

    # 3. DP 状态转移
    for t in range(tau):
        for (first, last), (sw, segs) in list(dp[t].items()):
            for (N, k, tk) in atoms:
                nt = t + tk
                if nt > tau:
                    continue
                if last is not None and last == N:
                    continue  # 1. 不允许相邻两段用同一分音: 否则逗号会连成一串, 超过 4 个
                nsw = sw + (0 if last is None or last == N else 1)  # 2. 切换计数: 前一段的末段分音与当前段的首段分音不同就 +1
                nfirst = N if first is None else first
                key = (nfirst, N)
                newsegs = segs + [(N, k)]
                cur = dp[nt].get(key)
                new_commas = sum(kk for _, kk in newsegs)
                if cur is None or nsw < cur[0] or (nsw == cur[0] and new_commas < sum(kk for _, kk in cur[1])):
                    dp[nt][key] = (nsw, newsegs)  # 3. 代价比较: 切换数优先, 其次逗号总数

    # 收口: 把 DP 终态 (dp[tau]) 转成 configs 返回。
    for key, val in dp[tau].items():
        if key == (None, None):
            continue
        configs[key] = val

    return configs







class _LayoutEngine:
    """
    simai 谱面排版引擎

    排版规则:
      - 将谱面按小节分割，一行一个小节
      - 每个小节完全独立, 互不影响
      - 每个行首固定写一次 {N}
      - 每次 bpm 切换后强制写一次 {N} (即使分音没变)

    分音策略:
      - 每个小节内部尽量减少 {N} 切换次数
      - 每个小节内部尽量减少逗号总数
      - 连续逗号不能超过 _MAX_COMMAS 个, 如果超过就拆成多段
    """

    def layout(self, items: list[MaidataItem]) -> str:
        """主入口: 接受 MaidataItem, 返回排版后的谱面正文"""

        # 特例: 空谱面
        if not items:
            return "{1},,,E"
        
        # 将所有音符按小节分组, 方便后续逐小节排版
        bars = {}  # key: 小节序号, value: list[MaidataItem]
        for item in items:
            # 音符落在第几小节 (向下取整)
            bar = item.time.numerator // item.time.denominator
            # 本小节的所有音符写入一个列表
            if bar not in bars: bars[bar] = []
            bars[bar].append(item)

        # 主循环: 逐小节排版
        final_texts = []
        for bar_index in range(max(bars) + 1):

            this_bar_notes = bars.get(bar_index)
            if not this_bar_notes:
                final_texts.append("{1},\n")  # 空小节使用 {1}, 填充
                continue

            # 已经在 maidata_generate.py 中排序过了
            # this_bar = sorted(this_bar, key=lambda x: (x[0], 0 if x[1].is_bpm else 1, x[1].content))

            # 生成该小节的 events
            events = []
            # 按 relative_time 将音符分组
            for relative_time, group in groupby(this_bar_notes, key=lambda it: it.relative_time):
                g1, g2 = tee(group, 2)  # group 是一次性迭代器, 需要 tee 复制两份
                bpm_parts  = [it.content for it in g1 if     it.is_bpm]
                note_parts = [it.content for it in g2 if not it.is_bpm]
                # 用 "/" 连接 each 音符
                note_content = "/".join(note_parts)
                # 假设同一时间不可能出现多个 BPM
                bpm_text = bpm_parts[0] if bpm_parts else ""
                # 写入 events
                event = (relative_time, bpm_text, note_content)
                events.append(event)
            
            # 排版生成该小节 maidata 文本
            maidata_text = self._layout_bar(events)
            final_texts.append(maidata_text)
            
        return "".join(final_texts) + "{1},,,E"





    def _layout_bar(self, events) -> str:
        """
        排版单个小节
        输入: list of (小节内时间, BPM文本, 音符文本)
        返回: 一整行 maidata 文本
        """
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
        # 总代价 = 切换次数*_MAX_COMMAS + 逗号总数; 用加权和是为了让逗号数也能反过来
        # 抵消"为省一次切换而堆一大堆逗号"的情况。
        first_idx, first_cfg = active[0]
        cur_layer = {}
        for (fd, ld), (sw, segs) in first_cfg.items():
            commas = sum(k for (_, k) in segs)
            cost = sw * _MAX_COMMAS + commas
            if ld not in cur_layer or cost < cur_layer[ld][0]:
                cur_layer[ld] = (cost, [(first_idx, segs)])
        for a_idx in range(1, len(active)):
            gi, cfg = active[a_idx]
            next_layer = {}
            for (fd, ld), (sw, segs) in cfg.items():
                seg_commas = sum(k for (_, k) in segs)
                best = None
                for prev_ld, (prev_cost, prev_choices) in cur_layer.items():
                    tot = prev_cost + (0 if prev_ld == fd else 1) * _MAX_COMMAS + sw * _MAX_COMMAS + seg_commas
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
