import cv2
import numpy as np
from pathlib import Path
from typing import Dict, Optional, Tuple
import ctypes
import time

from ...schemas.op_result import OpResult, ok, err

from ._pc_drawing import DrawingMixin
from ._pc_transform import TransformMixin
from ._pc_interaction import InteractionMixin




class PerspectiveCorrection(DrawingMixin, TransformMixin, InteractionMixin):
    
    SLIDER_MARGIN_X = 20
    SLIDER_MARGIN_Y = 10
    SLIDER_HEIGHT = 30
    CONTROL_PANEL_HEIGHT = SLIDER_MARGIN_Y * 6 + SLIDER_HEIGHT * 4

    FRAME_PREVIEW_SIZE = 800
    WINDOW_WIDTH = FRAME_PREVIEW_SIZE * 2
    WINDOW_HEIGHT = FRAME_PREVIEW_SIZE + CONTROL_PANEL_HEIGHT

    SLIDER_KNOB_RADIUS = 6
    PERSPECTIVE_POINT_RADIUS = 8
    OUTER_RADIUS_PLUS = 3
    POINT_COLOR = (0, 128, 255) # 橘色

    # 面板中心固定参考红点 (用于可视化中心拖拽点的偏移)
    CENTER_REF_RADIUS = 4
    CENTER_REF_COLOR = (0, 0, 255)   # 实心小红点 (BGR 红)
    CENTER_REF_LINE_THICK = 1
    CENTER_REF_LINE_COLOR = (0, 0, 255)

    SCALE_MIN_PERCENT = 20
    SCALE_MAX_PERCENT = 300
    SCALE_DEFAULT_PERCENT = 100

    STRETCH_MIN_PERCENT = 50
    STRETCH_MAX_PERCENT = 200
    STRETCH_DEFAULT_PERCENT = 100

    OFFSET_MIN_PX = -800
    OFFSET_MAX_PX = 800
    OFFSET_DEFAULT_PX = 0

    FINE_OFFSET_MIN_PX = -100
    FINE_OFFSET_MAX_PX = 100
    FINE_OFFSET_DEFAULT_PX = 0

    BRIGHTNESS_MIN_PERCENT = -100
    BRIGHTNESS_MAX_PERCENT = 100
    BRIGHTNESS_DEFAULT_PERCENT = 0

    

    def __init__(self,
                 input_video: Path,
                 circle_center: Tuple[int, int],
                 circle_radius: int,
                 start_sec: float,
                 end_sec: float):
        """
        Args:
            input_video(Path): 输入视频路径
            circle_center(Tuple[int, int]): 圆心坐标 (x, y)
            circle_radius(int): 圆半径
            start_sec(float): 开始时间(秒)
            end_sec(float): 结束时间(秒)
        """

        self.circle_center = circle_center
        self.circle_radius = circle_radius

        self.input_video = input_video
        self.start_sec = 0.0 if start_sec is None else float(start_sec)
        self.end_sec = 0.0 if end_sec is None else float(end_sec)

        self.frame_width = 0
        self.frame_height = 0
        self.quad_points: Optional[np.ndarray] = None
        # zoom_percent, top_left_x, top_left_y
        self.left_panel_meta: Optional[Dict[str, float]] = None

        # 正在拖动的透视点索引，-1表示没有
        self.dragging_point_index = -1
        # 正在拖动的滑块名称，None表示没有
        self.dragging_slider_name: Optional[str] = None

        # 正在拖动的中心点面板，None表示没有
        self.center_drag_panel: Optional[str] = None  # None / "left" / "right"
        self._center_drag_mouse: Optional[Tuple[float, float]] = None
        self._center_drag_start_mouse: Optional[Tuple[float, float]] = None
        self._center_drag_start_offset_x: int = 0
        self._center_drag_start_offset_y: int = 0

        # 左面板的输入偏移
        self.input_offset_x_px = self.OFFSET_DEFAULT_PX
        self.input_offset_y_px = self.OFFSET_DEFAULT_PX

        self.input_zoom_percent = self.SCALE_DEFAULT_PERCENT
        self.output_zoom_percent = self.SCALE_DEFAULT_PERCENT
        self.output_stretch_x_percent = self.STRETCH_DEFAULT_PERCENT
        self.output_stretch_y_percent = self.STRETCH_DEFAULT_PERCENT
        self.output_offset_x_px = self.OFFSET_DEFAULT_PX
        self.output_offset_y_px = self.OFFSET_DEFAULT_PX
        self.output_fine_offset_x_px = self.FINE_OFFSET_DEFAULT_PX
        self.output_fine_offset_y_px = self.FINE_OFFSET_DEFAULT_PX
        self.output_brightness_percent = self.BRIGHTNESS_DEFAULT_PERCENT





    def main(self) -> OpResult[
        Tuple[
            Tuple[int, int],
            float,
            float,
            float,
            Optional[Tuple[float, float, float, float, float, float, float, float]],
            float,
        ]
    ]:

        """
        画面矫正

        Returns:
            OpResult -> (circle_center, circle_radius,
                         scale_x, scale_y,
                         perspective_points,
                         brightness)
            
        perspective_points 是 tuple 或 None。
        透视四点 float 坐标 (tl_x, tl_y, tr_x, tr_y, bl_x, bl_y, br_x, br_y)
        """
        
        cap = None        

        try:
            # 1. 打开视频，获取基本信息
            cap = cv2.VideoCapture(str(self.input_video))
            if not cap.isOpened():
                return err(f"Cannot open video file: {self.input_video}")

            fps = cap.get(cv2.CAP_PROP_FPS)
            if fps <= 0: fps = 60.0
            total_frames = max(1, round(cap.get(cv2.CAP_PROP_FRAME_COUNT)))
            start_frame = max(0, round(self.start_sec * fps))
            end_frame = round(self.end_sec * fps) if self.end_sec > 0 else total_frames - 1
            end_frame = min(max(start_frame, end_frame), total_frames - 1)
            self.frame_width = max(1, round(cap.get(cv2.CAP_PROP_FRAME_WIDTH)))
            self.frame_height = max(1, round(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))


            # 2. 创建 OpenCV 窗口
            window_name = "Screen Rectification"
            cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
            cv2.resizeWindow(window_name, self.WINDOW_WIDTH, self.WINDOW_HEIGHT)
            cv2.setMouseCallback(window_name, self._on_mouse_event)
            # 使用 ctypes 获取屏幕尺寸
            user32 = ctypes.windll.user32
            screen_width = user32.GetSystemMetrics(0)
            screen_height = user32.GetSystemMetrics(1)
            # 每次打开窗口都默认居中显示
            pos_x = (screen_width - self.WINDOW_WIDTH) // 2
            pos_y = (screen_height - self.WINDOW_HEIGHT) // 2
            cv2.moveWindow(window_name, pos_x, pos_y)


            # 3. 将输入的 已检测到的圆心/半径 参数
            #    换算为右侧面板的初始 zoom 和 offset
            zoom_percent = round(self.FRAME_PREVIEW_SIZE / 2 / self.circle_radius * 100)
            if self.SCALE_MIN_PERCENT <= zoom_percent <= self.SCALE_MAX_PERCENT:
                self.input_zoom_percent = zoom_percent
                self.output_zoom_percent = zoom_percent
            input_cx = self.circle_center[0]
            input_cy = self.circle_center[1]
            frame_cx = self.frame_width / 2
            frame_cy = self.frame_height / 2
            cx_offset = input_cx - frame_cx
            cy_offset = input_cy - frame_cy
            offset_x = round(-1 * cx_offset * self.output_zoom_percent / 100)
            offset_y = round(-1 * cy_offset * self.output_zoom_percent / 100)
            if self.OFFSET_MIN_PX <= offset_x <= self.OFFSET_MAX_PX:
                self.output_offset_x_px = offset_x
            if self.OFFSET_MIN_PX <= offset_y <= self.OFFSET_MAX_PX:
                self.output_offset_y_px = offset_y

            
            # 4. 初始化播放状态
            is_playing = True
            raw_frame = None

            # 高帧率跳帧: fps > 70 时目标帧率减半, 主循环每隔一帧 cap.read() 丢弃
            # 最多跳一帧 (不递归减半): 110fps→55fps, 200fps→100fps
            skip_frame = fps > 70.0
            effective_fps = fps / 2.0 if skip_frame else fps

            # 动态delay保证播放时接近目标fps
            delay = 1
            last_time = time.time() * 1000
            target_delay_ms = max(1, int(1000 / effective_fps))
            delay_when_paused_ms = 50 # 暂停时视为 20 fps，省点性能

            # 跳帧 toggle: 0=保留本帧, 1=跳过下一帧 (仅播放时生效)
            skip_toggle = 0

            # 从 start_frame 开始播放
            cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
            current_frame_idx = start_frame







            # 5. 主循环

            while True:
                # 如果窗口被关闭了，就退出循环
                if cv2.getWindowProperty(window_name, cv2.WND_PROP_VISIBLE) < 1:
                    break



                # 5a. 读取下一帧
                if is_playing or raw_frame is None:
                    # 高帧率跳帧: toggle=1 时本帧将被丢弃, 用 cap.grab() 仅推进帧指针, 跳过解码
                    will_skip = skip_frame and is_playing and skip_toggle == 1

                    if will_skip:
                        ret = cap.grab()
                    else:
                        ret, raw_frame = cap.read()

                    if not ret or current_frame_idx > end_frame:
                        # 播放到 末尾或 end_frame 后循环回 start_frame
                        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
                        current_frame_idx = start_frame
                        continue
                    current_frame_idx += 1

                    # 跳过的帧: 不解码就不更新 raw_frame, 保持上一渲染帧, 直接进入下一轮
                    if will_skip:
                        skip_toggle = 0
                        continue

                    self.frame_height, self.frame_width = raw_frame.shape[:2]
                    # 如果没有透视四点，生成默认的透视四点
                    if self.quad_points is None:
                        self.quad_points = self._build_default_quad(self.frame_width, self.frame_height)

                    # 本帧将渲染, 置 toggle=1 让下一帧走 grab 跳过
                    if skip_frame and is_playing:
                        skip_toggle = 1

                

                # 锁定本帧的 zoom_percent
                current_input_zoom_percent = self.input_zoom_percent
                current_output_zoom_percent = self.output_zoom_percent



                # 5b. 左面板

                # 绘制画面
                left_panel, left_meta = self._compose_panel(
                    raw_frame, current_input_zoom_percent,
                    offset_x=self.input_offset_x_px,
                    offset_y=self.input_offset_y_px)
                # 绘制四边形透视点
                self.left_panel_meta = left_meta
                self._draw_quad_overlay(left_panel, left_meta)
                # 绘制中心拖拽点
                self._draw_center_handle(left_panel, "left")



                # 5c. 右面板

                # 右面板: 透视 → 拉伸 → 缩放 → 位移 → 亮度
                right_panel = self._render_output_panel(raw_frame)
                # 绘制固定参考标记
                self._draw_reference_marks(right_panel)
                # 绘制中心拖拽点
                self._draw_center_handle(right_panel, "right")



                # 5d. 绘制最终整体画布
                canvas = np.zeros((self.WINDOW_HEIGHT, self.WINDOW_WIDTH, 3), dtype=np.uint8)
                canvas[:self.FRAME_PREVIEW_SIZE, :self.FRAME_PREVIEW_SIZE] = left_panel
                canvas[:self.FRAME_PREVIEW_SIZE, self.FRAME_PREVIEW_SIZE:] = right_panel
                self._draw_combined_overlay(canvas, is_playing,
                                            current_input_zoom_percent,
                                            current_output_zoom_percent)

                cv2.imshow(window_name, canvas)



                # 5e. 帧率控制：动态 waitKey 补偿渲染耗时
                if is_playing:
                    current_time = time.time() * 1000
                    elapsed = current_time - last_time
                    last_time = current_time
                    delay = max(1, target_delay_ms - int(elapsed))
                else:
                    delay = delay_when_paused_ms

                key = cv2.waitKey(delay) & 0xFF
                if key == ord(" "):
                    is_playing = not is_playing
                elif key == 27:  # ESC
                    break

            




            # 6. 根据最终参数反算返回值
            circle_radius = self.FRAME_PREVIEW_SIZE / 2 / (self.output_zoom_percent / 100)
            offset_x = self.output_offset_x_px + self.output_fine_offset_x_px
            offset_y = self.output_offset_y_px + self.output_fine_offset_y_px
            cx_offset = -1 * offset_x / (self.output_zoom_percent / 100) / (self.output_stretch_x_percent / 100)
            cy_offset = -1 * offset_y / (self.output_zoom_percent / 100) / (self.output_stretch_y_percent / 100)
            output_cx = round(frame_cx + cx_offset)
            output_cy = round(frame_cy + cy_offset)
            scale_x = self.output_stretch_x_percent / 100
            scale_y = self.output_stretch_y_percent / 100
            brightness = self.output_brightness_percent / 100.0
            # 6a. 提取透视四边形四个点的坐标 (tl, tr, bl, br)
            if self.quad_points is not None:
                if np.array_equal(self.quad_points, self._build_default_quad(self.frame_width, self.frame_height)):
                    perspective_points = None
                else:
                    src_quad = self.quad_points.astype(np.float32)
                    dst_quad = self._build_target_quad(src_quad)
                    matrix = cv2.getPerspectiveTransform(src_quad, dst_quad)
                    frame_corners = np.array([
                        [[0.0, 0.0]],
                        [[float(self.frame_width - 1), 0.0]],
                        [[0.0, float(self.frame_height - 1)]],
                        [[float(self.frame_width - 1), float(self.frame_height - 1)]],
                    ], dtype=np.float32)
                    projected_corners = cv2.perspectiveTransform(frame_corners, matrix).reshape(-1, 2)
                    tl = projected_corners[0]
                    tr = projected_corners[1]
                    bl = projected_corners[2]
                    br = projected_corners[3]
                    perspective_points = (float(tl[0]), float(tl[1]),
                                          float(tr[0]), float(tr[1]),
                                          float(bl[0]), float(bl[1]),
                                          float(br[0]), float(br[1]))
            else:
                perspective_points = None
            
            return ok(((output_cx, output_cy),
                      circle_radius,
                      scale_x, scale_y,
                      perspective_points,
                      brightness))
                      

        except Exception as e:
            return err("Error in perspective correction preview", error_raw=e)

        finally:
            # . 清理：销毁窗口、释放视频
            try:
                cv2.destroyWindow(window_name)
            except Exception:
                pass
            try:
                cv2.destroyAllWindows()
            except Exception:
                pass
            if cap is not None:
                cap.release()
