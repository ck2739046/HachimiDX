from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QLabel, QVBoxLayout

from ..base_output_page import BaseOutputPage
from .simply_align import parse_offset_ms
from ...widgets import *
from ...ui_style import UI_Style

from src.core.build_worker_cmd import build_cmd_head_python_exe
from src.core.schemas.op_result import OpResult, ok, err, print_op_result
from src.core.schemas.media_config import MediaType
from src.core.schemas.media_config import MediaConfig_Definitions as M_Defs
from src.core.tools import show_notify_dialog, FFprobeInspect
from src.services import MediaPipeline, PathManage, process_manager_api
import i18n


I18N_Prefix = "app.media_subpages.arcade_timing"


class ArcadeTimingPage(BaseOutputPage):

    request_simply_align = pyqtSignal(str, str)

    def setup_content(self):
        self.content_layout = QVBoxLayout(self.content_area)
        self.content_layout.setContentsMargins(10, 10, 10, 10)

        self.reference_path_display = None
        self.target_media_input = None
        self._reference_media_type = MediaType.UNKNOWN

        self.bpm_line_edit = None
        self.click_count_combo_box = None
        self.click_start_time_line_edit = None

        self.run_button = None
        self.offset_label = None
        self.edit_audio_button = None
        self.video_align_button = None

        self.waveform_label = None
        self._offset_action = None
        self._offset_value_ms = None

        self._active_runner_id = None
        self._active_media_runner_id = None
        self._media_output_path = None

        self._build_file_section()
        self._build_param_section()
        self._build_preview_section()

        process_manager_api.get_signals().runner_output.connect(self.output_widget.handle_process_output)
        process_manager_api.get_signals().runner_ended.connect(self.output_widget.handle_process_ended)
        process_manager_api.get_signals().runner_ended.connect(self._on_runner_ended)

        self.content_layout.addStretch()



    def _build_file_section(self) -> None:
        self.content_layout.addWidget(create_divider(i18n.t(f"{I18N_Prefix}.ui_select_file_divider")))

        reference_button, self.reference_path_display, reference_help = create_file_selection_row(
            button_text=i18n.t(f"{I18N_Prefix}.ui_reference_file_button"),
            help_text=i18n.t(f"{I18N_Prefix}.ui_reference_file_help"),
        )
        self.create_row(reference_button, reference_help, self.reference_path_display)

        self.target_media_input = MediaInputProbeWidget(
            select_file_button_help=i18n.t(f"{I18N_Prefix}.ui_target_file_help"),
            select_file_button_text=i18n.t(f"{I18N_Prefix}.ui_target_file_button"),
        )
        self.target_media_input.media_loaded.connect(self.on_target_input_selected)
        self.content_layout.addWidget(self.target_media_input)
        self.reference_path_display.textChanged.connect(self._on_reference_file_changed)

    
    def on_target_input_selected(self, error_msg: str) -> None:
        self._on_file_changed()
        if len(error_msg) > 0:
            show_notify_dialog(i18n.t(f"{I18N_Prefix}.dialog_title"), error_msg)


    def _on_reference_file_changed(self, text: str) -> None:
        path = text.strip()
        if not path:
            self._reference_media_type = MediaType.UNKNOWN
            self._on_file_changed()
            return
        result = FFprobeInspect.inspect_media(path)
        if result.is_ok:
            self._reference_media_type = result.value.media_type
        else:
            self._reference_media_type = MediaType.UNKNOWN
        self._on_file_changed()


    def _on_file_changed(self) -> None:
        """当基准文件或目标文件变更时，清除旧的分析/编辑结果"""
        self._media_output_path = None
        self._reset_result_state()


    def _reset_result_state(self) -> None:
        """重置分析结果相关 UI 状态（不涉及输入控件）"""
        self._offset_action = None
        self._offset_value_ms = None
        self.offset_label.setText("")
        self.offset_label.hide()
        self.video_align_button.hide()
        self.edit_audio_button.hide()
        self.waveform_label.hide()
        self.waveform_label.clear()



    def _build_param_section(self) -> None:
        self.content_layout.addWidget(create_divider(i18n.t(f"{I18N_Prefix}.ui_params_divider")))

        bpm_label = create_label(i18n.t(f"{I18N_Prefix}.ui_bpm_label"))
        self.bpm_line_edit = create_line_edit(length=70, validator="float")
        bpm_help = create_help_icon(i18n.t(f"{I18N_Prefix}.ui_bpm_help"))

        click_count_label = create_label(i18n.t(f"{I18N_Prefix}.ui_click_count_label"))
        self.click_count_combo_box = create_combo_box(
            items=[str(i) for i in range(1, 10)], default_index=3, length=50)
        click_count_help = create_help_icon(i18n.t(f"{I18N_Prefix}.ui_click_count_help"))

        click_start_label = create_label(i18n.t(f"{I18N_Prefix}.ui_click_start_time_label"))
        self.click_start_time_line_edit = create_line_edit(default_text="0", length=70, validator="float")
        click_start_help = create_help_icon(i18n.t(f"{I18N_Prefix}.ui_click_start_time_help"))

        self.create_row(
            bpm_label,
            self.bpm_line_edit,
            bpm_help,
            click_count_label,
            self.click_count_combo_box,
            click_count_help,
            click_start_label,
            self.click_start_time_line_edit,
            click_start_help,
            add_stretch=True,
        )

        self.content_layout.addSpacing(UI_Style.widget_spacing)
        self.run_button = create_stated_button(i18n.t(f"{I18N_Prefix}.ui_run_button"), isbig=True)
        self.run_button.clicked.connect(self.on_run_clicked)

        self.offset_label = create_label(bold=True)
        self.offset_label.hide()

        self.edit_audio_button = create_stated_button(i18n.t(f"{I18N_Prefix}.ui_edit_audio_button"), width=100)
        self.edit_audio_button.clicked.connect(self.on_edit_audio_clicked)
        self.edit_audio_button.hide()

        self.video_align_button = create_stated_button(i18n.t(f"{I18N_Prefix}.ui_video_align_button"), width=100)
        self.video_align_button.clicked.connect(self.on_video_align_clicked)
        self.video_align_button.hide()

        self.create_row(self.run_button,
                        self.offset_label,
                        self.edit_audio_button,
                        self.video_align_button,
                        add_stretch=True)



    def _build_preview_section(self) -> None:

        self.waveform_label = QLabel()
        self.waveform_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.waveform_label.setMinimumHeight(210)
        self.waveform_label.hide()
        self.content_layout.addWidget(self.waveform_label)



    def _parse_inputs(self) -> OpResult[dict]:
        reference_file = self.reference_path_display.text().strip()
        target_file = self.target_media_input.get_path().strip()

        if not reference_file:
            return err(i18n.t(f"{I18N_Prefix}.warning_reference_file_required"))
        if not target_file:
            return err(i18n.t(f"{I18N_Prefix}.warning_target_file_required"))

        # Check both files contain audio streams
        if self._reference_media_type not in (MediaType.AUDIO, MediaType.VIDEO_WITH_AUDIO):
            return err(i18n.t(f"{I18N_Prefix}.warning_no_audio_stream_ref"))

        target_type = self.target_media_input.selected_file_type
        if target_type not in (MediaType.AUDIO, MediaType.VIDEO_WITH_AUDIO):
            return err(i18n.t(f"{I18N_Prefix}.warning_no_audio_stream_target"))

        try:
            bpm = float((self.bpm_line_edit.text() if self.bpm_line_edit else "").strip())
        except Exception:
            return err(i18n.t(f"{I18N_Prefix}.warning_invalid_bpm"))
        if not 10 <= bpm <= 400:
            return err(i18n.t(f"{I18N_Prefix}.warning_invalid_bpm"))

        try:
            click_count = int((self.click_count_combo_box.currentText()).strip())
        except Exception:
            return err(i18n.t(f"{I18N_Prefix}.warning_invalid_click_count"))
        if click_count < 1:
            return err(i18n.t(f"{I18N_Prefix}.warning_invalid_click_count"))

        try:
            click_start_time = float((self.click_start_time_line_edit.text() if self.click_start_time_line_edit else "").strip())
        except Exception:
            return err(i18n.t(f"{I18N_Prefix}.warning_invalid_click_start_time"))
        if click_start_time < 0:
            return err(i18n.t(f"{I18N_Prefix}.warning_invalid_click_start_time"))

        return ok({
            "reference_file": reference_file,
            "target_file": target_file,
            "bpm": bpm,
            "click_count": click_count,
            "click_start_time": click_start_time,
        })



    def on_run_clicked(self) -> None:
        if self._active_runner_id:
            return

        self.run_button.setEnabled(False)
        self._reset_result_state()

        try:
            res = self._parse_inputs()
            if not res.is_ok:
                show_notify_dialog(i18n.t(f"{I18N_Prefix}.dialog_title"), res.error_msg)
                return
            data = res.value

            cmd = build_cmd_head_python_exe(PathManage.AUDIO_ALIGN_WORKER_PATH)
            cmd.extend([
                "false", # is_simply_align
                str(data["reference_file"]),
                str(data["target_file"]),
                str(data["bpm"]),
                str(data["click_count"]),
                str(data["click_start_time"]),
            ])

            self.output_widget.append_text(i18n.t(f"{I18N_Prefix}.notice_run_start"))

            result = process_manager_api.start(cmd)
            if not result.is_ok:
                show_notify_dialog(
                    i18n.t(f"{I18N_Prefix}.dialog_title"),
                    i18n.t(f"{I18N_Prefix}.warning_worker_start_failed", error=print_op_result(result)),
                )
                return

            self._active_runner_id = result.value
            self.output_widget.bind_current_runner_id(self._active_runner_id)

        finally:
            if not self._active_runner_id:
                self.run_button.setEnabled(True)



    def _on_runner_ended(self, runner_id: str, ended) -> None:
        # Handle audio align worker
        if self._active_runner_id and runner_id == self._active_runner_id:
            self._active_runner_id = None
            self.run_button.setEnabled(True)

            if getattr(ended, "cancelled", False):
                self.output_widget.append_text(i18n.t(f"{I18N_Prefix}.notice_run_cancelled"))
                return

            failed = bool(getattr(ended, "crashed", False))
            exit_code = getattr(ended, "exit_code", None)
            if exit_code is None or exit_code != 0:
                failed = True

            if failed:
                self.output_widget.append_text(i18n.t(f"{I18N_Prefix}.warning_run_failed"))
                return

            self.output_widget.append_text(i18n.t(f"{I18N_Prefix}.notice_run_success"))

            self._try_parse_offset()
            self._try_show_wave_image()
            return

        # Handle media (edit audio) task
        if self._active_media_runner_id and runner_id == self._active_media_runner_id:
            self._active_media_runner_id = None
            self.edit_audio_button.setEnabled(True)

            if getattr(ended, "cancelled", False):
                self.output_widget.append_text(i18n.t(f"{I18N_Prefix}.notice_run_cancelled"))
                return

            failed = bool(getattr(ended, "crashed", False))
            exit_code = getattr(ended, "exit_code", None)
            if exit_code is None or exit_code != 0:
                failed = True

            if failed:
                self.output_widget.append_text(i18n.t(f"{I18N_Prefix}.warning_edit_audio_failed_log"))
                self.video_align_button.hide()
                return

            output_path_str = str(self._media_output_path) if self._media_output_path else "?"
            self.output_widget.append_text(
                i18n.t(f"{I18N_Prefix}.notice_edit_audio_success", output_path=output_path_str)
            )
            self.video_align_button.show()
            return



    def _try_show_wave_image(self) -> None:

        wave_path = PathManage.TEMP_WAV_IMAGE_PATH
        if not wave_path.is_file():
            self.output_widget.append_text(i18n.t(f"{I18N_Prefix}.warning_wave_not_found"))
            return

        pixmap = QPixmap(str(Path(wave_path)))
        if pixmap.isNull():
            self.output_widget.append_text(i18n.t(f"{I18N_Prefix}.warning_wave_load_failed"))
            return

        self.waveform_label.setPixmap(pixmap)
        self.waveform_label.show()

        try:
            if wave_path.is_file():
                wave_path.unlink()
        except Exception:
            pass



    def _try_parse_offset(self) -> None:
        offset = parse_offset_ms(self.output_widget.get_recent_lines(6))

        if offset is None:
            self.output_widget.append_text("ui: failed to parse offset from output")
            self._offset_action = None
            self._offset_value_ms = None
            self.edit_audio_button.hide()
            return

        if offset == 0:
            self._offset_action = "aligned"
            self._offset_value_ms = 0
            self.edit_audio_button.hide()
            return

        if offset > 0:  # delay
            self._offset_action = "delay"
            self._offset_value_ms = offset
            self.offset_label.setText(f"  Offset: delay {offset} ms ")
        else:  # trim
            value = abs(offset)
            self._offset_action = "trim"
            self._offset_value_ms = value
            self.offset_label.setText(f"  Offset: trim {value} ms ")
        self.offset_label.show()
        self.edit_audio_button.show()



    @staticmethod
    def _build_non_conflict_output_path(target_path: Path, audio_format: str) -> OpResult[Path]:
        base_filename = f"{target_path.stem}_arcade_timing"

        for i in range(0, 1000):
            candidate_name = base_filename if i == 0 else f"{base_filename}_{i}"
            path_res = M_Defs.build_full_output_path(str(target_path), candidate_name, audio_format)
            if not path_res.is_ok:
                return err("Failed to build output path", inner=path_res)

            candidate_path = Path(path_res.value[0])
            if not candidate_path.exists():
                return ok(candidate_path)

        return err("Failed to find non-conflicting output path")



    def on_edit_audio_clicked(self) -> None:
        if self._active_runner_id or self._active_media_runner_id:
            return

        if self._offset_action is None or self._offset_value_ms is None:
            show_notify_dialog(i18n.t(f"{I18N_Prefix}.dialog_title"), i18n.t(f"{I18N_Prefix}.warning_offset_not_ready"))
            return

        if self._offset_action == "aligned" or self._offset_value_ms == 0:
            self.output_widget.append_text(i18n.t(f"{I18N_Prefix}.notice_edit_audio_skip_zero_offset"))
            return

        target_file = self.target_media_input.get_path().strip()
        if not target_file:
            show_notify_dialog(i18n.t(f"{I18N_Prefix}.dialog_title"), i18n.t(f"{I18N_Prefix}.warning_target_file_required"))
            return

        target_path = Path(target_file)
        if not target_path.is_file():
            show_notify_dialog(i18n.t(f"{I18N_Prefix}.dialog_title"), i18n.t(f"{I18N_Prefix}.warning_target_file_missing"))
            return

        target_media_type = self.target_media_input.selected_file_type
        target_duration = self.target_media_input.selected_file_duration

        if target_media_type == MediaType.UNKNOWN:
            show_notify_dialog(i18n.t(f"{I18N_Prefix}.dialog_title"), i18n.t(f"{I18N_Prefix}.warning_offset_not_ready"))
            return

        res = M_Defs.get_audio_format_by_media_type(target_media_type)
        audio_format, _ = res.value
        if target_media_type == MediaType.AUDIO and target_path.suffix.lower() == ".mp3":
            audio_format = "mp3"

        output_res = self._build_non_conflict_output_path(target_path, audio_format)
        if not output_res.is_ok:
            show_notify_dialog(
                i18n.t(f"{I18N_Prefix}.dialog_title"),
                i18n.t(f"{I18N_Prefix}.warning_build_output_path_failed", error=print_op_result(output_res)),
            )
            return
        output_path = output_res.value

        offset_sec = round(self._offset_value_ms / 1000.0, 3)
        raw_data = {
            M_Defs.media_type.key: target_media_type,
            M_Defs.duration.key: target_duration,

            M_Defs.input_path.key: str(target_path),
            M_Defs.output_path.key: str(output_path),
            M_Defs.audio_format.key: audio_format,
            
            M_Defs.pad_start.key: offset_sec if self._offset_action == "delay" else None,
            M_Defs.start.key: offset_sec if self._offset_action == "trim" else None,
        }

        self.edit_audio_button.setEnabled(False)
        self.video_align_button.hide()
        self._media_output_path = output_path
        self.output_widget.append_text(i18n.t(f"{I18N_Prefix}.notice_edit_audio_start"))
        
        try:
            result = MediaPipeline.submit_task(raw_data, f"arcade_timing {target_path.name}")
            if not result.is_ok:
                show_notify_dialog(
                    i18n.t(f"{I18N_Prefix}.dialog_title"),
                    i18n.t(f"{I18N_Prefix}.warning_edit_audio_failed", error=print_op_result(result)),
                )
                self.output_widget.append_text(i18n.t(f"{I18N_Prefix}.warning_edit_audio_failed_log"))
                return

            runner_id, cmd_list = result.value
            self._active_media_runner_id = runner_id
            self.output_widget.bind_current_runner_id(runner_id)

            message = i18n.t("app.media_subpages.run_ffmpeg.notice_task_submit_success", task_id=runner_id)
            create_floating_notification(message, self.window())

        finally:
            if not self._active_media_runner_id:
                self.edit_audio_button.setEnabled(True)


    def on_video_align_clicked(self) -> None:
        """一键对齐视频：跳转到 Simply Align 页面，自动填充文件并开始分析"""
        if not self._media_output_path or not self._media_output_path.is_file():
            show_notify_dialog(
                i18n.t(f"{I18N_Prefix}.dialog_title"),
                i18n.t(f"{I18N_Prefix}.warning_offset_not_ready"),
            )
            return

        reference_path = self.reference_path_display.text().strip()
        if not reference_path:
            show_notify_dialog(
                i18n.t(f"{I18N_Prefix}.dialog_title"),
                i18n.t(f"{I18N_Prefix}.warning_reference_file_required"),
            )
            return

        self.request_simply_align.emit(str(self._media_output_path), reference_path)
