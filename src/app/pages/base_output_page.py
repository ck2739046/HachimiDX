from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QHBoxLayout
from ..widgets import OutputLogWidget
from ..ui_style import UI_Style

class BaseOutputPage(QWidget):
    """
    页面基类
    包含：
    1. 内容区域 (self.content_area)
    2. 日志输出区域 (self.output_widget)

    需要子类重写 setup_content() 方法来填充内容区域
    该类提供 create_row() 方法来简化行布局的创建
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()


    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.output_widget = OutputLogWidget()

        # 1. 内容区域容器
        self.content_area = QWidget()
        self.setup_content() # 这个部分由子类填充
        layout.addWidget(self.content_area, 1)  # 拉伸因子为1，使其扩展

        # 2. 日志输出区域
        layout.addWidget(self.output_widget, 0)  # 拉伸因子为0，固定在底部

        
        

    def setup_content(self):
        """
        子类重写此方法来填充 content_area
        已经创建了 self.content_layout (QVBox) 供使用。

        示例：
            def setup_content(self):
                label = QLabel("Hello")
                self.content_layout.addWidget(label)
        """
        pass


    def create_row(self, *widgets, add_stretch=False, add_to_layout=True):
        """
        创建一个水平布局行，会自动跳过 None 的 widget。
        
        Args:
            *widgets: 要添加到行中的 widgets
            add_stretch: 是否在末尾添加弹性空间，默认 False
            add_to_layout: 是否自动加入本页 content_layout，默认 True；
                           需要把行放进子面板时传 False，由调用方自行 addWidget
        
        Returns:
            QWidget: 包含所有 widgets 的行容器
        """

        row = _create_row_widget(*widgets, add_stretch=add_stretch)
        if add_to_layout:
            self.content_layout.addWidget(row)
        return row





def _create_row_widget(*widgets, add_stretch=False):
    """
    创建一个水平布局行并添加所有传入的 widgets。
    会自动跳过 None 的 widget。
    仅由 create_row() 调用，不要在本模块之外使用。
    
    Args:
        *widgets: 要添加到行中的 widgets
        add_stretch: 是否在末尾添加弹性空间，默认 False
    
    Returns:
        QWidget: 包含所有 widgets 的行容器
    """
    row = QWidget()
    row_layout = QHBoxLayout(row)
    row_layout.setSpacing(5)
    row_layout.setContentsMargins(0, 0, 0, 0)
    
    for widget in widgets:
        if widget is not None:
            row_layout.addWidget(widget)
    
    if add_stretch:
        row_layout.addStretch()

    return row
