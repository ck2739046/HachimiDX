from PyQt6.QtCore import Qt
from PyQt6.QtGui import QCursor

from .label import create_label
from .popup_tooltip import install_tooltip


def create_clickable_label(
    label_text="",
    tooltip_text="",
    label_color=None,
    label_font_size=None,
    label_bold=False,
    underline=False,
    on_click=None,
    selectable=False,
):
    """
    创建可点击的文本标签，支持悬停 tooltip 和点击回调。

    本组件只负责"可点击"这件事本身：点击后干什么由调用方通过 on_click 决定
    （例如打开浏览器、弹出窗口）。

    Args:
        label_text:      标签显示的文本
        tooltip_text:    悬停时 tooltip 显示的文本，默认空字符串表示不显示
        label_color:     文本颜色，默认 UI_Style.COLORS['text_primary']
        label_font_size: 字号，默认 UI_Style.default_text_size
        label_bold:      粗体，默认 False
        underline:       下划线，默认 False，用于提示文本可点击
        on_click:        点击后的回调，默认 None 表示不响应点击
        selectable:      是否允许划选文本，默认 False

    注意:
        selectable 与点击动作互斥: 开启后按下鼠标是"开始划选"还是"触发点击"
        无法两全, 需要划选文本时请改用 create_label(selectable=True)。

    Returns:
        QLabel: 配置好的可点击标签
    """

    # 直接调用 create_label() 创建基础标签
    label = create_label(
        text=label_text,
        color=label_color,
        font_size=label_font_size,
        bold=label_bold,
        underline=underline,
        selectable=selectable,
    )

    # 设置光标
    label.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

    # Tooltip
    install_tooltip(label, tooltip_text)

    # 点击回调
    if on_click is not None:

        def _mouse_press_event(event):
            # 只有左键才触发，避免右键/中键误触
            if event.button() != Qt.MouseButton.LeftButton:
                return
            on_click()

        label.mousePressEvent = _mouse_press_event

    return label
