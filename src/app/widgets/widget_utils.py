from PyQt6.QtCore import Qt
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import QLayout, QWidget


def clear_layout(layout: QLayout) -> None:
    """
    清空布局中的所有项并销毁其 widget。

    必须先 hide() 再 setParent(None)：setParent(None) 会把控件变成"顶层窗口"，
    而它此刻仍是可见的 —— Qt 会真的把这块控件当成一个带标题栏的窗口显示出来
    （标题栏用 Qt 默认标题，即应用名；本项目没设过 applicationName，于是显示 "python"），
    随后 deleteLater() 又把它销毁，用户就会看到"闪一下的空窗口"。
    tasks page 每次刷新任务卡片都会走这里，所以点 ✕ 取消任务时最容易看到。
    """
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w is not None:
            w.hide()
            w.setParent(None)
            w.deleteLater()


# ── 可点击控件的手型光标 ─────────────────────────────────────────────
# Qt 样式表不支持 cursor 属性，只能对每个控件调用 setCursor()；漏掉一个就会
# 出现“鼠标移到按钮上图标没变成可点击”的情况。
# 约定：可点击控件在构造时调用 set_pointer_cursor()，并在自己的 changeEvent
# 里响应 EnabledChange 维护禁用态（见 button.py / combo_box.py / check_box.py）。

_POINTING_HAND_CURSOR = QCursor(Qt.CursorShape.PointingHandCursor)
_ARROW_CURSOR = QCursor(Qt.CursorShape.ArrowCursor)

# 视为“未自定义”的光标：只有这两种才允许被手型光标覆盖，
# I 型（输入框）、问号（帮助图标）、抓手（可拖拽图片）等有意设置的光标保持原样
_NEUTRAL_CURSOR_SHAPES = (Qt.CursorShape.ArrowCursor, Qt.CursorShape.PointingHandCursor)


def has_custom_cursor(widget: QWidget) -> bool:
    """控件是否被显式设置了非默认光标（如 I 型、问号、抓手）"""
    return (
        widget.testAttribute(Qt.WidgetAttribute.WA_SetCursor)
        and widget.cursor().shape() not in _NEUTRAL_CURSOR_SHAPES
    )


def set_pointer_cursor(widget: QWidget) -> None:
    """
    给可点击控件设置手型光标；控件（或父级）被禁用时回退为箭头光标。

    控件若已显式设置过自定义光标（如输入框 I 型、帮助图标问号），不做改动。
    """
    if has_custom_cursor(widget):
        return
    widget.setCursor(_POINTING_HAND_CURSOR if widget.isEnabled() else _ARROW_CURSOR)
