from __future__ import annotations

import numpy as np
from filterpy.kalman import KalmanFilter

from .oc_sort_association import _greedy_match_many_to_one


def _k_previous_obs(observations: dict[int, np.ndarray], cur_age: int, k: int) -> np.ndarray:
    if len(observations) == 0:
        return np.array([-1.0, -1.0, -1.0, -1.0, -1.0], dtype=np.float64)

    for i in range(k):
        dt = k - i
        if cur_age - dt in observations:
            return observations[cur_age - dt]

    max_age = max(observations.keys())
    return observations[max_age]


def _convert_bbox_to_z(bbox: np.ndarray) -> np.ndarray:
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    x = bbox[0] + w / 2.0
    y = bbox[1] + h / 2.0
    s = w * h
    r = w / float(h + 1e-6)
    return np.array([x, y, s, r], dtype=np.float64).reshape((4, 1))


def _convert_x_to_bbox(x: np.ndarray) -> np.ndarray:
    w = np.sqrt(x[2] * x[3])
    h = x[2] / (w + 1e-6)
    return np.array([x[0] - w / 2.0, x[1] - h / 2.0, x[0] + w / 2.0, x[1] + h / 2.0], dtype=np.float64).reshape((1, 4))


def _speed_direction(bbox1: np.ndarray, bbox2: np.ndarray) -> np.ndarray:
    cx1 = (bbox1[0] + bbox1[2]) / 2.0
    cy1 = (bbox1[1] + bbox1[3]) / 2.0
    cx2 = (bbox2[0] + bbox2[2]) / 2.0
    cy2 = (bbox2[1] + bbox2[3]) / 2.0
    speed = np.array([cy2 - cy1, cx2 - cx1], dtype=np.float64)
    norm = np.sqrt((cy2 - cy1) ** 2 + (cx2 - cx1) ** 2) + 1e-6
    return speed / norm


class _KalmanBoxTracker:
    count = 0

    _F = np.array(
        [
            [1, 0, 0, 0, 1, 0, 0],
            [0, 1, 0, 0, 0, 1, 0],
            [0, 0, 1, 0, 0, 0, 1],
            [0, 0, 0, 1, 0, 0, 0],
            [0, 0, 0, 0, 1, 0, 0],
            [0, 0, 0, 0, 0, 1, 0],
            [0, 0, 0, 0, 0, 0, 1],
        ],
        dtype=np.float64,
    )
    _H = np.array(
        [
            [1, 0, 0, 0, 0, 0, 0],
            [0, 1, 0, 0, 0, 0, 0],
            [0, 0, 1, 0, 0, 0, 0],
            [0, 0, 0, 1, 0, 0, 0],
        ],
        dtype=np.float64,
    )

    def __init__(self, bbox: np.ndarray, delta_t: int = 3):
        self.kf = KalmanFilter(dim_x=7, dim_z=4)
        self.kf.F = _KalmanBoxTracker._F.copy()
        self.kf.H = _KalmanBoxTracker._H.copy()

        self.kf.R[2:, 2:] *= 10.0
        self.kf.P[4:, 4:] *= 1000.0
        self.kf.P *= 10.0
        self.kf.Q[-1, -1] *= 0.01
        self.kf.Q[4:, 4:] *= 0.01

        self.kf.x[:4] = _convert_bbox_to_z(bbox[:4])

        self.time_since_update = 0
        self.id = _KalmanBoxTracker.count
        _KalmanBoxTracker.count += 1

        self.hit_streak = 0
        self.age = 0

        self.last_observation = np.array([-1.0, -1.0, -1.0, -1.0, -1.0], dtype=np.float64)
        self.observations: dict[int, np.ndarray] = {}
        self.history_observations: list[np.ndarray] = []
        self.history_scores: list[float] = []
        self.history_classes: list[int] = []
        self.history_indices: list[int] = []
        self.history_max_sides: list[float] = []
        self.velocity: np.ndarray | None = None
        self.delta_t = delta_t

        self.score = float(bbox[4]) if len(bbox) > 4 else 0.0
        self.cls = int(bbox[5]) if len(bbox) > 5 else 0
        self.idx = int(bbox[6]) if len(bbox) > 6 else -1
        self._consecutive_shared_count: int = 0

    def update(self, bbox: np.ndarray | None) -> None:
        if bbox is None:
            return

        bbox = np.asarray(bbox, dtype=np.float64)
        obs = np.array([bbox[0], bbox[1], bbox[2], bbox[3], bbox[4]], dtype=np.float64)

        if self.last_observation.sum() >= 0:
            self.velocity = _speed_direction(self.last_observation, obs)

        self.last_observation = obs
        self.observations[self.age] = obs
        self.history_observations.append(obs)

        self.time_since_update = 0
        self.hit_streak += 1

        self.kf.update(_convert_bbox_to_z(obs[:4]))

        self.score = float(bbox[4]) if len(bbox) > 4 else self.score
        self.cls = int(bbox[5]) if len(bbox) > 5 else self.cls
        self.idx = int(bbox[6]) if len(bbox) > 6 else self.idx
        self.history_scores.append(self.score)
        self.history_classes.append(self.cls)
        self.history_indices.append(self.idx)
        w = obs[2] - obs[0]
        h = obs[3] - obs[1]
        self.history_max_sides.append(max(w, h))

    def predict(self) -> np.ndarray:
        if (self.kf.x[6] + self.kf.x[2]) <= 0:
            self.kf.x[6] *= 0.0

        self.kf.predict()
        self.age += 1

        if self.time_since_update > 0:
            self.hit_streak = 0
        self.time_since_update += 1

        return _convert_x_to_bbox(self.kf.x)

    def get_state(self) -> np.ndarray:
        return _convert_x_to_bbox(self.kf.x)

    @property
    def avg_max_side(self) -> float:
        """已匹配框 max(w,h) 的平均值；无历史时返回 0.0。"""
        if not self.history_max_sides:
            return 0.0
        return float(np.mean(self.history_max_sides))

    def can_claim_shared(self, min_track_hits_for_shared: int, max_consecutive_shared: int) -> bool:
        """轨迹是否有资格认领已被其他轨迹认领的共享候选框。"""
        return (
            self.hit_streak >= min_track_hits_for_shared
            and self._consecutive_shared_count < max_consecutive_shared
        )

    def mark_claimed(self, is_shared: bool) -> None:
        """标记本次认领是否为共享框。
        
        is_shared=True 时连续共享计数器+1；
        is_shared=False（独占框）时计数器归零。
        """
        if is_shared:
            self._consecutive_shared_count += 1
        else:
            self._consecutive_shared_count = 0


class OCSort:
    def __init__(
        self,
        det_thresh: float,
        max_age: int = 30,
        min_hits: int = 3,
        delta_t: int = 3,
        inertia: float = 0.2,
        use_byte: bool = False,
        max_ratio: float = 2.0,
        size_ratio: float = 0.85,
        max_size_increase_ratio: float = 0.10,
        min_track_hits_for_shared: int = 10,
        max_consecutive_shared: int = 3,
        inertia_gain_threshold: float = 0.8,
    ):
        self.max_age = int(max_age)
        self.min_hits = int(min_hits)
        self.trackers: list[_KalmanBoxTracker] = []
        self.frame_count = 0
        self.det_thresh = float(det_thresh)
        self.delta_t = int(delta_t)
        self.inertia = float(inertia)
        self.use_byte = bool(use_byte)
        self.low_thresh = 0.1
        self.max_ratio = float(max_ratio)
        self.size_ratio = float(size_ratio)
        self.max_size_increase_ratio = float(max_size_increase_ratio)
        self.min_track_hits_for_shared = int(min_track_hits_for_shared)
        self.max_consecutive_shared = int(max_consecutive_shared)
        self.inertia_gain_threshold = float(inertia_gain_threshold)

        _KalmanBoxTracker.count = 0

    @staticmethod
    def _to_obb_track_row(
        xyxy: np.ndarray,
        track_id: int,
        score: float,
        cls_id: int,
        idx: int,
        frame_offset: int = 0,
    ) -> np.ndarray:
        # 返回 track.py 需要的格式
        x1, y1, x2, y2 = xyxy
        w = x2 - x1
        h = y2 - y1
        cx = x1 + w / 2.0
        cy = y1 + h / 2.0
        return np.array([cx, cy, w, h, 0.0, track_id, score, cls_id, idx, frame_offset], dtype=np.float32)

    def update(self, output_results: np.ndarray | None) -> np.ndarray:
        if output_results is None:
            output_results = np.empty((0, 7), dtype=np.float64)

        if len(output_results) == 0:
            dets_all = np.empty((0, 7), dtype=np.float64)
        else:
            dets_all = np.asarray(output_results, dtype=np.float64)

        self.frame_count += 1

        scores = dets_all[:, 4] if len(dets_all) else np.empty((0,), dtype=np.float64)
        remain_inds = scores > self.det_thresh
        inds_second = np.logical_and(scores > self.low_thresh, scores < self.det_thresh)

        dets = dets_all[remain_inds]
        dets_second = dets_all[inds_second]
        dets_assoc = dets[:, :5]
        dets_second_assoc = dets_second[:, :5]

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

        if self.trackers:
            zero_vel = np.array((0.0, 0.0), dtype=np.float64)
            velocities = np.array([trk.velocity if trk.velocity is not None else zero_vel for trk in self.trackers])
            last_boxes = np.array([trk.last_observation for trk in self.trackers])
            trk_avg_sizes = np.array([trk.avg_max_side for trk in self.trackers], dtype=np.float64)
            trk_last_max_sides = np.array([
                max(trk.last_observation[2] - trk.last_observation[0],
                    trk.last_observation[3] - trk.last_observation[1])
                if trk.last_observation.sum() >= 0 else 0.0
                for trk in self.trackers
            ], dtype=np.float64)
        else:
            velocities = np.empty((0, 2), dtype=np.float64)
            last_boxes = np.empty((0, 5), dtype=np.float64)
            trk_avg_sizes = np.empty((0,), dtype=np.float64)
            trk_last_max_sides = np.empty((0,), dtype=np.float64)

        matched, unmatched_dets, unmatched_trks, det_claim_count = _greedy_match_many_to_one(
            dets_assoc,
            trks,
            self.inertia,
            velocities,
            last_boxes,
            tracker_objects=self.trackers,
            min_track_hits_for_shared=self.min_track_hits_for_shared,
            max_consecutive_shared=self.max_consecutive_shared,
            delta_t=self.delta_t,
            inertia_gain_threshold=self.inertia_gain_threshold,
            trk_last_boxes=last_boxes,
            max_ratio=self.max_ratio,
            trk_avg_sizes=trk_avg_sizes,
            size_ratio=self.size_ratio,
            trk_last_max_sides=trk_last_max_sides,
            max_size_increase_ratio=self.max_size_increase_ratio,
        )

        for det_idx, trk_idx in matched:
            self.trackers[trk_idx].update(dets[det_idx])

        if self.use_byte and len(dets_second_assoc) > 0 and unmatched_trks.shape[0] > 0:
            u_indices = unmatched_trks
            u_tracker_objs = [self.trackers[i] for i in u_indices]
            byte_matched, _, byte_unmatched_local, _ = _greedy_match_many_to_one(
                dets_second_assoc,
                trks[u_indices],
                self.inertia,
                velocities[u_indices],
                last_boxes[u_indices],
                tracker_objects=u_tracker_objs,
                min_track_hits_for_shared=self.min_track_hits_for_shared,
                max_consecutive_shared=self.max_consecutive_shared,
                delta_t=self.delta_t,
                inertia_gain_threshold=self.inertia_gain_threshold,
                trk_last_boxes=last_boxes[u_indices],
                max_ratio=self.max_ratio,
                trk_avg_sizes=trk_avg_sizes[u_indices],
                size_ratio=self.size_ratio,
                trk_last_max_sides=trk_last_max_sides[u_indices],
                max_size_increase_ratio=self.max_size_increase_ratio,
            )

            for det_idx2, trk_pos in byte_matched:
                trk_idx = u_indices[trk_pos]
                self.trackers[trk_idx].update(dets_second[det_idx2])

            if byte_matched.shape[0] > 0:
                matched_local = set(byte_matched[:, 1])
                unmatched_trks = np.array(
                    [u_indices[i] for i in range(len(u_indices)) if i not in matched_local],
                    dtype=int,
                )

        if unmatched_dets.shape[0] > 0 and unmatched_trks.shape[0] > 0:
            left_dets = dets_assoc[unmatched_dets]
            u_indices = unmatched_trks
            u_tracker_objs = [self.trackers[i] for i in u_indices]

            rec_matched, _, rec_unmatched_local, rec_claim = _greedy_match_many_to_one(
                left_dets,
                last_boxes[u_indices],
                self.inertia,
                velocities[u_indices],
                last_boxes[u_indices],
                tracker_objects=u_tracker_objs,
                min_track_hits_for_shared=self.min_track_hits_for_shared,
                max_consecutive_shared=self.max_consecutive_shared,
                delta_t=self.delta_t,
                inertia_gain_threshold=self.inertia_gain_threshold,
                trk_last_boxes=last_boxes[u_indices],
                max_ratio=self.max_ratio,
                trk_avg_sizes=trk_avg_sizes[u_indices],
                size_ratio=self.size_ratio,
                trk_last_max_sides=trk_last_max_sides[u_indices],
                max_size_increase_ratio=self.max_size_increase_ratio,
            )

            to_remove_trk = []
            for det_pos, trk_pos in rec_matched:
                det_idx = unmatched_dets[det_pos]
                trk_idx = u_indices[trk_pos]
                self.trackers[trk_idx].update(dets[det_idx])
                to_remove_trk.append(trk_idx)
                det_claim_count[det_idx] += 1

            if to_remove_trk:
                unmatched_trks = np.setdiff1d(unmatched_trks, np.array(to_remove_trk, dtype=int))

        for trk_idx in unmatched_trks:
            self.trackers[trk_idx].update(None)

        # 仅未被任何轨迹认领的候选框才能创建新轨迹
        for det_idx in np.where(det_claim_count == 0)[0]:
            self.trackers.append(_KalmanBoxTracker(dets[det_idx], delta_t=self.delta_t))

        ret = []
        i = len(self.trackers)
        for trk in reversed(self.trackers):
            if trk.last_observation.sum() < 0:
                d = trk.get_state()[0]
            else:
                d = trk.last_observation[:4]

            if (trk.time_since_update < 1) and (trk.hit_streak >= self.min_hits or self.frame_count <= self.min_hits):
                ret.append(self._to_obb_track_row(d, trk.id + 1, trk.score, trk.cls, trk.idx, frame_offset=0))

                # Head Padding: 在轨迹首次达标输出时，补回初始化阶段的历史观测。
                if trk.hit_streak == self.min_hits:
                    pad_cnt = min(self.min_hits - 1, len(trk.history_observations) - 1)
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
