"""
_gap_configs 严格等价性对拍 (方向 1+2 回归)

对一批 (g, R) 输入, 用独立实现的「暴力 DFS 枚举所有合法分段」作为 ground truth,
对比 _gap_configs 返回的每个 (first,last) key 的代价 (sw, commas) 是否一致。
覆盖 p>=5 的非平凡 gap (5/8, 7/8, 5/32, 11/16 等) 与多种 R。

PASS 判据: 两个方法对同一 (g,R) 产出的 key 集合相同, 且每个 key 的 (sw, sum(k)) 相同。

用法:
    python test/equiv_gap_configs.py
"""
import sys
from fractions import Fraction
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# bench/对拍只需 DP 函数, stub 掉 shared_context 的重依赖 (cv2 等)
import types as _types
_SHARED_CTX_MOD = "src.core.auto_rechart.analyze.shared_context"
sys.modules[_SHARED_CTX_MOD] = _types.ModuleType(_SHARED_CTX_MOD)

from src.core.auto_rechart.analyze.maidata_write import (
    _gap_configs, _MAX_COMMAS, _MAX_DIV,
)


def ground_truth_atoms(tau: int, R: int):
    """独立生成候选段 (不依赖 _raw_atoms_for_R), 作为 ground truth。"""
    atoms = []
    for k in range(1, _MAX_COMMAS + 1):
        for N in range(1, _MAX_DIV + 1):
            if (k * R) % N == 0:
                tk = (k * R) // N
                if 0 < tk < tau:
                    atoms.append((N, k, tk))
    return atoms


def brute_force_configs(g: Fraction, R: int):
    """
    ground truth: 复刻 _gap_configs 的两段语义, 用独立实现。
      1. 单段快通道: 若存在 k 使 N=kR/tau 整数且 N<=_MAX_DIV, 只返回这些单段 configs
         (与 _gap_configs 的 early-return 完全对齐)
      2. 否则: 暴力 DFS 枚举所有「禁连续同 N、段 tick 之和 == tau」的多段分段,
         对每个 (first, last) 记录 (sw, commas) 的字典序最小值。
    返回: {(first,last): (sw, commas)}
    """
    tau = (g.numerator * R) // g.denominator
    if tau <= 0:
        return {}
    if tau > 16:
        raise ValueError(f"brute_force DFS only supports tau<=16, got tau={tau} (g={g},R={R})")

    # 1. 单段快通道 (独立实现, 不调 _single_segments, 保持 ground-truth 独立性)
    single = {}
    for k in range(1, _MAX_COMMAS + 1):
        kR = k * R
        if kR % tau == 0:
            N = kR // tau
            if N <= _MAX_DIV:
                single[(N, N)] = (0, k)
    if single:
        return single

    # 2. 多段 DFS
    atoms = ground_truth_atoms(tau, R)
    best = {}  # (first, last) -> (sw, commas)

    def dfs(t, last, first, sw, commas):
        if t == tau:
            key = (first, last)
            cur = best.get(key)
            if cur is None or (sw, commas) < cur:
                best[key] = (sw, commas)
            return
        for (N, k, tk) in atoms:
            nt = t + tk
            if nt > tau:
                continue
            if last is not None and last == N:
                continue
            nsw = sw + (0 if last is None or last == N else 1)
            nfirst = N if first is None else first
            dfs(nt, N, nfirst, nsw, commas + k)

    dfs(0, None, None, 0, 0)
    return best


def dp_configs_cost(g: Fraction, R: int):
    """调用 _gap_configs, 把 (sw, segs) 折算成 (sw, sum(k))。"""
    cfg = _gap_configs(g, R)
    return {key: (sw, sum(k for _, k in segs)) for key, (sw, segs) in cfg.items()}


def main():
    # 测试用例: (g, R) 覆盖 p>=5 与多分母混合结构。
    # 关键: 暴力 DFS 复杂度随 tau 指数增长, 故全部控制在 tau<=16。
    # _gap_configs 的逻辑结构 (禁连续同 N / first 不变 / 字典序剪枝 / 快通道) 与 tau 大小无关,
    # 小 tau 已足够覆盖所有结构性分支; 大 tau 只会重复同一逻辑、徒增 DFS 指数爆炸。
    cases = []
    # 单个非标准 gap (p>=5), R=den 使 tau=num, 全部 tau<=13
    for num, den in [(5, 8), (7, 8), (5, 16), (7, 16), (9, 16), (11, 16), (13, 16),
                     (5, 12), (7, 12), (11, 12), (5, 24), (7, 24),
                     (5, 32), (7, 32), (11, 32), (13, 32)]:
        cases.append((Fraction(num, den), den))
    # 混合分母场景 (R=lcm), 仅选 tau<=16 的
    cases += [
        (Fraction(1, 7), 56), (Fraction(2, 7), 56),    # tau=8,16
        (Fraction(1, 9), 72), (Fraction(2, 9), 72),    # tau=8,16
        (Fraction(1, 8), 24), (Fraction(3, 8), 24),    # tau=3,9  (含单段快通道对照)
        (Fraction(1, 16), 48),                         # tau=3    (单段快通道对照)
    ]
    # 安全护栏: 跳过任何意外的大 tau, 避免 DFS 指数爆炸
    TAU_MAX = 16
    filtered = []
    for (g, R) in cases:
        if (g.numerator * R) % g.denominator != 0:
            continue
        tau = (g.numerator * R) // g.denominator
        if tau > TAU_MAX:
            print(f"[skip] g={g} R={R} tau={tau} > {TAU_MAX} (DFS too slow)")
            continue
        filtered.append((g, R))
    cases = filtered

    total = 0
    mismatches = 0
    for (g, R) in cases:
        total += 1
        bf = brute_force_configs(g, R)
        dp = dp_configs_cost(g, R)
        # key 集合应相同
        if set(bf) != set(dp):
            print(f"MISMATCH (key set) g={g} R={R}")
            print(f"  only in brute: {set(bf)-set(dp)}")
            print(f"  only in dp   : {set(dp)-set(bf)}")
            mismatches += 1
            continue
        # 每个 key 的 cost 应相同
        for key in bf:
            if bf[key] != dp[key]:
                print(f"MISMATCH (cost) g={g} R={R} key={key}: brute={bf[key]} dp={dp[key]}")
                mismatches += 1

    print(f"\n{'='*50}")
    print(f"cases: {total}   mismatches: {mismatches}")
    if mismatches == 0:
        # 统计多少 case 走了内层 DP (非快通道)
        inner = sum(1 for (g, R) in cases if _gap_configs(g, R))
        print(f"cases exercising inner DP (configs non-empty): {inner}")
        print("ALL PASS ✓  (_gap_configs 与暴力 DFS 逐 key 逐 cost 等价)")
    else:
        print("FAIL ✗")
        sys.exit(1)


if __name__ == "__main__":
    main()
