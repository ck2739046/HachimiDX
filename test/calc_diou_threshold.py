"""
计算 DIoU 阈值下，两个相似尺寸框允许的最大中心距离（按框宽百分比）。

用法: python calc_diou_threshold.py
然后输入逗号分隔的 DIoU 值，如: 0.99, 0.98, 0.975

假设: 两个框尺寸相同，沿单一轴偏移。DIoU 仅取决于距离与框宽的比例。
"""


def calc_iou(w: float, d: float) -> float:
    """两个相同 w×w 的框，沿 x 轴偏移 d 时的 IoU（w 归一化为 1）。"""
    if d >= w:
        return 0.0
    overlap_w = w - d
    return overlap_w / (2 * w - overlap_w)


def calc_enclosing_diag2(w: float, d: float) -> float:
    """最小包围框对角线平方（框高=框宽=w 归一化为 1）。"""
    return (w + d) ** 2 + w ** 2


def calc_diou_rescaled(w: float, d: float) -> float:
    """缩放后的 DIoU，范围 [0, 1]，w 归一化为 1。"""
    if d >= w:
        iou = 0.0
    else:
        iou = calc_iou(w, d)
    c2 = calc_enclosing_diag2(w, d)
    raw = iou - (d ** 2) / c2
    return (raw + 1.0) / 2.0


def max_distance_ratio_for_diou(target_diou: float) -> float:
    """对给定 DIoU 阈值，二分搜索最大允许距离/框宽比例。"""
    lo, hi = 0.0, 2.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if calc_diou_rescaled(1.0, mid) >= target_diou:
            lo = mid
        else:
            hi = mid
    return lo


def main():
    print("=" * 55)
    print("  DIoU 阈值 → 最大中心距离 (占框宽百分比)")
    print("  假设: 两个框尺寸相同，正方形，沿单一轴偏移")
    print("  直接回车退出")
    print("=" * 55)

    while True:
        user_input = input("\n请输入 DIoU 阈值 (逗号分隔，如 0.99, 0.98, 0.975): ").strip()
        if not user_input:
            print("退出。")
            return

        thresholds = [float(x.strip()) for x in user_input.split(",") if x.strip()]
        if not thresholds:
            print("未输入有效阈值，退出。")
            return

        print(f"\n  {'DIoU 阈值':>10}  {'最大中心距离 / 框宽':>22}")
        print(f"  {'-'*10}  {'-'*22}")

        for t in sorted(thresholds, reverse=True):
            ratio = max_distance_ratio_for_diou(t)
            print(f"  {t:10.4f}  {ratio:21.2%}")

        print()
        print("解读: 中心距离 ≤ 框宽 × 上表比例时，DIoU ≥ 阈值。")


if __name__ == "__main__":
    main()

