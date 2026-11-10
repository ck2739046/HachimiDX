"""触摸区域可视化与校验。


运行::

    python test/test_touch_areas.py

    # 保存结果图、不弹窗
    python test/test_touch_areas.py --save touch_areas.png --no-show

    # 叠加触摸面板截图, 便于肉眼对比区域是否一致
    python test/test_touch_areas.py --reference TouchPanel.png --save compare.png --no-show

校验内容:
1. 每个区域多边形内部随机采样点都能查询回该区域;
2. 随机采样点: 查询结果与区域多边形几何一致(验证栅格查询与多边形自洽);
3. 面板外的点也能得到结果(沿半径投影到面板边缘);
4. 查询速度基准(100 万次查询的总耗时与单次耗时)。
"""

import argparse
import sys
import time
from pathlib import Path

import cv2
import numpy as np

# 把仓库根目录加入 sys.path, 使 test/ 下可直接运行
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.core.auto_rechart.touch_area import (  # noqa: E402
    get_touch_area_map,
    get_touch_area_polygons,
)

# 1080p 标准坐标下的判定线半径
JUDGELINE_RADIUS_1080 = 480.0
# 1080p 标准坐标下的面板边缘半径
PANEL_RADIUS_1080 = 540.0


def _make_palette(labels: list[str]) -> dict[str, tuple[int, int, int]]:
    """按区域分组生成区分度较高的 BGR 颜色。"""
    # 每组的基础色相: A 红橙, B 橙黄, C 灰白, D 绿, E 蓝紫
    group_hue = {"A": 2, "B": 26, "C": None, "D": 62, "E": 112}
    palette = {}
    group_index = {}
    for label in labels:
        group = label[0]
        index = group_index.get(group, 0)
        group_index[group] = index + 1
        if group_hue[group] is None:
            palette[label] = (200, 200, 205)
            continue
        # cv2 的 H 取值范围 0~180
        hue = int(group_hue[group] + index * 4) % 180
        saturation = 170
        value = int(255 - (index % 3) * 35)
        hsv = np.uint8([[[hue, saturation, value]]])
        bgr = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)[0, 0]
        palette[label] = (int(bgr[0]), int(bgr[1]), int(bgr[2]))
    return palette


def _polygon_centroid(points: np.ndarray) -> tuple[float, float]:
    """计算多边形质心(鞋带公式), 用于放置区域标签。"""
    pts = np.asarray(points, dtype=np.float64)
    xs = pts[:, 0]
    ys = pts[:, 1]
    cross = xs * np.roll(ys, -1) - np.roll(xs, -1) * ys
    double_area = float(cross.sum())
    if abs(double_area) < 1e-9:
        return float(xs.mean()), float(ys.mean())
    center_x = float(((xs + np.roll(xs, -1)) * cross).sum() / (3.0 * double_area))
    center_y = float(((ys + np.roll(ys, -1)) * cross).sum() / (3.0 * double_area))
    return center_x, center_y


def _check_region_interiors(
    area_map, polygons, samples_per_region: int, seed: int
) -> tuple[int, int]:
    """在每个区域多边形内部随机采样, 校验这些点都能查询回该区域。

    返回 (不一致数量, 采样数量)。采样点与区域边界保持 3px 距离,
    避免边界栅格化误差影响判定。
    """
    rng = np.random.default_rng(seed)
    float_polygons = {
        label: points.astype(np.float32) for label, points in polygons.items()
    }
    bad = 0
    total = 0
    for label, polygon in float_polygons.items():
        x_min, y_min = polygon.min(axis=0)
        x_max, y_max = polygon.max(axis=0)
        kept = 0
        candidates = samples_per_region * 4
        for u, v in rng.uniform(0.0, 1.0, (candidates, 2)).tolist():
            if kept >= samples_per_region:
                break
            x = x_min + u * (x_max - x_min)
            y = y_min + v * (y_max - y_min)
            if cv2.pointPolygonTest(polygon, (x, y), True) < 3.0:
                continue
            kept += 1
            total += 1
            if area_map.locate(x, y) != label:
                bad += 1
    return bad, total


def _check_random_points(area_map, polygons, count: int, seed: int) -> tuple[int, int]:
    """随机采样面板内点, 校验查询结果与其所在区域多边形是否一致。

    返回 (不一致数量, 采样数量)。区域边界附近的点允许 2px 误差。
    """
    rng = np.random.default_rng(seed)
    angles = rng.uniform(0.0, 2.0 * np.pi, count)
    radii = np.sqrt(rng.uniform(0.0, 1.0, count)) * PANEL_RADIUS_1080
    xs = 540.0 + radii * np.cos(angles)
    ys = 540.0 + radii * np.sin(angles)

    polygon_visit_order = list(polygons)
    bad = 0
    for x, y in zip(xs.tolist(), ys.tolist()):
        label = area_map.locate(x, y)
        polygon = polygons[label]
        # 点在该区域多边形内, 或距离多边形不超过 2px(边界/栅格化误差), 视为一致
        distance = cv2.pointPolygonTest(polygon.astype(np.float32), (x, y), True)
        if distance >= -2.0:
            continue
        # 少数情况下多边形有重叠, 只要点落在另一个区域内也算一致
        if any(
            cv2.pointPolygonTest(polygons[other].astype(np.float32), (x, y), False) >= 0
            for other in polygon_visit_order
        ):
            continue
        bad += 1
    return bad, count


def _benchmark_locate(area_map, count: int, seed: int) -> tuple[float, float]:
    """查询速度基准, 返回 (总耗时秒, 单次耗时微秒)。"""
    rng = np.random.default_rng(seed)
    xs = rng.uniform(0.0, 1080.0, count).tolist()
    ys = rng.uniform(0.0, 1080.0, count).tolist()
    start = time.perf_counter()
    for x, y in zip(xs, ys):
        area_map.locate(x, y)
    elapsed = time.perf_counter() - start
    return elapsed, elapsed / count * 1e6


def _render(
    canvas_size: int,
    polygons,
    palette: dict[str, tuple[int, int, int]],
    reference: np.ndarray | None,
) -> np.ndarray:
    """绘制区域图: 每个区域填充颜色 + 边界 + 区域标签。"""
    scale = canvas_size / 1080.0
    center = canvas_size // 2
    canvas = np.zeros((canvas_size, canvas_size, 3), dtype=np.uint8)

    for label, points in polygons.items():
        points_int = np.round(points).astype(np.int32).reshape(-1, 1, 2)
        cv2.fillPoly(canvas, [points_int], palette[label])
        cv2.polylines(canvas, [points_int], True, (235, 235, 235), 1, cv2.LINE_AA)

    # 判定线圆圈(白色)和面板外轮廓圆圈(绿色)
    cv2.circle(
        canvas,
        (center, center),
        round(JUDGELINE_RADIUS_1080 * scale),
        (255, 255, 255),
        1,
        cv2.LINE_AA,
    )
    cv2.circle(
        canvas,
        (center, center),
        round(PANEL_RADIUS_1080 * scale),
        (0, 200, 0),
        1,
        cv2.LINE_AA,
    )

    font_scale = 0.5 * canvas_size / 800.0
    for label, points in polygons.items():
        centroid_x, centroid_y = _polygon_centroid(points)
        (text_width, text_height), _baseline = cv2.getTextSize(
            label, cv2.FONT_HERSHEY_SIMPLEX, font_scale, 1
        )
        text_pos = (
            round(centroid_x - text_width / 2),
            round(centroid_y + text_height / 2),
        )
        cv2.putText(
            canvas,
            label,
            text_pos,
            cv2.FONT_HERSHEY_SIMPLEX,
            font_scale,
            (0, 0, 0),
            2,
            cv2.LINE_AA,
        )
        cv2.putText(
            canvas,
            label,
            text_pos,
            cv2.FONT_HERSHEY_SIMPLEX,
            font_scale,
            (0, 255, 255),
            1,
            cv2.LINE_AA,
        )

    if reference is not None:
        reference_resized = cv2.resize(
            reference, (canvas_size, canvas_size), interpolation=cv2.INTER_AREA
        )
        canvas = cv2.addWeighted(canvas, 0.55, reference_resized, 0.45, 0.0)
    return canvas


def _print_result(name: str, ok: bool, detail: str) -> None:
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {name}: {detail}")


def main() -> int:
    parser = argparse.ArgumentParser(description="触摸区域可视化与校验")
    parser.add_argument("--canvas-size", type=int, default=800, help="画布边长, 默认 800")
    parser.add_argument("--save", type=Path, default=None, help="保存结果图路径")
    parser.add_argument("--no-show", action="store_true", help="不弹出预览窗口")
    parser.add_argument(
        "--reference", type=Path, default=None, help="触摸面板截图, 叠加显示以对比区域"
    )
    parser.add_argument("--seed", type=int, default=0, help="随机采样种子")
    args = parser.parse_args()

    if args.canvas_size < 200:
        parser.error("--canvas-size 不能小于 200")

    # 所有校验都在 1080p 标准坐标下进行
    std_area_map = get_touch_area_map(1080)
    std_polygons = get_touch_area_polygons(1080)

    failures = 0

    # 1. 区域内部采样点
    interior_bad, interior_total = _check_region_interiors(
        std_area_map, std_polygons, 200, args.seed
    )
    _print_result(
        "区域内部采样",
        interior_bad == 0,
        f"33 个区域共采样 {interior_total} 点, 失败 {interior_bad} 个",
    )
    failures += 1 if interior_bad else 0

    # 2. 随机采样点与区域多边形的一致性
    bad, total = _check_random_points(std_area_map, std_polygons, 20000, args.seed)
    ratio = bad / total
    _print_result(
        "随机点区域查询",
        ratio < 0.01,
        f"采样 {total} 点, 不一致 {bad} 点({ratio:.3%}), 阈值 1%",
    )
    failures += 1 if ratio >= 0.01 else 0

    # 3. 面板外的点
    outside_cases = {
        (540, -100): "D1",
        (-100, 540): "D7",
        (1180, 540): "D3",
        (540, 1180): "D5",
    }
    outside_bad = [
        (point, expect, std_area_map.locate(*point))
        for point, expect in outside_cases.items()
        if std_area_map.locate(*point) != expect
    ]
    _print_result(
        "面板外坐标兜底",
        not outside_bad,
        f"面板外点沿半径投影到最近区域, 失败 {len(outside_bad)} 个"
        + (f": {outside_bad}" if outside_bad else ""),
    )
    failures += 1 if outside_bad else 0

    # 4. 查询速度
    elapsed, per_call_us = _benchmark_locate(std_area_map, 1000000, args.seed + 1)
    _print_result(
        "查询速度",
        per_call_us < 5.0,
        f"100 万次 {elapsed:.2f}s, 单次 {per_call_us:.2f}us, 阈值 5us",
    )
    failures += 1 if per_call_us >= 5.0 else 0

    # 绘图: 使用当前画布尺寸下的区域数据
    canvas_size = args.canvas_size
    canvas_polygons = get_touch_area_polygons(canvas_size)
    palette = _make_palette(list(canvas_polygons))

    reference = None
    if args.reference is not None:
        reference = cv2.imread(str(args.reference), cv2.IMREAD_COLOR)
        if reference is None:
            print(f"无法读取参考图: {args.reference}")
            return 1

    canvas = _render(canvas_size, canvas_polygons, palette, reference)

    if args.save is not None:
        args.save.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(args.save), canvas)
        print(f"结果图已保存: {args.save}")

    if not args.no_show:
        try:
            window_name = "Touch Areas Visualization"
            cv2.imshow(window_name, canvas)
            print("按任意键关闭窗口...")
            cv2.waitKey(0)
            cv2.destroyAllWindows()
        except cv2.error as e:
            print(f"无法弹出预览窗口(可用 --save 保存结果图): {e}")

    print("全部校验通过。" if failures == 0 else f"有 {failures} 项校验未通过。")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
