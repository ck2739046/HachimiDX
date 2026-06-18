from PyQt6.QtWidgets import QWidget, QVBoxLayout, QStackedWidget
from PyQt6.QtCore import pyqtSignal

import i18n

from ..ui_style import UI_Style
from ..widgets import SegmentedNavBar
from .media_subpages.arcade_timing import ArcadeTimingPage
from .media_subpages.simply_align import SimplyAlignPage
from .media_subpages.run_ffmpeg import RunFFmpegPage
from .media_subpages.measure_bpm import MeasureBpmPage

class MediaToolsPage(QWidget):
    """
    Media Tools 主页面
    包含内部导航栏和子页面 Stack
    """

    # (video_path, bpm_config_path) — 透传到 RightPanel，用于填入 Auto Rechart 页
    request_send_to_auto_rechart = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 0. 顶部增加空隙，让内部导航栏与整体导航栏分离
        layout.addSpacing(UI_Style.widget_spacing)

        # 1. 内部导航栏
        nav_items = ["Arcade Timing",
                     "Simply Align",
                     "Run FFmpeg",
                     "Measure Bpm"]
        nav_tooltips = [
            i18n.t("app.sub_nav_bar.arcade_timing_desc"),
            i18n.t("app.sub_nav_bar.simply_align_desc"),
            i18n.t("app.sub_nav_bar.run_ffmpeg_desc"),
            i18n.t("app.sub_nav_bar.measure_bpm_desc"),
            i18n.t("app.sub_nav_bar.others_desc"),
        ]
        self.nav_bar = SegmentedNavBar(nav_items,
                                       height=UI_Style.sub_navbar_height,
                                       tooltip_texts=nav_tooltips)
        layout.addWidget(self.nav_bar)

        # 2. 内容 Stack
        self.stack = QStackedWidget()
        layout.addWidget(self.stack)

        # 添加子页面
        self.arcade_timing_page = ArcadeTimingPage()
        self.simply_align_page = SimplyAlignPage()
        self.stack.addWidget(self.arcade_timing_page)
        self.stack.addWidget(self.simply_align_page)
        self.stack.addWidget(RunFFmpegPage())
        self.measure_bpm_page = MeasureBpmPage()
        self.stack.addWidget(self.measure_bpm_page)

        # 连接信号：Arcade Timing → Simply Align 一键跳转
        self.arcade_timing_page.request_simply_align.connect(self._on_request_simply_align)
        # 连接信号：Measure Bpm → Auto Rechart 一键填入（透传到上层）
        self.measure_bpm_page.request_send_to_auto_rechart.connect(self.request_send_to_auto_rechart)

        # 连接信号
        self.nav_bar.currentChanged.connect(self.stack.setCurrentIndex)

    def _on_request_simply_align(self, reference_path: str, target_path: str) -> None:
        """处理 Arcade Timing 的一键对齐视频请求"""
        self.simply_align_page.set_files_and_auto_run(reference_path, target_path)
        self.nav_bar.setCurrentIndex(1)
