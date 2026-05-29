import numpy as np

from .shared_context import *


def estimate_touch_DefaultMsec(shared_context, touch_data):
    '''
    正向：
    根据 time_progress = (current_time - move_start_time) / DefaultMsec 获得 time_progress
    应用缓动函数, location_progress = 缓动函数(time_progress)
    根据 location_progress 决定4个三角距离中心点的距离
    current_Dist = total_Dist * (1 - location_progress) 纯线性的

    逆向：
    反推 location_progress = 1 - current_Dist / total_Dist
    二分法, 通过location_progress反推出time_progress ( y -> x )
    反推 DefaultMsec = (current_time - move_start_time) / time_progress

    方案:
    已知 current_dist, current_time, 求解 DefaultMsec, move_start_time
    通过dump游戏得知total_Dist = 34 (对于标准1080p)
    DispAdjustFlame: 0 (时间微调参数没有影响, 可以忽略)
    DefaultCorlsPos Values: [(0.0, 34.0, -1.0), (0.0, -34.0, -1.0), (34.0, 0.0, 0.0), (-34.0, 0.0, 0.0)]

    首先反推出每个点的time_progress, (只保留location_progress 0.15-0.85)
    选择缓动函数斜率较大的区间，因为这些区间对时间变化更敏感
    选两个点相减消除未知的move_start_time常量
    -> DefaultMsec = (current_time1 - current_time2) / (time_progress1 - time_progress2)

    计算多个数据点对的 DefaultMsec 然后取平均值
    '''

    def reverse_function(y, tolerance=0.001):
        # 二分查找求解 y = 3.5x⁴ - 3.75x³ + 1.45x² - 0.05x + 0.0005 的反函数
        low, high = 0.0, 1.0
        
        while high - low > tolerance:
            mid = (low + high) / 2
            eased_y = 3.5 * mid**4 - 3.75 * mid**3 + 1.45 * mid**2 - 0.05 * mid + 0.0005
            
            if abs(eased_y - y) < tolerance:
                return mid
            elif eased_y < y:
                low = mid  # 二分查找更新
            else:
                high = mid
        return (low + high) / 2


    DefaultMsecs = []

    for (track_id, note_type, note_variant, note_position), path in touch_data.items():

        # 过滤掉斜率较小的轨迹点
        big_slope_points = []
        for point in path:
            # 反推 location_progress (保留15%-85%的点)
            cur_dist = point['dist']
            location_progress = 1 - cur_dist / shared_context.touch_travel_dist
            if location_progress < 0.15 or location_progress > 0.85:
                continue
            # 反推 time_progress
            time_progress = reverse_function(location_progress)
            # 加入列表
            cur_time = shared_context.frame_to_msec(point['frame'])
            big_slope_points.append((cur_time, time_progress))

        if len(big_slope_points) < 3:
            print(f"estimate_touch_DefaultMsec: [track_id {track_id}] not enough big slope points, length: {len(big_slope_points)}")
            continue

        # 轨迹点配对并计算 DefaultMsec
        big_slope_points.sort(key=lambda x: x[1]) # 按 time_progress 排序
        for i in range(len(big_slope_points)):
            for j in range(i + 1, len(big_slope_points)):
                time1, progress1 = big_slope_points[i]
                time2, progress2 = big_slope_points[j]
                if abs(progress1 - progress2) < 0.15:
                    continue # 忽略相近的 progress 减少误差 (15%) 
                default_msec_estimate = abs(time1 - time2) / abs(progress1 - progress2)
                DefaultMsecs.append(default_msec_estimate)


    if not DefaultMsecs:
        print_info = "estimate_touch_DefaultMsec: no valid touch data"
        return 0, 0, 0, print_info
    
    length = len(DefaultMsecs)
    mean = np.mean(DefaultMsecs)
    min = np.min(DefaultMsecs)
    max = np.max(DefaultMsecs)
    median = np.median(DefaultMsecs)
    std_dev = np.std(DefaultMsecs)
    print_info1 = f"touch DefaultMsec {length}: [Median {median:.3f}], Min {min:.3f}, Max {max:.3f}, Mean {mean:.3f}, Std Dev {std_dev:.3f}"

    touch_DefaultMsec, touch_OptionNotespeed, touch_SpeedIndex, print_info2 = get_touch_DefaultMsec(median)
    return touch_DefaultMsec, touch_OptionNotespeed, touch_SpeedIndex, f"{print_info1}\n{print_info2}"





def get_touch_DefaultMsec(detected_touch_DefaultMsec):

    def get_standard_touch_DefaultMsec(ui_speed):
        # 游戏源码实现
        option_touchspeed_dict = {
            1.00: 175.0, 1.25: 183.0, 1.50: 200.0, 1.75: 212.0,
            2.00: 225.0, 2.25: 237.0, 2.50: 250.0, 2.75: 262.0,
            3.00: 275.0, 3.25: 283.0, 3.50: 300.0, 3.75: 312.0,
            4.00: 325.0, 4.25: 337.0, 4.50: 350.0, 4.75: 375.0,
            5.00: 400.0, 5.25: 425.0, 5.50: 450.0, 5.75: 475.0,
            6.00: 500.0, 6.25: 525.0, 6.50: 550.0, 6.75: 575.0,
            7.00: 600.0, 7.25: 625.0, 7.50: 650.0, 7.75: 675.0,
            8.00: 700.0, 8.25: 725.0, 8.50: 750.0, 8.75: 775.0,
            9.00: 800.0, 9.25: 825.0, 9.50: 850.0, 9.75: 875.0,
            10.00: 900.0
        }
        ui_speed = f'{ui_speed:.2f}'
        OptionNotespeed = option_touchspeed_dict[float(ui_speed)]
        NoteSpeedForBeat = 1000 / (OptionNotespeed / 60)
        DefaultMsec = NoteSpeedForBeat * 4
        return DefaultMsec, OptionNotespeed
    
    # 查找最接近的 DefaultMsec
    cloest_DefaultMsec = 0
    cloest_i = 0
    cloest_OptionNotespeed = 0
    i = 1
    while i <= 10:

        DefaultMsec, OptionNotespeed = get_standard_touch_DefaultMsec(i)

        if abs(DefaultMsec - detected_touch_DefaultMsec) < abs(cloest_DefaultMsec - detected_touch_DefaultMsec):
            cloest_DefaultMsec = DefaultMsec
            cloest_i = i
            cloest_OptionNotespeed = OptionNotespeed
        i += 0.25

    print_info = f"estimate touch speed: {cloest_i:.2f} - {cloest_DefaultMsec:.3f}ms (detect {detected_touch_DefaultMsec:.3f}ms)"

    return cloest_DefaultMsec, cloest_OptionNotespeed, cloest_i, print_info
