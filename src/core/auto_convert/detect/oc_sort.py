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
    dy = cy2 - cy1
    dx = cx2 - cx1
    speed = np.array([dy, dx], dtype=np.float64)
    norm = np.sqrt(dy ** 2 + dx ** 2) + 1e-6
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


def _convert_wh_to_z(cx: float, cy: float, w: float, h: float) -> np.ndarray:
    """(cx,cy,w,h) → [x,y,s,r] as (4,1); avoids re-extracting w/h from bbox."""
    s = w * h
    r = w / float(h + 1e-6)
    return np.array([cx, cy, s, r], dtype=np.float64).reshape((4, 1))


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

        self.kf.x[:4] = _convert_wh_to_z(cx, cy, w, h)

        # 框尺寸缓存（从检测框读取，用于 _find_ref_obs 阈值）
        self._last_w = max(w, 1.0)
        self._last_h = max(h, 1.0)

        self.time_since_update = 0
        self.time_since_output = 0
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

        # --- freeze/unfreeze 状态机（原版 OC-SORT 在线平滑） ---
        self._history_obs_z: list[np.ndarray | None] = [
            np.array([[cx], [cy]], dtype=np.float64)
        ]  # z-format 观测历史（含 None 表示缺失帧）
        self._observed: bool = True
        self._frozen_state: dict | None = None

        self.score = float(bbox[4]) if len(bbox) > 4 else 0.0
        self.cls = int(bbox[5]) if len(bbox) > 5 else 0
        self.idx = int(bbox[6]) if len(bbox) > 6 else -1
        self.history_scores: list[float] = []
        self.history_classes: list[int] = []
        self.history_indices: list[int] = []
        self.history_frame_numbers: list[int] = []

    def _find_ref_obs(self, current_obs: np.ndarray) -> np.ndarray | None:
        """在轨迹历史中回溯，找到第一个与最新框中心距离 > delta_dist_pct*框尺寸 的观测 H。
        VDC 两向量共享该参考观测作为起点：
          轨迹速度方向 = H → current_obs
          VDC 方向     = H → 候选框
        找不到则回退到最旧观测；无历史则返回 None."""
        if len(self.history_observations) == 0:
            return None

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
                return h

        # 回退：所有历史都太近，用最旧观测（至少比单帧稳定）
        return self.history_observations[0]

    def update(self, bbox: np.ndarray | None, frame_number: int = 0) -> None:
        self.frame_number = frame_number
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
        obs = np.array(
            [bbox[0], bbox[1], bbox[2], bbox[3], bbox[4]], dtype=np.float64
        )

        if self.last_observation.sum() >= 0:
            ref_obs = self._find_ref_obs(obs)
            self._ref_obs = ref_obs
            if ref_obs is not None:
                self.velocity = speed_direction(ref_obs, obs)

        self.last_observation = obs
        self.observations[self.age] = obs
        self.history_observations.append(obs)

        self.time_since_update = 0
        self.hit_streak += 1

        # 4 维观测更新 [x,y,s,r]
        self.kf.update(_convert_wh_to_z(cx, cy, w, h))

        self.score = float(bbox[4]) if len(bbox) > 4 else self.score
        self.cls = int(bbox[5]) if len(bbox) > 5 else self.cls
        self.idx = int(bbox[6]) if len(bbox) > 6 else self.idx
        self.history_scores.append(self.score)
        self.history_classes.append(self.cls)
        self.history_indices.append(self.idx)
        self.history_frame_numbers.append(self.frame_number)

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
            self.hit_streak = max(0, self.hit_streak - 2)
        self.time_since_update += 1
        self.time_since_output += 1

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
    # Precompute per-box area and center to avoid redundant broadcast computation
    area1_pre = (bboxes1[:, 2] - bboxes1[:, 0]) * (bboxes1[:, 3] - bboxes1[:, 1])
    area2_pre = (bboxes2[:, 2] - bboxes2[:, 0]) * (bboxes2[:, 3] - bboxes2[:, 1])
    cx1_pre = (bboxes1[:, 0] + bboxes1[:, 2]) / 2.0
    cy1_pre = (bboxes1[:, 1] + bboxes1[:, 3]) / 2.0
    cx2_pre = (bboxes2[:, 0] + bboxes2[:, 2]) / 2.0
    cy2_pre = (bboxes2[:, 1] + bboxes2[:, 3]) / 2.0

    bboxes2 = np.expand_dims(bboxes2, 0)
    bboxes1 = np.expand_dims(bboxes1, 1)

    xx1 = np.maximum(bboxes1[..., 0], bboxes2[..., 0])
    yy1 = np.maximum(bboxes1[..., 1], bboxes2[..., 1])
    xx2 = np.minimum(bboxes1[..., 2], bboxes2[..., 2])
    yy2 = np.minimum(bboxes1[..., 3], bboxes2[..., 3])
    w = np.maximum(0.0, xx2 - xx1)
    h = np.maximum(0.0, yy2 - yy1)
    wh = w * h
    union = area1_pre[:, np.newaxis] + area2_pre[np.newaxis, :] - wh
    iou = wh / union

    inner_diag = (cx1_pre[:, np.newaxis] - cx2_pre[np.newaxis, :]) ** 2 + (cy1_pre[:, np.newaxis] - cy2_pre[np.newaxis, :]) ** 2

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
    diou_matrix: np.ndarray,
    validity_sub: np.ndarray,
    velocities: np.ndarray,
    previous_obs: np.ndarray,
    vdc_weight: float,
    debug_enabled: bool = False,
    debug_frame_number: int = 0,
    debug_track_ids: list[int] | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Stage 1: VDC + DIoU joint association on pre-filtered subset.

    diou_matrix and validity_sub are (N,M) for the subset.
    Invalid pairs are penalized in cost so Hungarian avoids them.
    All output pairs are accepted as-is (no DIoU threshold post-filtering).
    """
    LARGE_PENALTY = 1e6

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

    scores = detections[:, -1][:, np.newaxis]
    valid_mask = valid_mask[:, np.newaxis]

    angle_diff_cost = (valid_mask * diff_angle) * vdc_weight
    angle_diff_cost = angle_diff_cost.T * scores

    # ====== debug: 打印每条轨迹对每个候选框的 DIoU 和 VDC 代价 ======
    if debug_enabled and debug_track_ids is not None and len(detections) > 0:
        num_trks = len(debug_track_ids)
        num_dets = len(detections)
        for j in range(num_trks):
            for i in range(num_dets):
                print(
                    f"[OC-SORT DEBUG] frame={debug_frame_number} | "
                    f"track_id={debug_track_ids[j]} det#{i} | "
                    f"DIoU={diou_matrix[i, j]:.4f} | "
                    f"VDC_cost={angle_diff_cost[i, j]:.4f}"
                )

    # Cost = -(DIoU + VDC), penalize invalid pairs heavily
    cost = -(diou_matrix + angle_diff_cost)
    cost[~validity_sub] += LARGE_PENALTY

    if min(diou_matrix.shape) > 0:
        matched_indices = linear_assignment(cost)
    else:
        matched_indices = np.empty(shape=(0, 2))

    if matched_indices.shape[0] > 0:
        unmatched_detections = np.setdiff1d(
            np.arange(len(detections)), matched_indices[:, 0]
        )
        unmatched_trackers = np.setdiff1d(
            np.arange(len(trackers)), matched_indices[:, 1]
        )
        matches = matched_indices
    else:
        unmatched_detections = np.arange(len(detections))
        unmatched_trackers = np.arange(len(trackers))
        matches = np.empty((0, 2), dtype=int)

    return matches, unmatched_detections.astype(int), unmatched_trackers.astype(int)


def _build_size_gate_mask(
    det_max_side: np.ndarray,
    trk_last_max_sides: np.ndarray,
    max_size_increase_ratio: float = 0.15,
    max_size_decrease_ratio: float = 0.15,
) -> np.ndarray:
    """Build (N,M) bool mask: True = size compatible between det_i and trk_j.

    trk_last_max == 0 (new track, no history) → always compatible.
    """
    N = len(det_max_side)
    M = len(trk_last_max_sides)
    if N == 0 or M == 0:
        return np.empty((N, M), dtype=bool)

    det_max = det_max_side[:, None]            # (N, 1)
    trk_max = trk_last_max_sides[None, :]      # (1, M)

    ok = np.ones((N, M), dtype=bool)

    if max_size_increase_ratio > 0:
        inc_thresh = trk_max * (1.0 + max_size_increase_ratio)
        ok &= (trk_max == 0.0) | (det_max <= inc_thresh)

    if max_size_decrease_ratio > 0:
        dec_thresh = trk_max * (1.0 - max_size_decrease_ratio)
        ok &= (trk_max == 0.0) | (det_max >= dec_thresh)

    return ok


def _pre_filter(
    validity_mask: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Split det/trk indices by whether they have ≥1 legal connection.

    Returns: (valid_dets, valid_trks, orphan_dets, orphan_trks)
    """
    has_det = validity_mask.any(axis=1)
    has_trk = validity_mask.any(axis=0)
    return (
        np.where(has_det)[0],
        np.where(has_trk)[0],
        np.where(~has_det)[0],
        np.where(~has_trk)[0],
    )


def _post_check(
    matched_indices: np.ndarray,
    validity_sub: np.ndarray,
    valid_det_map: np.ndarray,
    valid_trk_map: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Check Hungarian output pairs against validity mask.

    Returns: (good_matches, bad_det_indices, bad_trk_indices)
    All returned indices are mapped back to original (full) indexing.
    """
    if matched_indices.shape[0] == 0:
        return (
            np.empty((0, 2), dtype=int),
            np.array([], dtype=int),
            np.array([], dtype=int),
        )

    det_pos = matched_indices[:, 0]
    trk_pos = matched_indices[:, 1]
    valid = validity_sub[det_pos, trk_pos]

    good = (
        np.column_stack([
            valid_det_map[det_pos[valid]],
            valid_trk_map[trk_pos[valid]],
        ]).astype(int)
        if valid.any()
        else np.empty((0, 2), dtype=int)
    )

    bad_dets = valid_det_map[det_pos[~valid]].astype(int)
    bad_trks = valid_trk_map[trk_pos[~valid]].astype(int)

    return good, bad_dets, bad_trks


# ============================================================================
# 精简 OCSort — 仅 Stage 1 (VDC + DIoU)
# ============================================================================

class OCSort:
    def __init__(
        self,
        det_thresh: float,
        max_age: int = 30,
        min_hits: int = 3,
        s1_diou_thresh: float = 0.3,
        delta_dist_pct: float = 0.5,
        inertia: float = 0.2,
        max_size_increase_ratio: float = 0.15,
        max_size_decrease_ratio: float = 0.15,
        s3_diou_thresh: float = 0.3,
        debug: bool = False,
    ):
        """delta_dist_pct: 在历史中找参考观测时，要求中心距离 > pct*框尺寸。
        max_size_increase_ratio: 尺寸变大门控上限，候选框max(w,h) ≤ 轨迹最后一帧 × (1+ratio)。
        max_size_decrease_ratio: 尺寸变小门控下限，候选框max(w,h) ≥ 轨迹最后一帧 × (1-ratio)。
        s3_diou_thresh: Stage 3 回收匹配的 DIoU 阈值，用于剩余检测与轨迹最后观测的纯 DIoU 匹配。"""
        self.max_age = int(max_age)
        self.min_hits = int(min_hits)
        self.s1_diou_thresh = float(s1_diou_thresh)
        self.trackers: list[KalmanBoxTracker] = []
        self.frame_count = 0
        self.det_thresh = float(det_thresh)
        self.delta_dist_pct = float(delta_dist_pct)
        self.inertia = float(inertia)
        self.max_size_increase_ratio = float(max_size_increase_ratio)
        self.max_size_decrease_ratio = float(max_size_decrease_ratio)
        self.s3_diou_thresh = float(s3_diou_thresh)
        self.debug = bool(debug)
        self._next_track_id = 0

    @staticmethod
    def _to_obb_track_row(
        xyxy: np.ndarray,
        track_id: int,
        score: float,
        cls_id: int,
        det_frame: int,
        det_idx: int,
    ) -> np.ndarray:
        """Convert xyxy bbox → track.py 需要的 10 列格式."""
        x1, y1, x2, y2 = xyxy
        w = x2 - x1
        h = y2 - y1
        cx = x1 + w / 2.0
        cy = y1 + h / 2.0
        return np.array(
            [cx, cy, w, h, 0.0, track_id, score, cls_id, det_frame, det_idx],
            dtype=np.float32,
        )

    def update(self, dets_all: np.ndarray | None, frame_number: int = 0) -> np.ndarray:
        """Stage-1 VDC+DIoU + Stage-3 DIoU recovery.

        Args:
            dets_all: (N,7) [x1,y1,x2,y2,score,cls,idx]
            frame_number: current video frame number
        Returns:
            (M,10) [cx,cy,w,h,r,track_id,score,cls_id,det_frame,det_idx]
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
        det_max_side = np.maximum(
            dets[:, 2] - dets[:, 0],
            dets[:, 3] - dets[:, 1],
        ) if len(dets) > 0 else np.empty((0,), dtype=np.float64)

        # ====== predict ======
        trks = np.zeros((len(self.trackers), 5), dtype=np.float64)
        to_del = []
        for t, trk in enumerate(trks):
            pos = self.trackers[t].predict()[0]
            trk[:] = [pos[0], pos[1], pos[2], pos[3], 0.0]
            if np.any(np.isnan(pos)):
                to_del.append(t)
        trks = trks[~np.any(np.isnan(trks), axis=1)]
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
        ref_obs_list = np.array(
            [
                trk._ref_obs if trk._ref_obs is not None else _sentinel
                for trk in self.trackers
            ]
        )

        # ====== debug: 打印轨迹状态 ======
        debug_track_ids = None
        if self.debug and len(dets) > 0:
            debug_track_ids = [trk.id + 1 for trk in self.trackers]
            for trk in self.trackers:
                print(
                    f"[OC-SORT DEBUG] frame={frame_number} | "
                    f"track_id={trk.id + 1} | "
                    f"hit_streak={trk.hit_streak} | "
                    f"time_since_update={trk.time_since_update} | "
                    f"time_since_output={trk.time_since_output} | "
                    f"age={trk.age} | "
                    f"score={trk.score:.4f}"
                )

        # ====== 轨迹最后一帧尺寸（提前计算，Stage 1 / Stage 3 共用） ======
        if self.trackers:
            trk_last_max_sides = np.array([
                max(trk._last_w, trk._last_h)
                if trk.last_observation.sum() >= 0 else 0.0
                for trk in self.trackers
            ], dtype=np.float64)
        else:
            trk_last_max_sides = np.empty((0,), dtype=np.float64)

        # ====== Stage 1: VDC + DIoU（前置过滤 + 惩罚成本 + 后置兜底） ======
        if len(dets) > 0 and len(trks) > 0:
            full_diou = diou_batch(dets[:, :5], trks)
            size_mask = _build_size_gate_mask(
                det_max_side, trk_last_max_sides,
                self.max_size_increase_ratio, self.max_size_decrease_ratio,
            )
            validity = (full_diou >= self.s1_diou_thresh) & size_mask

            valid_dets, valid_trks, orphan_dets, orphan_trks = _pre_filter(validity)

            if len(valid_dets) > 0 and len(valid_trks) > 0:
                diou_sub = full_diou[valid_dets][:, valid_trks]
                validity_sub = validity[valid_dets][:, valid_trks]

                dets_sub = dets[valid_dets, :5]
                trks_sub = trks[valid_trks]
                vel_sub = velocities[valid_trks]
                ref_sub = ref_obs_list[valid_trks]

                debug_ids_sub = None
                if self.debug and debug_track_ids is not None:
                    debug_ids_sub = [debug_track_ids[i] for i in valid_trks]

                matched_sub, unmapped_dets_sub, unmapped_trks_sub = associate(
                    dets_sub, trks_sub,
                    diou_sub, validity_sub,
                    vel_sub, ref_sub, self.inertia,
                    debug_enabled=self.debug,
                    debug_frame_number=frame_number,
                    debug_track_ids=debug_ids_sub,
                )

                good, bad_dets, bad_trks = _post_check(
                    matched_sub, validity_sub, valid_dets, valid_trks,
                )
                unmapped_dets = valid_dets[unmapped_dets_sub]
                unmapped_trks = valid_trks[unmapped_trks_sub]

                matched = good
                unmatched_dets = np.concatenate([
                    orphan_dets, unmapped_dets, bad_dets,
                ]).astype(int)
                unmatched_trks = np.concatenate([
                    orphan_trks, unmapped_trks, bad_trks,
                ]).astype(int)
            else:
                matched = np.empty((0, 2), dtype=int)
                unmatched_dets = np.arange(len(dets))
                unmatched_trks = np.arange(len(self.trackers))
        else:
            matched = np.empty((0, 2), dtype=int)
            unmatched_dets = np.arange(len(dets))
            unmatched_trks = np.arange(len(self.trackers))

        # ====== Stage 3: DIoU 回收（前置过滤 + 惩罚成本 + 后置兜底） ======
        if unmatched_dets.size > 0 and unmatched_trks.size > 0:
            left_dets = dets[unmatched_dets, :5]
            last_obs_list = np.array(
                [trk.last_observation for trk in self.trackers], dtype=np.float64
            )
            left_trks = last_obs_list[unmatched_trks]
            left_det_max_side = det_max_side[unmatched_dets]
            left_trk_max_sides = trk_last_max_sides[unmatched_trks]

            diou_left = diou_batch(left_dets, left_trks)
            size_mask_left = _build_size_gate_mask(
                left_det_max_side, left_trk_max_sides,
                self.max_size_increase_ratio, self.max_size_decrease_ratio,
            )
            validity_left = (diou_left >= self.s3_diou_thresh) & size_mask_left

            s3_valid_dets, s3_valid_trks, _, _ = _pre_filter(validity_left)

            if len(s3_valid_dets) > 0 and len(s3_valid_trks) > 0:
                diou_sub = diou_left[s3_valid_dets][:, s3_valid_trks]
                validity_sub = validity_left[s3_valid_dets][:, s3_valid_trks]

                cost = -diou_sub
                cost[~validity_sub] += 1e6
                raw_indices = linear_assignment(cost)

                good, bad_dets, bad_trks = _post_check(
                    raw_indices, validity_sub,
                    s3_valid_dets, s3_valid_trks,
                )

                # good pairs → update tracker with detection
                to_remove_det = []
                to_remove_trk = []
                for det_pos, trk_pos in good:
                    det_idx = unmatched_dets[det_pos]
                    trk_idx = unmatched_trks[trk_pos]
                    self.trackers[trk_idx].update(dets[det_idx], frame_number)
                    to_remove_det.append(det_idx)
                    to_remove_trk.append(trk_idx)

                if to_remove_det:
                    unmatched_dets = np.setdiff1d(
                        unmatched_dets, np.array(to_remove_det, dtype=int)
                    )
                if to_remove_trk:
                    unmatched_trks = np.setdiff1d(
                        unmatched_trks, np.array(to_remove_trk, dtype=int)
                    )

        # ====== 更新 ======
        for m in matched:
            det_idx, trk_idx = m[0], m[1]
            self.trackers[trk_idx].update(dets[det_idx], frame_number)

        for trk_idx in unmatched_trks:
            self.trackers[trk_idx].update(None, frame_number)

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
                        d, trk.id + 1, trk.score, trk.cls, frame_number, trk.idx
                    )
                )
                trk.time_since_output = 0

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
                        prev_frame = trk.history_frame_numbers[hist_pos]
                        ret.append(
                            self._to_obb_track_row(
                                prev_obs[:4],
                                trk.id + 1,
                                prev_score,
                                prev_cls,
                                prev_frame,
                                prev_idx,
                            )
                        )

            i -= 1
            if trk.time_since_output > self.max_age:
                self.trackers.pop(i)

        if len(ret) > 0:
            return np.asarray(ret, dtype=np.float32)
        return np.empty((0, 10), dtype=np.float32)
