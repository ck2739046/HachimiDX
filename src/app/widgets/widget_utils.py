from PyQt6.QtWidgets import QLayout


def clear_layout(layout: QLayout) -> None:
    """
    清空布局中的所有项并销毁其 widget。
    先对每个 widget 执行 setParent(None) 使其脱离父窗口树，再 deleteLater() 销毁。
    """
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w is not None:
            w.setParent(None)
            w.deleteLater()
