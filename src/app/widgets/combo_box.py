from PyQt6.QtWidgets import (
    QComboBox, QStyledItemDelegate, QListView, QFrame, QVBoxLayout,
    QStyle, QAbstractItemView, QApplication,
)
from PyQt6.QtCore import (
    QPoint, QEvent, Qt, QPropertyAnimation, QRect, QRectF,
    QEasingCurve, QSize, pyqtSignal,
)
from PyQt6.QtGui import QPainter, QPen, QColor, QRegion, QPainterPath

from ..ui_style import UI_Style
from .popup_tooltip import get_shared_tooltip

c = UI_Style.COLORS
BORDER_R = 5
BORDER_R_Sub = 3   # 下拉菜单内部子项的矩形圆角
POPUP_MAX_H = 300  # 下拉菜单最大高度，超出则显示滚动条




class ComboItemDelegate(QStyledItemDelegate):
    """
    自绘下拉菜单项：
        选中的选项 accent 高亮
        绘制选项间的分隔线
        绘制选项文字
    """

    def sizeHint(self, option, index):
        return QSize(0, UI_Style.element_height)

    def paint(self, painter, option, index):
        painter.save()

        # 选项高亮
        is_highlight = bool(option.state & QStyle.StateFlag.State_MouseOver)
        if is_highlight:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            r = option.rect.adjusted(2, 2, -2, -2)  # 内部收缩 2px
            path = QPainterPath()
            path.addRoundedRect(QRectF(r), BORDER_R_Sub, BORDER_R_Sub)
            painter.fillPath(path, QColor(c['accent']))

        # 选项文字
        text = index.data(Qt.ItemDataRole.DisplayRole)
        if text is not None:
            painter.setPen(QColor(c['text_primary']))
            text_rect = option.rect.adjusted(8, 0, -8, 0)
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter, str(text))

        # 选项之间的分隔线
        model = index.model()
        # 在每一项的底部绘制分隔线，并跳过最后一项
        if model and index.row() < model.rowCount() - 1:
            painter.setPen(QPen(QColor(c['grey_hover']), 0.8))
            y = option.rect.bottom() + 1
            painter.drawLine(option.rect.left() + 4, y, option.rect.right() - 4, y)

        painter.restore()











class ComboListView(QListView):
    """下拉列表视图：共享 QComboBox 的 model"""

    def __init__(self, combo: QComboBox):
        super().__init__()
        self.setModel(combo.model())
        self.setItemDelegate(ComboItemDelegate(self))
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.setMouseTracking(True)
        self.setUniformItemSizes(True)

        self.setStyleSheet(f"""
            QListView {{
                background-color: {c['grey']};
                border: 1px solid {c['grey_hover']};
                border-radius: {BORDER_R}px;
            }}
        """)











class _ComboPopup(QFrame):
    """下拉菜单的弹窗容器，有展开的动画"""

    aboutToHide = pyqtSignal()

    def __init__(self, combo: QComboBox):
        super().__init__(None)
        self.setWindowFlags(
            Qt.WindowType.Popup  # 点击其他地方自动关闭
            | Qt.WindowType.FramelessWindowHint  # 无边框
            | Qt.WindowType.NoDropShadowWindowHint  # 无阴影
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)  # 透明背景

        self._combo = combo
        self._ani: QPropertyAnimation | None = None
        self._end_y: int = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.view = ComboListView(combo)
        layout.addWidget(self.view)



    def show_animated(self, pos: QPoint, width: int):
        """
        在 pos 处以展开动画弹出
        - 动画属性: b'pos'（Qt 原生属性，start() 会同步设置起始值）
        - mask: 从 end_y - current_y 计算，逐步揭示内容
        - 方向: 超出最大高度或屏幕空间不足时启用滚动条
        """
        rows = self.view.model().rowCount() if self.view.model() else 0
        if rows == 0:
            return

        content_h = rows * UI_Style.element_height + 2

        # 如果下拉菜单超出最大高度，或屏幕下方空间不够放下整个下拉菜单，启用滚动条
        screen = QApplication.screenAt(pos)
        if screen:
            avail_geo = screen.availableGeometry()
            space_below = avail_geo.bottom() - pos.y() - 10
        else:
            space_below = 99999

        full_h = min(content_h, space_below, POPUP_MAX_H)
        self.view.setFixedSize(width, full_h) # 显示设置 view 尺寸

        if full_h < content_h:
            # 显示滚动条
            self.view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            self.view.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        else:
            # 隐藏滚动条
            self.view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)





        # 设置最终 geometry
        self.setGeometry(QRect(pos.x(), pos.y(), width, full_h))
        self._end_y = pos.y()
        start_pos = QPoint(pos.x(), pos.y() - full_h)

        # 设置起始位置 + 初始 mask
        self.move(start_pos)
        self.setMask(QRegion(0, full_h, width, full_h))

        # 创建并启动动画
        self._ani = QPropertyAnimation(self, b'pos', self)
        self._ani.setStartValue(start_pos)
        self._ani.setEndValue(pos)
        self._ani.setDuration(200)
        self._ani.setEasingCurve(QEasingCurve.Type.OutQuad)
        self._ani.valueChanged.connect(self._on_ani_step)
        self._ani.finished.connect(self._on_ani_finished)
        self._ani.start()

        # 最后再显示下拉菜单，避免闪烁
        self.show()



    def _on_ani_step(self):
        """动画每帧更新 mask"""
        y = self._end_y - self.y()
        self.setMask(QRegion(0, y, self.width(), self.height()))

    def _on_ani_finished(self):
        """动画结束，清除 mask"""
        self.setMask(QRegion())

    def hideEvent(self, event):
        # 发送停止信号
        self.aboutToHide.emit()
        # 停止动画
        if self._ani and self._ani.state() == QPropertyAnimation.State.Running:
            self._ani.stop()
            self._ani = None
        # 清除遮罩
        self.setMask(QRegion())
        # cleanup
        if self._combo and self._combo._popup is self:
            self._combo._popup = None

        super().hideEvent(event)











class StyledComboBox(QComboBox):
    """
    自定义 ComboBox
    - QSS 主体
    - 自绘 V 形下拉箭头
    - 自定义下拉弹窗
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._popup: _ComboPopup | None = None

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

    def showPopup(self):
        if self._popup is not None:
            self.hidePopup()
            return
        if self.count() == 0:
            return
        self._popup = _ComboPopup(self)
        self._popup.view.clicked.connect(self._on_popup_item_clicked)
        pos = self.mapToGlobal(QPoint(0, self.height() + 4))
        self._popup.show_animated(pos, self.width())

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

    def paintEvent(self, e):
        super().paintEvent(e)
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

        # 获取选项文本
        text = index.data()
        if not text:  # 忽略空文本
            self._tooltip.hide()
            return
        text = str(text)

        # 计算 tooltip 显示位置（选项右侧）
        viewport_right = viewport.mapToGlobal(QPoint(viewport.width(), 0))
        item_rect = view.visualRect(index)
        item_center_y = item_rect.center().y()
        item_center_global = viewport.mapToGlobal(QPoint(0, item_center_y))

        # 显示 tooltip
        tooltip_pos = QPoint(viewport_right.x() - 5, item_center_global.y() - 29)
                                            # 此处是向左 5px，向上 29px
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













def create_combo_box(length, items=None, default_index=0, show_tooltip=False):
    """
    创建带悬停提示的下拉选择框

    Args:
        length: int，宽度（像素）
        items: list，选项列表，可选，默认None
        default_index: int，默认选中的索引，可选，默认0
        show_tooltip: bool，是否显示悬停提示，可选，默认False

    Returns:
        配置好的下拉选择框
    """
    if show_tooltip:
        combo = ToolTipComboBox()
    else:
        combo = StyledComboBox()

    combo.setEditable(False)
    combo.setFixedSize(length, UI_Style.element_height)

    if items:
        str_items = [str(item) for item in items]
        combo.addItems(str_items)
        if 0 <= default_index < len(str_items):
            combo.setCurrentIndex(default_index)

    return combo
