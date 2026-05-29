import numpy as np

from .shared_context import *



def analyze_touch_time(shared_context, touch_data):
    """
    返回：
    dict{
        key: 同 preprocess_touch_data,
        value: time
    }
    """

    touch_info = {}

    for key, path in touch_data.items():

        times = []

        # 平均所有轨迹的到达时间
        for point in path:
            frame_num = point['frame']
            dist = point['dist']

            reach_end_Msec = predict_touch_reach_end_time(shared_context, dist, frame_num, shared_context.touch_travel_dist)
            if reach_end_Msec != 0:
                times.append(reach_end_Msec)
                
        mean = np.mean(times)
        touch_info[key] = mean

        # print(f"Touch ID {track_id} Position {position}:")
        # min = np.min(times)
        # max = np.max(times)
        # median = np.median(times)
        # std_dev = np.std(times)
        # print(f"  Mean {mean:.3f}, Min {min:.3f}, Max {max:.3f}, Median {median:.3f}, Std Dev {std_dev:.3f}")


    return touch_info





def predict_touch_reach_end_time(shared_context, dist, cur_frame, total_dist):
    '''
    正向：
    根据 time_progress = (current_time - move_start_time) / DefaultMsec 获得 time_progress
    应用缓动函数, location_progress = 缓动函数(time_progress)
    根据 location_progress 决定4个三角距离中心点的距离
    current_Dist = total_Dist * (1 - location_progress) 纯线性的

    逆向：
    反推 location_progress = 1 - current_Dist / total_Dist
    二分法, 通过location_progress反推出time_progress ( y -> x )
    反推 move_start_time = current_time - time_progress * DefaultMsec
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


    # 反推 location_progress
    location_progress = 1 - dist / total_dist
    if location_progress < 0.15 or location_progress > 0.85:
        return 0
    # 反推 time_progress
    time_progress = reverse_function(location_progress)
    # 反推 move_start_time
    cur_time = shared_context.frame_to_msec(cur_frame)
    move_start_time = cur_time - time_progress * shared_context.touch_DefaultMsec
    reach_end_time = move_start_time + shared_context.touch_DefaultMsec

    return reach_end_time
