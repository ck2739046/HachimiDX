from PyQt6.QtCore import QPoint, QRect, QSize, Qt, QTimer
from PyQt6.QtGui import QColor, QCursor, QFont
from PyQt6.QtWidgets import QApplication, QFrame, QGraphicsDropShadowEffect, QLabel, QVBoxLayout, QWidget

from ..ui_style import UI_Style


class PopupToolTip(QWidget):

    def __init__(self):
        super().__init__(None, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        # 带外圈阴影的总体布局
        root_layout = QVBoxLayout(self)
        # 这里的边距是给主体外部的阴影留出空间
        root_layout.setContentsMargins(12, 12, 12, 12)

        self._bubble = QFrame(self)
        self._bubble.setObjectName("tooltipBubble")
        root_layout.addWidget(self._bubble)

        # tooltip 主体内部的布局
        bubble_layout = QVBoxLayout(self._bubble)
        # 这里是文本与边框的边距
        bubble_layout.setContentsMargins(12, 8, 12, 8)
        bubble_layout.setSpacing(0)

        self._label = QLabel(self._bubble)
        self._label.setTextFormat(Qt.TextFormat.PlainText)
        self._label.setWordWrap(False)
        self._label.setStyleSheet(f"background: transparent; color: {UI_Style.COLORS['text_primary']};")
        bubble_layout.addWidget(self._label)

        # 阴影效果
        shadow = QGraphicsDropShadowEffect(self._bubble)
        shadow.setBlurRadius(20)               # 模糊半径
        shadow.setColor(QColor(0, 0, 0, 100))  # 半透明黑色
        shadow.setOffset(0, 3)                 # 向右下方向
        self._bubble.setGraphicsEffect(shadow)

        self._bubble.setStyleSheet(
            f"""
            QFrame#tooltipBubble {{
                border: 1px solid rgba(0, 0, 0, 0.2);
                border-radius: 6px;
                background-color: {UI_Style.COLORS['grey']};
                color: {UI_Style.COLORS['text_secondary']};
            }}
            """
        )

        font = QFont()
        font.setFamilies(['Consolas', 'Microsoft YaHei UI'])
        font.setBold(True)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self._label.setFont(font)



    def _prepare(self, text: str) -> QSize:
        """设置文本并重算尺寸，返回 tooltip 总尺寸（不显示）"""
        self._label.setText(text)
        self._label.adjustSize()          # 从里到外调整尺寸
        self._bubble.adjustSize()
        self.adjustSize()
        return self.size()

    def measure(self, text: str) -> QSize:
        """计算给定文本的 tooltip 尺寸（不显示，供调用方定位用）"""
        text_to_show = text.rstrip()
        if not text_to_show:
            return QSize()
        return self._prepare(text_to_show)

    @staticmethod
    def _screen_avail(point) -> QRect:
        """点所在屏幕的可用区域，取不到时回退主屏"""
        screen = QApplication.screenAt(point)
        if screen is None:
            screen = QApplication.primaryScreen()
        return screen.availableGeometry() if screen is not None else QRect()

    def show_text(self, text: str, global_pos):
        text_to_show = text.rstrip()
        if not text_to_show: return

        self._prepare(text_to_show)
        self.move(global_pos)             # 移动位置
        self.show()
        self.raise_()                     # 提升到顶层，防止被其他窗口遮挡



    def show_near_cursor(self, text: str, cursor_pos):
        """在光标旁显示，自动选择不越出所在屏幕的一侧（右下→左下→右上→左上）"""
        text_to_show = text.rstrip()
        if not text_to_show: return

        size = self._prepare(text_to_show)
        avail = self._screen_avail(cursor_pos)

        w, h = size.width(), size.height()
        cx, cy = cursor_pos.x(), cursor_pos.y()
        candidates = [QPoint(cx, cy),           # 右下
                      QPoint(cx - w, cy),       # 左下
                      QPoint(cx, cy - h),       # 右上
                      QPoint(cx - w, cy - h)]   # 左上

        target = None
        for pos in candidates:
            if (pos.x() >= avail.left() and pos.x() + w <= avail.right()
                    and pos.y() >= avail.top() and pos.y() + h <= avail.bottom()):
                target = pos
                break

        if target is None:
            # 均放不下，默认回到右下
            target = candidates[0]

        self.move(target)
        self.show()
        self.raise_()






# 全局共享的 tooltip 单例, lazy initialization
# 避免 QWidget: Must construct a QApplication before a QWidget 错误
_shared_tooltip = None

def get_shared_tooltip() -> PopupToolTip:
    global _shared_tooltip
    if _shared_tooltip is None:
        _shared_tooltip = PopupToolTip()
    return _shared_tooltip


DEFAULT_TOOLTIP_DELAY_MS = 500


def install_tooltip(widget, text: str, delay_ms: int = DEFAULT_TOOLTIP_DELAY_MS) -> None:
    """
    为任意 widget 安装悬停 tooltip（共享单例）。

    鼠标进入后延迟 delay_ms 毫秒显示，离开时立即隐藏。
    若 text 为空则不安装任何行为。

    Args:
        widget:  目标 QWidget
        text:    tooltip 显示的文本，空字符串表示不显示
        delay_ms: 延迟毫秒数，默认 500
    """
    if not text:
        return

    tooltip = get_shared_tooltip()
    timer: QTimer | None = None

    def _enter_event(_event):
        nonlocal timer
        if timer is not None:
            timer.stop()
        timer = QTimer(widget)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda: tooltip.show_near_cursor(text, QCursor.pos()))
        timer.start(delay_ms)

    def _leave_event(_event):
        nonlocal timer
        if timer is not None:
            timer.stop()
            timer = None
        tooltip.hide()

    widget.enterEvent = _enter_event
    widget.leaveEvent = _leave_event
