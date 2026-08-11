import cv2
import numpy as np
from typing import Dict




class TransformMixin:


    def _build_default_quad(self, frame_w: int, frame_h: int) -> np.ndarray:
        """生成默认透视四点: 位于画面中心、约占画面 20% 的矩形"""
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




    def _frame_to_panel(self, frame_point: np.ndarray, meta: Dict[str, float]) -> np.ndarray:
        """把帧坐标点换算为面板坐标 (乘 zoom 再加左上角偏移)"""
        zoom = meta["zoom_percent"] / 100.0
        panel_x = frame_point[0] * zoom + meta["top_left_x"]
        panel_y = frame_point[1] * zoom + meta["top_left_y"]
        return np.array([panel_x, panel_y], dtype=np.float32)


    def _panel_to_frame(self, panel_x: float, panel_y: float, meta: Dict[str, float]) -> np.ndarray:
        """把面板坐标换算为帧坐标 (减左上角偏移再除 zoom, clip 到帧范围内)"""
        zoom = max(1e-6, meta["zoom_percent"] / 100.0)
        frame_x = (panel_x - meta["top_left_x"]) / zoom
        frame_y = (panel_y - meta["top_left_y"]) / zoom

        frame_x = float(np.clip(frame_x, 0.0, max(0.0, self.frame_width - 1.0)))
        frame_y = float(np.clip(frame_y, 0.0, max(0.0, self.frame_height - 1.0)))
        return np.array([frame_x, frame_y], dtype=np.float32)




    def _build_target_quad(self, src_quad: np.ndarray) -> np.ndarray:
        """
        给定用户拖出来的任意四边形,
        计算一个矩形作为透视矫正的目标形状,
        使 cv2.getPerspectiveTransform(src, dst) 能把源四边形"拉直"为矩形
        """
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
        """按当前四边形透视点对整帧做透视矫正"""
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
        """按 stretch_x / stretch_y 拉伸整帧"""
        stretch_x = self.output_stretch_x_percent / 100.0
        stretch_y = self.output_stretch_y_percent / 100.0

        if abs(stretch_x - 1.0) < 1e-6 and abs(stretch_y - 1.0) < 1e-6:
            return frame

        frame_h, frame_w = frame.shape[:2]
        stretched_w = max(1, int(round(frame_w * stretch_x)))
        stretched_h = max(1, int(round(frame_h * stretch_y)))
        return cv2.resize(frame, (stretched_w, stretched_h), interpolation=cv2.INTER_LINEAR)


    def _apply_output_brightness(self, frame: np.ndarray) -> np.ndarray:
        """实现帧画面的亮度调整"""
        brightness = self.output_brightness_percent / 100.0
        if abs(brightness) < 1e-6:
            return frame

        adjusted = frame.astype(np.float32) + brightness * 255.0
        adjusted = np.clip(adjusted, 0, 255)
        return adjusted.astype(np.uint8)


    def _compute_output_panel_matrix(self) -> np.ndarray:
        """
        右面板坐标 的复合 3×3 透视矩阵。

        数学等价于渲染链的正向映射:
            M_warp (透视矫正, 帧→帧)
          × S      (stretch 拉伸, diag(sx, sy, 1))
          × T      (zoom 缩放 + 面板左上角偏移)

        默认 quad / stretch=1 / zoom=1 / offset=0 时
        退化为 identity, 与原默认渲染等价
        """
        fw = float(self.frame_width)
        fh = float(self.frame_height)

        # M_warp: 透视矫正
        if self.quad_points is None or fw <= 0.0 or fh <= 0.0:
            m_warp = np.eye(3, dtype=np.float32)
        else:
            src_quad = self.quad_points.astype(np.float32)
            default_quad = self._build_default_quad(int(round(fw)), int(round(fh)))
            if np.array_equal(src_quad, default_quad):
                m_warp = np.eye(3, dtype=np.float32)
            else:
                dst_quad = self._build_target_quad(src_quad)
                m_warp = cv2.getPerspectiveTransform(src_quad, dst_quad)

        # S: stretch 拉伸
        sx = self.output_stretch_x_percent / 100.0
        sy = self.output_stretch_y_percent / 100.0
        s = np.array([[sx, 0.0, 0.0],
                      [0.0, sy, 0.0],
                      [0.0, 0.0, 1.0]], dtype=np.float32)

        # T: 先 zoom 缩放, 再应用面板左上角偏移
        z = self.output_zoom_percent / 100.0
        scaled_w = fw * sx * z
        scaled_h = fh * sy * z
        tlx = (self.FRAME_PREVIEW_SIZE - scaled_w) * 0.5 \
            + (self.output_offset_x_px + self.output_fine_offset_x_px)
        tly = (self.FRAME_PREVIEW_SIZE - scaled_h) * 0.5 \
            + (self.output_offset_y_px + self.output_fine_offset_y_px)
        t = np.array([[z, 0.0, tlx],
                      [0.0, z, tly],
                      [0.0, 0.0, 1.0]], dtype=np.float32)

        ui_scale = np.array(
            [
                [self.ui_scale_factor, 0.0, 0.0],
                [0.0, self.ui_scale_factor, 0.0],
                [0.0, 0.0, 1.0],
            ],
            dtype=np.float32,
        )
        return (ui_scale @ t @ s @ m_warp).astype(np.float32)



    def _render_output_panel(self, raw_frame: np.ndarray) -> np.ndarray:
        """透视 → 拉伸 → 缩放 → 位移 → 亮度"""

        # 单次 cv2.warpPerspective 直接实现 透视+拉伸+位移+缩放
        matrix = self._compute_output_panel_matrix()
        panel = cv2.warpPerspective(
            raw_frame,
            matrix,
            (self.frame_preview_size_px, self.frame_preview_size_px),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=(0, 0, 0),
        )
        # 调整亮度
        panel = self._apply_output_brightness(panel)
        return panel
