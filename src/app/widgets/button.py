from PyQt6.QtWidgets import QPushButton
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QCursor

from ..ui_style import UI_Style


c = UI_Style.COLORS
def button_qss_base(color):
    return (
        f"QPushButton:hover {{ background-color: {c[color+'_hover']}; }}"
        f"QPushButton:disabled {{ background-color: {c['grey']}; }}"
         "QPushButton {"
        f"  border: 1px solid {c[color+'_hover']};"
        f"  border-radius: 6px;"
        f"  color: {c['text_primary']};"
        f"  background-color: {c[color]};"
        f"  padding: 0px 10px;"  # 内边距，让按钮根据文本长度自适应宽度
    )


class StatedButton(QPushButton):
    """A primary button.

    States:
      - Enabled: blue
      - Disabled: grey
    """

    def __init__(self, text: str, isbig: bool = False, width: int = None, height: int = None, parent=None):
        super().__init__(text, parent)

        if width is not None:
            self.setFixedWidth(width)
        if height is not None:
            self.setFixedHeight(height)

        self._apply_style(isbig)
        self._update_cursor()


    def _apply_style(self, isbig: bool) -> None:

        if not isbig:
            self.setStyleSheet(button_qss_base('accent') + "}")

        if isbig:
            self.setStyleSheet(
                button_qss_base('accent')
                + "  font-size: 16px;"
                + "  font-weight: bold;"
                + "}"
            )
            

    def _update_cursor(self) -> None:
        if self.isEnabled():
            self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        else:
            self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))

    def setEnabled(self, enabled: bool) -> None:  # type: ignore[override]
        super().setEnabled(enabled)
        self._update_cursor()




def create_stated_button(text: str, isbig: bool = False, width: int = None) -> StatedButton:
    """
    创建大按钮，带启用/禁用状态切换

    Args:
        text (str): 按钮文本
        isbig (bool, optional): 是否为大按钮. 默认值为 False
        width (int, optional): 按钮宽度. 默认值 None
        
        大按钮默认高度: 35
        小按钮默认高度: element_height

        大按钮默认宽度: 100
        小按钮默认宽度: 无
    
    Returns:
        StatedButton: 按钮实例

    设置按钮状态:
        setEnabled(True): 启用状态，显示为蓝色
        setEnabled(False): 禁用状态，显示为灰色
    """
    
    if isbig:
        height = 35
    else:
        height = UI_Style.element_height

    if not width and isbig:
        width = 100

    return StatedButton(text, isbig=isbig, width=width, height=height)




def create_button(text: str, width: int = None, color = 'accent') -> QPushButton:
    """
    创建普通按钮

    Args:
        text (str): 按钮文本
        width (int, 可选): 按钮宽度. 默认 None，根据文本自适应宽度
        color (str, 可选): 按钮颜色. 默认 accent

    Returns:
        QPushButton: 按钮实例
    """
    
    button = QPushButton(text)
    button.setFixedHeight(UI_Style.element_height)
    if width is not None:
        button.setFixedWidth(width)
    button.setStyleSheet(button_qss_base(color) + '}')
    return button
