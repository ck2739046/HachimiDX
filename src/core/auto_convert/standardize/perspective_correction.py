import cv2
import numpy as np
from pathlib import Path
from typing import Dict, Optional, Tuple
import ctypes
import time
import os

from ...schemas.op_result import OpResult, ok, err
from src.services import PathManage




class PerspectiveCorrection:
    
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
            cap = cv2.VideoCapture(str(self.input_video))
            if not cap.isOpened():
                return err(f"Cannot open video file: {self.input_video}")
            
            # 从 cap 获取基本是视频信息
            fps = cap.get(cv2.CAP_PROP_FPS)
            if fps <= 0: fps = 60.0
            total_frames = max(1, round(cap.get(cv2.CAP_PROP_FRAME_COUNT)))
            start_frame = max(0, round(self.start_sec * fps))
            end_frame = round(self.end_sec * fps) if self.end_sec > 0 else total_frames - 1
            end_frame = min(max(start_frame, end_frame), total_frames - 1)
            self.frame_width = max(1, round(cap.get(cv2.CAP_PROP_FRAME_WIDTH)))
            self.frame_height = max(1, round(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))


            # 设置窗口
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


            # 将传入的圆心和半径转化为 offset 和 zoom
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

            
            is_playing = True
            raw_frame = None

            # 动态delay保证播放时接近目标fps
            delay = 1
            last_time = time.time() * 1000
            target_delay_ms = max(1, int(1000 / fps))
            delay_when_paused_ms = 50 # 暂停时视为 20 fps，省点性能

            # 从 start_frame 开始播放
            cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
            current_frame_idx = start_frame

            while True:
                # 如果窗口被关闭了，就退出循环
                if cv2.getWindowProperty(window_name, cv2.WND_PROP_VISIBLE) < 1:
                    break

                if is_playing or raw_frame is None:
                    ret, raw_frame = cap.read()
                    if not ret or current_frame_idx > end_frame:
                        # 播放到 末尾或 end_frame 后循环回 start_frame
                        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
                        current_frame_idx = start_frame
                        continue
                    current_frame_idx += 1

                    self.frame_height, self.frame_width = raw_frame.shape[:2]
                    if self.quad_points is None:
                        self.quad_points = self._build_default_quad(self.frame_width, self.frame_height)

                current_input_zoom_percent = self.input_zoom_percent
                current_output_zoom_percent = self.output_zoom_percent

                left_panel, left_meta = self._compose_panel(raw_frame, current_input_zoom_percent)
                self.left_panel_meta = left_meta
                self._draw_quad_overlay(left_panel, left_meta)

                corrected_frame = self._apply_perspective_correction(raw_frame)
                corrected_frame = self._apply_output_stretch(corrected_frame)
                corrected_frame = self._apply_output_brightness(corrected_frame)
                right_panel, _ = self._compose_panel(
                    corrected_frame,
                    current_output_zoom_percent,
                    offset_x=self.output_offset_x_px + self.output_fine_offset_x_px,
                    offset_y=self.output_offset_y_px + self.output_fine_offset_y_px,
                )
                # 在右侧面板上绘制固定参考标记
                self._draw_reference_marks(right_panel)

                canvas = np.zeros((self.WINDOW_HEIGHT, self.WINDOW_WIDTH, 3), dtype=np.uint8)
                canvas[:self.FRAME_PREVIEW_SIZE, :self.FRAME_PREVIEW_SIZE] = left_panel
                canvas[:self.FRAME_PREVIEW_SIZE, self.FRAME_PREVIEW_SIZE:] = right_panel
                self._draw_combined_overlay(canvas, is_playing,
                                            current_input_zoom_percent,
                                            current_output_zoom_percent)

                cv2.imshow(window_name, canvas)


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

            
            # 计算 return 值
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
            # 提取透视四边形四个点的坐标 (tl, tr, bl, br)
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




    




    def _compose_panel(self, frame, zoom_percent: float, offset_x: int = 0, offset_y: int = 0):

        # 空画布
        canvas = np.zeros((self.FRAME_PREVIEW_SIZE, self.FRAME_PREVIEW_SIZE, 3), dtype=np.uint8)

        frame_h, frame_w = frame.shape[:2]
        scaled_w = max(1, int(round(frame_w * zoom_percent / 100)))
        scaled_h = max(1, int(round(frame_h * zoom_percent / 100)))
        scaled = cv2.resize(frame, (scaled_w, scaled_h), interpolation=cv2.INTER_LINEAR)

        top_left_x = int(round((self.FRAME_PREVIEW_SIZE - scaled_w) * 0.5 + offset_x))
        top_left_y = int(round((self.FRAME_PREVIEW_SIZE - scaled_h) * 0.5 + offset_y))

        dst_x1 = max(0, top_left_x)
        dst_y1 = max(0, top_left_y)
        dst_x2 = min(self.FRAME_PREVIEW_SIZE, top_left_x + scaled_w)
        dst_y2 = min(self.FRAME_PREVIEW_SIZE, top_left_y + scaled_h)

        src_x1 = max(0, -top_left_x)
        src_y1 = max(0, -top_left_y)
        src_x2 = src_x1 + max(0, dst_x2 - dst_x1)
        src_y2 = src_y1 + max(0, dst_y2 - dst_y1)

        if src_x1 < src_x2 and src_y1 < src_y2 and dst_x1 < dst_x2 and dst_y1 < dst_y2:
            canvas[dst_y1:dst_y2, dst_x1:dst_x2] = scaled[src_y1:src_y2, src_x1:src_x2]

        meta = {
            "zoom_percent": float(zoom_percent),
            "top_left_x": float(top_left_x),
            "top_left_y": float(top_left_y),
        }
        return canvas, meta





    def _draw_reference_marks(self, panel: np.ndarray) -> None:
        """在右侧面板上绘制固定参考标记"""
        height, width = panel.shape[:2]
        center_x = width // 2
        center_y = height // 2
        
        # 半径为5的红色圆形（中心点）
        cv2.circle(panel, (center_x, center_y),
                   5, (0, 0, 255), 2)
        
        # 半径为600的绿色圆形
        d = self.FRAME_PREVIEW_SIZE * 960/1080 # 判定线参考圆
        cv2.circle(panel, (center_x, center_y),
                   round(d/2), (0, 255, 0), 2)
        
        # 垂直线 x 1/3, 2/3
        v_line1_x = int(round(width / 3))
        v_line2_x = int(round(2 * width / 3))
        cv2.line(panel, (v_line1_x, 0), (v_line1_x, height), (0, 255, 0), 1)
        cv2.line(panel, (v_line2_x, 0), (v_line2_x, height), (0, 255, 0), 1)
        
        # 水平线 y 1/3, 2/3
        h_line1_y = int(round(height / 3))
        h_line2_y = int(round(2 * height / 3))
        cv2.line(panel, (0, h_line1_y), (width, h_line1_y), (0, 255, 0), 1)
        cv2.line(panel, (0, h_line2_y), (width, h_line2_y), (0, 255, 0), 1)




    def _build_default_quad(self, frame_w: int, frame_h: int) -> np.ndarray:
        """默认四点的位置在画面中心，大小占画面约20%（宽高各10%）"""
        cx = frame_w / 2.0
        cy = frame_h / 2.0
        half_w = frame_w * 0.1
        half_h = frame_h * 0.1
        return np.array(
            [
                [cx - half_w, cy - half_h],
                [cx + half_w, cy - half_h],
                [cx + half_w, cy + half_h],
                [cx - half_w, cy + half_h],
            ],
            dtype=np.float32,
        )
    

    

    def _draw_quad_overlay(self, panel: np.ndarray, meta: Dict[str, float]) -> None:
        if self.quad_points is None:
            return

        canvas_points = []
        for pt in self.quad_points:
            canvas_points.append(self._frame_to_panel(pt, meta))
        canvas_points = np.array(canvas_points, dtype=np.int32)

        cv2.polylines(panel, [canvas_points], isClosed=True, color=(0, 255, 0), thickness=1)

        for i, pt in enumerate(canvas_points):
            cv2.circle(panel, (int(pt[0]), int(pt[1])),
                       self.PERSPECTIVE_POINT_RADIUS,
                       self.POINT_COLOR, 1)
            cv2.circle(panel, (int(pt[0]), int(pt[1])),
                       self.PERSPECTIVE_POINT_RADIUS + self.OUTER_RADIUS_PLUS,
                       (255, 255, 255), 1)
            
            # 在点旁边标记序号
            cv2.putText(
                panel,
                str(i + 1),
                (int(pt[0]) + 10, int(pt[1]) - 10),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,  # 字体大小
                (255, 255, 255),
                1,    # 字体粗细
                cv2.LINE_AA,
            )




    def _draw_combined_overlay(self, canvas: np.ndarray, is_playing: bool,
                               input_zoom_percent: float, output_zoom_percent: float) -> None:
        
        # 中间纵向的分割线
        cv2.line(canvas, (self.FRAME_PREVIEW_SIZE, 0), (self.FRAME_PREVIEW_SIZE, self.FRAME_PREVIEW_SIZE), (255, 255, 255), 1)

        self._draw_slider_panel(canvas, 0, # 左侧 panel
                                "Scale", input_zoom_percent, "input")
        self._draw_slider_panel(canvas, self.FRAME_PREVIEW_SIZE, # 右侧 panel
                                "Scale", output_zoom_percent, "output")
        self._draw_left_brightness_slider(canvas)
        self._draw_right_stretch_sliders(canvas)
        self._draw_right_offset_sliders(canvas)
        self._draw_right_fine_offset_sliders(canvas)

        cv2.putText(
            canvas,
            "SPACE: pause/play  ESC: exit",
            (12, self.WINDOW_HEIGHT - 15),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )

        if not is_playing:
            cv2.putText(
                canvas,
                "PAUSED",
                (12, self.WINDOW_HEIGHT - 40),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 255, 255), # yellow
                2,
                cv2.LINE_AA,
            )





    def _draw_slider_panel(self,
                           canvas: np.ndarray,
                           panel_offset_x: int,
                           label: str,
                           zoom_percent: float,
                           slider_name: str) -> None:
        
        control_top = self.FRAME_PREVIEW_SIZE
        control_bottom = self.WINDOW_HEIGHT

        # 清空旧 slider 区域
        cv2.rectangle(
            canvas,
            (panel_offset_x, control_top),
            (panel_offset_x + self.FRAME_PREVIEW_SIZE, control_bottom),
            (0, 0, 0),
            -1,
        )

        cv2.rectangle(
            canvas,
            (panel_offset_x, control_top),
            (panel_offset_x + self.FRAME_PREVIEW_SIZE - 1, control_bottom - 1),
            (70, 70, 70),
            1,
        )

        slider_geo = self._get_slider_geometries()[slider_name]
        self._draw_slider(
            canvas=canvas,
            label=f"{label}: {round(zoom_percent)}%",
            value_text=f"{zoom_percent / 100:.2f}x",
            is_selected=(self.dragging_slider_name == slider_name),
            track_x1=slider_geo["x1"],
            track_x2=slider_geo["x2"],
            track_y=slider_geo["y"],
            percent_value=round(zoom_percent),
            min_percent=slider_geo["min"],
            max_percent=slider_geo["max"],
        )






    def _draw_right_stretch_sliders(self, canvas: np.ndarray) -> None:
        geo = self._get_slider_geometries()
        x_geo = geo["stretch_x"]
        y_geo = geo["stretch_y"]

        self._draw_slider(
            canvas=canvas,
            label=f"H stretch: {self.output_stretch_x_percent}%",
            value_text=f"{self.output_stretch_x_percent}%",
            is_selected=(self.dragging_slider_name == "stretch_x"),
            track_x1=x_geo["x1"],
            track_x2=x_geo["x2"],
            track_y=x_geo["y"],
            percent_value=self.output_stretch_x_percent,
            min_percent=x_geo["min"],
            max_percent=x_geo["max"],
        )
        self._draw_slider(
            canvas=canvas,
            label=f"V stretch: {self.output_stretch_y_percent}%",
            value_text=f"{self.output_stretch_y_percent}%",
            is_selected=(self.dragging_slider_name == "stretch_y"),
            track_x1=y_geo["x1"],
            track_x2=y_geo["x2"],
            track_y=y_geo["y"],
            percent_value=self.output_stretch_y_percent,
            min_percent=y_geo["min"],
            max_percent=y_geo["max"],
        )


    def _draw_left_brightness_slider(self, canvas: np.ndarray) -> None:
        geo = self._get_slider_geometries()["brightness"]
        brightness_value = self.output_brightness_percent / 100.0

        self._draw_slider(
            canvas=canvas,
            label=f"Brightness: {brightness_value:+.2f}",
            value_text=f"{brightness_value:+.2f}",
            is_selected=(self.dragging_slider_name == "brightness"),
            track_x1=geo["x1"],
            track_x2=geo["x2"],
            track_y=geo["y"],
            percent_value=self.output_brightness_percent,
            min_percent=geo["min"],
            max_percent=geo["max"],
        )






    def _draw_right_offset_sliders(self, canvas: np.ndarray) -> None:
        geo = self._get_slider_geometries()
        x_geo = geo["offset_x"]
        y_geo = geo["offset_y"]

        self._draw_slider(
            canvas=canvas,
            label=f"H offset: {self.output_offset_x_px}px",
            value_text=f"{self.output_offset_x_px}px",
            is_selected=(self.dragging_slider_name == "offset_x"),
            track_x1=x_geo["x1"],
            track_x2=x_geo["x2"],
            track_y=x_geo["y"],
            percent_value=self.output_offset_x_px,
            min_percent=x_geo["min"],
            max_percent=x_geo["max"],
        )
        self._draw_slider(
            canvas=canvas,
            label=f"V offset: {self.output_offset_y_px}px",
            value_text=f"{self.output_offset_y_px}px",
            is_selected=(self.dragging_slider_name == "offset_y"),
            track_x1=y_geo["x1"],
            track_x2=y_geo["x2"],
            track_y=y_geo["y"],
            percent_value=self.output_offset_y_px,
            min_percent=y_geo["min"],
            max_percent=y_geo["max"],
        )






    def _draw_right_fine_offset_sliders(self, canvas: np.ndarray) -> None:
        geo = self._get_slider_geometries()
        x_geo = geo["fine_offset_x"]
        y_geo = geo["fine_offset_y"]

        self._draw_slider(
            canvas=canvas,
            label=f"H fine offset: {self.output_fine_offset_x_px}px",
            value_text=f"{self.output_fine_offset_x_px}px",
            is_selected=(self.dragging_slider_name == "fine_offset_x"),
            track_x1=x_geo["x1"],
            track_x2=x_geo["x2"],
            track_y=x_geo["y"],
            percent_value=self.output_fine_offset_x_px,
            min_percent=x_geo["min"],
            max_percent=x_geo["max"],
        )
        self._draw_slider(
            canvas=canvas,
            label=f"V fine offset: {self.output_fine_offset_y_px}px",
            value_text=f"{self.output_fine_offset_y_px}px",
            is_selected=(self.dragging_slider_name == "fine_offset_y"),
            track_x1=y_geo["x1"],
            track_x2=y_geo["x2"],
            track_y=y_geo["y"],
            percent_value=self.output_fine_offset_y_px,
            min_percent=y_geo["min"],
            max_percent=y_geo["max"],
        )


    def _draw_slider(self,
                     canvas: np.ndarray,
                     label: str,          # slider 左上方的标签文本
                     value_text: str,     # slider 右上方的数值文本
                     is_selected: bool,   # 是否正在被拖动（选中）
                     track_x1: int,
                     track_x2: int,
                     track_y: int,
                     percent_value: int,  # 用于绘制滑块位置
                     min_percent: int,
                     max_percent: int) -> None:
        
        # slider 左上方的标签
        label_y = track_y - 14
        cv2.putText(
            canvas,
            label,
            (track_x1, label_y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.46,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )

        # 滑轨
        cv2.line(canvas, (track_x1, track_y), (track_x2, track_y), (170, 170, 170), 2)

        # 滑块
        knob_x = int(round(self._slider_percent_to_x(percent_value, track_x1, track_x2, min_percent, max_percent)))
        knob_color = self.POINT_COLOR if not is_selected else (0, 200, 255)
        cv2.circle(canvas, (knob_x, track_y),
                   self.SLIDER_KNOB_RADIUS,
                   knob_color, -1) # 实心
        cv2.circle(canvas, (knob_x, track_y),
                   self.SLIDER_KNOB_RADIUS + self.OUTER_RADIUS_PLUS,
                   (255, 255, 255), 1)
        
        # slider 右上方的数值
        cv2.putText(
            canvas,
            value_text,
            (track_x2 - 94, label_y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.46,
            (200, 200, 200),
            1,
            cv2.LINE_AA,
        )






    def _slider_percent_to_x(self,
                             percent_value: int,
                             track_x1: int,
                             track_x2: int,
                             min_percent: int,
                             max_percent: int) -> float:
        clamped = self._clamp_value(percent_value, min_percent, max_percent)
        ratio = (clamped - min_percent) / float(max(1, max_percent - min_percent))
        return track_x1 + ratio * (track_x2 - track_x1)


    def _slider_x_to_percent(self,
                             x: float,
                             track_x1: int,
                             track_x2: int,
                             min_percent: int,
                             max_percent: int) -> int:
        ratio = (x - track_x1) / float(max(1, track_x2 - track_x1))
        percent = min_percent + ratio * (max_percent - min_percent)
        return self._clamp_value(int(round(percent)), min_percent, max_percent)


    def _clamp_value(self, value: int, min_value: int, max_value: int) -> int:
        return max(min_value, min(max_value, int(value)))


    def _get_slider_geometries(self) -> Dict[str, Dict[str, int]]:

        control_top = self.FRAME_PREVIEW_SIZE
        
        left_full_x1 = self.SLIDER_MARGIN_X
        left_full_x2 = self.FRAME_PREVIEW_SIZE - self.SLIDER_MARGIN_X
        right_full_x1 = self.FRAME_PREVIEW_SIZE + left_full_x1
        right_full_x2 = self.FRAME_PREVIEW_SIZE + left_full_x2

        # 右边实际滑条的长度 (减去了边距)
        available_len = right_full_x2 - right_full_x1
        # 将右侧滑条分成两半，中间的间距 = SLIDER_MARGIN_X
        half_len = max(1, int(available_len/2 - self.SLIDER_MARGIN_X/2))

        right_half_left_x1 = right_full_x1
        right_half_left_x2 = right_half_left_x1 + half_len
        right_half_right_x2 = right_full_x2
        right_half_right_x1 = right_half_right_x2 - half_len

        # 第一层
        y1 = control_top + self.SLIDER_MARGIN_Y*2 + self.SLIDER_HEIGHT // 2
        # 第二层
        y2 = y1 + self.SLIDER_MARGIN_Y + self.SLIDER_HEIGHT
        # 第三层
        y3 = y2 + self.SLIDER_MARGIN_Y + self.SLIDER_HEIGHT
        # 第四层（精细调整）
        y4 = y3 + self.SLIDER_MARGIN_Y + self.SLIDER_HEIGHT

        return {
            "input": {
                "x1": left_full_x1,
                "x2": left_full_x2,
                "y": y1,
                "min": self.SCALE_MIN_PERCENT,
                "max": self.SCALE_MAX_PERCENT,
            },
            "brightness": {
                "x1": left_full_x1,
                "x2": left_full_x2,
                "y": y2,
                "min": self.BRIGHTNESS_MIN_PERCENT,
                "max": self.BRIGHTNESS_MAX_PERCENT,
            },
            "output": {
                "x1": right_full_x1,
                "x2": right_full_x2,
                "y": y1,
                "min": self.SCALE_MIN_PERCENT,
                "max": self.SCALE_MAX_PERCENT,
            },
            "stretch_x": {
                "x1": right_half_left_x1,
                "x2": right_half_left_x2,
                "y": y2,
                "min": self.STRETCH_MIN_PERCENT,
                "max": self.STRETCH_MAX_PERCENT,
            },
            "stretch_y": {
                "x1": right_half_right_x1,
                "x2": right_half_right_x2,
                "y": y2,
                "min": self.STRETCH_MIN_PERCENT,
                "max": self.STRETCH_MAX_PERCENT,
            },
            "offset_x": {
                "x1": right_half_left_x1,
                "x2": right_half_left_x2,
                "y": y3,
                "min": -self.frame_width if self.frame_width > 0 else self.OFFSET_MIN_PX,
                "max": self.frame_width if self.frame_width > 0 else self.OFFSET_MAX_PX,
            },
            "offset_y": {
                "x1": right_half_right_x1,
                "x2": right_half_right_x2,
                "y": y3,
                "min": -self.frame_height if self.frame_height > 0 else self.OFFSET_MIN_PX,
                "max": self.frame_height if self.frame_height > 0 else self.OFFSET_MAX_PX,
            },
            "fine_offset_x": {
                "x1": right_half_left_x1,
                "x2": right_half_left_x2,
                "y": y4,
                "min": self.FINE_OFFSET_MIN_PX,
                "max": self.FINE_OFFSET_MAX_PX,
            },
            "fine_offset_y": {
                "x1": right_half_right_x1,
                "x2": right_half_right_x2,
                "y": y4,
                "min": self.FINE_OFFSET_MIN_PX,
                "max": self.FINE_OFFSET_MAX_PX,
            },
        }







    def _frame_to_panel(self, frame_point: np.ndarray, meta: Dict[str, float]) -> np.ndarray:
        zoom = meta["zoom_percent"] / 100.0
        panel_x = frame_point[0] * zoom + meta["top_left_x"]
        panel_y = frame_point[1] * zoom + meta["top_left_y"]
        return np.array([panel_x, panel_y], dtype=np.float32)


    def _panel_to_frame(self, panel_x: float, panel_y: float, meta: Dict[str, float]) -> np.ndarray:
        zoom = max(1e-6, meta["zoom_percent"] / 100.0)
        frame_x = (panel_x - meta["top_left_x"]) / zoom
        frame_y = (panel_y - meta["top_left_y"]) / zoom

        frame_x = float(np.clip(frame_x, 0.0, max(0.0, self.frame_width - 1.0)))
        frame_y = float(np.clip(frame_y, 0.0, max(0.0, self.frame_height - 1.0)))
        return np.array([frame_x, frame_y], dtype=np.float32)






    def _build_target_quad(self, src_quad: np.ndarray) -> np.ndarray:
        top = np.linalg.norm(src_quad[1] - src_quad[0])
        bottom = np.linalg.norm(src_quad[2] - src_quad[3])
        left = np.linalg.norm(src_quad[3] - src_quad[0])
        right = np.linalg.norm(src_quad[2] - src_quad[1])

        rect_w = max(40.0, (top + bottom) * 0.5)
        rect_h = max(40.0, (left + right) * 0.5)

        center = src_quad.mean(axis=0)
        half_w = rect_w * 0.5
        half_h = rect_h * 0.5

        return np.array(
            [
                [center[0] - half_w, center[1] - half_h],
                [center[0] + half_w, center[1] - half_h],
                [center[0] + half_w, center[1] + half_h],
                [center[0] - half_w, center[1] + half_h],
            ],
            dtype=np.float32,
        )


    def _apply_perspective_correction(self, frame: np.ndarray) -> np.ndarray:
        if self.quad_points is None:
            return frame

        src_quad = self.quad_points.astype(np.float32)
        dst_quad = self._build_target_quad(src_quad)
        matrix = cv2.getPerspectiveTransform(src_quad, dst_quad)
        return cv2.warpPerspective(
            frame,
            matrix,
            (self.frame_width, self.frame_height),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=(0, 0, 0),
        )


    def _apply_output_stretch(self, frame: np.ndarray) -> np.ndarray:
        stretch_x = self.output_stretch_x_percent / 100.0
        stretch_y = self.output_stretch_y_percent / 100.0

        if abs(stretch_x - 1.0) < 1e-6 and abs(stretch_y - 1.0) < 1e-6:
            return frame

        frame_h, frame_w = frame.shape[:2]
        stretched_w = max(1, int(round(frame_w * stretch_x)))
        stretched_h = max(1, int(round(frame_h * stretch_y)))
        return cv2.resize(frame, (stretched_w, stretched_h), interpolation=cv2.INTER_LINEAR)


    def _apply_output_brightness(self, frame: np.ndarray) -> np.ndarray:
        brightness = self.output_brightness_percent / 100.0
        if abs(brightness) < 1e-6:
            return frame

        adjusted = frame.astype(np.float32) + brightness * 255.0
        adjusted = np.clip(adjusted, 0, 255)
        return adjusted.astype(np.uint8)






    def _on_mouse_event(self, event, x, y, flags, param) -> None:
        _ = flags
        _ = param
        if self.quad_points is None or self.left_panel_meta is None:
            return

        if self._handle_slider_event(event, x, y):
            return

        if x >= self.FRAME_PREVIEW_SIZE:
            if event == cv2.EVENT_LBUTTONUP:
                self.dragging_point_index = -1
            return

        if event == cv2.EVENT_LBUTTONDOWN:
            min_dist = float("inf")
            min_idx = -1
            for idx, frame_pt in enumerate(self.quad_points):
                panel_pt = self._frame_to_panel(frame_pt, self.left_panel_meta)
                dist = float(np.hypot(panel_pt[0] - x, panel_pt[1] - y))
                if dist < min_dist:
                    min_dist = dist
                    min_idx = idx

            if min_dist <= (self.PERSPECTIVE_POINT_RADIUS + self.OUTER_RADIUS_PLUS):
                self.dragging_point_index = min_idx

        elif event == cv2.EVENT_MOUSEMOVE:
            if self.dragging_point_index >= 0:
                new_point = self._panel_to_frame(float(x), float(y), self.left_panel_meta)
                self.quad_points[self.dragging_point_index] = new_point

        elif event == cv2.EVENT_LBUTTONUP:
            self.dragging_point_index = -1






    def _handle_slider_event(self, event: int, x: int, y: int) -> bool:
        control_top = self.FRAME_PREVIEW_SIZE
        slider_geo = self._get_slider_geometries()

        if self.dragging_slider_name is not None:
            slider_name = self.dragging_slider_name
            geo = slider_geo.get(slider_name)
            if geo is None:
                self.dragging_slider_name = None
                return False

            if event == cv2.EVENT_MOUSEMOVE:
                self._update_slider_from_mouse(slider_name, x, geo)
                return True

            if event == cv2.EVENT_LBUTTONUP:
                self._update_slider_from_mouse(slider_name, x, geo)
                self.dragging_slider_name = None
                return True

            return True

        if y < control_top:
            if event == cv2.EVENT_LBUTTONUP:
                self.dragging_slider_name = None
            return False

        if x < 0 or x >= self.WINDOW_WIDTH:
            return False

        if event == cv2.EVENT_LBUTTONDOWN:
            for slider_name, geo in slider_geo.items():
                hit_x_min = geo["x1"] - 8
                hit_x_max = geo["x2"] + 8
                hit_y_min = geo["y"] - 8
                hit_y_max = geo["y"] + 8
                if hit_x_min <= x <= hit_x_max and hit_y_min <= y <= hit_y_max:
                    self.dragging_slider_name = slider_name
                    self._update_slider_from_mouse(slider_name, x, geo)
                    return True

        return True






    def _update_slider_from_mouse(self, slider_name: str, x: int, geo: Dict[str, int]) -> None:
        percent = self._slider_x_to_percent(
            float(x),
            geo["x1"],
            geo["x2"],
            geo["min"],
            geo["max"],
        )
        if slider_name == "input":
            self.input_zoom_percent = percent
        elif slider_name == "brightness":
            self.output_brightness_percent = percent
        elif slider_name == "output":
            self.output_zoom_percent = percent
        elif slider_name == "stretch_x":
            self.output_stretch_x_percent = percent
        elif slider_name == "stretch_y":
            self.output_stretch_y_percent = percent
        elif slider_name == "offset_x":
            self.output_offset_x_px = percent
        elif slider_name == "offset_y":
            self.output_offset_y_px = percent
        elif slider_name == "fine_offset_x":
            self.output_fine_offset_x_px = percent
        elif slider_name == "fine_offset_y":
            self.output_fine_offset_y_px = percent
