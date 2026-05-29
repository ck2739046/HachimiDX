import numpy as np



def calculate_oct_position(circle_center_x, circle_center_y, note_x, note_y):
    x_diff = note_x - circle_center_x
    y_diff = note_y - circle_center_y
    if x_diff >= 0 and y_diff <= 0:
        # 1, 2
        if abs(x_diff) < abs(y_diff):
            return 1
        else:
            return 2
    elif x_diff >= 0 and y_diff >= 0:
        # 3, 4
        if abs(x_diff) > abs(y_diff):
            return 3
        else:
            return 4
    elif x_diff <= 0 and y_diff >= 0:
        # 5, 6
        if abs(x_diff) < abs(y_diff):
            return 5
        else:
            return 6
    elif x_diff <= 0 and y_diff <= 0:
        # 7, 8
        if abs(x_diff) > abs(y_diff):
            return 7
        else:
            return 8
            






def calculate_all_position(touch_areas, note_x, note_y):
    
    closeset_label = None
    closeset_dist = 9999

    for label, (cx, cy) in touch_areas.items():
        dist = np.sqrt(((note_x - cx) ** 2 + (note_y - cy) ** 2))
        if dist < closeset_dist:
            closeset_label = label
            closeset_dist = dist
    
    return closeset_label




def draw_path_on_frame(screen_cx, screen_cy, judgeline_end, judgeline_start,
                       video_path, frame_num, track_id, note_path):

    cap = cv2.VideoCapture(video_path)  
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
    ret, frame = cap.read()
    if not ret:
        print(f"draw_path_on_frame: failed to read frame {frame_num}")
        cap.release()
        return
    
    cv2.putText(frame, f"track_id: {track_id}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
    # 绘制两个圈
    cv2.circle(frame, (round(screen_cx), round(screen_cy)), round(judgeline_end), (0, 255, 0), 2)
    cv2.circle(frame, (round(screen_cx), round(screen_cy)), round(judgeline_start), (255, 0, 0), 2)

    for point in note_path:
        frame_num = point['frame']
        cx = point['cx']
        cy = point['cy']
        cv2.circle(frame, (round(cx), round(cy)), 3, (0, 0, 255), -1)

    # Resize and show frame
    resized_frame = cv2.resize(frame, (900, 900), interpolation=cv2.INTER_AREA)
    window_name = f'Tap ID: {track_id}'
    cv2.namedWindow(window_name)
    cv2.moveWindow(window_name, 500, 80)
    cv2.imshow(window_name, resized_frame)
    cv2.waitKey(0)
    cv2.destroyAllWindows()
    cap.release()






def catmull_rom_spline(points: list, num_samples: int = 4, tension: float = 1.5) -> np.ndarray:
    """对控制点列表使用 Catmull-Rom 样条插值生成平滑曲线点。

    Args:
        points: 控制点列表 [(x, y), ...]
        num_samples: 每段采样点数（包含段起点，不含段终点）
        tension:  张力系数。=1.0 标准 Catmull-Rom；>1.0 放大切线产生更大过冲（更松弛）；
                  <1.0 收紧曲线趋近折线。

    Returns:
        shape (N, 1, 2) 的 np.int32 数组
    """
    n = len(points)
    if n < 2:
        return np.array([], dtype=np.int32).reshape((-1, 1, 2))

    pts = np.asarray(points, dtype=np.float32)
    s = float(tension)

    if n == 2:
        t = np.linspace(0, 1, num_samples + 1, endpoint=True, dtype=np.float32)
        interp = pts[0] + (pts[1] - pts[0]) * t[:, None]
        return np.asarray(np.round(interp), dtype=np.int32).reshape((-1, 1, 2))

    # n >= 3: 全向量化一次计算所有段的所有插值点
    n_seg = n - 1

    # 控制点矩阵 (n_seg, 2)，每个段的 P0 P1 P2 P3
    # 边界：首段 P0=P1，尾段 P3=P2
    p0 = pts[np.clip(np.arange(n_seg) - 1, 0, n - 1)]
    p1 = pts[np.arange(n_seg)]
    p2 = pts[np.arange(n_seg) + 1]
    p3 = pts[np.clip(np.arange(n_seg) + 2, 0, n - 1)]

    # t 网格 (num_samples, n_seg)
    t = np.arange(num_samples, dtype=np.float32) / num_samples
    t2 = t * t
    t3 = t2 * t

    # 基函数 (num_samples, n_seg)
    c0 = s * (-t + 2.0 * t2 - t3)[:, None]
    c1 = (2.0 + (s - 6.0) * t2 + (4.0 - s) * t3)[:, None]
    c2 = (s * t + (6.0 - 2.0 * s) * t2 + (s - 4.0) * t3)[:, None]
    c3 = s * (-t2 + t3)[:, None]

    # 广播聚合: (num_samples, n_seg, 2)
    result = 0.5 * (c0[..., None] * p0[None, ...] +
                    c1[..., None] * p1[None, ...] +
                    c2[..., None] * p2[None, ...] +
                    c3[..., None] * p3[None, ...])

    # 转置为 (n_seg, num_samples, 2) → 展平 → 追加末点
    result = np.ascontiguousarray(result.transpose(1, 0, 2).reshape(-1, 2))
    result = np.vstack([result, pts[-1][None, :]])

    return np.asarray(np.round(result), dtype=np.int32).reshape((-1, 1, 2))






if __name__ == "__main__":

    import cv2
    
    track_result_content = """
7122, slide, normal, 0.9800, 731.2500, 62.8594, 908.4375, 62.8594, 908.4375, 240.1875, 731.2500, 240.1875, 819.8438, 151.5234, 177.1875, 177.3281, 0.0000
7123, slide, normal, 0.9849, 771.7500, 95.2031, 950.0625, 95.2031, 950.0625, 273.2344, 771.7500, 273.2344, 860.9062, 184.2188, 178.3125, 178.0312, 0.0000
7124, slide, normal, 0.9839, 804.3750, 127.6875, 981.5625, 127.6875, 981.5625, 305.4375, 804.3750, 305.4375, 892.9688, 216.5625, 177.1875, 177.7500, 0.0000
7125, slide, normal, 0.9849, 840.9375, 172.1250, 1017.5625, 172.1250, 1017.5625, 349.3125, 840.9375, 349.3125, 929.2500, 260.7188, 176.6250, 177.1875, 0.0000
7126, slide, normal, 0.9824, 868.5000, 215.1562, 1044.0000, 215.1562, 1044.0000, 392.0625, 868.5000, 392.0625, 956.2500, 303.6094, 175.5000, 176.9062, 0.0000
7127, slide, normal, 0.9854, 888.1875, 252.8438, 1064.2500, 252.8438, 1064.2500, 430.0312, 888.1875, 430.0312, 976.2188, 341.4375, 176.0625, 177.1875, 0.0000
7128, slide, normal, 0.9849, 911.8125, 318.3750, 1080.0000, 318.3750, 1080.0000, 495.2812, 911.8125, 495.2812, 995.9062, 406.8281, 168.1875, 176.9062, 0.0000
7129, slide, normal, 0.9844, 921.9375, 363.3750, 1080.0000, 363.3750, 1080.0000, 541.6875, 921.9375, 541.6875, 1000.9688, 452.5312, 158.0625, 178.3125, 0.0000
7130, slide, normal, 0.9814, 929.2500, 417.3750, 1079.4375, 417.3750, 1079.4375, 594.5625, 929.2500, 594.5625, 1004.3438, 505.9688, 150.1875, 177.1875, 0.0000
7131, slide, normal, 0.9844, 930.3750, 455.3438, 1080.0000, 455.3438, 1080.0000, 632.8125, 930.3750, 632.8125, 1005.1875, 544.0781, 149.6250, 177.4688, 0.0000
7132, slide, normal, 0.9839, 925.8750, 518.6250, 1080.0000, 518.6250, 1080.0000, 696.3750, 925.8750, 696.3750, 1002.9375, 607.5000, 154.1250, 177.7500, 0.0000
7133, slide, normal, 0.9824, 914.6250, 572.6250, 1080.0000, 572.6250, 1080.0000, 750.3750, 914.6250, 750.3750, 997.3125, 661.5000, 165.3750, 177.7500, 0.0000
7134, slide, normal, 0.9858, 900.5625, 616.5000, 1078.8750, 616.5000, 1078.8750, 794.2500, 900.5625, 794.2500, 989.7188, 705.3750, 178.3125, 177.7500, 0.0000
7135, slide, normal, 0.9839, 880.8750, 661.5000, 1059.7500, 661.5000, 1059.7500, 839.8125, 880.8750, 839.8125, 970.3125, 750.6562, 178.8750, 178.3125, 0.0000
7136, slide, normal, 0.9839, 849.3750, 718.8750, 1027.1250, 718.8750, 1027.1250, 896.6250, 849.3750, 896.6250, 938.2500, 807.7500, 177.7500, 177.7500, 0.0000
7137, slide, normal, 0.9854, 815.0625, 764.4375, 992.8125, 764.4375, 992.8125, 941.6250, 815.0625, 941.6250, 903.9375, 853.0312, 177.7500, 177.1875, 0.0000
7138, slide, normal, 0.9854, 780.7500, 798.7500, 958.5000, 798.7500, 958.5000, 976.5000, 780.7500, 976.5000, 869.6250, 887.6250, 177.7500, 177.7500, 0.0000
7139, slide, normal, 0.9854, 743.0625, 831.9375, 920.2500, 831.9375, 920.2500, 1008.0000, 743.0625, 1008.0000, 831.6562, 919.9688, 177.1875, 176.0625, 0.0000
7140, slide, normal, 0.9829, 695.2500, 864.0000, 871.8750, 864.0000, 871.8750, 1039.5000, 695.2500, 1039.5000, 783.5625, 951.7500, 176.6250, 175.5000, 0.0000
7141, slide, normal, 0.9849, 649.6875, 887.0625, 828.0000, 887.0625, 828.0000, 1063.6875, 649.6875, 1063.6875, 738.8438, 975.3750, 178.3125, 176.6250, 0.0000
7142, slide, normal, 0.9844, 635.0625, 894.3750, 812.2500, 894.3750, 812.2500, 1071.0000, 635.0625, 1071.0000, 723.6562, 982.6875, 177.1875, 176.6250, 0.0000
"""
    # 构建 note_path
    # 参考 detect.track._load_track_results()
    note_path = []
    for line in track_result_content.strip().splitlines():
        parts = line.split(",")
        point = {
            'frame': int(parts[0].strip()),
            # 'x1': float(parts[4].strip()),
            # 'y1': float(parts[5].strip()),
            # 'x2': float(parts[6].strip()),
            # 'y2': float(parts[7].strip()),
            # 'x3': float(parts[8].strip()),
            # 'y3': float(parts[9].strip()),
            # 'x4': float(parts[10].strip()),
            # 'y4': float(parts[11].strip()),
            'cx': float(parts[12].strip()),
            'cy': float(parts[13].strip()),
        }
        note_path.append(point)
    
    screen_cx, screen_cy = 540, 540
    judgeline_end = 480
    judgeline_start = 120
    video_path = r"C:\Users\ck273\Desktop\[maimai谱面确认] キミは“見ていたね”？ MASTER\[maimai谱面确认] キミは“見ていたね”？ MASTER_std.mp4"
    frame_num = 7176
    track_id = 262

    draw_path_on_frame(screen_cx, screen_cy, judgeline_end, judgeline_start,
                       video_path, frame_num, track_id, note_path)
