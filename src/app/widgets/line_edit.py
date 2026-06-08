from PyQt6.QtWidgets import QLineEdit, QToolButton, QHBoxLayout
from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QPainter, QPainterPath, QPen, QColor, QDoubleValidator, QIntValidator

from ..ui_style import UI_Style

c = UI_Style.COLORS
BORDER_R = 5


class _ClearButton(QToolButton):
    """内嵌清除按钮，用 QPainter 画交叉线"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(14, 14)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.hide()

    def paintEvent(self, e):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(c['text_primary']), 1)
        painter.setPen(pen)

        margin = 3
        painter.drawLine(margin, margin, self.width() - margin, self.height() - margin)
        painter.drawLine(self.width() - margin, margin, margin, self.height() - margin)








class StyledLineEdit(QLineEdit):
    """自定义 LineEdit：QSS 统一样式 + paintEvent 底部高亮线 + 可选清除按钮"""

    # 底部高亮线颜色
    _FOCUS_COLOR = QColor(c['accent_hover'])
    _UNFOCUS_COLOR = QColor(c['light_grey'])

    def __init__(self, parent=None, *, clear_button_enabled=False):
        super().__init__(parent)
        self._clearBtnEnabled = clear_button_enabled

        self.setStyleSheet(
             "QLineEdit {"
            f"  background-color: {c['grey']};"
            f"  border: 1px solid {c['grey_hover']};"
            f"  border-radius: {BORDER_R}px;"
            f"  padding: 0px 8px;"
            f"  color: {c['text_primary']};"
            f"  selection-background-color: {c['accent']};"
             "}"
            f"QLineEdit:hover {{ background-color: {c['grey_hover']}; }}"
        )

        self._clearButton = None
        self._hBoxLayout = None
        if clear_button_enabled:
            self._initClearButton()





    def _initClearButton(self):
        if self._hBoxLayout is None:
            self._hBoxLayout = QHBoxLayout(self)
            self._hBoxLayout.setContentsMargins(0, 0, 4, 0)
            self._hBoxLayout.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._clearButton = _ClearButton(self)
        self._hBoxLayout.addWidget(self._clearButton, 0, Qt.AlignmentFlag.AlignRight)
        self._clearButton.clicked.connect(self.clear)
        self.textChanged.connect(self._onTextChanged)
        self.setTextMargins(0, 0, 14, 0)




    def _drawBottomArc(self, painter: QPainter):
        color = self._FOCUS_COLOR if self.hasFocus() else self._UNFOCUS_COLOR
        painter.setBrush(color)

        m = self.contentsMargins()
        w = self.width() - m.left() - m.right()
        h = self.height()

        arc_h = BORDER_R * 2
        path = QPainterPath()
        path.addRoundedRect(QRectF(m.left(), h - arc_h, w, arc_h), BORDER_R, BORDER_R)

        rect_path = QPainterPath()
        rect_path.addRect(QRectF(m.left(), h - arc_h, w, arc_h - 2))

        path = path.subtracted(rect_path)
        painter.fillPath(path, color)






    def _shouldShowClear(self) -> bool:
        return self._clearBtnEnabled and bool(self.text()) and self.hasFocus()

    def _updateClearVisible(self):
        if self._clearButton:
            self._clearButton.setVisible(self._shouldShowClear())

    def focusInEvent(self, e):
        super().focusInEvent(e)
        self._updateClearVisible()

    def focusOutEvent(self, e):
        super().focusOutEvent(e)
        if self._clearButton:
            self._clearButton.hide()

    def _onTextChanged(self, text):
        self._updateClearVisible()

    def paintEvent(self, e):
        super().paintEvent(e)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        self._drawBottomArc(painter)








def create_line_edit(default_text=None, placeholder=None, length=None, validator=None, clear_button=False):
    """
    创建文本输入框

    Args:
        default_text: str，可选
        placeholder: str，可选
        length: int，可选，固定宽度
        validator: str，可选，取值可以是 int 或 float/double
        clear_button: bool，可选，是否启用清除按钮，默认 False

    Returns:
        StyledLineEdit: 配置好的文本输入框
    """

    line_edit = StyledLineEdit(clear_button_enabled=clear_button)

    if length:
        line_edit.setFixedSize(length, UI_Style.element_height)
    else:
        line_edit.setFixedHeight(UI_Style.element_height)

    if placeholder:
        line_edit.setPlaceholderText(placeholder)

    if validator == 'int':
        line_edit.setValidator(QIntValidator())
    elif validator in ('float', 'double'):
        line_edit.setValidator(QDoubleValidator())

    if default_text:
        line_edit.setText(default_text)

    return line_edit
