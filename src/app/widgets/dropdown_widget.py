import ctypes
import sys

from PyQt6.QtWidgets import (
    QComboBox, QStyledItemDelegate, QListView, QFrame, QVBoxLayout,
    QStyle, QAbstractItemView, QApplication,
)
from PyQt6.QtCore import (
    QPoint, Qt, QPropertyAnimation, QRect, QRectF, QTimer,
    QEasingCurve, QSize, pyqtSignal,
)
from PyQt6.QtGui import (
    QCursor, QKeySequence, QPainter, QPen, QColor, QRegion,
    QPainterPath, QShortcut,
)

from ..ui_style import UI_Style

c = UI_Style.COLORS
BORDER_R = 5
BORDER_R_Sub = 3   # 下拉菜单内部子项的矩形圆角
POPUP_MAX_H = 300  # 下拉菜单最大高度，超出则显示滚动条


class ComboItemDelegate(QStyledItemDelegate):
    """
    自绘下拉菜单项：
        对已选中的选项，文字左侧添加箭头并加粗
        对悬停的选项 accent 高亮
        绘制选项间的分隔线
        绘制选项文字
    """

    def __init__(self, parent, combo: QComboBox | None = None):
        super().__init__(parent)
        self._combo = combo

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
            is_selected = self._combo is not None and index.row() == self._combo.currentIndex()
            if is_selected:
                font = painter.font()
                font.setBold(True)
                painter.setFont(font)
                # → ↠ ↣ ↪ ↬ ⇀ ⇁ ⇉ ⇒ ⇛ ➡
                # ⇝ ⇢ ⇥ ⇨ ⇰ ⇴ ⇶ ⇸ ⇻ ⇾
                # 👉 ➡️ ⏭️ ⏩ » > ＞
                # ▶ ► ▸ ▹ ► ▻
                display_text = f"👉 {text}"
            else:
                display_text = str(text)
            text_rect = option.rect.adjusted(8, 0, -8, 0)
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter, display_text)

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

    def __init__(self, combo: QComboBox | None = None, model=None):
        super().__init__()
        self.setModel(model if model is not None else combo.model())
        self.setItemDelegate(ComboItemDelegate(self, combo))
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

    def __init__(self, combo: QComboBox | None = None, model=None, anchor=None):
        super().__init__(None)
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint  # 无边框
            | Qt.WindowType.NoDropShadowWindowHint  # 无阴影
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)  # 透明背景

        self._combo = combo
        self._anchor = anchor if anchor is not None else combo
        self._ani: QPropertyAnimation | None = None
        self._end_y: int = 0
        self._wait_for_mouse_button_release = False
        self._outside_click_timer = QTimer(self)
        self._outside_click_timer.setInterval(16)
        self._outside_click_timer.timeout.connect(self._check_outside_click)
        self._escape_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        self._escape_shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self._escape_shortcut.activated.connect(self.close)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.view = ComboListView(combo, model)
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
        self.view.setFixedSize(width, full_h)  # 显示设置 view 尺寸

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
        self._wait_for_mouse_button_release = self._left_button_down()
        self._outside_click_timer.start()

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
        anchor = self._anchor
        if anchor is not None and getattr(anchor, '_popup', None) is self:
            anchor._popup = None

        self._outside_click_timer.stop()
        self._escape_shortcut.setEnabled(False)
        super().hideEvent(event)

    @staticmethod
    def _left_button_down() -> bool:
        if sys.platform == 'win32':
            return bool(ctypes.windll.user32.GetAsyncKeyState(0x01) & 0x8000)
        return bool(QApplication.mouseButtons() & Qt.MouseButton.LeftButton)

    @staticmethod
    def _escape_key_down() -> bool:
        if sys.platform == 'win32':
            return bool(ctypes.windll.user32.GetAsyncKeyState(0x1B) & 0x8000)
        return False

    def _check_outside_click(self):
        if self._escape_key_down():
            self.close()
            return
        left_button_down = self._left_button_down()
        if self._wait_for_mouse_button_release:
            if not left_button_down:
                self._wait_for_mouse_button_release = False
            return
        if left_button_down and not self.frameGeometry().contains(QCursor.pos()):
            self.close()


def open_combo_popup(anchor, combo=None, model=None, width=None, on_item_clicked=None) -> bool:
    """
    共享的下拉菜单弹出逻辑，供 StyledComboBox 与 SplitDropButton 复用。

    - anchor: 弹窗锚点，需提供 mapToGlobal / height / width，并用 `_popup` 引用当前弹窗
    - combo: 需要选中态箭头时的关联 combo（可为 None）
    - model: 列表模型；None 时回退 combo.model()
    - width: 弹窗宽度；None 时使用 anchor.width()

    成功打开返回 True；无需打开（已打开或无选项）返回 False。
    """
    if getattr(anchor, '_popup', None) is not None:
        anchor.hidePopup()
        return False

    popup = _ComboPopup(combo=combo, model=model, anchor=anchor)
    if popup.view.model().rowCount() == 0:
        popup.close()
        return False

    anchor._popup = popup
    if on_item_clicked is not None:
        popup.view.clicked.connect(on_item_clicked)

    pos = anchor.mapToGlobal(QPoint(0, anchor.height() + 4))
    popup.show_animated(pos, width if width is not None else anchor.width())
    return True
