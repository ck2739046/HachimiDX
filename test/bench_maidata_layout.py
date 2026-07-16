"""
bench _LayoutEngine.layout() 的双层 DP 性能

从真实测试文件夹复现 MaidataItem 列表 (note_preprocess_result.txt +
new tekisuto_aligned.txt → generate_maidata)，pickle 缓存后反复计时 layout。

用法:
    python test/bench_maidata_layout.py            # 默认 N=20
    python test/bench_maidata_layout.py --n 50
    python test/bench_maidata_layout.py --rebuild  # 强制重建 items 缓存
"""
import argparse
import io
import pickle
import re
import statistics
import sys
import time
import types
import contextlib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# generate_maidata / _LayoutEngine.layout 不依赖 shared_context 的任何符号，
# 但模块顶部 `from .shared_context import *` 会触发 cv2 / detect.track / FFprobeInspect
# 等重依赖。bench 只测 DP，注入空 stub 跳过这些。
_SHARED_CTX_MOD = "src.core.auto_rechart.analyze.shared_context"
sys.modules[_SHARED_CTX_MOD] = types.ModuleType(_SHARED_CTX_MOD)

from src.core.auto_rechart.analyze.maidata_generate import generate_maidata
from src.core.auto_rechart.analyze.maidata_write import _LayoutEngine
from src.core.auto_rechart.detect.note_definition import NoteType, NoteVariant  # noqa: F401  (供 eval 使用)

TEST_DIR = Path(r"C:\Users\ck273\Desktop\[maimai谱面确认] 純情アルメリア MASTER-p01-120")
PICKLE = Path(__file__).parent / "_bench_items.pkl"


def parse_notes_info(path: Path):
    """反序列化 note_preprocess_result.txt → list[((track_id, NoteType, NoteVariant, pos), time)]"""
    notes = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split(",")]
        track_id = int(parts[0])
        note_type = eval(parts[1])      # NoteType.HOLD
        note_variant = eval(parts[2])   # NoteVariant.NORMAL
        position = parts[3]
        times = [float(x) for x in parts[4:]]
        time_val = times[0] if len(times) == 1 else tuple(times)
        key = (track_id, note_type, note_variant, position)
        notes.append((key, time_val))
    return notes


def parse_timing_points(path: Path):
    """new tekisuto_aligned.txt → list[(beat_index, bpm, start_ms)]，start_ms 累加重建"""
    beats = []
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"beat_index\s*=\s*([\d.]+),\s*bpm\s*=\s*([\d.]+)", line)
        if m:
            beats.append((float(m.group(1)), float(m.group(2))))
    beats.sort()
    tps = []
    acc = 0.0
    for i, (beat, bpm) in enumerate(beats):
        tps.append((beat, bpm, acc))
        if i + 1 < len(beats):
            acc += (beats[i + 1][0] - beat) * 60000.0 / bpm
    return tps


def build_items():
    notes = parse_notes_info(TEST_DIR / "note_preprocess_result.txt")
    tps = parse_timing_points(TEST_DIR / "new tekisuto_aligned.txt")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        items = generate_maidata(notes, tps, 32, 32)
    print(buf.getvalue())
    return items


def get_items(rebuild: bool):
    if rebuild or not PICKLE.exists():
        items = build_items()
        with open(PICKLE, "wb") as f:
            pickle.dump(items, f)
        print(f"rebuilt & cached {len(items)} items → {PICKLE.name}")
    with open(PICKLE, "rb") as f:
        return pickle.load(f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--rebuild", action="store_true")
    args = ap.parse_args()

    items = get_items(args.rebuild)
    print(f"items count: {len(items)}")

    # 统计能触发 p>=5 内层 DP 的"非平凡" gap 分布（仅信息性）
    from fractions import Fraction
    import math
    bar_items = {}
    for it in items:
        bar = it.time.numerator // it.time.denominator
        bar_items.setdefault(bar, []).append(it)
    nontrivial = 0
    total_gaps = 0
    for bar, lst in bar_items.items():
        times = []
        seen = set()
        for it in sorted(lst, key=lambda x: x.time):
            r = it.relative_time
            if r not in seen:
                seen.add(r)
                times.append(r)
        gaps = []
        prev = Fraction(0)
        for t in times:
            gaps.append(t - prev)
            prev = t
        gaps.append(Fraction(1) - prev)
        R = 1
        for g in gaps:
            if g > 0:
                R = math.lcm(R, g.denominator)
        for g in gaps:
            if g > 0:
                total_gaps += 1
                p = g.numerator * R // g.denominator
                # 是否需要内层 DP：分子无法用 1..4 单段表示
                single_ok = any((k * R) % p == 0 for k in range(1, 6)) if p > 0 else True
                if not single_ok:
                    nontrivial += 1
    print(f"non-trivial gaps (trigger inner DP): {nontrivial} / {total_gaps}")

    engine = _LayoutEngine()
    # warmup
    body_ref = engine.layout(items)

    # 完整字符串等价校验: 首次运行写入参考 body, 之后逐字符对比 (文本逐字节一致性证明)
    ref_path = Path(__file__).parent / "_bench_body_ref.txt"
    if not ref_path.exists():
        ref_path.write_text(body_ref, encoding="utf-8")
        print(f"[equiv] wrote reference body ({len(body_ref)} chars) → {ref_path.name}")
    else:
        saved = ref_path.read_text(encoding="utf-8")
        ok_equiv = (saved == body_ref)
        print(f"[equiv] body identical to reference: {'PASS' if ok_equiv else 'FAIL'}")
        if not ok_equiv:
            # 找第一个差异位置
            for i, (a, b) in enumerate(zip(saved, body_ref)):
                if a != b:
                    print(f"        first diff at char {i}: ref={a!r} got={b!r}")
                    print(f"        context ref: ...{saved[max(0,i-20):i+20]!r}")
                    print(f"        context got: ...{body_ref[max(0,i-20):i+20]!r}")
                    break
            print(f"        len ref={len(saved)} len got={len(body_ref)}")

    N = args.n
    ts = []
    for _ in range(N):
        t0 = time.perf_counter()
        engine.layout(items)
        ts.append(time.perf_counter() - t0)

    med = statistics.median(ts) * 1000
    print(f"\nlayout median over {N}: {med:.3f} ms")
    print(f"  min {min(ts)*1000:.3f} ms   max {max(ts)*1000:.3f} ms   mean {statistics.mean(ts)*1000:.3f} ms")
    # 输出长度，供前后对比文本一致性
    print(f"  body length: {len(body_ref)} chars")


if __name__ == "__main__":
    main()
