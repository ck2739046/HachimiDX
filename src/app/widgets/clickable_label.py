from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QCursor, QDesktopServices

from .label import create_label
from .popup_tooltip import install_tooltip


def create_clickable_label(
    label_text="",
    tooltip_text="",
    url=None,
    label_color=None,
    label_font_size=None,
    label_bold=False,
):
    """
    创建可点击的文本标签，支持悬停 tooltip 和点击打开 URL。

    Args:
        label_text:      标签显示的文本
        tooltip_text:    悬停时 tooltip 显示的文本，默认空字符串表示不显示
        url:             点击后打开的 URL，默认 None 表示不跳转
        label_color:     文本颜色，默认 UI_Style.COLORS['text_primary']
        label_font_size: 字号，默认 UI_Style.default_text_size
        label_bold:      粗体，默认 False

    Returns:
        QLabel: 配置好的可点击标签
    """

    # 直接调用 create_label() 创建基础标签
    label = create_label(
        text=label_text, color=label_color, font_size=label_font_size, bold=label_bold
    )

    # 设置光标
    label.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

    # Tooltip
    install_tooltip(label, tooltip_text)

    # 点击打开 URL
    if url is not None:

        def _mouse_press_event(_event):
            QDesktopServices.openUrl(QUrl(url))

        label.mousePressEvent = _mouse_press_event

    return label
