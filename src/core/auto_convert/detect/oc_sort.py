from __future__ import annotations

import math
import numpy as np
from filterpy.kalman import KalmanFilter


# ============================================================================
# 辅助函数 — 参考原版 OC-SORT (https://github.com/noahcao/OC_SORT)
# ============================================================================

def convert_bbox_centre(bbox: np.ndarray) -> tuple[float, float, float, float]:
    """从 [x1,y1,x2,y2] 提取 (cx,cy,w,h)."""
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    cx = bbox[0] + w / 2.0
    cy = bbox[1] + h / 2.0
    return cx, cy, w, h


def speed_direction(bbox1: np.ndarray, bbox2: np.ndarray) -> np.ndarray:
    """Unit speed direction from bbox1 to bbox2, as (dy, dx)."""
    cx1 = (bbox1[0] + bbox1[2]) / 2.0
    cy1 = (bbox1[1] + bbox1[3]) / 2.0
    cx2 = (bbox2[0] + bbox2[2]) / 2.0
    cy2 = (bbox2[1] + bbox2[3]) / 2.0
    speed = np.array([cy2 - cy1, cx2 - cx1], dtype=np.float64)
    norm = np.sqrt((cy2 - cy1) ** 2 + (cx2 - cx1) ** 2) + 1e-6
    return speed / norm


def convert_bbox_to_z(bbox: np.ndarray) -> np.ndarray:
    """[x1,y1,x2,y2] → [x,y,s,r] as (4,1)."""
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    x = bbox[0] + w / 2.0
    y = bbox[1] + h / 2.0
    s = w * h
    r = w / float(h + 1e-6)
    return np.array([x, y, s, r], dtype=np.float64).reshape((4, 1))


def convert_x_to_bbox(x: np.ndarray) -> np.ndarray:
    """Kalman state [x,y,s,r,...] → xyxy as (1,4). 兼容 (7,) 和 (7,1) 形状."""
    x = np.atleast_1d(np.squeeze(x))
    x0, y0 = float(x[0]), float(x[1])
    s, r = float(x[2]), float(x[3])
    w = math.sqrt(s * r) if (s * r) > 0 else 1.0
    h = s / w if w > 0 else 1.0
    return np.array(
        [[x0 - w / 2.0, y0 - h / 2.0, x0 + w / 2.0, y0 + h / 2.0]],
        dtype=np.float64,
    )


# ============================================================================
# 7 维恒速 (CV) KalmanBoxTracker — 对齐原版 OC-SORT
#
# 状态: [x,y,s,r, vx,vy,vs] — 位置+面积+宽高比+速度。
# 观测: [x,y,s,r] (4 维).
# s=w*h, r=w/h. w/h 由 s,r 解算。
# ============================================================================

class KalmanBoxTracker:
    """7 维恒速 Kalman: [x,y,s,r, vx,vy,vs].
    观测: [x,y,s,r] (4 维)."""

    # 状态转移矩阵 F (7×7, dt=1) — 照搬原版 OC-SORT
    _F = np.array([
        [1, 0, 0, 0, 1, 0, 0],
        [0, 1, 0, 0, 0, 1, 0],
        [0, 0, 1, 0, 0, 0, 1],
        [0, 0, 0, 1, 0, 0, 0],
        [0, 0, 0, 0, 1, 0, 0],
        [0, 0, 0, 0, 0, 1, 0],
        [0, 0, 0, 0, 0, 0, 1],
    ], dtype=np.float64)

    # 观测矩阵 H (4×7): 直读前 4 维
    _H = np.array([
        [1, 0, 0, 0, 0, 0, 0],
        [0, 1, 0, 0, 0, 0, 0],
        [0, 0, 1, 0, 0, 0, 0],
        [0, 0, 0, 1, 0, 0, 0],
    ], dtype=np.float64)

    def __init__(self, bbox: np.ndarray, delta_dist_pct: float = 0.5, track_id: int = 0):
        cx, cy, w, h = convert_bbox_centre(bbox[:4])

        self.kf = KalmanFilter(dim_x=7, dim_z=4)
        self.kf.F = KalmanBoxTracker._F.copy()
        self.kf.H = KalmanBoxTracker._H.copy()

        # 观测噪声 R — 照搬原版: s/r 维加 10× 噪声
        self.kf.R[2:, 2:] *= 10.

        # 初始状态协方差 P — 照搬原版: 速度高不确定
        self.kf.P[4:, 4:] *= 1000.
        self.kf.P *= 10.

        # 过程噪声 Q — tuned on SLIDE tracks (7D CV)
        #   q_pos=0.01: 极低位置噪声 → 强信任模型外推
        #   q_vel=0.4:  中速噪声 → 转弯比较灵敏
        #   q_s=0.01:   低面积噪声 → 框尺寸稳定
        self.kf.Q[0, 0] = 0.01   # x
        self.kf.Q[1, 1] = 0.01   # y
        self.kf.Q[2, 2] = 0.01   # s (面积)
        self.kf.Q[3, 3] = 0.01   # r (宽高比)
        self.kf.Q[4, 4] = 0.4    # vx
        self.kf.Q[5, 5] = 0.4    # vy
        self.kf.Q[6, 6] = 0.0001 # vs

        self.kf.x[:4] = convert_bbox_to_z(bbox[:4])

        # 框尺寸缓存（从检测框读取，用于 _find_ref_obs 阈值）
        self._last_w = max(w, 1.0)
        self._last_h = max(h, 1.0)

        self.time_since_update = 0
        self.id = track_id

        self.hit_streak = 0
        self.age = 0

        self.last_observation = np.array(
            [-1.0, -1.0, -1.0, -1.0, -1.0], dtype=np.float64
        )
        self.observations: dict[int, np.ndarray] = {}
        self.history_observations: list[np.ndarray] = []
        self.velocity: np.ndarray | None = None
        self.delta_dist_pct = float(delta_dist_pct)

        # 动态 delta：基于距离百分比在历史中找参考观测
        self._ref_obs: np.ndarray | None = None
        self._ref_next_obs: np.ndarray | None = None

        # --- freeze/unfreeze 状态机（原版 OC-SORT 在线平滑） ---
        self._history_obs_z: list[np.ndarray | None] = [
            np.array([[cx], [cy]], dtype=np.float64)
        ]  # z-format 观测历史（含 None 表示缺失帧）
        self._observed: bool = True
        self._frozen_state: dict | None = None

        self.score = float(bbox[4]) if len(bbox) > 4 else 0.0
        self.cls = int(bbox[5]) if len(bbox) > 5 else 0
        self.idx = int(bbox[6]) if len(bbox) > 6 else -1
        self.history_scores: list[float] = [self.score]
        self.history_classes: list[int] = [self.cls]
        self.history_indices: list[int] = [self.idx]

    def _find_ref_obs(self, current_obs: np.ndarray) -> tuple[np.ndarray | None, np.ndarray | None]:
        """在轨迹历史中回溯，找到第一个与最新框中心距离 > delta_dist_pct*框尺寸 的观测 H。
        返回 (H, H_next)。找不到则回退到最旧观测；无历史则返回 (None, None).

        H:   参考观测框（用于计算轨迹速度方向：H → current_obs）
        H_next: H 的下一帧观测（用于 VDC 匹配：H_next → 候选框）"""
        if len(self.history_observations) == 0:
            return (None, None)

        cx_cur = (current_obs[0] + current_obs[2]) / 2.0
        cy_cur = (current_obs[1] + current_obs[3]) / 2.0
        threshold = self.delta_dist_pct * max(self._last_w, self._last_h)

        n = len(self.history_observations)
        for i in range(n - 1, -1, -1):
            h = self.history_observations[i]
            cx_h = (h[0] + h[2]) / 2.0
            cy_h = (h[1] + h[3]) / 2.0
            dist = np.sqrt((cx_cur - cx_h) ** 2 + (cy_cur - cy_h) ** 2)
            if dist > threshold:
                h_next = self.history_observations[i + 1] if i + 1 < n else current_obs
                return (h, h_next)

        # 回退：所有历史都太近，用最旧观测（至少比单帧稳定）
        h = self.history_observations[0]
        h_next = self.history_observations[1] if len(self.history_observations) >= 2 else current_obs
        return (h, h_next)

    def update(self, bbox: np.ndarray | None) -> None:
        # ====== 记录 z-format 观测 (cx,cy) ======
        if bbox is not None:
            cx, cy, w, h = convert_bbox_centre(bbox[:4])
            self._history_obs_z.append(
                np.array([[cx], [cy]], dtype=np.float64)
            )
            self._last_w = max(w, 1.0)
            self._last_h = max(h, 1.0)
        else:
            self._history_obs_z.append(None)

        # ====== freeze / unfreeze ======
        if bbox is None:
            if self._observed:
                self._freeze_kf()
            self._observed = False
            return

        if not self._observed:
            self._unfreeze_kf()

        # ====== 正常 tracker 级更新 ======
        bbox = np.asarray(bbox, dtype=np.float64)
        obs = np.array(
            [bbox[0], bbox[1], bbox[2], bbox[3], bbox[4]], dtype=np.float64
        )

        if self.last_observation.sum() >= 0:
            ref_obs, ref_next_obs = self._find_ref_obs(obs)
            self._ref_obs = ref_obs
            self._ref_next_obs = ref_next_obs
            if ref_obs is not None:
                self.velocity = speed_direction(ref_obs, obs)

        self.last_observation = obs
        self.observations[self.age] = obs
        self.history_observations.append(obs)

        self.time_since_update = 0
        self.hit_streak += 1

        # 4 维观测更新 [x,y,s,r]
        self.kf.update(convert_bbox_to_z(bbox[:4]))

        self.score = float(bbox[4]) if len(bbox) > 4 else self.score
        self.cls = int(bbox[5]) if len(bbox) > 5 else self.cls
        self.idx = int(bbox[6]) if len(bbox) > 6 else self.idx
        self.history_scores.append(self.score)
        self.history_classes.append(self.cls)
        self.history_indices.append(self.idx)

    # ========================================================================
    # freeze / unfreeze — 原版 OC-SORT 在线平滑
    # ========================================================================

    def _freeze_kf(self) -> None:
        self._frozen_state = {
            'x': self.kf.x.copy(),
            'P': self.kf.P.copy(),
            'K': self.kf.K.copy(),
            '_history_obs_z': list(self._history_obs_z),
        }

    def _unfreeze_kf(self) -> None:
        if self._frozen_state is None:
            self._observed = True
            return

        new_history = list(self._history_obs_z)
        fs = self._frozen_state
        self.kf.x = fs['x'].copy()
        self.kf.P = fs['P'].copy()
        self.kf.K = fs['K'].copy()
        self._frozen_state = None

        self._history_obs_z = list(fs['_history_obs_z'])
        self._history_obs_z = self._history_obs_z[:-1]

        non_none_indices = [
            i for i, z in enumerate(new_history) if z is not None
        ]
        if len(non_none_indices) < 2:
            self._observed = True
            return

        i1, i2 = non_none_indices[-2], non_none_indices[-1]
        gap = i2 - i1
        if gap <= 1:
            self._observed = True
            return

        # 线性插值 cx,cy，s/r 从当前 Kalman 状态取
        x1, y1 = new_history[i1].flatten()
        x2, y2 = new_history[i2].flatten()
        dx = (x2 - x1) / gap
        dy = (y2 - y1) / gap

        for j in range(1, gap):
            x = x1 + j * dx
            y = y1 + j * dy
            # _history_obs_z 保持 2D 格式 ([cx,cy])，与 update() 一致
            # Kalman 更新需要用 4D 观测 [x,y,s,r]
            z_2d = np.array([[x], [y]], dtype=np.float64)
            s_val = float(self.kf.x[2].item())
            r_val = float(self.kf.x[3].item())
            z_4d = np.array([[x], [y], [s_val], [r_val]], dtype=np.float64)
            self._history_obs_z.append(z_2d)
            self.kf.update(z_4d)
            self.kf.predict()

        self._history_obs_z.append(new_history[i2])
        self._observed = True

    def predict(self) -> np.ndarray:
        # 原版 OC-SORT: 若 (vs + s) <= 0，将 vs 置零防止面积坍缩
        if (self.kf.x[6].item() + self.kf.x[2].item()) <= 0:
            self.kf.x[6] *= 0.0

        self.kf.predict()
        self.age += 1

        if self.time_since_update > 0:
            self.hit_streak = 0
        self.time_since_update += 1

        return convert_x_to_bbox(self.kf.x)

    def get_state(self) -> np.ndarray:
        return convert_x_to_bbox(self.kf.x)


# 导出别名
_KalmanBoxTracker = KalmanBoxTracker


# ============================================================================
# 关联匹配函数 — 源自原版 OC-SORT association.py (Stage 1 仅 VDC+DIoU)
# ============================================================================

def diou_batch(bboxes1: np.ndarray, bboxes2: np.ndarray) -> np.ndarray:
    """Compute DIoU between two sets of bboxes in [x1,y1,x2,y2] form.

    DIoU = IoU - center_distance² / enclosing_diag², rescaled to (0,1).
    Ref: https://arxiv.org/abs/1911.08287
    """
    bboxes2 = np.expand_dims(bboxes2, 0)
    bboxes1 = np.expand_dims(bboxes1, 1)

    xx1 = np.maximum(bboxes1[..., 0], bboxes2[..., 0])
    yy1 = np.maximum(bboxes1[..., 1], bboxes2[..., 1])
    xx2 = np.minimum(bboxes1[..., 2], bboxes2[..., 2])
    yy2 = np.minimum(bboxes1[..., 3], bboxes2[..., 3])
    w = np.maximum(0.0, xx2 - xx1)
    h = np.maximum(0.0, yy2 - yy1)
    wh = w * h
    area1 = (bboxes1[..., 2] - bboxes1[..., 0]) * (bboxes1[..., 3] - bboxes1[..., 1])
    area2 = (bboxes2[..., 2] - bboxes2[..., 0]) * (bboxes2[..., 3] - bboxes2[..., 1])
    union = area1 + area2 - wh
    iou = wh / union

    centerx1 = (bboxes1[..., 0] + bboxes1[..., 2]) / 2.0
    centery1 = (bboxes1[..., 1] + bboxes1[..., 3]) / 2.0
    centerx2 = (bboxes2[..., 0] + bboxes2[..., 2]) / 2.0
    centery2 = (bboxes2[..., 1] + bboxes2[..., 3]) / 2.0
    inner_diag = (centerx1 - centerx2) ** 2 + (centery1 - centery2) ** 2

    xxc1 = np.minimum(bboxes1[..., 0], bboxes2[..., 0])
    yyc1 = np.minimum(bboxes1[..., 1], bboxes2[..., 1])
    xxc2 = np.maximum(bboxes1[..., 2], bboxes2[..., 2])
    yyc2 = np.maximum(bboxes1[..., 3], bboxes2[..., 3])
    outer_diag = (xxc2 - xxc1) ** 2 + (yyc2 - yyc1) ** 2

    diou = iou - inner_diag / (outer_diag + 1e-6)
    return (diou + 1.0) / 2.0


def speed_direction_batch(
    dets: np.ndarray, tracks: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Batch speed direction: dets (N,4) vs tracks (M,5) → (dy, dx) of shape (M,N)."""
    tracks = tracks[..., np.newaxis]
    cx1 = (dets[:, 0] + dets[:, 2]) / 2.0
    cy1 = (dets[:, 1] + dets[:, 3]) / 2.0
    cx2 = (tracks[:, 0, :] + tracks[:, 2, :]) / 2.0
    cy2 = (tracks[:, 1, :] + tracks[:, 3, :]) / 2.0
    dx = cx1 - cx2
    dy = cy1 - cy2
    norm = np.sqrt(dx ** 2 + dy ** 2) + 1e-6
    dx = dx / norm
    dy = dy / norm
    return dy, dx


def linear_assignment(cost_matrix: np.ndarray) -> np.ndarray:
    """Hungarian algorithm on cost_matrix; prefers `lap` if available."""
    try:
        import lap  # type: ignore
        _, x, y = lap.lapjv(cost_matrix, extend_cost=True)
        return np.array([[y[i], i] for i in x if i >= 0])
    except ImportError:
        from scipy.optimize import linear_sum_assignment
        x, y = linear_sum_assignment(cost_matrix)
        return np.array(list(zip(x, y)))


def associate(
    detections: np.ndarray,
    trackers: np.ndarray,
    iou_threshold: float,
    velocities: np.ndarray,
    previous_obs: np.ndarray,
    vdc_weight: float,
    vdc_disable_diou_thresh: float = 0.8,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Stage 1: VDC + DIoU joint association."""
    if len(trackers) == 0:
        return (
            np.empty((0, 2), dtype=int),
            np.arange(len(detections)),
            np.empty((0, 5), dtype=int),
        )

    Y, X = speed_direction_batch(detections, previous_obs)
    inertia_Y, inertia_X = velocities[:, 0], velocities[:, 1]
    inertia_Y = inertia_Y[:, np.newaxis]
    inertia_X = inertia_X[:, np.newaxis]
    diff_angle_cos = inertia_X * X + inertia_Y * Y
    diff_angle_cos = np.clip(diff_angle_cos, a_min=-1, a_max=1)
    diff_angle = np.arccos(diff_angle_cos)
    diff_angle = (np.pi / 2.0 - np.abs(diff_angle)) / np.pi

    valid_mask = np.ones(previous_obs.shape[0])
    valid_mask[previous_obs[:, 4] < 0] = 0

    diou_matrix = diou_batch(detections, trackers)
    scores = detections[:, -1][:, np.newaxis]
    valid_mask = valid_mask[:, np.newaxis]

    angle_diff_cost = (valid_mask * diff_angle) * vdc_weight
    angle_diff_cost = angle_diff_cost.T * scores

    # 如果 DIoU 已经足够高（几何上高度重合），禁用 VDC，避免方向
    # 噪声干扰到本来就很明确的匹配
    angle_diff_cost[diou_matrix > vdc_disable_diou_thresh] = 0

    if min(diou_matrix.shape) > 0:
        a = (diou_matrix > iou_threshold).astype(np.int32)
        if a.sum(1).max() == 1 and a.sum(0).max() == 1:
            matched_indices = np.stack(np.where(a), axis=1)
        else:
            matched_indices = linear_assignment(-(diou_matrix + angle_diff_cost))
    else:
        matched_indices = np.empty(shape=(0, 2))

    if matched_indices.shape[0] > 0:
        unmatched_detections = np.setdiff1d(
            np.arange(len(detections)), matched_indices[:, 0]
        )
        unmatched_trackers = np.setdiff1d(
            np.arange(len(trackers)), matched_indices[:, 1]
        )
        diou_vals = diou_matrix[matched_indices[:, 0], matched_indices[:, 1]]
        low_diou_mask = diou_vals < iou_threshold
        unmatched_detections = np.concatenate(
            [unmatched_detections, matched_indices[low_diou_mask, 0]]
        )
        unmatched_trackers = np.concatenate(
            [unmatched_trackers, matched_indices[low_diou_mask, 1]]
        )
        matches = matched_indices[~low_diou_mask]
    else:
        unmatched_detections = np.arange(len(detections))
        unmatched_trackers = np.arange(len(trackers))
        matches = np.empty((0, 2), dtype=int)

    return matches, unmatched_detections.astype(int), unmatched_trackers.astype(int)


def _size_increase_gate(
    matched_indices: np.ndarray,
    det_boxes: np.ndarray,
    trk_last_max_sides: np.ndarray,
    max_size_increase_ratio: float = 0.15,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """尺寸变大门控：候选框 max(w,h) 不应明显大于轨迹最后一帧的 max(w,h)。

    过滤候选框 max(w,h) > trk_last_max * (1 + ratio) 的匹配。
    trk_last_max == 0 表示新轨迹无有效历史，不设限。
    返回 (good_matches, rejected_det_indices, rejected_trk_indices)。
    """
    if matched_indices.shape[0] == 0 or max_size_increase_ratio < 0:
        return matched_indices, np.array([], dtype=int), np.array([], dtype=int)

    det_idx = matched_indices[:, 0]
    trk_idx = matched_indices[:, 1]

    det_w = det_boxes[det_idx, 2] - det_boxes[det_idx, 0]
    det_h = det_boxes[det_idx, 3] - det_boxes[det_idx, 1]
    det_max_side = np.maximum(det_w, det_h)

    trk_last_max = np.asarray(trk_last_max_sides, dtype=np.float64)[trk_idx]
    threshold = trk_last_max * (1.0 + max_size_increase_ratio)

    # trk_last_max == 0 表示轨迹无历史，通过所有匹配
    ok = (trk_last_max == 0.0) | (det_max_side <= threshold)
    return matched_indices[ok], matched_indices[~ok, 0], matched_indices[~ok, 1]


def _size_decrease_gate(
    matched_indices: np.ndarray,
    det_boxes: np.ndarray,
    trk_last_max_sides: np.ndarray,
    max_size_decrease_ratio: float = 0.15,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """尺寸变小门控：候选框 max(w,h) 不应明显小于轨迹最后一帧的 max(w,h)。

    过滤候选框 max(w,h) < trk_last_max * (1 - ratio) 的匹配。
    trk_last_max == 0 表示新轨迹无有效历史，不设限。
    返回 (good_matches, rejected_det_indices, rejected_trk_indices)。
    """
    if matched_indices.shape[0] == 0 or max_size_decrease_ratio < 0:
        return matched_indices, np.array([], dtype=int), np.array([], dtype=int)

    det_idx = matched_indices[:, 0]
    trk_idx = matched_indices[:, 1]

    det_w = det_boxes[det_idx, 2] - det_boxes[det_idx, 0]
    det_h = det_boxes[det_idx, 3] - det_boxes[det_idx, 1]
    det_max_side = np.maximum(det_w, det_h)

    trk_last_max = np.asarray(trk_last_max_sides, dtype=np.float64)[trk_idx]
    threshold = trk_last_max * (1.0 - max_size_decrease_ratio)

    # trk_last_max == 0 表示轨迹无历史，通过所有匹配
    ok = (trk_last_max == 0.0) | (det_max_side >= threshold)
    return matched_indices[ok], matched_indices[~ok, 0], matched_indices[~ok, 1]


# ============================================================================
# 精简 OCSort — 仅 Stage 1 (VDC + DIoU)
# ============================================================================

class OCSort:
    def __init__(
        self,
        det_thresh: float,
        max_age: int = 30,
        min_hits: int = 3,
        iou_threshold: float = 0.3,
        delta_dist_pct: float = 0.5,
        inertia: float = 0.2,
        vdc_disable_diou_thresh: float = 0.5,
        max_size_increase_ratio: float = 0.15,
        max_size_decrease_ratio: float = 0.15,
    ):
        """delta_dist_pct: 在历史中找参考观测时，要求中心距离 > pct*框尺寸。
        vdc_disable_diou_thresh: DIoU 高于此值时禁用 VDC（几何上已足够匹配）。
        max_size_increase_ratio: 尺寸变大门控上限，候选框max(w,h) ≤ 轨迹最后一帧 × (1+ratio)。
        max_size_decrease_ratio: 尺寸变小门控下限，候选框max(w,h) ≥ 轨迹最后一帧 × (1-ratio)。"""
        self.max_age = int(max_age)
        self.min_hits = int(min_hits)
        self.iou_threshold = float(iou_threshold)
        self.trackers: list[KalmanBoxTracker] = []
        self.frame_count = 0
        self.det_thresh = float(det_thresh)
        self.delta_dist_pct = float(delta_dist_pct)
        self.inertia = float(inertia)
        self.vdc_disable_diou_thresh = float(vdc_disable_diou_thresh)
        self.max_size_increase_ratio = float(max_size_increase_ratio)
        self.max_size_decrease_ratio = float(max_size_decrease_ratio)
        self._next_track_id = 0

    @staticmethod
    def _to_obb_track_row(
        xyxy: np.ndarray,
        track_id: int,
        score: float,
        cls_id: int,
        idx: int,
        frame_offset: int = 0,
    ) -> np.ndarray:
        """Convert xyxy bbox → track.py 需要的 10 列格式."""
        x1, y1, x2, y2 = xyxy
        w = x2 - x1
        h = y2 - y1
        cx = x1 + w / 2.0
        cy = y1 + h / 2.0
        return np.array(
            [cx, cy, w, h, 0.0, track_id, score, cls_id, idx, frame_offset],
            dtype=np.float32,
        )

    def update(self, dets_all: np.ndarray | None) -> np.ndarray:
        """Stage-1-only update.

        Args:
            dets_all: (N,7) [x1,y1,x2,y2,score,cls,idx]
        Returns:
            (M,10) [cx,cy,w,h,r,track_id,score,cls,idx,frame_offset]
        """
        if dets_all is None:
            dets_all = np.empty((0, 7), dtype=np.float64)
        if len(dets_all) == 0:
            dets_all = np.empty((0, 7), dtype=np.float64)
        else:
            dets_all = np.asarray(dets_all, dtype=np.float64)

        self.frame_count += 1

        scores = dets_all[:, 4] if len(dets_all) else np.empty((0,), dtype=np.float64)
        remain_inds = scores > self.det_thresh
        dets = dets_all[remain_inds]

        # ====== predict ======
        trks = np.zeros((len(self.trackers), 5), dtype=np.float64)
        to_del = []
        for t, trk in enumerate(trks):
            pos = self.trackers[t].predict()[0]
            trk[:] = [pos[0], pos[1], pos[2], pos[3], 0.0]
            if np.any(np.isnan(pos)):
                to_del.append(t)
        trks = np.ma.compress_rows(np.ma.masked_invalid(trks))
        for t in reversed(to_del):
            self.trackers.pop(t)

        # ====== 轨迹速度和 VDC 参考观测 ======
        _sentinel = np.array([-1.0, -1.0, -1.0, -1.0, -1.0], dtype=np.float64)
        _zero_vel = np.array((0.0, 0.0), dtype=np.float64)
        velocities = np.array(
            [
                trk.velocity if trk.velocity is not None else _zero_vel
                for trk in self.trackers
            ]
        )
        ref_next_obs_list = np.array(
            [
                trk._ref_next_obs if trk._ref_next_obs is not None else _sentinel
                for trk in self.trackers
            ]
        )

        # ====== Stage 1: VDC + DIoU ======
        if len(dets) > 0 and len(trks) > 0:
            matched, unmatched_dets, unmatched_trks = associate(
                dets[:, :5],
                trks,
                self.iou_threshold,
                velocities,
                ref_next_obs_list,
                self.inertia,
                self.vdc_disable_diou_thresh,
            )
        else:
            matched = np.empty((0, 2), dtype=int)
            unmatched_dets = np.arange(len(dets))
            unmatched_trks = np.arange(len(self.trackers))

        # ====== 尺寸门控：基于轨迹最后一帧尺寸过滤不合理匹配 ======
        if matched.shape[0] > 0 and (self.max_size_increase_ratio > 0 or self.max_size_decrease_ratio > 0):
            trk_last_max_sides = np.array([
                max(trk._last_w, trk._last_h)
                if trk.last_observation.sum() >= 0 else 0.0
                for trk in self.trackers
            ], dtype=np.float64)

            if self.max_size_increase_ratio > 0:
                matched, rej_dets, rej_trks = _size_increase_gate(
                    matched, dets[:, :5], trk_last_max_sides,
                    max_size_increase_ratio=self.max_size_increase_ratio,
                )
                if rej_dets.size:
                    unmatched_dets = np.concatenate([unmatched_dets, rej_dets])
                if rej_trks.size:
                    unmatched_trks = np.concatenate([unmatched_trks, rej_trks])

            if matched.shape[0] > 0 and self.max_size_decrease_ratio > 0:
                matched, rej_dets, rej_trks = _size_decrease_gate(
                    matched, dets[:, :5], trk_last_max_sides,
                    max_size_decrease_ratio=self.max_size_decrease_ratio,
                )
                if rej_dets.size:
                    unmatched_dets = np.concatenate([unmatched_dets, rej_dets])
                if rej_trks.size:
                    unmatched_trks = np.concatenate([unmatched_trks, rej_trks])

        # ====== 更新 ======
        for m in matched:
            det_idx, trk_idx = m[0], m[1]
            self.trackers[trk_idx].update(dets[det_idx])

        for trk_idx in unmatched_trks:
            self.trackers[trk_idx].update(None)

        for det_idx in unmatched_dets:
            self.trackers.append(
                KalmanBoxTracker(
                    dets[det_idx],
                    delta_dist_pct=self.delta_dist_pct,
                    track_id=self._next_track_id,
                )
            )
            self._next_track_id += 1

        # ====== 输出 ======
        ret = []
        i = len(self.trackers)
        for trk in reversed(self.trackers):
            if trk.last_observation.sum() >= 0:
                d = trk.last_observation[:4]
            else:
                d = trk.get_state()[0]

            if (trk.time_since_update < 1) and (
                trk.hit_streak >= self.min_hits or self.frame_count <= self.min_hits
            ):
                ret.append(
                    self._to_obb_track_row(
                        d, trk.id + 1, trk.score, trk.cls, trk.idx, frame_offset=0
                    )
                )

                if trk.hit_streak == self.min_hits:
                    pad_cnt = min(
                        self.min_hits - 1, len(trk.history_observations) - 1
                    )
                    for prev_i in range(pad_cnt):
                        hist_pos = -(prev_i + 2)
                        prev_obs = trk.history_observations[hist_pos]
                        prev_score = trk.history_scores[hist_pos]
                        prev_cls = trk.history_classes[hist_pos]
                        prev_idx = trk.history_indices[hist_pos]
                        ret.append(
                            self._to_obb_track_row(
                                prev_obs[:4],
                                trk.id + 1,
                                prev_score,
                                prev_cls,
                                prev_idx,
                                frame_offset=-(prev_i + 1),
                            )
                        )

            i -= 1
            if trk.time_since_update > self.max_age:
                self.trackers.pop(i)

        if len(ret) > 0:
            return np.asarray(ret, dtype=np.float32)
        return np.empty((0, 10), dtype=np.float32)
