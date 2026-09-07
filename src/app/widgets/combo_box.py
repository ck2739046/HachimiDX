from PyQt6.QtWidgets import QComboBox, QSizePolicy
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPainter, QPen, QColor

from ..ui_style import UI_Style
from .dropdown_widget import open_combo_popup

c = UI_Style.COLORS
BORDER_R = 5




class StyledComboBox(QComboBox):
    """
    自定义 ComboBox
    - QSS 主体
    - 自绘 V 形下拉箭头
    - 自定义下拉弹窗
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._popup = None

        self.setStyleSheet(
            f"QComboBox {{"
            f"  background-color: {c['grey']};"
            f"  border: 1px solid {c['grey_hover']};"
            f"  border-radius: {BORDER_R}px;"
            f"  padding-left: 8px;"
            f"  padding-right: 22px;"  # 让文字避让下拉箭头
            f"  color: {c['text_primary']};"
            f"}}"
            f"QComboBox:hover {{"
            f"  background-color: {c['grey_hover']};"
            f"}}"
            f"QComboBox::drop-down {{"  # 隐藏自带的下拉箭头
            f"  width: 0px;"
            f"  border: none;"
            f"}}"
        )

    # ---- popup 生命周期管理 ----
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and not self.isEditable():
            if self._popup is not None:
                self.hidePopup()
            else:
                self.showPopup()
                self.setFocus(Qt.FocusReason.MouseFocusReason)
            event.accept()
            return
        super().mousePressEvent(event)

    def showPopup(self):
        open_combo_popup(self, combo=self, on_item_clicked=self._on_popup_item_clicked)

    def hidePopup(self):
        if self._popup:
            popup = self._popup
            self._popup = None
            popup.close()

    def _on_popup_item_clicked(self, index):
        self.setCurrentIndex(index.row())
        self.hidePopup()
        self.activated.emit(index.row())

    # ---- 自绘 V 形下拉箭头 ----

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(c['text_primary']), 1.2)
        painter.setPen(pen)

        cx = self.width() - 12
        cy = self.height() / 2
        w = 4
        half_h = 2

        painter.drawLine(int(cx - w), int(cy - half_h), int(cx), int(cy + half_h))
        painter.drawLine(int(cx + w), int(cy - half_h), int(cx), int(cy + half_h))






class ToolTipComboBox(StyledComboBox):
    """StyledComboBox with immediate hover tooltip for dropdown items."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._item_tooltips: list[str | None] | None = None

    def set_item_tooltips(self, tooltips: list[str | None]) -> None:
        """为每个选项设置自定义 tooltip 文本，索引一一对应"""
        self._item_tooltips = list(tooltips)

    def showPopup(self):
        open_combo_popup(
            self,
            combo=self,
            show_tooltip=True,
            item_tooltips=self._item_tooltips,
            on_item_clicked=self._on_popup_item_clicked,
        )






def create_combo_box(length=None, items=None, default_index=0, show_tooltip=False, item_tooltips=None):
    """
    创建带悬停提示的下拉选择框

    Args:
        length: int/None，宽度，可选，默认None，代表自适应父布局的 stretch
        items: list，选项列表，可选，默认None
        default_index: int，默认选中的索引，可选，默认0
        show_tooltip: bool，是否显示悬停提示，可选，默认False
        item_tooltips: list[str]/None，逐项自定义 tooltip 文本，索引与 items 一一对应

    Returns:
        配置好的下拉选择框
    """
    if show_tooltip:
        combo = ToolTipComboBox()
    else:
        combo = StyledComboBox()

    combo.setEditable(False)
    combo.setFixedHeight(UI_Style.element_height)

    if length is None:
        combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    else:
        combo.setFixedWidth(length)

    if items:
        str_items = [str(item) for item in items]
        combo.addItems(str_items)
        if 0 <= default_index < len(str_items):
            combo.setCurrentIndex(default_index)

    if show_tooltip and item_tooltips:
        combo.set_item_tooltips(item_tooltips)

    return combo
