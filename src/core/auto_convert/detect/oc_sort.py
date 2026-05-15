from __future__ import annotations

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


def k_previous_obs(
    observations: dict[int, np.ndarray], cur_age: int, k: int
) -> np.ndarray:
    """Return the observation from k steps ago, or the oldest if none."""
    if len(observations) == 0:
        return np.array([-1.0, -1.0, -1.0, -1.0, -1.0], dtype=np.float64)
    for i in range(k):
        dt = k - i
        if cur_age - dt in observations:
            return observations[cur_age - dt]
    max_age = max(observations.keys())
    return observations[max_age]


def speed_direction(bbox1: np.ndarray, bbox2: np.ndarray) -> np.ndarray:
    """Unit speed direction from bbox1 to bbox2, as (dy, dx)."""
    cx1 = (bbox1[0] + bbox1[2]) / 2.0
    cy1 = (bbox1[1] + bbox1[3]) / 2.0
    cx2 = (bbox2[0] + bbox2[2]) / 2.0
    cy2 = (bbox2[1] + bbox2[3]) / 2.0
    speed = np.array([cy2 - cy1, cx2 - cx1], dtype=np.float64)
    norm = np.sqrt((cy2 - cy1) ** 2 + (cx2 - cx1) ** 2) + 1e-6
    return speed / norm


# ============================================================================
# 6 维恒加速 (CA) KalmanBoxTracker6D
#
# SLIDE 音符框始终是 1:1 正方形 → s/r 无需 Kalman 估计。
# 状态: [cx,cy, vx,vy, ax,ay] — 仅位置+速度+加速度。
# w/h 直接从最近一次检测框读取，predict 时用最近尺寸构造 xyxy。
# ============================================================================

class KalmanBoxTracker6D:
    """6 维恒加速 Kalman: [cx,cy, vx,vy, ax,ay].
    观测: [cx,cy] (2 维).

    框的尺寸 w/h 直接从检测框获取，不做 Kalman 估计（SLIDE 总是 ~108×108 px）。"""

    count = 0

    # 状态转移矩阵 F (6×6, dt=1)
    _F = np.eye(6, dtype=np.float64)
    _F[0, 2] = 1.0   # cx += vx
    _F[1, 3] = 1.0   # cy += vy
    _F[0, 4] = 0.5   # cx += 0.5*ax
    _F[1, 5] = 0.5   # cy += 0.5*ay
    _F[2, 4] = 1.0   # vx += ax
    _F[3, 5] = 1.0   # vy += ay

    # 观测矩阵 H (2×6): 直读前 2 维
    _H = np.hstack([np.eye(2, dtype=np.float64), np.zeros((2, 4), dtype=np.float64)])

    def __init__(self, bbox: np.ndarray, delta_t: int = 3):
        cx, cy, w, h = convert_bbox_centre(bbox[:4])

        self.kf = KalmanFilter(dim_x=6, dim_z=2)
        self.kf.F = KalmanBoxTracker6D._F.copy()
        self.kf.H = KalmanBoxTracker6D._H.copy()

        # 观测噪声 R — 位置噪声低（检测较准）
        self.kf.R[0, 0] = 1.0
        self.kf.R[1, 1] = 1.0

        # 初始状态协方差 P — 速度/加速度从零开始，中等不确定
        self.kf.P[0, 0] = 10.0     # cx
        self.kf.P[1, 1] = 10.0     # cy
        self.kf.P[2, 2] = 1000.0   # vx 完全未知
        self.kf.P[3, 3] = 1000.0   # vy
        self.kf.P[4, 4] = 100.0    # ax 中等不确定
        self.kf.P[5, 5] = 100.0    # ay

        # 过程噪声 Q
        self.kf.Q[0, 0] = 0.01     # cx 信任模型
        self.kf.Q[1, 1] = 0.01     # cy
        self.kf.Q[2, 2] = 1.0      # vx 灵活（转弯时快速转向）
        self.kf.Q[3, 3] = 1.0      # vy
        self.kf.Q[4, 4] = 0.00001  # ax 极稳定（CA 强约束）
        self.kf.Q[5, 5] = 0.00001  # ay

        self.kf.x[0] = cx
        self.kf.x[1] = cy

        # 框尺寸（直接从检测读取，不参与 Kalman）
        self._last_w = max(w, 1.0)
        self._last_h = max(h, 1.0)

        self.time_since_update = 0
        self.id = KalmanBoxTracker6D.count
        KalmanBoxTracker6D.count += 1

        self.hit_streak = 0
        self.age = 0

        self.last_observation = np.array(
            [-1.0, -1.0, -1.0, -1.0, -1.0], dtype=np.float64
        )
        self.observations: dict[int, np.ndarray] = {}
        self.history_observations: list[np.ndarray] = []
        self.velocity: np.ndarray | None = None
        self.delta_t = delta_t

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

    def update(self, bbox: np.ndarray | None) -> None:
        # ====== 记录 z-format 观测 ======
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
            previous_box = None
            for i in range(self.delta_t):
                dt = self.delta_t - i
                if self.age - dt in self.observations:
                    previous_box = self.observations[self.age - dt]
                    break
            if previous_box is None:
                previous_box = self.last_observation
            self.velocity = speed_direction(previous_box, obs)

        self.last_observation = obs
        self.observations[self.age] = obs
        self.history_observations.append(obs)

        self.time_since_update = 0
        self.hit_streak += 1

        cx, cy = (obs[0] + obs[2]) / 2.0, (obs[1] + obs[3]) / 2.0
        self.kf.update(np.array([[cx], [cy]], dtype=np.float64))

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
            '_alpha_sq': self.kf._alpha_sq,
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
        self.kf._alpha_sq = fs['_alpha_sq']
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

        # 线性插值 cx,cy
        x1, y1 = new_history[i1].flatten()
        x2, y2 = new_history[i2].flatten()
        dx = (x2 - x1) / gap
        dy = (y2 - y1) / gap

        for j in range(1, gap):
            x = x1 + j * dx
            y = y1 + j * dy
            z_virtual = np.array([[x], [y]], dtype=np.float64)
            self._history_obs_z.append(z_virtual)
            self.kf.update(z_virtual)
            self.kf.predict()

        self._history_obs_z.append(new_history[i2])
        self._observed = True

    def predict(self) -> np.ndarray:
        self.kf.predict()
        self.age += 1

        if self.time_since_update > 0:
            self.hit_streak = 0
        self.time_since_update += 1

        cx = float(self.kf.x[0].item())
        cy = float(self.kf.x[1].item())
        w, h = self._last_w, self._last_h
        return np.array(
            [[cx - w / 2.0, cy - h / 2.0, cx + w / 2.0, cy + h / 2.0]],
            dtype=np.float64,
        )

    def get_state(self) -> np.ndarray:
        cx = float(self.kf.x[0].item())
        cy = float(self.kf.x[1].item())
        w, h = self._last_w, self._last_h
        return np.array(
            [[cx - w / 2.0, cy - h / 2.0, cx + w / 2.0, cy + h / 2.0]],
            dtype=np.float64,
        )


# 导出别名
_KalmanBoxTracker = KalmanBoxTracker6D


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
        delta_t: int = 3,
        inertia: float = 0.2,
        warmup_frames: int = 3,
    ):
        """warmup_frames: 新建轨迹前 N 帧不输出 Kalman 预测，直接用检测框位置。"""
        self.max_age = int(max_age)
        self.min_hits = int(min_hits)
        self.iou_threshold = float(iou_threshold)
        self.trackers: list[KalmanBoxTracker6D] = []
        self.frame_count = 0
        self.det_thresh = float(det_thresh)
        self.delta_t = int(delta_t)
        self.inertia = float(inertia)
        self.warmup_frames = int(warmup_frames)
        KalmanBoxTracker6D.count = 0

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

        # ====== 轨迹速度和 k 步前观测 ======
        _zero_vel = np.array((0.0, 0.0), dtype=np.float64)
        velocities = np.array(
            [
                trk.velocity if trk.velocity is not None else _zero_vel
                for trk in self.trackers
            ]
        )
        k_observations = np.array(
            [
                k_previous_obs(trk.observations, trk.age, self.delta_t)
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
                k_observations,
                self.inertia,
            )
        else:
            matched = np.empty((0, 2), dtype=int)
            unmatched_dets = np.arange(len(dets))
            unmatched_trks = np.arange(len(self.trackers))

        # ====== 更新 ======
        for m in matched:
            det_idx, trk_idx = m[0], m[1]
            self.trackers[trk_idx].update(dets[det_idx])

        for trk_idx in unmatched_trks:
            self.trackers[trk_idx].update(None)

        for det_idx in unmatched_dets:
            self.trackers.append(
                KalmanBoxTracker6D(dets[det_idx], delta_t=self.delta_t)
            )

        # ====== 输出 ======
        ret = []
        i = len(self.trackers)
        for trk in reversed(self.trackers):
            # --- 暖机期间：直接输出检测框位置，不用 Kalman 预测 ---
            if trk.hit_streak < self.warmup_frames:
                if trk.last_observation.sum() >= 0:
                    d = trk.last_observation[:4]
                else:
                    d = trk.get_state()[0]
            else:
                if trk.last_observation.sum() < 0:
                    d = trk.get_state()[0]
                else:
                    d = trk.last_observation[:4]

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
