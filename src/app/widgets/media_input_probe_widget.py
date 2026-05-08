from PyQt6.QtWidgets import QWidget, QVBoxLayout
from PyQt6.QtCore import pyqtSignal
import i18n

from src.core.tools import FFprobeInspect, FFprobeInspectResult
from src.core.schemas.op_result import print_op_result
from src.core.schemas.media_config import MediaType

from ..pages.base_output_page import _create_row
from .file_selection_row import create_file_selection_row
from .label import create_label
from .help_icon import create_help_icon



I18N_Prefix = "app.widgets.media_input_probe_widget"


class MediaInputProbeWidget(QWidget):

    # Signal
    # 如果成功，结果是空字符串
    # 如果失败，结果是错误信息
    media_loaded = pyqtSignal(str)
    

    def __init__(self, parent=None,
                 select_file_button_help: str = None,
                 select_file_button_text: str = None,
                 select_file_button_length: int = None):

        super().__init__(parent)

        # widgets
        self.input_file_path_display_line_edit = None
        self.probe_result_display_label = None

        # data
        self.selected_file_duration = None
        self.selected_file_type = MediaType.UNKNOWN
        self.selected_video_fps = None

        self._init_ui(select_file_button_help,
                      select_file_button_text,
                      select_file_button_length)
        





    def _init_ui(self,
                 select_file_button_help: str,
                 select_file_button_text: str,
                 select_file_button_length: int):

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Row 1: File selection
        (select_file_button,
         self.input_file_path_display_line_edit,
         select_file_help,
        ) = create_file_selection_row(
            button_text = select_file_button_text or i18n.t(f"{I18N_Prefix}.ui_select_input_file_button"),
            button_length = select_file_button_length,
            help_text = select_file_button_help,
            on_button_clicked_handler = self._on_input_file_selected
        )

        row1 = _create_row(select_file_button,
                           select_file_help,
                           self.input_file_path_display_line_edit)
        
        layout.addWidget(row1)


        
        # Row 2: Probe result

        probe_result_display_prefix = create_label(
            text=i18n.t(f"{I18N_Prefix}.ui_ffprobe_inspect_prefix"))
        
        probe_result_display_help = create_help_icon(
            i18n.t(f"{I18N_Prefix}.ui_ffprobe_inspect_help"))
        
        self.probe_result_display_label = create_label(expand=True)

        row2 = _create_row(probe_result_display_prefix,
                           probe_result_display_help,
                           self.probe_result_display_label)
        
        layout.addWidget(row2)
        









    def _on_input_file_selected(self, selected_file_path: str) -> None:
         
        result = FFprobeInspect.inspect_media(selected_file_path)
        if not result.is_ok:
            # reset
            self.probe_result_display_label.setText(MediaType.UNKNOWN.name)
            self.selected_file_duration = None
            self.selected_file_type = MediaType.UNKNOWN
            self.selected_video_fps = None
            # emit signal
            error_msg = i18n.t(f"{I18N_Prefix}.warning_ffprobe_inspect_failed", error_msg = print_op_result(result))
            self.media_loaded.emit(error_msg)
            return

        # ok    
        ffprobe_result = result.value
        # 更新公共变量
        self.selected_file_duration = ffprobe_result.duration
        self.selected_file_type = ffprobe_result.media_type

        raw_fps = ffprobe_result.video_stream.get("avg_frame_rate")
        try:
            if raw_fps is not None:
                s = str(raw_fps).strip()
                if "/" in s:
                    num, denom = s.split("/")
                    self.selected_video_fps = float(num) / float(denom)
                else:
                    self.selected_video_fps = float(s)
            else:
                self.selected_video_fps = None
        except Exception:
            self.selected_video_fps = None
        # 显示检测结果
        display_text = self._build_probe_result_text(ffprobe_result)
        self.probe_result_display_label.setText(display_text)
        # emit signal
        self.media_loaded.emit("")
        





    def _build_probe_result_text(self, result: FFprobeInspectResult) -> str:

        video_info = result.video_stream.get("info_str", "")

        if video_info:
            video_line = i18n.t(f"{I18N_Prefix}.ui_video_stream_info_prefix") + video_info
        else:
            video_line = i18n.t(f"{I18N_Prefix}.ui_no_video_stream_info")
        
        audio_info = result.audio_stream.get("info_str", "")

        if audio_info:
            audio_line = i18n.t(f"{I18N_Prefix}.ui_audio_stream_info_prefix") + audio_info
        else:
            audio_line = i18n.t(f"{I18N_Prefix}.ui_no_audio_stream_info")

        return f"{video_line}\n{audio_line}"




    def get_path(self) -> str:
        return str(self.input_file_path_display_line_edit.text()).strip()
    