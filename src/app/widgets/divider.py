from PyQt6.QtWidgets import QWidget, QHBoxLayout, QFrame, QLabel, QSizePolicy
from PyQt6.QtCore import Qt
from ..ui_style import UI_Style

def create_divider(text, up_margin=5, down_margin=5):
    """
    创建分隔线

    Args:
        text: str，分隔栏文本内容
        up_margin: int，默认5，分隔栏上边距（像素）
        down_margin: int，默认5，分隔栏下边距（像素）
    
    Returns:
        QWidget: 包含分隔线的容器widget
    """

    colors = UI_Style.COLORS
    divider_container = QWidget()
    divider_layout = QHBoxLayout(divider_container)
    
    divider_layout.setContentsMargins(0, up_margin, 0, down_margin)
    divider_layout.setSpacing(5) # 间距5px

    if text:
        line_left = QFrame()
        line_left.setFrameShape(QFrame.Shape.HLine)
        line_left.setFixedSize(18, 15) # 固定宽度18像素
        line_left.setStyleSheet(f"color: {colors['grey']};")
        divider_layout.addWidget(line_left)

        label = QLabel(text)
        label.setStyleSheet(f"color: {colors['grey_hover']}; font-size: {UI_Style.default_text_size}px;")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        divider_layout.addWidget(label)

        line_right = QFrame()
        line_right.setFrameShape(QFrame.Shape.HLine)
        line_right.setFixedHeight(15) # 无固定宽度
        line_right.setStyleSheet(f"color: {colors['grey']};")
        # 设置大小策略，让 QLabel 能够充分利用水平方向上的可用空间
        line_right.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        divider_layout.addWidget(line_right)

    return divider_container


def create_vertical_divider():
    """
    创建竖直分隔线，用于并列区域之间的简单分隔

    颜色与 create_divider 的横线一致

    Returns:
        QFrame: 竖直分隔线
    """

    line = QFrame()
    line.setFrameShape(QFrame.Shape.VLine)
    line.setFixedWidth(3) # 无固定高度
    line.setStyleSheet(f"color: {UI_Style.COLORS['grey']};")
    # 设置大小策略，让竖直分隔线在垂直方向上能够充分利用可用空间
    line.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
    
    return line
