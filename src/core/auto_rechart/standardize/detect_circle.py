import cv2
import numpy as np
from typing import Tuple
from pathlib import Path

from ...schemas.op_result import OpResult, ok, err, print_op_result




def main(input_video: Path,
         mode: str,
         need_screen_rectification: bool,
         start_sec: float | None = None
        ) -> OpResult[Tuple[Tuple[int, int], int]]:
    """
    检测视频中的圆形判定线
    
    Args:
        input_video(Path): 输入视频路径
        mode(str): 视频模式（'source video'或'camera footage'）
        need_screen_rectification(bool): 是否需要画面矫正
            start_sec(float | None): 开始时间(秒)

    Returns:
        OpResult -> (circle_center, circle_radius)
    """

    try:
        # 获取视频基本信息
        cap = cv2.VideoCapture(input_video)
        if not cap.isOpened():
            return err(f"Cannot open video file: {input_video}")
        video_width = round(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        video_height = round(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        total_frames = round(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = cap.get(cv2.CAP_PROP_FPS)

        # 如果跳过检测，直接返回屏幕中心点
        if not need_screen_rectification:
            print("Detect circle...skip")
            # 默认已经全屏并且在屏幕中心
            circle_center = (video_width // 2, video_height // 2)
            circle_radius = min(video_width, video_height) // 2
            return ok((circle_center, circle_radius))
        


        # 开始圆形检测

        target_circles_quantity = 20  # 期望检测到20个圆形以确定最终结果

        # 允许圆圈半径 25%-55%，对应直径 50%-110%
        # 也就是说圆形起码要占据视频宽高的一半
        video_size = min(video_width, video_height)
        r_small = round(video_size * 0.25)
        r_large = round(video_size * 0.55)

        # 从 start_sec 往前 4 秒开始搜，总共搜 5 秒
        search_start_sec = max((start_sec if start_sec is not None else 0.0) - 4.0, 0.0)
        search_end_sec = search_start_sec + 5.0
        search_start_frame = round(search_start_sec * fps)
        search_end_frame = min(total_frames, round(search_end_sec * fps))

        if search_start_frame >= total_frames or search_end_frame <= search_start_frame:
            circle_center = (video_width // 2, video_height // 2)
            circle_radius = min(video_width, video_height) // 2 - 2
            print("Initial detection...fallback")
            print(f"  Circle center: {circle_center}, radius: {circle_radius}")
            return ok((circle_center, circle_radius))

        cap.set(cv2.CAP_PROP_POS_FRAMES, search_start_frame)

        frame_counter = 0
        circles_detected = []

        # 处理帧
        while frame_counter < (search_end_frame - search_start_frame):

            # 打印进度
            frame_counter += 1
            print(f"Initial detection...{frame_counter}/{search_end_frame - search_start_frame}", end="\r")

            ret, frame = cap.read()
            if not ret: break  # 视频结束

            processed_frame = preprocess_frame(frame, mode)
            
            # 寻找轮廓并过滤有效圆形
            valid_circles = filter_valid_circles(processed_frame, r_small, r_large)
            
            # 如果找到合适的圆形，选择半径最大的
            if valid_circles:
                valid_circles.sort(key=lambda x: x[2], reverse=True)
                x, y, radius = valid_circles[0]
                circles_detected.append((round(x), round(y), round(radius)))

                if len(circles_detected) >= target_circles_quantity : break
            
        
        if len(circles_detected) < target_circles_quantity:
            circle_center = (video_width // 2, video_height // 2)
            circle_radius = min(video_width, video_height) // 2 - 2
            print("Initial detection...fallback")
            print(f"  Circle center: {circle_center}, radius: {circle_radius}")
            return ok((circle_center, circle_radius))
        
        # 取出现次数最多的圆
        most_common = max(set(circles_detected), key=circles_detected.count)
        circle_center = (most_common[0], most_common[1])
        circle_radius = most_common[2]

        # 微调
        circle_center = (circle_center[0]+1, circle_center[1]) # x轴左移1像素
        circle_radius -= int(video_size / 800)  # 半径减掉一点以避免边缘误差

        print(f"Initial detection...ok{' '*12}")
        print(f"  Circle center: {circle_center}, radius: {circle_radius}")
        
        return ok((circle_center, circle_radius))
    
    except Exception as e:
        return err(f"Unpected error in detect_circle: {str(e)}", error_raw = e)
    
    finally:
        try: cap.release()
        except: pass


 
def preprocess_frame(frame, mode: str):
    """预处理 帧画面"""

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    # 如果是录屏，直接固定阈值二值化
    if mode == 'source video':
        _, binary = cv2.threshold(gray, 60, 255, cv2.THRESH_BINARY)

    # 如果是摄屏，使用自适应 Canny 边缘检测    
    else: # mode == 'camera footage'
        median = np.median(gray)
        lower = int(max(0, 0.66 * median))
        upper = int(min(255, 1.33 * median))
        binary = cv2.Canny(gray, lower, upper)
        # 形态学闭操作，连接断裂边缘
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)

    return binary



def filter_valid_circles(processed_frame, r_small, r_large) -> list[tuple[float, float, float]] | None:
    """
    在帧画面中查找轮廓，如果轮廓接近圆形且尺寸合适，返回最小包围圆
    """

    # 查找轮廓
    contours, _ = cv2.findContours(processed_frame, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    
    valid_circles = []

    # 遍历所有轮廓
    for contour in contours:
        # 计算最小包围圆
        (x, y), radius = cv2.minEnclosingCircle(contour)
        # 忽略尺寸不对的轮廓
        if radius < r_small or radius > r_large: 
            continue
        # 验证轮廓是否接近圆形 (圆形度大于0.9）
        area = cv2.contourArea(contour)
        circle_area = 3.14 * radius * radius
        circularity = area / circle_area
        if circularity <= 0.9:
            continue

        valid_circles.append((x, y, radius))
    
    return valid_circles if valid_circles else None
