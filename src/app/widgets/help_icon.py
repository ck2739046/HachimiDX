from PyQt6.QtWidgets import QLabel
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QCursor
from ..ui_style import UI_Style
from .label import create_label
from .popup_tooltip import install_tooltip

def create_help_icon(text):
    """
    创建帮助图标（ⓘ），鼠标悬停后过一会儿显示提示文本
    
    Args:
        text: str，提示文本内容
    
    Returns:
        QLabel: 配置好的帮助图标widget
    """
    help_label = create_label("ⓘ")
    help_label.setFixedSize(20, 20)
    help_label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
    help_label.setCursor(QCursor(Qt.CursorShape.WhatsThisCursor))

    install_tooltip(help_label, text)
    return help_label
