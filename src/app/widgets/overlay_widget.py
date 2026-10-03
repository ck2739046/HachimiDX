from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QWidget


class OverlayWidget(QWidget):
    """
    A semi-transparent overlay widget that covers its parent.
    Used to visually indicate that a section is disabled while intercepting mouse events.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.hide()  # Hidden by default

        if parent:
            parent.installEventFilter(self)
            self.resize(parent.size())
            self.move(0, 0)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.fillRect(self.rect(), QColor(60, 60, 60, 170))

    def eventFilter(self, obj, event):
        if obj == self.parent() and event.type() == QEvent.Type.Resize:
            self.resize(event.size())
        return super().eventFilter(obj, event)
