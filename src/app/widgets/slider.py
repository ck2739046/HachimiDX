from PyQt6.QtWidgets import QSlider
from PyQt6.QtCore import Qt

from ..ui_style import UI_Style
from .label import create_label


class _SnapSlider(QSlider):
    """带档位吸附的滑块控件。通过重写 sliderChange 将鼠标拖动值吸附到最近的有效步进。"""

    def __init__(self, step, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._step = step

    def sliderChange(self, change):
        if change == QSlider.SliderChange.SliderValueChange:
            v = self.value()
            snapped = round(v / self._step) * self._step
            snapped = max(self.minimum(), min(self.maximum(), snapped))
            if snapped != v:
                self.setValue(snapped)
                return
        super().sliderChange(change)


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
            background: {c['grey']};
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
