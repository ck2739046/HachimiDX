from PyQt6.QtCore import Qt
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import QLineEdit

from ..ui_style import UI_Style


def create_path_display(
    default_text: str | None = None,
    length: int | None = None,
    font_color=UI_Style.COLORS["text_secondary"],
    font_bold: bool = False,
) -> QLineEdit:
    """
    创建路径显示LineEdit组件

    Args:
        default_text: 可选，默认None
        length: 可选，默认None
        font_color: 可选，默认 UI_Style.COLORS['text_secondary']
        font_bold: 可选，默认False

    Returns:
        QLineEdit: 配置好的路径显示LineEdit组件
    """

    # 创建路径显示LineEdit
    line_edit = QLineEdit(default_text or "")
    line_edit.setStyleSheet(
        f"color: {font_color}; font-size: {UI_Style.default_text_size}px; font-weight: {'bold' if font_bold else 'normal'};"
    )
    line_edit.setReadOnly(True)

    if not length:
        line_edit.setFixedHeight(UI_Style.element_height)
    else:
        line_edit.setFixedSize(length, UI_Style.element_height)

    line_edit.setCursor(QCursor(Qt.CursorShape.IBeamCursor))
    line_edit.setFrame(False)

    return line_edit
