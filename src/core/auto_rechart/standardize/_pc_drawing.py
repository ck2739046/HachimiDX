import cv2
import numpy as np
from typing import Dict




class DrawingMixin:

    def _compose_panel(self, frame, zoom_percent: float, offset_x: int = 0, offset_y: int = 0):
        """
        将原始帧绘制到 800×800 黑色画布上

        输入: 
            原始帧 frame
            缩放百分比 zoom_percent
            像素偏移 offset_x/y

        输出: 
            tuple
                canvas,
                定位元信息 meta {zoom_percent, top_left_x, top_left_y})
        """

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






    def _draw_dashed_circle(self, panel: np.ndarray,
                            center,
                            radius,
                            color,
                            thickness: int = 2,
                            dash_deg: float = 3,
                            gap_deg: float = 2) -> None:
        """绘制虚线圆"""
        if radius <= 0:
            return
        angle = 0.0
        step = dash_deg + gap_deg
        while angle < 360.0:
            end = min(angle + dash_deg, 360.0)
            cv2.ellipse(panel, center, (radius, radius), 0,
                        angle, end, color, thickness)
            angle += step

    def _draw_reference_marks(self, panel: np.ndarray) -> None:
        """
        在右侧面板绘制固定参考标记:
            判定线圆
            屏幕边缘圆
            八个判定红点
            九宫格分隔线
        """
        height, width = panel.shape[:2]
        center_x = width // 2
        center_y = height // 2
        
        # 内圆 判定线
        inner_d = self.FRAME_PREVIEW_SIZE * 960/1080 # 判定线参考圆
        inner_r = int(inner_d / 2)
        inner_cx, inner_cy = center_x - 1, center_y - 1
        self._draw_dashed_circle(panel, (inner_cx, inner_cy),
                                 inner_r, (0, 255, 0))

        # 内圈上 8 个红色判定点
        for deg in (22.5, 67.5, 112.5, 157.5, 202.5, 247.5, 292.5, 337.5):
            rad = np.deg2rad(deg)
            px = int(round(inner_cx + inner_r * np.cos(rad)))
            py = int(round(inner_cy + inner_r * np.sin(rad)))
            cv2.circle(panel, (px, py), 9, (0, 0, 255), 2)

        # 外圆 屏幕边缘
        outer_radius = min(width, height) // 2
        self._draw_dashed_circle(panel, (inner_cx, inner_cy),
                                 outer_radius, (0, 255, 0))
        
        # 垂直/水平线 穿过内圈上的 8 个参考点
        # 每条线距圆心 = inner_r * sin(22.5°) 恰好经过参考点
        line_offset = int(round(inner_r * np.sin(np.deg2rad(22.5))))
        v_line1_x = inner_cx - line_offset
        v_line2_x = inner_cx + line_offset
        cv2.line(panel, (v_line1_x, 0), (v_line1_x, height), (0, 255, 0), 1)
        cv2.line(panel, (v_line2_x, 0), (v_line2_x, height), (0, 255, 0), 1)
        h_line1_y = inner_cy - line_offset
        h_line2_y = inner_cy + line_offset
        cv2.line(panel, (0, h_line1_y), (width, h_line1_y), (0, 255, 0), 1)
        cv2.line(panel, (0, h_line2_y), (width, h_line2_y), (0, 255, 0), 1)







    def _draw_center_handle(self, panel: np.ndarray, panel_side: str) -> None:
        """左右面板通用: 在面板中心绘制可拖动的中心点"""
        if self.center_drag_panel == panel_side and self._center_drag_mouse is not None:
            cx = int(round(self._center_drag_mouse[0]))
            cy = int(round(self._center_drag_mouse[1]))
        else:
            cx = self.FRAME_PREVIEW_SIZE // 2
            cy = self.FRAME_PREVIEW_SIZE // 2

        cv2.circle(panel, (cx, cy),
                   self.PERSPECTIVE_POINT_RADIUS,
                   self.POINT_COLOR, 1)
        cv2.circle(panel, (cx, cy),
                   self.PERSPECTIVE_POINT_RADIUS + self.OUTER_RADIUS_PLUS,
                   (255, 255, 255), 1)
        cv2.putText(
            panel, "C",
            (cx + 10, cy - 10),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )





    def _draw_quad_overlay(self, panel: np.ndarray, meta: Dict[str, float]) -> None:
        """在左面板绘制四边形透视框"""
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
        """
        在整块画布底部绘制控制区:
            滑块
            分隔线
            提示文字(SPACE/ESC、PAUSED)。
        """
        
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
        """左右面板通用: 仅绘制单面板底部控制区的 scale 滑块"""
        
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
        """绘制右侧 stretch_x / stretch_y 拉伸滑块"""
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
        """绘制左侧亮度滑块(brightness)"""
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
        """绘制右侧 offset_x / offset_y 粗偏移滑块"""
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
        """绘制右侧 fine_offset_x / fine_offset_y 精细偏移滑块"""
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
        """
        通用单滑块绘制工具:
           标签、滑轨、滑块(选中时高亮)、数值文本
        """
        
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
