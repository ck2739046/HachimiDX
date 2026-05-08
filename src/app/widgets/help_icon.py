from PyQt6.QtWidgets import QLabel
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QCursor
from ..ui_style import UI_Style
from src.app.widgets.popup_tooltip import get_shared_tooltip

def create_help_icon(text):
    """
    创建帮助图标（ⓘ），鼠标悬停时显示提示文本
    
    Args:
        text: str，提示文本内容
    
    Returns:
        QLabel: 配置好的帮助图标widget
    """
    tooltip = get_shared_tooltip()

    def enter_event():
        tooltip.show_text(text, QCursor.pos())

    help_label = QLabel("ⓘ")
    help_label.setStyleSheet(f"font-size: {UI_Style.default_text_size}px;")
    help_label.setFixedSize(20, 20)
    help_label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
    help_label.setCursor(QCursor(Qt.CursorShape.WhatsThisCursor))
    help_label.enterEvent = lambda event: enter_event()
    help_label.leaveEvent = lambda event: tooltip.hide()
    return help_label
