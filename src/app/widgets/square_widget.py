"""
Square Widget - 保持宽高比为 1:1 的容器
"""

from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from ..ui_style import UI_Style


class SquareWidget(QWidget):
    """
    正方形 Widget
    实际尺寸控制由父容器 LeftPanel 通过 resizeEvent 动态计算宽度来实现
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.background_color = UI_Style.COLORS["grey"]
        # 创建内部布局，用于嵌入外部窗口
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

    def paintEvent(self, event):
        """
        绘制背景色
        """
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(self.background_color))
