import cv2
import numpy as np
from typing import Dict




class InteractionMixin:


    def _on_mouse_event(self, event, x, y, flags, param) -> None:
        """
        鼠标事件总入口
        依次分发到滑块拖拽、四边形透视点拖拽 (左面板四点)
        """
        _ = flags
        _ = param
        if self.quad_points is None or self.left_panel_meta is None:
            return

        if self._handle_slider_event(event, x, y):
            return

        # 超出左面板区域: 仅清理状态
        if y >= self.FRAME_PREVIEW_SIZE or x >= self.FRAME_PREVIEW_SIZE:
            if event == cv2.EVENT_LBUTTONUP:
                self.dragging_point_index = -1
            return

        # 左面板: 四边形透视点拖拽
        if event == cv2.EVENT_LBUTTONDOWN:
            min_dist = float("inf")
            min_idx = -1
            for idx, frame_pt in enumerate(self.quad_points):
                panel_pt = self._frame_to_panel(frame_pt, self.left_panel_meta)
                dist = float(np.hypot(panel_pt[0] - x, panel_pt[1] - y))
                if dist < min_dist:
                    min_dist = dist
                    min_idx = idx
            if min_dist <= float(self.PERSPECTIVE_POINT_RADIUS + self.OUTER_RADIUS_PLUS):
                self.dragging_point_index = min_idx

        elif event == cv2.EVENT_MOUSEMOVE:
            if self.dragging_point_index >= 0:
                new_point = self._panel_to_frame(float(x), float(y), self.left_panel_meta)
                self.quad_points[self.dragging_point_index] = new_point

        elif event == cv2.EVENT_LBUTTONUP:
            self.dragging_point_index = -1






    def _handle_slider_event(self, event: int, x: int, y: int) -> bool:
        """
        处理滑块命中与拖拽:
          鼠标按下 → 开始拖
          鼠标移动 → 更新
          鼠标抬起 → 结束
        """
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
        """按鼠标 x 坐标换算百分比, 写入对应滑块状态字段"""
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


    def _slider_percent_to_x(self,
                             percent_value: int,
                             track_x1: int,
                             track_x2: int,
                             min_percent: int,
                             max_percent: int) -> float:
        """把滑块百分比换算为轨道上的像素 x (用于绘制滑块位置)"""
        clamped = self._clamp_value(percent_value, min_percent, max_percent)
        ratio = (clamped - min_percent) / float(max(1, max_percent - min_percent))
        return track_x1 + ratio * (track_x2 - track_x1)


    def _slider_x_to_percent(self,
                             x: float,
                             track_x1: int,
                             track_x2: int,
                             min_percent: int,
                             max_percent: int) -> int:
        """把鼠标像素 x 反算为滑块百分比 (用于拖拽写入)"""
        ratio = (x - track_x1) / float(max(1, track_x2 - track_x1))
        percent = min_percent + ratio * (max_percent - min_percent)
        return self._clamp_value(int(round(percent)), min_percent, max_percent)


    def _clamp_value(self, value: int, min_value: int, max_value: int) -> int:
        """把 value 限制到 [min_value, max_value] 区间"""
        return max(min_value, min(max_value, int(value)))


    def _get_slider_geometries(self) -> Dict[str, Dict[str, int]]:
        """计算所有滑块的轨道坐标 (x1/x2/y) 与取值范围 (min/max)"""

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
