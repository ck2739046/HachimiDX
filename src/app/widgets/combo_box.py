from PyQt6.QtWidgets import (
    QComboBox, QSizePolicy,
)
from PyQt6.QtCore import (
    QPoint, QEvent, Qt,
)
from PyQt6.QtGui import QPainter, QPen, QColor

from ..ui_style import UI_Style
from .dropdown_widget import open_combo_popup
from .popup_tooltip import get_shared_tooltip

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
        self._is_popup_shown = False
        self._connected_view = None
        self._event_filter_installed = False
        self._tooltip = get_shared_tooltip()
        self._item_tooltips: list[str | None] | None = None



    def set_item_tooltips(self, tooltips: list[str]) -> None:
        """为每个选项设置自定义 tooltip 文本，索引一一对应"""
        self._item_tooltips = tooltips
        for i, tip in enumerate(tooltips):
            if i < self.count():
                self.setItemData(i, tip, Qt.ItemDataRole.UserRole)



    def showPopup(self):
        super().showPopup()

        # 清理 view 旧连接
        self._disconnect_view()

        # 连接 _ComboPopup.aboutToHide 信号
        # 当 popup 自行关闭时（点击外部 / ESC）触发清理
        if self._popup is None: return
        self._popup.aboutToHide.connect(self._on_popup_about_to_hide)

        # 安装事件过滤器（避免重复安装）
        view = self._popup.view
        if not view or not view.viewport():
            return
        if not self._event_filter_installed:
            view.viewport().installEventFilter(self)
            self._popup.installEventFilter(self) # 监听 popup 本身的 Leave
            self._event_filter_installed = True

        # 连接新的 view
        try:
            view.entered.connect(self._on_view_entered)
            self._connected_view = view
        except (RuntimeError, TypeError):
            pass

        self._is_popup_shown = True



    def hidePopup(self):
        self._is_popup_shown = False
        self._cleanup_view()
        self._tooltip.hide()
        super().hidePopup()



    def _on_popup_about_to_hide(self):
        """popup 自行关闭时（点击外部 / ESC）清理 tooltip 状态"""
        self._is_popup_shown = False
        self._cleanup_view()
        self._tooltip.hide()



    def _cleanup_view(self):
        """清理 eventFilter 和信号连接"""
        if self._popup is not None:
            # 信号断连
            try:
                self._popup.aboutToHide.disconnect(self._on_popup_about_to_hide)
            except (RuntimeError, TypeError):
                pass
            # 移除事件过滤器
            try:
                self._popup.removeEventFilter(self)
            except (RuntimeError, AttributeError):
                pass
            # 移除事件过滤器
            view = self._popup.view
            if view and view.viewport() and self._event_filter_installed:
                try:
                    view.viewport().removeEventFilter(self)
                except (RuntimeError, AttributeError):
                    pass
                # reset flag
                self._event_filter_installed = False

        # 断连 view
        self._disconnect_view()



    def _disconnect_view(self):
        if self._connected_view:
            try:
                self._connected_view.entered.disconnect(self._on_view_entered)
            except (RuntimeError, TypeError):
                pass
            self._connected_view = None



    def _on_view_entered(self, index):

        # 检查弹窗状态和索引有效性
        if not self._is_popup_shown or not index.isValid():
            self._tooltip.hide()
            return
        
        # 检查 view 和 viewport 是否存在
        if self._popup is None:
            return
        view = self._popup.view
        if not view or not view.viewport():
            return
        viewport = view.viewport()

        row = index.row()
        # 若该选项 tooltip 被显式设为 None，不显示任何 tooltip
        if self._item_tooltips and row < len(self._item_tooltips) and self._item_tooltips[row] is None:
            self._tooltip.hide()
            return
        # 获取自定义 tooltip，若无则回退到显示文本
        text = index.data(Qt.ItemDataRole.UserRole)
        if not text:
            text = index.data()
        if not text:  # 忽略空文本
            self._tooltip.hide()
            return
        text = str(text)

        # 计算 tooltip 显示位置
        viewport_right_x = viewport.mapToGlobal(QPoint(viewport.width(), 0)).x()
        viewport_left_x = viewport.mapToGlobal(QPoint(0, 0)).x()
        item_rect = view.visualRect(index)
        item_center_y = item_rect.center().y()
        item_center_global = viewport.mapToGlobal(QPoint(0, item_center_y))

        # tooltip 默认显示在右侧
        x_offset = -5   # 向左 5px
        y_offset = -29  # 向上 29px
        tip_w = self._tooltip.measure(text).width()
        x_right = viewport_right_x + x_offset
        x_left = viewport_left_x - x_offset - tip_w
        y = item_center_global.y() + y_offset
        tooltip_pos = QPoint(x_right, y)
        # 检查 tooltip 是否超出主窗口右缘
        win = self.window()
        if win is not None:
            rect = win.frameGeometry()
            if rect.isValid() and not rect.isEmpty():
                if x_right + tip_w > rect.right():
                    # 右侧越界，尝试显示在左侧
                    if x_left >= rect.left():
                        tooltip_pos = QPoint(x_left, y)
                    # 左边也越界则仍显示在右侧

        self._tooltip.show_text(text, tooltip_pos)



    def eventFilter(self, obj, event):
        if not self._is_popup_shown:
            return super().eventFilter(obj, event)
        if event.type() == QEvent.Type.Leave:
            if self._popup:
                if (obj == self._popup.view.viewport() or obj == self._popup):
                    self._tooltip.hide()
        return super().eventFilter(obj, event)



    def __del__(self):
        try:
            self._disconnect_view()
            if self._popup is not None:
                view = self._popup.view
                if view and view.viewport() and self._event_filter_installed:
                    view.viewport().removeEventFilter(self)
        except (RuntimeError, AttributeError):
            pass













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
