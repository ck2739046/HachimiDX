from __future__ import annotations

from PyQt6.QtCore import QPoint, Qt, QRect, QRectF, QStringListModel, pyqtSignal
from PyQt6.QtGui import QPainter, QPen, QPainterPath, QColor
from PyQt6.QtWidgets import QWidget

from ..ui_style import UI_Style
from .combo_box import open_combo_popup


c = UI_Style.COLORS
DROPDOWN_W = 20  # 右侧下拉三角区域宽度
BORDER_R = 6     # 圆角，与 button_qss_base 一致


class SplitDropButton(QWidget):
    """
    左侧按钮 + 中间竖分隔线 + 右侧下拉三角的组合按钮。

    - 整体圆角矩形，配色与现有 accent 按钮一致
    - 左右区域 hover 独立变色
    - 点击右侧弹出与 combo_box 相同的动画下拉菜单
    """

    clicked = pyqtSignal()                 # 点击左区按钮
    item_triggered = pyqtSignal(int, str)  # 点击右区菜单项 (row, text)

    def __init__(self, text: str, items: list[str], width: int | None = None,
                 color: str = 'accent', parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._text = text
        self._items = list(items)
        self._color = color

        self._hover_left = False
        self._hover_right = False
        self._popup = None

        self.setFixedHeight(UI_Style.element_height)
        if width is not None:
            self.setFixedWidth(width)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    # ---- 区域划分 ----

    def _left_rect(self) -> QRect:
        return QRect(0, 0, self.width() - DROPDOWN_W, self.height())

    def _right_rect(self) -> QRect:
        return QRect(self.width() - DROPDOWN_W, 0, DROPDOWN_W, self.height())

    # ---- 绘制 ----

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        outer = QPainterPath()
        outer.addRoundedRect(QRectF(0, 0, w, h), BORDER_R, BORDER_R)

        # 底色
        painter.fillPath(outer, QColor(c[self._color]))

        # 分区 hover（clip 到圆角路径，避免溢出圆角）
        painter.setClipPath(outer)
        hover_color = QColor(c[self._color + '_hover'])
        if self._hover_left:
            painter.fillRect(self._left_rect(), hover_color)
        if self._hover_right:
            painter.fillRect(self._right_rect(), hover_color)
        painter.setClipping(False)

        # 边框
        painter.setPen(QPen(QColor(c[self._color + '_hover']), 1))
        painter.drawPath(outer)

        # 竖分隔线
        sep_x = self.width() - DROPDOWN_W
        painter.setPen(QPen(QColor(c[self._color + '_hover']), 1))
        painter.drawLine(sep_x, 0, sep_x, h)

        # 左区文本
        painter.setPen(QColor(c['text_primary']))
        painter.drawText(self._left_rect(), Qt.AlignmentFlag.AlignCenter, self._text)

        # 右区 V 形三角（与 combo_box 的 paintEvent 一致的画法）
        painter.setPen(QPen(QColor(c['text_primary']), 1.2))
        cx = self.width() - DROPDOWN_W / 2
        cy = h / 2
        tw = 4
        half_h = 2
        painter.drawLine(int(cx - tw), int(cy - half_h), int(cx), int(cy + half_h))
        painter.drawLine(int(cx + tw), int(cy - half_h), int(cx), int(cy + half_h))

        painter.end()

    # ---- 悬停 ----

    def mouseMoveEvent(self, event) -> None:
        x = event.position().x()
        self._hover_left = x < self.width() - DROPDOWN_W
        self._hover_right = x >= self.width() - DROPDOWN_W
        self.update()

    def leaveEvent(self, event) -> None:
        self._hover_left = False
        self._hover_right = False
        self.update()

    # ---- 点击 ----

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            if event.position().x() >= self.width() - DROPDOWN_W:
                self.showPopup()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            if event.position().x() < self.width() - DROPDOWN_W:
                self.clicked.emit()

    # ---- 下拉弹窗 ----

    def showPopup(self) -> None:
        model = QStringListModel(self._items, self)
        open_combo_popup(self, model=model, width=self.width(),
                         on_item_clicked=self._on_item_clicked)

    def hidePopup(self) -> None:
        if self._popup:
            popup = self._popup
            self._popup = None
            popup.close()

    def _on_item_clicked(self, index) -> None:
        row = index.row()
        self.hidePopup()
        if 0 <= row < len(self._items):
            self.item_triggered.emit(row, self._items[row])


def create_split_drop_button(text: str, items: list[str], width: int | None = None,
                             color: str = 'accent') -> SplitDropButton:
    """创建 split 下拉按钮（左按钮 + 右三角）"""
    return SplitDropButton(text, items, width=width, color=color)
