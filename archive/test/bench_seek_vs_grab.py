"""
基准测试: cap.grab() vs cap.set(CAP_PROP_POS_FRAMES) 的成本换算。

回答: SEEK_THRESHOLD 应设多少, 才能让"小 gap 用 grab 循环 / 大 gap 用 seek"
始终落在更快的分支? 即: 多少次 grab 才抵得上一次 seek?

关键改进: seek 成本高度依赖"终点帧在 GOP 中的位置"(FFmpeg 会 seek 到目标前
最近的关键帧再逐帧解码), 单点测量方差极大。本脚本扫描多个起点覆盖不同 GOP
位置, 对每个 distance 给出 seek 成本的 p50/p90/max 分布, 据此稳健决策。

用法:
    python test/bench_seek_vs_grab.py "<video_path>"
"""
import sys
import time
import statistics
import subprocess
from pathlib import Path

import cv2


VIDEO_DEFAULT = (
    r"C:\Users\ck273\Desktop\[maimai谱面确认] Absolute Queen MASTER-p01-120"
    r"\[maimai谱面确认] Absolute Queen MASTER-p01-120_std.mp4"
)

GRAB_SAMPLE = 800                 # 连续 grab/read 的采样帧数
SEEK_DISTANCES = [1, 2, 5, 10, 25, 50, 100, 200, 300, 400, 600, 1000, 2000, 4000]
SEEK_REPEATS = 7                  # 每个 (distance, base) 组合重复次数
BASE_FRAMES = [50, 500, 1500, 4000, 8000, 12000]  # 多个起点覆盖不同 GOP 位置
WARMUP_GRABS = 50


def get_keyframes(path: str) -> list[int]:
    try:
        out = subprocess.run(
            [
                "ffprobe", "-loglevel", "error",
                "-select_streams", "v:0",
                "-show_entries", "packet=flags",
                "-of", "csv", str(path),
            ],
            capture_output=True, text=True, check=True,
        )
    except Exception:
        return []
    kfs: list[int] = []
    for i, line in enumerate(out.stdout.splitlines()):
        if line.strip().endswith("K"):
            kfs.append(i)
    return kfs


def measure_grab_unit(cap) -> float:
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    for _ in range(WARMUP_GRABS):
        if not cap.grab():
            break
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    t0 = time.perf_counter()
    n = 0
    for _ in range(GRAB_SAMPLE):
        if not cap.grab():
            break
        n += 1
    return (time.perf_counter() - t0) / n if n else float("nan")


def measure_read_unit(cap) -> float:
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    for _ in range(WARMUP_GRABS):
        if not cap.read()[0]:
            break
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    t0 = time.perf_counter()
    n = 0
    for _ in range(GRAB_SAMPLE):
        ok, _ = cap.read()
        if not ok:
            break
        n += 1
    return (time.perf_counter() - t0) / n if n else float("nan")


def percentile(sorted_vals: list[float], p: float) -> float:
    if not sorted_vals:
        return float("nan")
    k = (len(sorted_vals) - 1) * p
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    if f == c:
        return sorted_vals[f]
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


def measure_seek_dist(cap, distance: int, total_frames: int) -> list[float]:
    """
    在多个 BASE_FRAMES 起点上测 seek 成本, 返回所有样本(秒, 已减去 1 次 grab 单价)。
    每个 (base, distance): 先 reset 到 base, 再 set(base+distance)+grab。
    """
    samples: list[float] = []
    for base in BASE_FRAMES:
        if base + distance >= total_frames:
            continue
        for _ in range(SEEK_REPEATS):
            cap.set(cv2.CAP_PROP_POS_FRAMES, base)
            cap.grab()  # 让 reset 真正生效
            t0 = time.perf_counter()
            cap.set(cv2.CAP_PROP_POS_FRAMES, base + distance)
            cap.grab()  # 触发真正的 seek + 解码到目标
            dt = time.perf_counter() - t0
            samples.append(dt)
    return samples


def main():
    video = sys.argv[1] if len(sys.argv) > 1 else VIDEO_DEFAULT
    if not Path(video).is_file():
        print(f"[error] 视频不存在: {video}")
        sys.exit(1)

    print(f"视频: {video}")
    cap = cv2.VideoCapture(video)
    if not cap.isOpened():
        print("[error] 无法打开视频")
        sys.exit(1)

    fps = cap.get(cv2.CAP_PROP_FPS)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"backend={cap.getBackendName()}  {w}x{h}@{fps:.1f}fps  total={total}")
    print(f"扫描起点 BASE_FRAMES={BASE_FRAMES}  每点重复={SEEK_REPEATS}\n")

    kfs = get_keyframes(video)
    if len(kfs) >= 2:
        gaps = [kfs[i + 1] - kfs[i] for i in range(len(kfs) - 1)]
        print(f"关键帧 {len(kfs)} 个 | GOP gap min={min(gaps)} "
              f"median={int(statistics.median(gaps))} max={max(gaps)}\n")

    grab_unit = measure_grab_unit(cap)
    read_unit = measure_read_unit(cap)
    print(f"grab 单价: {grab_unit * 1e6:8.1f} us/帧")
    print(f"read 单价: {read_unit * 1e6:8.1f} us/帧  (read/grab = {read_unit / grab_unit:.2f}x)\n")

    # 汇总 seek 成本分布 (折算成等效 grab 次数)
    print(f"{'distance':>9} | {'p50':>7} {'p90':>7} {'max':>7}  (单位: 等效 grab 次数)")
    print("-" * 52)
    p90_by_dist = {}
    max_by_dist = {}
    for d in SEEK_DISTANCES:
        raw = measure_seek_dist(cap, d, total)
        if not raw:
            print(f"{d:>9} | {'N/A':>7}")
            continue
        pure = sorted(x - grab_unit for x in raw)
        p50 = percentile(pure, 0.50) / grab_unit
        p90 = percentile(pure, 0.90) / grab_unit
        mx = pure[-1] / grab_unit
        p90_by_dist[d] = p90
        max_by_dist[d] = mx
        print(f"{d:>9} | {p50:>7.0f} {p90:>7.0f} {mx:>7.0f}")

    print()
    print("判定规则: gap=N 时, grab 循环成本 = N grabs (确定值)。")
    print("  若 N < seek_p90(N), grab 几乎必胜 (90% 把握); 反之 seek 更划算。\n")

    print("=== 候选阈值对比 ===")
    for cand in [300, 400, 600]:
        if cand in p90_by_dist:
            print(f"  SEEK_THRESHOLD={cand}: gap={cand} 走 grab 成本={cand} grabs, "
                  f"同点 seek p90={p90_by_dist[cand]:.0f} / max={max_by_dist[cand]:.0f} grabs "
                  f"-> {'grab 更稳' if cand < p90_by_dist[cand] else 'seek 更划算'}")

    cap.release()


if __name__ == "__main__":
    main()
