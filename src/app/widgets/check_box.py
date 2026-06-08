from PyQt6.QtWidgets import QCheckBox, QStyle, QStyleOptionButton
from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QPainter, QColor, QPen, QPainterPath
from ..ui_style import UI_Style

class StyledCheckBox(QCheckBox):
    def __init__(self, colors, size, border_width, parent=None):
        super().__init__(parent)
        
        # 默认颜色配置（转换为QColor对象）
        self.checked_color = QColor(colors['accent'])
        self.checked_hover_color = QColor(colors['accent_hover'])
        self.unchecked_color = QColor(colors['grey'])
        self.unchecked_hover_color = QColor(colors['grey_hover'])
        self.border_color = QColor(colors['light_grey'])

        self.size = size
        self.border_width = border_width
        self.is_hover = False
        self.setFixedSize(size, size)
        
        # 设置样式表控制指示器尺寸
        self.setStyleSheet(f"""
            QCheckBox::indicator {{
                width: {self.size}px;
                height: {self.size}px;
                border: none;
            }}
        """)

    def enterEvent(self, event):
        """鼠标进入"""
        self.is_hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        """鼠标离开"""
        self.is_hover = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        """自定义绘制"""
        # 先绘制文本
        super().paintEvent(event)
        
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # 获取指示器区域
        opt = QStyleOptionButton()
        opt.initFrom(self)
        indicator_rect = self.style().subElementRect(QStyle.SubElement.SE_CheckBoxIndicator, opt, self)

        # 缩小 indicator，给边框留出位置
        rect = QRectF(indicator_rect).adjusted(self.border_width, self.border_width, -self.border_width, -self.border_width)
        
        # 确定背景颜色
        if self.isChecked():
            bg_color = self.checked_hover_color if self.is_hover else self.checked_color
        else:
            bg_color = self.unchecked_hover_color if self.is_hover else self.unchecked_color
        
        # 绘制圆角矩形 + 1px边框
        painter.setPen(QPen(self.border_color, self.border_width))
        painter.setBrush(bg_color)
        painter.drawRoundedRect(rect, 4, 4)
        
        # 绘制对勾
        if self.isChecked():
            path = QPainterPath()
            w, h = rect.width(), rect.height()
            
            # 对勾路径
            path.moveTo(rect.left() + w * 0.25, rect.top() + h * 0.5)
            path.lineTo(rect.left() + w * 0.45, rect.top() + h * 0.7)
            path.lineTo(rect.left() + w * 0.75, rect.top() + h * 0.3)
            
            pen = QPen(QColor("white"), 1.5, Qt.PenStyle.SolidLine, 
                      Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.drawPath(path)


def create_check_box(default_checked=False) -> QCheckBox:
    """
    创建复选框

    Args:
        default_checked: bool，是否默认选中，默认False
    
    Returns:
        QCheckBox: 配置好的复选框
    """
    checkbox = StyledCheckBox(colors=UI_Style.COLORS, size=20, border_width=1)
    checkbox.setChecked(default_checked)
    return checkbox
