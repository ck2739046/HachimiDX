from PyQt6.QtWidgets import QWidget, QHBoxLayout, QPushButton, QButtonGroup
from PyQt6.QtCore import pyqtSignal, QEvent
from ..ui_style import UI_Style
from .popup_tooltip import install_tooltip


class SegmentedNavBar(QWidget):
    """
    通用分段导航栏
    """
    currentChanged = pyqtSignal(int)

    def __init__(self, items: list[str],
                 height: int,
                 parent=None,
                 tooltip_texts: list[str] | None = None):
        super().__init__(parent)
        self.items = items
        self.height = height
        self.tooltip_texts = tooltip_texts or []
        self.setup_ui()


    def setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.button_group = QButtonGroup(self)
        self.button_group.setExclusive(True)
        self._hovered_btn: QPushButton | None = None

        self.button_group.idClicked.connect(self.currentChanged.emit)

        for i, text in enumerate(self.items):
            btn = QPushButton(text)
            btn.setCheckable(True)
            btn.setFixedHeight(self.height)
            btn.setMouseTracking(True)
            btn.installEventFilter(self)
            
            # 设置样式
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {UI_Style.COLORS['surface']};
                    color: {UI_Style.COLORS['text_secondary']};
                    border: none;
                    font-size: 14px;
                    font-weight: bold;
                }}
                QPushButton[hovered="true"] {{
                    background-color: {UI_Style.COLORS['surface_hover']};
                }}
                QPushButton:checked {{
                    background-color: {UI_Style.COLORS['accent']};
                    color: {UI_Style.COLORS['text_primary']};
                    border: none;
                    font-size: 14px;
                    font-weight: bold;
                }}
                QPushButton:checked[hovered="true"] {{
                    background-color: {UI_Style.COLORS['accent_hover']};
                }}
            """)

            layout.addWidget(btn)
            self.button_group.addButton(btn, i)

            # 为该按钮安装 tooltip
            if i < len(self.tooltip_texts):
                install_tooltip(btn, self.tooltip_texts[i])

        # 默认选中第一个
        if self.button_group.buttons():
            self.button_group.buttons()[0].setChecked(True)


    def setCurrentIndex(self, index: int) -> None:
        """编程方式切换选中项，触发 currentChanged 信号"""
        buttons = self.button_group.buttons()
        if 0 <= index < len(buttons):
            buttons[index].click()


    # ── 集中管理 hover 状态 ────────────────────────────────
    def eventFilter(self, watched, event):
        if isinstance(watched, QPushButton) and watched in self.button_group.buttons():
            t = event.type()
            if t == QEvent.Type.Enter or t == QEvent.Type.MouseMove:
                self._set_hover_button(watched)
            elif t == QEvent.Type.Leave:
                self._clear_hover_if(watched)
        return super().eventFilter(watched, event)

    def _set_hover_button(self, btn):
        # 整个导航栏在任何时刻，最多只有一个按钮处于 hover 状态
        if self._hovered_btn is btn:
            return
        self._clear_all_hover()
        self._hovered_btn = btn
        btn.setProperty("hovered", True)
        self._repolish(btn)

    def _clear_hover_if(self, btn):
        # leave 事件保守处理
        # 只有当离开的按钮恰好是 hovered 按钮时，才清空 hover 状态
        if self._hovered_btn is btn:
            self._clear_all_hover()

    def _clear_all_hover(self):
        if self._hovered_btn:
            old = self._hovered_btn
            old.setProperty("hovered", False)
            self._repolish(old)
            self._hovered_btn = None

    @staticmethod
    def _repolish(w):
        # 强制即时重绘
        w.style().unpolish(w)
        w.style().polish(w)
        w.update()
