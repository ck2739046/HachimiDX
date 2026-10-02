from PyQt6.QtWidgets import QLabel, QSizePolicy

from ..ui_style import UI_Style


def create_label(text=None, color=None, font_size=None, bold=False, expand=False):
    """
    创建文本标签

    Args:
        text: str，可选，默认空字符串
        color: #xxx，可选，默认 UI_Style.COLORS['text_primary']
        font_size: int，可选，默认 UI_Style.default_text_size
        bold: bool，可选，默认False
        expand: bool，可选，默认False，是否在水平方向上扩展以利用可用空间

    Returns:
        QLabel: 配置好的文本标签
    """

    if not text:
        text = ""

    if not color:
        color = UI_Style.COLORS["text_primary"]

    if not font_size:
        font_size = UI_Style.default_text_size

    label = QLabel(text)
    label.setWordWrap(False)  # 始终显示为一行，不换行

    # 设置大小策略，让 QLabel 能够充分利用水平方向上的可用空间
    if expand:
        label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    if bold:
        label.setStyleSheet(
            f"color: {color}; font-size: {font_size}px; font-weight: bold;"
        )
    else:
        label.setStyleSheet(f"color: {color}; font-size: {font_size}px;")

    return label
