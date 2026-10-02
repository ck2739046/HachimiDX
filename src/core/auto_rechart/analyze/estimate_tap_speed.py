import i18n
import numpy as np


def _collect_note_approach_paths(shared_context, tap_data, slide_head_data, hold_data):
    """
    汇总所有音符路径用于计算流速

    tap / slide_head 直接加入; hold 头尾视为两个独立 tap 分别加入

    返回: list[list[dict]]，每个 dict 形如 {'frame': int, 'dist': float}
    """

    final_paths = []

    for data in (tap_data, slide_head_data):
        for path in data.values():
            final_paths.append(path)

    # hold 头尾可能长时间停在判定线，导致流速计算异常
    tolerance = shared_context.note_travel_dist * 0.1
    valid_start = shared_context.judgeline_start + tolerance
    valid_end = shared_context.judgeline_end - tolerance

    for path in hold_data.values():
        for dist_key in ("dist-head", "dist-tail"):
            filtered = []
            for p in path:
                if valid_start <= p[dist_key] <= valid_end:
                    filtered.append({"frame": p["frame"], "dist": p[dist_key]})
            if filtered:
                final_paths.append(filtered)

    return final_paths


def estimate_tap_DefaultMsec(shared_context, tap_data, slide_head_data, hold_data):
    """
    音符从起点移动到判定线需要耗时 DefaultMsec (ms)
    采样4个点（0%、25%、50%、100%）计算三个阶段性速度
    """

    note_paths = _collect_note_approach_paths(
        shared_context, tap_data, slide_head_data, hold_data
    )

    if not note_paths:
        print_info = i18n.t("estimate_tap_speed.notice_no_data")
        return None, None, None, print_info

    note_speeds = []

    for path in note_paths:
        # 获取4个采样点的索引
        path_length = len(path)
        indices = [
            0,  # 0%
            path_length // 4,  # 25%
            path_length // 2,  # 50%
            path_length - 1,  # 100%
        ]

        # 计算三个阶段性速度
        for i in range(3):
            start_idx = indices[i]
            end_idx = indices[i + 1]

            frame_num_start = path[start_idx]["frame"]
            frame_num_end = path[end_idx]["frame"]
            dist_start = path[start_idx]["dist"]
            dist_end = path[end_idx]["dist"]

            total_dist = dist_end - dist_start

            time_diff_msec = shared_context.frame_delta_msec(
                frame_num_start, frame_num_end
            )

            if time_diff_msec > 0:  # 避免除零错误
                note_speed = total_dist / time_diff_msec  # pixel/ms
                note_speeds.append(note_speed)

    length = len(note_speeds)
    mean = np.mean(note_speeds)
    min = np.min(note_speeds)
    max = np.max(note_speeds)
    median = np.median(note_speeds)
    std_dev = np.std(note_speeds)
    print_info1 = i18n.t(
        "estimate_tap_speed.notice_speed_stat",
        count=length,
        median=f"{median:.3f}",
        min=f"{min:.3f}",
        max=f"{max:.3f}",
        mean=f"{mean:.3f}",
        std_dev=f"{std_dev:.3f}",
    )

    note_DefaultMsec, note_OptionNotespeed, note_SpeedIndex, print_info2 = (
        get_note_DefaultMsec(shared_context, median)
    )
    return (
        note_DefaultMsec,
        note_OptionNotespeed,
        note_SpeedIndex,
        f"{print_info1}\n{print_info2}",
    )


def get_note_DefaultMsec(shared_context, detected_note_speed):

    def get_standard_note_DefaultMsec(ui_speed):
        # 游戏源码实现
        OptionNotespeed = round(ui_speed * 100 + 100)  # 6.25 = 725
        NoteSpeedForBeat = 1000 / (OptionNotespeed / 60)
        DefaultMsec = NoteSpeedForBeat * 4  # 一小节四拍
        return DefaultMsec, OptionNotespeed

    total_dist = shared_context.note_travel_dist
    detected_note_DefaultMsec = (
        total_dist / detected_note_speed
    )  # 走完全程需要多少时间 (lifetime)

    # 查找最接近的 DefaultMsec
    cloest_DefaultMsec = 0
    cloest_i = 0
    cloest_OptionNotespeed = 0
    i = 1
    while i <= 10:
        DefaultMsec, OptionNotespeed = get_standard_note_DefaultMsec(i)

        if abs(DefaultMsec - detected_note_DefaultMsec) < abs(
            cloest_DefaultMsec - detected_note_DefaultMsec
        ):
            cloest_DefaultMsec = DefaultMsec
            cloest_i = i
            cloest_OptionNotespeed = OptionNotespeed
        i += 0.25

    print_info = i18n.t(
        "estimate_tap_speed.notice_estimate",
        index=f"{cloest_i:.2f}",
        msec=f"{cloest_DefaultMsec:.3f}",
        detected=f"{detected_note_DefaultMsec:.3f}",
    )

    return cloest_DefaultMsec, cloest_OptionNotespeed, cloest_i, print_info
