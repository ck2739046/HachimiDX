from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..ui_style import UI_Style


_SCROLLBAR_STYLE = f"""
    QScrollBar:horizontal {{
        background-color: {UI_Style.COLORS['bg']};
        height: 11px;
        margin-top: 4px;
        border: none;
    }}
    QScrollBar::handle:horizontal {{
        background-color: {UI_Style.COLORS['light_grey']};
    }}
    QScrollBar::handle:horizontal:hover {{
        background-color: {UI_Style.COLORS['accent']};
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0px;
    }}
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
        background: none;
    }}
"""


class _DragLabel(QLabel):
    """QLabel that supports mouse-drag to scroll a parent QScrollArea horizontally."""

    def __init__(self, scroll_area: QScrollArea, parent: QWidget | None = None):
        super().__init__(parent)
        self._scroll_area = scroll_area
        self._dragging = False
        self._drag_start_x = 0
        self._scroll_start_value = 0
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._drag_start_x = int(event.globalPosition().x())
            self._scroll_start_value = self._scroll_area.horizontalScrollBar().value()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragging:
            dx = int(event.globalPosition().x()) - self._drag_start_x
            hbar = self._scroll_area.horizontalScrollBar()
            new_value = self._scroll_start_value - dx
            new_value = max(0, min(new_value, hbar.maximum()))
            hbar.setValue(new_value)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._dragging and event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()
        else:
            super().mouseReleaseEvent(event)






class ScrollableImageLabel(QWidget):
    """A horizontally scrollable image viewer with mouse-drag panning.

    Usage:
        label = ScrollableImageLabel()
        label.setMinimumHeight(210)
        label.set_image(QPixmap("wave.png"))
        label.clear_image()
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(False)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet(_SCROLLBAR_STYLE)

        self._label = _DragLabel(self._scroll)
        self._scroll.setWidget(self._label)

        layout.addWidget(self._scroll)

    def set_image(self, pixmap: QPixmap) -> None:
        """Display pixmap at its native resolution and make the widget visible."""
        self._label.setPixmap(pixmap)
        self._label.setFixedSize(pixmap.size())
        self.show()

    def clear_image(self) -> None:
        """Remove the current image (does not change visibility)."""
        self._label.clear()
        self._label.setFixedSize(0, 0)
