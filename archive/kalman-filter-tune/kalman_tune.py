"""
kalman_tune.py — 6 维恒加速 Kalman 离线调参

用 detect_result.txt (YOLO 检测) 和 track_result.txt (dump 真值)
对 KalmanBoxTracker6D 的 Q/R 超参进行贝叶斯优化。

6 维状态: [cx,cy, vx,vy, ax,ay]，w/h 不参与 Kalman。
不依赖 fps 自适应（dt=1 硬编码）。
"""

from __future__ import annotations

import sys
import os
import math
import time
import numpy as np
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

# ── 确保 src 可导入 ──
_project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_project_root))

from src.core.auto_convert.detect.oc_sort import KalmanBoxTracker6D


# ============================================================================
# 数据加载
# ============================================================================

def _parse_track_center(parts: list[str]) -> tuple[float, float]:
    """解析 track 行数据的中心点 (cx, cy).
    格式: frame, note_type, variant, conf, x1..y4, cx, cy, w, h, r
    → parts[12]=cx, parts[13]=cy
    """
    return float(parts[12]), float(parts[13])


def load_track_slides(path: str | Path) -> list[np.ndarray]:  # 每条 track 返回 (N,columns)
    """解析 track_result.txt，返回每条 SLIDE track 的真值行列表。

    每行: [frame, note_type_str, variant_str, conf, x1,y1,x2,y2,x3,y3,x4,y4, cx,cy,w,h,r]
    """
    tracks: dict[int, list[list[str]]] = {}
    cur_id: int | None = None
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line.startswith('track_id:'):
                parts = [x.strip() for x in line.split(',')]
                tid = int(parts[0].split(':')[1].strip())
                nt = parts[1].split(':')[1].strip()
                if nt == 'slide':
                    cur_id = tid
                    tracks[cur_id] = []
                else:
                    cur_id = None
            elif cur_id is not None:
                parts = [x.strip() for x in line.split(',')]
                if parts[1] == 'slide':
                    tracks[cur_id].append(parts)

    # 按 frame 升序，只保留 non-empty
    result = []
    for pts in tracks.values():
        pts.sort(key=lambda p: int(p[0]))
        if len(pts) >= 3:  # 至少 3 帧才有意义
            result.append(pts)
    return result


def load_detect_slides(path: str | Path) -> dict[int, list[np.ndarray]]:
    """解析 detect_result.txt → {frame: [(x1,y1,x2,y2,cx,cy,conf,cls,idx), ...]}
    
    detect 格式也是 OBB（x1..y4），用 cx,cy 做匹配，同时导出 xyxy 供 Kalman update。
    xyxy = (min(x1..x4), min(y1..y4), max(x1..x4), max(y1..y4))
    """
    detect_by_frame: dict[int, list[np.ndarray]] = {}
    cur_frame: int | None = None
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line.startswith('frame:'):
                cur_frame = int(line.split(':')[1].strip())
                detect_by_frame[cur_frame] = []
            elif cur_frame is not None:
                parts = [x.strip() for x in line.split(',')]
                if parts[1] != 'slide':
                    continue
                # OBB corners: x1..y4, then cx,cy,w,h,r
                xs = [float(parts[4]), float(parts[6]), float(parts[8]), float(parts[10])]
                ys = [float(parts[5]), float(parts[7]), float(parts[9]), float(parts[11])]
                xyxy_x1, xyxy_y1 = min(xs), min(ys)
                xyxy_x2, xyxy_y2 = max(xs), max(ys)
                det_cx = float(parts[12])
                det_cy = float(parts[13])
                conf = float(parts[3])
                idx = len(detect_by_frame[cur_frame])
                detect_by_frame[cur_frame].append(
                    np.array([xyxy_x1, xyxy_y1, xyxy_x2, xyxy_y2,
                              det_cx, det_cy, conf, 1.0, float(idx)], dtype=np.float64)
                )
    return detect_by_frame


# ============================================================================
# 检测 → 真值匹配（按中心距离）
# ============================================================================

@dataclass
class TrackFrame:
    truth_cx: float
    truth_cy: float
    obs_xyxy: np.ndarray | None  # 匹配到的检测框（含 conf），或 None


def build_track_observations(
    track_pts: list[list[str]],
    detect_by_frame: dict[int, list[np.ndarray]],
    center_max_dist: float = 20.0,
) -> list[TrackFrame] | None:
    """将一条 track 的真值帧与 detection 匹配（按中心距离），返回带观测的帧列表.

    track 真值框是 OBB 格式且尺寸极小，detection 框是 YOLO 大框。
    两者中心相同，故按中心距离匹配。
    """
    frames: list[TrackFrame] = []
    for pt in track_pts:
        fnum = int(pt[0])
        tc_x, tc_y = _parse_track_center(pt)
        dets = detect_by_frame.get(fnum, [])
        # 选中心距离最近的 detection
        best_dist = float('inf')
        best_det: np.ndarray | None = None
        for det in dets:
            dcx, dcy = det[4], det[5]  # detect 的 cx,cy
            dist = math.hypot(tc_x - dcx, tc_y - dcy)
            if dist < best_dist:
                best_dist = dist
                best_det = det
        obs = best_det if best_dist < center_max_dist else None
        frames.append(TrackFrame(
            truth_cx=tc_x,
            truth_cy=tc_y,
            obs_xyxy=obs,
        ))
    # 首帧必须有观测（Kalman 需要初始化）
    if frames[0].obs_xyxy is None or len(frames) < 3:
        return None
    return frames


# ============================================================================
# 评估函数
# ============================================================================

def _build_kalman_with_params(
    init_bbox: np.ndarray,
    q_pos: float, q_vel: float, q_acc: float,
    r_pos: float,
) -> KalmanBoxTracker6D:
    """创建 KalmanBoxTracker6D 并用给定缩放因子覆写 Q/R.
    init_bbox: [x1,y1,x2,y2, cx,cy, conf, cls, idx] from detect array
    """
    kf_bbox = np.array([init_bbox[0], init_bbox[1], init_bbox[2], init_bbox[3],
                         init_bbox[6], init_bbox[7], init_bbox[8]], dtype=np.float64)
    kf = KalmanBoxTracker6D(kf_bbox)

    # Q (6×6): indices 0,1=cx,cy; 2,3=vx,vy; 4,5=ax,ay
    kf.kf.Q[0, 0] *= q_pos; kf.kf.Q[1, 1] *= q_pos
    kf.kf.Q[2, 2] *= q_vel; kf.kf.Q[3, 3] *= q_vel
    kf.kf.Q[4, 4] *= q_acc; kf.kf.Q[5, 5] *= q_acc
    # 同时也缩放初始 P
    kf.kf.P[0, 0] *= q_pos; kf.kf.P[1, 1] *= q_pos
    kf.kf.P[2, 2] *= q_vel; kf.kf.P[3, 3] *= q_vel
    kf.kf.P[4, 4] *= q_acc; kf.kf.P[5, 5] *= q_acc

    # R (2×2)
    kf.kf.R[0, 0] *= r_pos; kf.kf.R[1, 1] *= r_pos
    return kf


def evaluate_track(
    track_frames: list[TrackFrame],
    q_pos: float, q_vel: float, q_acc: float,
    r_pos: float,
) -> tuple[float, list[float]]:
    """评估一条 track: 返回 (平均误差, 逐帧误差列表)."""
    init_obs = track_frames[0].obs_xyxy
    assert init_obs is not None

    kf = _build_kalman_with_params(init_obs, q_pos, q_vel, q_acc, r_pos)

    errors: list[float] = []
    for tf in track_frames[1:]:
        pred_xyxy = kf.predict().flatten()
        pred_cx = (pred_xyxy[0] + pred_xyxy[2]) / 2.0
        pred_cy = (pred_xyxy[1] + pred_xyxy[3]) / 2.0
        err = math.hypot(pred_cx - tf.truth_cx, pred_cy - tf.truth_cy)
        errors.append(err)

        if tf.obs_xyxy is not None:
            # Kalman expects [x1,y1,x2,y2,score,cls,idx]
            kf.update(np.array([tf.obs_xyxy[0], tf.obs_xyxy[1],
                                tf.obs_xyxy[2], tf.obs_xyxy[3],
                                tf.obs_xyxy[6], tf.obs_xyxy[7],
                                tf.obs_xyxy[8]], dtype=np.float64))
        else:
            kf.update(None)

    mean_err = float(np.mean(errors)) if errors else 0.0
    return mean_err, errors


def evaluate_params(
    params: tuple[float, float, float, float],
    all_tracks: list[list[TrackFrame]],
    verbose: bool = False,
) -> float:
    """返回所有 track 的平均 MPE（像素）."""
    q_pos, q_vel, q_acc, r_pos = params
    total_err = 0.0
    total_frames = 0
    for tframes in all_tracks:
        mean_e, _ = evaluate_track(tframes, q_pos, q_vel, q_acc, r_pos)
        total_err += mean_e * (len(tframes) - 1)
        total_frames += (len(tframes) - 1)
    mpe = total_err / total_frames if total_frames else float('inf')
    if verbose:
        print(f"  MPE={mpe:.3f}  q=({q_pos:.4f},{q_vel:.4f},{q_acc:.4f}) r_pos={r_pos:.4f}")
    return mpe


# ============================================================================
# 误差分解
# ============================================================================

def analyze_results(
    all_tracks: list[list[TrackFrame]],
    q_pos: float, q_vel: float, q_acc: float,
    r_pos: float,
) -> dict:
    """详细误差分析：P50/P95/转弯vs直线."""
    all_errors: list[float] = []
    straight_errs: list[float] = []
    turn_errs: list[float] = []
    total_frames = 0

    for tframes in all_tracks:
        init_obs = tframes[0].obs_xyxy
        assert init_obs is not None
        kf = _build_kalman_with_params(init_obs, q_pos, q_vel, q_acc, r_pos)

        prev_pred_c = None
        for tf in tframes[1:]:
            pred_xyxy = kf.predict().flatten()
            pred_cx = (pred_xyxy[0] + pred_xyxy[2]) / 2.0
            pred_cy = (pred_xyxy[1] + pred_xyxy[3]) / 2.0
            err = math.hypot(pred_cx - tf.truth_cx, pred_cy - tf.truth_cy)
            all_errors.append(err)

            # 转弯检测：比较预测位移方向 vs 预测→真值方向
            if prev_pred_c is not None:
                pred_dx = pred_cx - prev_pred_c[0]
                pred_dy = pred_cy - prev_pred_c[1]
                truth_dx = tf.truth_cx - prev_pred_c[0]
                truth_dy = tf.truth_cy - prev_pred_c[1]
                dot = pred_dx * truth_dx + pred_dy * truth_dy
                norm_p = math.hypot(pred_dx, pred_dy) + 1e-6
                norm_t = math.hypot(truth_dx, truth_dy) + 1e-6
                cos_angle = max(-1.0, min(1.0, dot / (norm_p * norm_t)))
                angle_deg = math.degrees(math.acos(cos_angle))
                if angle_deg > 30:
                    turn_errs.append(err)
                else:
                    straight_errs.append(err)
            else:
                straight_errs.append(err)

            prev_pred_c = (pred_cx, pred_cy)
            total_frames += 1

            if tf.obs_xyxy is not None:
                kf.update(np.array([tf.obs_xyxy[0], tf.obs_xyxy[1],
                                    tf.obs_xyxy[2], tf.obs_xyxy[3],
                                    tf.obs_xyxy[6], tf.obs_xyxy[7],
                                    tf.obs_xyxy[8]], dtype=np.float64))
            else:
                kf.update(None)

    arr = np.array(all_errors)
    return {
        'MPE': float(np.mean(arr)),
        'P50': float(np.percentile(arr, 50)),
        'P95': float(np.percentile(arr, 95)),
        'P99': float(np.percentile(arr, 99)),
        'Max': float(np.max(arr)),
        'MPE_straight': float(np.mean(straight_errs)) if straight_errs else 0,
        'MPE_turn': float(np.mean(turn_errs)) if turn_errs else 0,
        'straight_pct': len(straight_errs) / len(all_errors) * 100,
        'turn_pct': len(turn_errs) / len(all_errors) * 100,
        'total_frames': total_frames,
    }


# ============================================================================
# 超参搜索
# ============================================================================

def grid_search(
    all_tracks: list[list[TrackFrame]],
) -> tuple[tuple, float]:
    """粗粒度 L1 网格搜索 q_pos/q_vel/q_acc（log 间隔）."""
    q_candidates = [0.01, 0.1, 1.0, 10.0, 100.0]
    best_params = None
    best_mpe = float('inf')
    total = len(q_candidates) ** 3

    print(f"Grid search: {total} combinations...")
    i = 0
    for qp in q_candidates:
        for qv in q_candidates:
            for qa in q_candidates:
                mpe = evaluate_params((qp, qv, qa, 1.0), all_tracks)
                i += 1
                if mpe < best_mpe:
                    best_mpe = mpe
                    best_params = (qp, qv, qa)
                if i % 10 == 0:
                    print(f"  [{i}/{total}] best MPE={best_mpe:.3f} @ q=({best_params[0]},{best_params[1]},{best_params[2]})")

    print(f"\nGrid best: MPE={best_mpe:.3f} @ q_pos={best_params[0]}, q_vel={best_params[1]}, q_acc={best_params[2]}")
    return best_params, best_mpe


def bayesian_optimize(
    all_tracks: list[list[TrackFrame]],
    initial_guess: tuple[float, float, float, float] | None = None,
    n_calls: int = 30,
    seed: int = 42,
) -> tuple[tuple, float]:
    """L2 贝叶斯优化 4 参数."""
    try:
        from skopt import gp_minimize
        from skopt.space import Real
        from skopt.utils import use_named_args
    except ImportError:
        print("Warning: scikit-optimize not installed. Install with: pip install scikit-optimize")
        return (initial_guess or (1.0, 1.0, 1.0, 1.0)), 0.0

    space = [
        Real(0.005, 200.0, name='q_pos', prior='log-uniform'),
        Real(0.005, 200.0, name='q_vel', prior='log-uniform'),
        Real(0.005, 200.0, name='q_acc', prior='log-uniform'),
        Real(0.1, 20.0, name='r_pos', prior='log-uniform'),
    ]

    x0 = list(initial_guess) if initial_guess else [1.0, 1.0, 1.0, 1.0]

    print(f"\nBayesian optimization: {n_calls} calls...")

    @use_named_args(space)
    def objective(**kwargs):
        params = (kwargs['q_pos'], kwargs['q_vel'], kwargs['q_acc'], kwargs['r_pos'])
        return evaluate_params(params, all_tracks, verbose=False)

    result = gp_minimize(
        objective, space, x0=[x0], n_calls=n_calls,
        random_state=seed, n_jobs=1, verbose=True,
    )

    best = (result.x[0], result.x[1], result.x[2], result.x[3])
    return best, result.fun


# ============================================================================
# 主入口
# ============================================================================

def main():
    data_dir = Path(__file__).resolve().parent
    detect_path = data_dir / 'detect_result.txt'
    track_path = data_dir / 'track_result.txt'

    print("Loading detect_result.txt ...")
    detect_by_frame = load_detect_slides(detect_path)
    print(f"  {len(detect_by_frame)} frames, {sum(len(v) for v in detect_by_frame.values())} slide detections")

    print("Loading track_result.txt (ground truth) ...")
    raw_tracks = load_track_slides(track_path)
    print(f"  {len(raw_tracks)} valid slide tracks")

    print("Matching detections to tracks (center dist < 10px) ...")
    all_tracks: list[list[TrackFrame]] = []
    skipped = 0
    for pts in raw_tracks:
        tf = build_track_observations(pts, detect_by_frame, center_max_dist=10.0)
        if tf is not None:
            all_tracks.append(tf)
        else:
            skipped += 1
    total_frames = sum(len(t) - 1 for t in all_tracks)
    print(f"  {len(all_tracks)} tracks with matched detections ({total_frames} predict frames), {skipped} skipped")

    # ── L1: Grid search on Q only ──
    grid_start = time.time()
    (gqp, gqv, gqa), grid_mpe = grid_search(all_tracks)
    print(f"  Grid search took {time.time() - grid_start:.0f}s")

    # ── L2: Bayesian refine on all 4 params ──
    bayes_start = time.time()
    opt_params, opt_mpe = bayesian_optimize(
        all_tracks,
        initial_guess=(gqp, gqv, gqa, 1.0),
        n_calls=40,
    )
    print(f"  Bayesian optimization took {time.time() - bayes_start:.0f}s")

    # ── Final analysis ──
    print("\n" + "=" * 60)
    print("FINAL RESULTS")
    print("=" * 60)
    bp = opt_params
    print(f"q_pos  = {bp[0]:.6f}")
    print(f"q_vel  = {bp[1]:.6f}")
    print(f"q_acc  = {bp[2]:.6f}")
    print(f"r_pos  = {bp[3]:.6f}")
    print(f"MPE    = {opt_mpe:.4f} px")

    detail = analyze_results(all_tracks, bp[0], bp[1], bp[2], bp[3])
    print(f"\nError distribution ({detail['total_frames']} frames):")
    print(f"  MPE  = {detail['MPE']:.4f} px")
    print(f"  P50  = {detail['P50']:.4f} px")
    print(f"  P95  = {detail['P95']:.4f} px")
    print(f"  P99  = {detail['P99']:.4f} px")
    print(f"  Max  = {detail['Max']:.4f} px")
    print(f"  Straight ({detail['straight_pct']:.0f}%): {detail['MPE_straight']:.4f} px")
    print(f"  Turn    ({detail['turn_pct']:.0f}%): {detail['MPE_turn']:.4f} px")

    # ── 硬编码到 oc_sort.py 的建议 ──
    print("\n--- 建议写入 KalmanBoxTracker6D.__init__ 的代码 ---")
    print("    # 过程噪声 Q — tuned on SLIDE tracks (6D CA)")
    print(f"    self.kf.Q[0, 0] *= {bp[0]:.6f}; self.kf.Q[1, 1] *= {bp[0]:.6f}")
    print(f"    self.kf.Q[2, 2] *= {bp[1]:.6f}; self.kf.Q[3, 3] *= {bp[1]:.6f}")
    print(f"    self.kf.Q[4, 4] *= {bp[2]:.6f}; self.kf.Q[5, 5] *= {bp[2]:.6f}")
    print(f"    self.kf.R[0, 0] *= {bp[3]:.6f}; self.kf.R[1, 1] *= {bp[3]:.6f}")


if __name__ == '__main__':
    main()
