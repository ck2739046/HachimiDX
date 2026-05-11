import numpy as np


def iou_batch(bboxes1: np.ndarray, bboxes2: np.ndarray) -> np.ndarray:
    """Compute pairwise IoU for boxes in [x1, y1, x2, y2, ...] format."""
    bboxes1 = np.asarray(bboxes1)
    bboxes2 = np.asarray(bboxes2)

    if bboxes1.size == 0 or bboxes2.size == 0:
        return np.zeros((len(bboxes1), len(bboxes2)), dtype=np.float64)

    bboxes2 = np.expand_dims(bboxes2, 0)
    bboxes1 = np.expand_dims(bboxes1, 1)

    xx1 = np.maximum(bboxes1[..., 0], bboxes2[..., 0])
    yy1 = np.maximum(bboxes1[..., 1], bboxes2[..., 1])
    xx2 = np.minimum(bboxes1[..., 2], bboxes2[..., 2])
    yy2 = np.minimum(bboxes1[..., 3], bboxes2[..., 3])

    w = np.maximum(0.0, xx2 - xx1)
    h = np.maximum(0.0, yy2 - yy1)
    wh = w * h

    union = (
        (bboxes1[..., 2] - bboxes1[..., 0]) * (bboxes1[..., 3] - bboxes1[..., 1])
        + (bboxes2[..., 2] - bboxes2[..., 0]) * (bboxes2[..., 3] - bboxes2[..., 1])
        - wh
    )
    return wh / np.maximum(union, 1e-12)


def diou_batch(bboxes1: np.ndarray, bboxes2: np.ndarray) -> np.ndarray:
    """Compute pairwise DIoU (Distance-IoU) for boxes in [x1, y1, x2, y2, ...] format.

    DIoU = IoU - ρ²(b_d, b_t) / c², rescaled from [-1, 1] to [0, 1].

    当 IoU=0 时，中心距离 ρ 提供梯度，优先匹配距离较近的框。
    Ref: https://arxiv.org/abs/1902.09630
    """
    bboxes1 = np.asarray(bboxes1)
    bboxes2 = np.asarray(bboxes2)

    if bboxes1.size == 0 or bboxes2.size == 0:
        return np.zeros((len(bboxes1), len(bboxes2)), dtype=np.float64)

    bboxes2 = np.expand_dims(bboxes2, 0)
    bboxes1 = np.expand_dims(bboxes1, 1)

    # --- IoU part ---
    xx1 = np.maximum(bboxes1[..., 0], bboxes2[..., 0])
    yy1 = np.maximum(bboxes1[..., 1], bboxes2[..., 1])
    xx2 = np.minimum(bboxes1[..., 2], bboxes2[..., 2])
    yy2 = np.minimum(bboxes1[..., 3], bboxes2[..., 3])
    w = np.maximum(0.0, xx2 - xx1)
    h = np.maximum(0.0, yy2 - yy1)
    wh = w * h
    union = (
        (bboxes1[..., 2] - bboxes1[..., 0]) * (bboxes1[..., 3] - bboxes1[..., 1])
        + (bboxes2[..., 2] - bboxes2[..., 0]) * (bboxes2[..., 3] - bboxes2[..., 1])
        - wh
    )
    iou = wh / np.maximum(union, 1e-12)

    # --- Center distance part ---
    cx1 = (bboxes1[..., 0] + bboxes1[..., 2]) / 2.0
    cy1 = (bboxes1[..., 1] + bboxes1[..., 3]) / 2.0
    cx2 = (bboxes2[..., 0] + bboxes2[..., 2]) / 2.0
    cy2 = (bboxes2[..., 1] + bboxes2[..., 3]) / 2.0
    inner_diag = (cx1 - cx2) ** 2 + (cy1 - cy2) ** 2

    # --- Outer enclosing box diagonal ---
    xxc1 = np.minimum(bboxes1[..., 0], bboxes2[..., 0])
    yyc1 = np.minimum(bboxes1[..., 1], bboxes2[..., 1])
    xxc2 = np.maximum(bboxes1[..., 2], bboxes2[..., 2])
    yyc2 = np.maximum(bboxes1[..., 3], bboxes2[..., 3])
    outer_diag = (xxc2 - xxc1) ** 2 + (yyc2 - yyc1) ** 2 + 1e-12

    diou = iou - inner_diag / outer_diag
    return (diou + 1.0) / 2.0  # rescale [-1, 1] → [0, 1]


def speed_direction_batch(dets: np.ndarray, tracks: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """计算检测框到轨迹历史框的单位方向向量。

    Returns:
        (dy, dx): (T, D) 单位方向向量
    """
    tracks = tracks[..., np.newaxis]
    cx1 = (dets[:, 0] + dets[:, 2]) / 2.0
    cy1 = (dets[:, 1] + dets[:, 3]) / 2.0
    cx2 = (tracks[:, 0] + tracks[:, 2]) / 2.0
    cy2 = (tracks[:, 1] + tracks[:, 3]) / 2.0

    dx = cx1 - cx2
    dy = cy1 - cy2
    norm = np.sqrt(dx ** 2 + dy ** 2) + 1e-6

    dx = dx / norm
    dy = dy / norm
    return dy, dx


def linear_assignment(cost_matrix: np.ndarray) -> np.ndarray:
    try:
        import lap

        _, x, y = lap.lapjv(cost_matrix, extend_cost=True)
        return np.array([[y[i], i] for i in x if i >= 0], dtype=int)
    except ImportError:
        from scipy.optimize import linear_sum_assignment

        x, y = linear_sum_assignment(cost_matrix)
        return np.array(list(zip(x, y)), dtype=int)


def _split_matches(
    matched_indices: np.ndarray,
    num_dets: int,
    num_trks: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """将 Hungarian 配对结果拆分为 matched / unmatched_dets / unmatched_trks。

    不按 IoU 硬门控过滤，完全信任代价矩阵 + Hungarian 的全局最优解。
    """
    if matched_indices.shape[0] > 0:
        unmatched_dets = np.setdiff1d(np.arange(num_dets), matched_indices[:, 0])
        unmatched_trks = np.setdiff1d(np.arange(num_trks), matched_indices[:, 1])
        matches = matched_indices
    else:
        unmatched_dets = np.arange(num_dets)
        unmatched_trks = np.arange(num_trks)
        matches = np.empty((0, 2), dtype=int)

    return matches, unmatched_dets.astype(int), unmatched_trks.astype(int)


def center_distance_gate(
    matched_indices: np.ndarray,
    det_boxes: np.ndarray,
    trk_boxes: np.ndarray,
    trk_last_boxes: np.ndarray,
    max_ratio: float = 2.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """过滤中心距离超过 max_ratio × 轨迹最后观测框 max(w,h) 的匹配。

    返回 (good_matches, rejected_det_indices, rejected_trk_indices)。
    rejected 索引会被加入 unmatched 集合。
    """
    if matched_indices.shape[0] == 0:
        return matched_indices, np.array([], dtype=int), np.array([], dtype=int)

    det_idx = matched_indices[:, 0]
    trk_idx = matched_indices[:, 1]

    det_cx = (det_boxes[det_idx, 0] + det_boxes[det_idx, 2]) / 2.0
    det_cy = (det_boxes[det_idx, 1] + det_boxes[det_idx, 3]) / 2.0
    trk_cx = (trk_boxes[trk_idx, 0] + trk_boxes[trk_idx, 2]) / 2.0
    trk_cy = (trk_boxes[trk_idx, 1] + trk_boxes[trk_idx, 3]) / 2.0
    center_dist = np.sqrt((det_cx - trk_cx) ** 2 + (det_cy - trk_cy) ** 2)

    trk_w = trk_last_boxes[trk_idx, 2] - trk_last_boxes[trk_idx, 0]
    trk_h = trk_last_boxes[trk_idx, 3] - trk_last_boxes[trk_idx, 1]
    max_side = np.maximum(trk_w, trk_h)

    # max_side ≤ 0 表示新轨迹尚无有效观测（last_observation 为占位值 [-1,-1,-1,-1,-1]），不设限
    ok = (max_side <= 0.0) | (center_dist <= max_ratio * max_side)
    return matched_indices[ok], matched_indices[~ok, 0], matched_indices[~ok, 1]


def size_consistency_gate(
    matched_indices: np.ndarray,
    det_boxes: np.ndarray,
    trk_avg_sizes: np.ndarray,
    size_ratio: float = 0.85,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """过滤候选框 max(w,h) < trk_avg_max_side * size_ratio 的匹配。

    候选框尺寸不应明显小于该轨迹已有框的平均尺寸。
    trk_avg_sizes[i] 为轨迹 i 的 avg_max_side；值为 0 表示无历史，不设限。
    """
    if matched_indices.shape[0] == 0 or size_ratio <= 0:
        return matched_indices, np.array([], dtype=int), np.array([], dtype=int)

    det_idx = matched_indices[:, 0]
    trk_idx = matched_indices[:, 1]

    det_w = det_boxes[det_idx, 2] - det_boxes[det_idx, 0]
    det_h = det_boxes[det_idx, 3] - det_boxes[det_idx, 1]
    det_max_side = np.maximum(det_w, det_h)

    trk_avg = np.asarray(trk_avg_sizes, dtype=np.float64)[trk_idx]
    threshold = trk_avg * size_ratio

    # avg=0 表示轨迹无历史，通过所有匹配
    ok = (trk_avg == 0.0) | (det_max_side >= threshold)
    return matched_indices[ok], matched_indices[~ok, 0], matched_indices[~ok, 1]


def max_size_increase_gate(
    matched_indices: np.ndarray,
    det_boxes: np.ndarray,
    trk_last_max_sides: np.ndarray,
    max_size_increase_ratio: float = 0.10,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """过滤候选框 max(w,h) > trk_last_max_side * (1 + ratio) 的匹配。

    候选框尺寸不应明显大于轨迹最后一个观测框的最大边长。
    trk_last_max_sides[i] 为轨迹 i 的 last_observation 的 max(w,h)；
    值为 0 表示新轨迹尚无有效历史，不设限。

    与 size_consistency_gate（下限）互补，本门控为上限。
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


def associate(
    detections: np.ndarray,
    trackers: np.ndarray,
    iou_threshold: float,
    velocities: np.ndarray,
    previous_obs: np.ndarray,
    vdc_weight: float,
    trk_last_boxes: np.ndarray | None = None,
    max_ratio: float = 2.0,
    trk_avg_sizes: np.ndarray | None = None,
    size_ratio: float = 0.85,
    trk_last_max_sides: np.ndarray | None = None,
    max_size_increase_ratio: float = 0.10,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if len(trackers) == 0:
        return np.empty((0, 2), dtype=int), np.arange(len(detections)), np.empty((0,), dtype=int)

    if len(detections) == 0:
        return np.empty((0, 2), dtype=int), np.empty((0,), dtype=int), np.arange(len(trackers))

    y_speed, x_speed = speed_direction_batch(detections, previous_obs)

    inertia_y = velocities[:, 0][:, np.newaxis]
    inertia_x = velocities[:, 1][:, np.newaxis]

    diff_angle_cos = inertia_x * x_speed + inertia_y * y_speed
    diff_angle_cos = np.clip(diff_angle_cos, a_min=-1.0, a_max=1.0)
    diff_angle = np.arccos(diff_angle_cos)
    diff_angle = (np.pi / 2.0 - np.abs(diff_angle)) / np.pi

    valid_mask = np.ones(previous_obs.shape[0])
    valid_mask[previous_obs[:, 4] < 0] = 0

    diou_matrix = diou_batch(detections, trackers)
    scores = detections[:, -1][:, np.newaxis]
    valid_mask = valid_mask[:, np.newaxis]

    angle_diff_cost = (valid_mask * diff_angle) * vdc_weight
    angle_diff_cost = angle_diff_cost.T
    angle_diff_cost = angle_diff_cost * scores

    if min(diou_matrix.shape) > 0:
        # DIoU + VDC 联合代价，IoU=0 时中心距离提供梯度，优先选较近匹配
        matched_indices = linear_assignment(-(diou_matrix + angle_diff_cost))
    else:
        matched_indices = np.empty((0, 2), dtype=int)

    # 中心距离硬门控：过滤距离超过 max_ratio × 轨迹最后框 max(w,h) 的匹配
    if trk_last_boxes is not None and matched_indices.shape[0] > 0:
        matched_indices, _, _ = center_distance_gate(
            matched_indices, detections, trackers, trk_last_boxes,
            max_ratio=max_ratio,
        )

    # 尺寸一致性门控：候选框不应明显小于轨迹历史平均尺寸
    if trk_avg_sizes is not None and matched_indices.shape[0] > 0:
        matched_indices, _, _ = size_consistency_gate(
            matched_indices, detections, trk_avg_sizes,
            size_ratio=size_ratio,
        )

    # 尺寸增大门控：候选框不应明显大于轨迹最后一个框的 max(w,h)
    if trk_last_max_sides is not None and matched_indices.shape[0] > 0:
        matched_indices, _, _ = max_size_increase_gate(
            matched_indices, detections, trk_last_max_sides,
            max_size_increase_ratio=max_size_increase_ratio,
        )

    return _split_matches(matched_indices, len(detections), len(trackers))


def _compute_gate_mask(
    det_boxes: np.ndarray,
    trk_boxes: np.ndarray,
    trk_last_boxes: np.ndarray | None,
    max_ratio: float,
    trk_avg_sizes: np.ndarray | None,
    size_ratio: float,
    trk_last_max_sides: np.ndarray | None,
    max_size_increase_ratio: float,
) -> np.ndarray:
    """计算 (num_trks, num_dets) 布尔掩码，True 表示该对通过全部门控。

    三门控逻辑与 associate() 中后置过滤完全一致，仅改为矩阵形式。
    """
    num_trks = len(trk_boxes)
    num_dets = len(det_boxes)
    combined = np.ones((num_trks, num_dets), dtype=bool)

    if num_trks == 0 or num_dets == 0:
        return combined

    # --- 中心距离门控 ---
    if trk_last_boxes is not None:
        det_cx = (det_boxes[:, 0] + det_boxes[:, 2]) / 2.0
        det_cy = (det_boxes[:, 1] + det_boxes[:, 3]) / 2.0
        trk_cx = (trk_boxes[:, 0] + trk_boxes[:, 2]) / 2.0
        trk_cy = (trk_boxes[:, 1] + trk_boxes[:, 3]) / 2.0

        center_dist = np.sqrt(
            (det_cx[np.newaxis, :] - trk_cx[:, np.newaxis]) ** 2
            + (det_cy[np.newaxis, :] - trk_cy[:, np.newaxis]) ** 2
        )
        trk_w = trk_last_boxes[:, 2] - trk_last_boxes[:, 0]
        trk_h = trk_last_boxes[:, 3] - trk_last_boxes[:, 1]
        max_side = np.maximum(trk_w, trk_h)
        threshold = max_ratio * max_side[:, np.newaxis]
        center_ok = (max_side[:, np.newaxis] <= 0.0) | (center_dist <= threshold)
        combined = combined & center_ok

    # --- 尺寸一致性门控（下限） ---
    if trk_avg_sizes is not None and size_ratio > 0:
        det_w = det_boxes[:, 2] - det_boxes[:, 0]
        det_h = det_boxes[:, 3] - det_boxes[:, 1]
        det_max_side = np.maximum(det_w, det_h)
        trk_avg = np.asarray(trk_avg_sizes, dtype=np.float64)
        threshold = trk_avg * size_ratio
        size_ok = (trk_avg[:, np.newaxis] == 0.0) | (det_max_side[np.newaxis, :] >= threshold[:, np.newaxis])
        combined = combined & size_ok

    # --- 尺寸增大门控（上限） ---
    if trk_last_max_sides is not None and max_size_increase_ratio >= 0:
        det_w = det_boxes[:, 2] - det_boxes[:, 0]
        det_h = det_boxes[:, 3] - det_boxes[:, 1]
        det_max_side = np.maximum(det_w, det_h)
        trk_last_max = np.asarray(trk_last_max_sides, dtype=np.float64)
        threshold = trk_last_max * (1.0 + max_size_increase_ratio)
        inc_ok = (trk_last_max[:, np.newaxis] == 0.0) | (det_max_side[np.newaxis, :] <= threshold[:, np.newaxis])
        combined = combined & inc_ok

    return combined


def _greedy_match_many_to_one(
    detections: np.ndarray,
    trackers: np.ndarray,
    vdc_weight: float,
    velocities: np.ndarray,
    previous_obs: np.ndarray,
    tracker_objects: list,
    min_track_hits_for_shared: int,
    max_consecutive_shared: int,
    vdc_disable_threshold: float = 0.7,
    trk_last_boxes: np.ndarray | None = None,
    max_ratio: float = 2.0,
    trk_avg_sizes: np.ndarray | None = None,
    size_ratio: float = 0.85,
    trk_last_max_sides: np.ndarray | None = None,
    max_size_increase_ratio: float = 0.10,
    initial_det_claim_count: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """贪心 many-to-one 匹配：每条轨迹独立选最优候选框，同一候选框可被多条轨迹认领。

    与 associate() 的区别：
    - 用贪心替代匈牙利算法，候选框不互斥
    - 轨迹按 hit_streak 降序排列，优先选独占框
    - 仅在满足 min_track_hits_for_shared / max_consecutive_shared 资格时才认领共享框

    Returns:
        matches: (M, 2) [det_idx, trk_idx]，同一 det_idx 可出现多次
        unmatched_dets: 未被任何轨迹认领的检测框索引
        unmatched_trks: 未找到合格检测框的轨迹索引
        det_claim_count: (num_dets,) 每个检测框的被认领次数
    """
    num_dets = len(detections)
    num_trks = len(trackers)

    det_claim_count = (
        np.zeros(num_dets, dtype=int)
        if initial_det_claim_count is None
        else np.asarray(initial_det_claim_count, dtype=int).copy()
    )

    if num_trks == 0:
        return (
            np.empty((0, 2), dtype=int),
            np.arange(num_dets, dtype=int),
            np.empty((0,), dtype=int),
            det_claim_count,
        )

    if num_dets == 0:
        return (
            np.empty((0, 2), dtype=int),
            np.empty((0,), dtype=int),
            np.arange(num_trks, dtype=int),
            det_claim_count,
        )

    # --- 代价计算 ---
    y_speed, x_speed = speed_direction_batch(detections, previous_obs)

    inertia_y = velocities[:, 0][:, np.newaxis]
    inertia_x = velocities[:, 1][:, np.newaxis]

    diff_angle_cos = inertia_x * x_speed + inertia_y * y_speed
    diff_angle_cos = np.clip(diff_angle_cos, a_min=-1.0, a_max=1.0)
    diff_angle = np.arccos(diff_angle_cos)
    diff_angle = (np.pi / 2.0 - np.abs(diff_angle)) / np.pi

    valid_mask = np.ones(previous_obs.shape[0])
    valid_mask[previous_obs[:, 4] < 0] = 0

    diou_matrix = diou_batch(detections, trackers)
    scores = detections[:, -1][:, np.newaxis]
    valid_mask = valid_mask[:, np.newaxis]

    angle_diff_cost = (valid_mask * diff_angle) * vdc_weight
    angle_diff_cost = angle_diff_cost.T  # (D, T)
    angle_diff_cost = angle_diff_cost * scores  # (D,T)



    cost_matrix = -(diou_matrix + angle_diff_cost)  # 负号：cost 越小越好

    # --- 预计算三门控掩码 ---
    gate_mask = _compute_gate_mask(
        detections, trackers,
        trk_last_boxes=trk_last_boxes, max_ratio=max_ratio,
        trk_avg_sizes=trk_avg_sizes, size_ratio=size_ratio,
        trk_last_max_sides=trk_last_max_sides, max_size_increase_ratio=max_size_increase_ratio,
    )  # (T, D)

    # --- 按 hit_streak 降序排列轨迹 ---
    trk_order = sorted(
        range(num_trks),
        key=lambda i: tracker_objects[i].hit_streak,
        reverse=True,
    )

    matches: list[tuple[int, int]] = []
    matched_trk_set: set[int] = set()

    for trk_i in trk_order:
        trk_obj = tracker_objects[trk_i]

        # 通过全部门控且 cost 有效的候选框
        candidate_mask = gate_mask[trk_i]  # (D,)
        if not candidate_mask.any():
            continue

        # 分为独占框和共享框
        unshared_mask = candidate_mask & (det_claim_count == 0)
        shared_mask = candidate_mask & (det_claim_count > 0)

        # 优先选独占框中 cost 最小者
        best_det: int | None = None
        nd = len(candidate_mask)
        trk_costs = cost_matrix[:nd, trk_i].ravel()
        if unshared_mask.any():
            unshared_costs = trk_costs.copy()
            unshared_costs[~unshared_mask] = np.inf
            best_det = int(np.argmin(unshared_costs))
        elif shared_mask.any() and trk_obj.can_claim_shared(min_track_hits_for_shared, max_consecutive_shared):
            shared_costs = trk_costs.copy()
            shared_costs[~shared_mask] = np.inf
            best_det = int(np.argmin(shared_costs))

        if best_det is None:
            continue

        is_shared = det_claim_count[best_det] > 0
        det_claim_count[best_det] += 1
        trk_obj.mark_claimed(is_shared)
        matches.append((best_det, trk_i))
        matched_trk_set.add(trk_i)

    matched_arr = np.array(matches, dtype=int) if matches else np.empty((0, 2), dtype=int)

    # unmatched_dets = 未被任何轨迹认领的检测框
    all_det_indices = np.arange(num_dets, dtype=int)
    unmatched_dets = all_det_indices[det_claim_count == 0]

    # unmatched_trks = 未找到合格候选框的轨迹
    unmatched_trks = np.array([i for i in range(num_trks) if i not in matched_trk_set], dtype=int)

    return matched_arr, unmatched_dets, unmatched_trks, det_claim_count
