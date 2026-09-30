from PyQt6.QtWidgets import QSlider, QStyle, QStyleOptionSlider
from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QCursor, QMouseEvent

from ..ui_style import UI_Style
from .label import create_label


# 滑条（横条）的可点击区域在上下各外扩 2px，即总高度 +4px
# 视觉粗细仍由样式表里的 height 决定，保持不变。
_GROOVE_HIT_PADDING = 2


class _SnapSlider(QSlider):
    """带档位吸附的滑块控件。通过重写 sliderChange 将鼠标拖动值吸附到最近的有效步进。

    光标约定（样式表不支持 cursor 属性，只能自己按悬停位置切换）：
      - 悬停在滑块本体（小方块）上：张开手，表示可拖拽；拖拽过程中为握拳
      - 悬停在滑条（横条）其余可点击区域上：手型，表示可点击跳转
    """

    def __init__(self, step, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._step = step
        self._dragging_handle = False
        self._cursor_shape = None
        self.setMouseTracking(True)  # 不按键也要收到 mouseMoveEvent，才能实时切换光标

    def sliderChange(self, change):
        if change == QSlider.SliderChange.SliderValueChange:
            v = self.value()
            snapped = round(v / self._step) * self._step
            snapped = max(self.minimum(), min(self.maximum(), snapped))
            if snapped != v:
                self.setValue(snapped)
                return
        super().sliderChange(change)

    # ── 命中区域 ──────────────────────────────────────────────────
    def _sub_control_rect(self, sub_control):
        opt = QStyleOptionSlider()
        self.initStyleOption(opt)
        return self.style().subControlRect(QStyle.ComplexControl.CC_Slider, opt, sub_control, self)

    def _handle_rect(self):
        """滑块本体（小方块）的矩形"""
        return self._sub_control_rect(QStyle.SubControl.SC_SliderHandle)

    def _groove_rect(self):
        """滑条（横条）的矩形"""
        return self._sub_control_rect(QStyle.SubControl.SC_SliderGroove)

    def _groove_hit_rect(self):
        """滑条的可点击区域：上下各外扩，比视觉横条高"""
        return self._groove_rect().adjusted(0, -_GROOVE_HIT_PADDING, 0, _GROOVE_HIT_PADDING)

    # ── 光标 ──────────────────────────────────────────────────────
    def _refresh_cursor(self, pos):
        if self._dragging_handle:
            shape = Qt.CursorShape.ClosedHandCursor
        elif self._handle_rect().contains(pos):
            shape = Qt.CursorShape.OpenHandCursor
        elif self._groove_hit_rect().contains(pos):
            shape = Qt.CursorShape.PointingHandCursor
        else:
            shape = Qt.CursorShape.ArrowCursor

        if shape == self._cursor_shape:
            return
        self._cursor_shape = shape
        self.setCursor(QCursor(shape))

    # ── 鼠标事件 ──────────────────────────────────────────────────
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            if self._handle_rect().contains(pos):
                self._dragging_handle = True
            elif self._groove_hit_rect().contains(pos) and not self._groove_rect().contains(pos):
                # 落在滑条的扩展可点击区（视觉横条之外的区域）：把纵坐标折算进滑条，
                # 复用 Qt 原生的“点击滑条跳转”逻辑
                event = self._clamped_to_groove(event)
        super().mousePressEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            self._refresh_cursor(event.position().toPoint())

    def mouseMoveEvent(self, event):
        self._refresh_cursor(event.position().toPoint())
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._dragging_handle = False
        super().mouseReleaseEvent(event)
        self._refresh_cursor(event.position().toPoint())

    def _clamped_to_groove(self, event):
        """复制一个纵坐标折算到滑条中心的鼠标事件"""
        pos = event.position()
        return QMouseEvent(
            event.type(),
            QPointF(pos.x(), self._groove_rect().center().y()),
            event.globalPosition(),
            event.button(),
            event.buttons(),
            event.modifiers(),
        )


def create_slider(min_val, max_val, step, default_value, slider_length=200, text_transform=None):
    """创建带档位吸附的滑块和数值标签。

    Args:
        min_val: 最小值（必须）
        max_val: 最大值（必须）
        step: 步进/档位间距（必须）
        default_value: 默认值（必须）
        slider_length: 滑条宽度（像素），默认 200。
        text_transform: (int) -> str，将滑块数值转为显示文本。为 None 则直接显示数字。

    Returns:
        (QSlider, QLabel): 滑块控件和数值标签。
    """
    slider = _SnapSlider(step, Qt.Orientation.Horizontal)
    slider.setMinimum(min_val)
    slider.setMaximum(max_val)
    slider.setSingleStep(step)  # 键盘上下左右方向键
    slider.setPageStep(step)    # 鼠标滚轮/PageUp/PageDown
    slider.setValue(default_value)
    slider.setFixedWidth(slider_length)
    _apply_style(slider)
    label = create_label()

    def _on_value_changed(v):
        snapped = round(v / step) * step
        label.setText(text_transform(snapped) if text_transform else str(snapped))

    _on_value_changed(default_value)
    slider.valueChanged.connect(_on_value_changed)

    return slider, label


def _apply_style(slider):
    c = UI_Style.COLORS
    slider.setStyleSheet(f"""
        /* 整体下移 1px, 与同行 label 对齐 */
        QSlider {{
            padding-top: 1px;
        }}
        
        /* 滑条右侧 */
        QSlider::groove:horizontal {{
            background: {c['light_grey']};
            height: 3px;
        }}

        /* 滑条左侧 */
        QSlider::sub-page:horizontal {{
            background: {c['accent']};
            height: 3px;
        }}

        /* 滑块本体, margin = -1/2 * (长宽 - 滑条高度) */
        QSlider::handle:horizontal {{
            background: {c['accent']};
            width: 13px;
            height: 13px;
            margin: -5px 0;
            border-radius: 4px;
        }}
        
        /* 滑块 hover 颜色 */
        QSlider::handle:horizontal:hover {{
            background: {c['accent_hover']};
        }}
    """)
