from PyQt6.QtWidgets import QPushButton, QLineEdit, QFileDialog
import os
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QCursor
from ..ui_style import UI_Style
from .help_icon import create_help_icon
from .path_display import create_path_display
from .button import create_button

# --- File filter constants (Qt setNameFilter format) ---

_SUPPORTED_AUDIO = [
    "*.mp3", "*.m4a", "*.aac",
    "*.wav", "*.mka", "*.flac",
    "*.ogg", "*.oga", "*.opus",
]
_SUPPORTED_VIDEO = [
    "*.mov", "*.mkv", "*.mp4", "*.webm",
]

AUDIO_FILTER = f"audio ({' '.join(_SUPPORTED_AUDIO)})"
VIDEO_FILTER = f"video ({' '.join(_SUPPORTED_VIDEO)})"
MEDIA_FILTER = f"video/audio ({' '.join(_SUPPORTED_VIDEO + _SUPPORTED_AUDIO)}))"

_FILTER_MAP = {
    "audio": AUDIO_FILTER,
    "video": VIDEO_FILTER,
}


def create_file_selection_row(button_text: str,
                              button_length: int = None,
                              help_text: str = None,
                              on_button_clicked_handler=None,
                              name_filter: str = None):
    """
    创建文件选择行UI组件

    Args:
        button_text: str，按钮显示文本
        button_length: int，可选，按钮长度，默认 120
        help_text: str，可选，默认None，不创建help_icon
        on_button_clicked_handler: function，可选，按钮点击事件处理函数 (这个函数需要接受"选择的文件路径"作为参数)
        name_filter: str，可选，文件过滤器。支持以下简写：
                     "audio" — 仅音频文件
                     "video" — 仅视频文件
                     None — 默认 video+audio（所有媒体文件）
                     其他字符串 — 作为 Qt setNameFilter 原始值透传（如 "bpm config (*.txt)"）

    Returns:
        tuple: (button_widget, line_edit_widget, help_label_widget | None)
    """

    if button_length is None: button_length = 120

    # 创建文件选择按钮
    button = create_button(button_text, button_length)

    # 创建可选的帮助图标
    help_label = None
    if help_text:
        help_label = create_help_icon(help_text)

    # 创建路径显示LineEdit
    line_edit = create_path_display()

    # 默认的文件选择处理函数
    def _default_file_select_handler():
        """默认处理: 打开文件选择界面，更新 LineEdit 显示所选择的文件路径"""
        resolved_filter = _FILTER_MAP.get(name_filter, name_filter) or MEDIA_FILTER

        file_dialog = QFileDialog()
        file_dialog.setFileMode(QFileDialog.FileMode.ExistingFile)
        file_dialog.setNameFilter(resolved_filter)
        file_dialog.setViewMode(QFileDialog.ViewMode.Detail)
        if file_dialog.exec():
            selected_files = file_dialog.selectedFiles()
            if selected_files:
                selected_file_path = os.path.normpath(os.path.abspath(selected_files[0]))
                line_edit.setText(selected_file_path)

                # 如果有自定义处理函数，则调用它
                # 闭包保存自定义处理函数的引用
                if on_button_clicked_handler:
                    on_button_clicked_handler(selected_file_path)

    # 连接按钮点击事件
    button.clicked.connect(_default_file_select_handler)

    return button, line_edit, help_label


def create_directory_selection_row(button_text: str,
                                   help_text: str = None,
                                   button_length = None,
                                   on_button_clicked_handler=None):
    """
    创建目录选择行UI组件

    Args:
        button_text: str，按钮显示文本
        help_text: str，可选，默认None，不创建help_icon
        button_length: int，可选，按钮长度，默认 120
        on_button_clicked_handler: function，可选，按钮点击事件处理函数 (这个函数需要接受"选择的目录路径"作为参数)

    Returns:
        tuple: (button_widget, line_edit_widget, help_label_widget | None)
    """

    if button_length is None: button_length = 120

    # 创建文件选择按钮
    button = create_button(button_text, button_length)

    # 创建可选的帮助图标
    help_label = None
    if help_text:
        help_label = create_help_icon(help_text)

    # 创建路径显示LineEdit
    line_edit = create_path_display()

    def _default_directory_select_handler():
        """默认处理: 打开文件选择界面，更新 LineEdit 显示所选择的文件路径"""
        start_dir = line_edit.text().strip() or os.getcwd()
        selected_dir = QFileDialog.getExistingDirectory(
            None,
            button_text,
            start_dir,
            QFileDialog.Option.ShowDirsOnly
        )
        if not selected_dir:
            return

        selected_dir_path = os.path.normpath(os.path.abspath(selected_dir))
        line_edit.setText(selected_dir_path)

        # 如果有自定义处理函数，则调用它
        # 闭包保存自定义处理函数的引用
        if on_button_clicked_handler:
            on_button_clicked_handler(selected_dir_path)

    # 连接按钮点击事件
    button.clicked.connect(_default_directory_select_handler)

    return button, line_edit, help_label
