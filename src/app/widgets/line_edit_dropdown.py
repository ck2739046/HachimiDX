from __future__ import annotations

from PyQt6.QtCore import QEvent, QRect, QRectF, QStringListModel, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QLineEdit, QSizePolicy, QWidget

from ..ui_style import UI_Style
from .dropdown_widget import open_combo_popup


c = UI_Style.COLORS
DROPDOWN_W = 20
BORDER_R = 5


class SplitDropLineEdit(QWidget):
    textChanged = pyqtSignal(str)
    item_triggered = pyqtSignal(int, str)

    def __init__(self, items: list[str] | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._items = list(items or [])
        self._model = QStringListModel(self._items, self)
        self._popup = None
        self._hover_left = False
        self._hover_right = False

        self.line_edit = QLineEdit(self)
        self.line_edit.setFrame(False)
        self.line_edit.setStyleSheet(
            "QLineEdit {"
            "  background: transparent;"
            "  border: none;"
            "  padding: 0px 8px;"
            f"  color: {c['text_primary']};"
            f"  selection-background-color: {c['accent']};"
            "}"
        )
        self.line_edit.installEventFilter(self)
        self.line_edit.textChanged.connect(self.textChanged)

        self.setFixedHeight(UI_Style.element_height)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMouseTracking(True)

    def text(self) -> str:
        return self.line_edit.text()

    def setText(self, text: str) -> None:
        self.line_edit.setText(text)

    def clear(self) -> None:
        self.line_edit.clear()

    def setPlaceholderText(self, text: str) -> None:
        self.line_edit.setPlaceholderText(text)

    def set_items(self, items: list[str]) -> None:
        self._items = list(items)
        self._model.setStringList(self._items)
        self.hidePopup()

    def items(self) -> list[str]:
        return list(self._items)

    def resizeEvent(self, event) -> None:
        self.line_edit.setGeometry(1, 1, max(0, self.width() - DROPDOWN_W - 1), self.height() - 2)
        super().resizeEvent(event)

    def eventFilter(self, obj, event):
        if obj is self.line_edit:
            if event.type() == QEvent.Type.Enter:
                self._hover_left = True
                self.update()
            elif event.type() == QEvent.Type.Leave:
                self._hover_left = False
                self.update()
            elif event.type() in (QEvent.Type.FocusIn, QEvent.Type.FocusOut):
                self.update()
        return super().eventFilter(obj, event)

    def mouseMoveEvent(self, event) -> None:
        self._hover_right = event.position().x() >= self.width() - DROPDOWN_W
        self.setCursor(
            Qt.CursorShape.PointingHandCursor
            if self._hover_right else Qt.CursorShape.ArrowCursor
        )
        self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover_left = False
        self._hover_right = False
        self.unsetCursor()
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if (
            event.button() == Qt.MouseButton.LeftButton
            and event.position().x() >= self.width() - DROPDOWN_W
        ):
            if self._popup is not None:
                self.hidePopup()
            else:
                self.showPopup()
            event.accept()
            return
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        outer = QPainterPath()
        outer.addRoundedRect(QRectF(0, 0, self.width(), self.height()), BORDER_R, BORDER_R)
        painter.fillPath(outer, QColor(c["grey"]))

        painter.setClipPath(outer)
        if self._hover_left:
            painter.fillRect(QRect(0, 0, self.width() - DROPDOWN_W, self.height()), QColor(c["grey_hover"]))
        if self._hover_right:
            painter.fillRect(QRect(self.width() - DROPDOWN_W, 0, DROPDOWN_W, self.height()), QColor(c["grey_hover"]))
        painter.setClipping(False)

        painter.setPen(QPen(QColor(c["grey_hover"]), 1))
        painter.drawPath(outer)
        separator_x = self.width() - DROPDOWN_W
        painter.drawLine(separator_x, 0, separator_x, self.height())

        indicator_color = QColor(c["accent_hover"] if self.line_edit.hasFocus() else c["light_grey"])
        indicator_height = BORDER_R * 2
        indicator = QPainterPath()
        indicator.addRoundedRect(
            QRectF(0, self.height() - indicator_height, self.width(), indicator_height),
            BORDER_R,
            BORDER_R,
        )
        indicator_cutout = QPainterPath()
        indicator_cutout.addRect(
            QRectF(0, self.height() - indicator_height, self.width(), indicator_height - 2)
        )
        painter.fillPath(indicator.subtracted(indicator_cutout), indicator_color)

        painter.setPen(QPen(QColor(c["text_primary"]), 1.2))
        center_x = self.width() - DROPDOWN_W / 2
        center_y = self.height() / 2
        painter.drawLine(int(center_x - 4), int(center_y - 2), int(center_x), int(center_y + 2))
        painter.drawLine(int(center_x + 4), int(center_y - 2), int(center_x), int(center_y + 2))

    def showPopup(self) -> None:
        open_combo_popup(
            self,
            model=self._model,
            width=self.width(),
            on_item_clicked=self._on_item_clicked,
        )

    def hidePopup(self) -> None:
        if self._popup is not None:
            popup = self._popup
            self._popup = None
            popup.close()

    def _on_item_clicked(self, index) -> None:
        row = index.row()
        self.hidePopup()
        if 0 <= row < len(self._items):
            text = self._items[row]
            self.setText(text)
            self.item_triggered.emit(row, text)


def create_split_drop_line_edit(
    items: list[str] | None = None,
    default_text: str = "",
    placeholder: str = "",
    length: int | None = None,
) -> SplitDropLineEdit:
    widget = SplitDropLineEdit(items=items)
    widget.setText(default_text)
    widget.setPlaceholderText(placeholder)
    if length is not None:
        widget.setFixedWidth(length)
    return widget
