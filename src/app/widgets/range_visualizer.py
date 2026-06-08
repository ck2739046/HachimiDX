from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPainter, QPen, QColor

from ..ui_style import UI_Style



class RangeVisualizer(QWidget):
    """
    视频范围可视化器
    显示一条横线代表视频长度，并在 start_sec 和 end_sec 位置画竖线
    """
    
    def __init__(self, parent = None, length = 200):
        """
        范围可视化组件

        Args:
            length: int, 可选，默认200，组件的总长度（像素）

        Method:
            update_val(total, start, end)
        """

        super().__init__(parent)

        self.fixed_width = length  # 整个组件的总长度
        self.fixed_height = 12     # 整个组件的总高度
        self.indicator_height = 10 # start/end 竖线高度
        self.setFixedSize(self.fixed_width, self.fixed_height)
        
        self.total = None
        self.start = None
        self.end = None
    


    def update_val(self, total, start, end):
        """
        更新范围显示，三个值总是需要一起提供
        
        Args:
            total: 总长度
            start: 起始位置
            end:   结束位置
        """

        if total is None: total = 0
        if start is None: start = 0
        if end is None: end = 0

        self.total = max(total, 0.001) # 避免除零错误
        self.start = start
        if end <= 0: end = self.total + end # 支持负数
        self.end = end

        self.update()  # 触发重绘
    


    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # 绘制总长度横线 (灰色)
        line_y = self.fixed_height // 2
        line_margin = 5
        line_start_x = line_margin
        line_end_x = self.fixed_width - line_margin
        line_length = line_end_x - line_start_x
        
        pen = QPen(QColor(UI_Style.COLORS['light_grey']))
        pen.setWidth(2)
        painter.setPen(pen)
        painter.drawLine(line_start_x, line_y, line_end_x, line_y)
        
        # 计算位置
        def value_to_x(value: float) -> int:
            ratio = value / self.total
            if not 0 < ratio < 1.1:
                return None
            return int(line_start_x + ratio * line_length)
        
        # 绘制 start 竖线（绿色）
        if self.start is not None and self.start >= 0:
            start_x = value_to_x(self.start)
            if start_x is not None:
                pen = QPen(Qt.GlobalColor.green)
                pen.setWidth(2)
                painter.setPen(pen)
                painter.drawLine(start_x, line_y - self.indicator_height // 2, start_x, line_y + self.indicator_height // 2)
        
        # 绘制 end 竖线（红色）
        if self.end is not None and self.end >= 0:
            end_x = value_to_x(self.end)
            if end_x is not None:
                pen = QPen(Qt.GlobalColor.red)
                pen.setWidth(2)
                painter.setPen(pen)
                painter.drawLine(end_x, line_y - self.indicator_height // 2, end_x, line_y + self.indicator_height // 2)
