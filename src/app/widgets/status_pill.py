"""通用状态胶囊组件。

用于把「环境可用」「模型可用」这类短状态显示成带底色的胶囊，
支持 success / warning / error 三种语义色，供各页面复用。
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QSizePolicy

from ..ui_style import UI_Style

_LEVEL_COLORS = {
    "success": (
        UI_Style.COLORS["success"],
        "rgba(95, 201, 126, 16%)",
        "rgba(95, 201, 126, 55%)",
    ),
    "warning": (
        UI_Style.COLORS["warning"],
        "rgba(230, 180, 80, 16%)",
        "rgba(230, 180, 80, 55%)",
    ),
    "error": (
        UI_Style.COLORS["error"],
        "rgba(255, 138, 138, 16%)",
        "rgba(255, 138, 138, 55%)",
    ),
}


class StatusPill(QLabel):
    """带文字的胶囊状态标签，内置三种语义色。"""

    def __init__(self, text: str = "", level: str = "success", parent=None):
        super().__init__(text, parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFixedHeight(20)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.set_status(text, level)

    def set_status(self, text: str, level: str) -> None:
        """更新胶囊文字和颜色（success / warning / error）。"""
        self.setText(text)
        text_color, background, border = _LEVEL_COLORS.get(
            level, _LEVEL_COLORS["error"]
        )
        self.setStyleSheet(
            f"QLabel {{"
            f"  background-color: {background};"
            f"  color: {text_color};"
            f"  border: 1px solid {border};"
            f"  border-radius: 10px;"
            f"  padding: 0px 8px;"
            f"  font-size: {UI_Style.default_text_size - 1}px;"
            f"}}"
        )
        self.adjustSize()


def create_status_pill(text: str = "", level: str = "success") -> StatusPill:
    """创建状态胶囊；level 取 success / warning / error。"""
    return StatusPill(text, level)
