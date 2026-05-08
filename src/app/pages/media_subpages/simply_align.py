from PyQt6.QtWidgets import QVBoxLayout
from ..base_output_page import BaseOutputPage
from ...widgets import *
from ...ui_style import UI_Style

from src.core.build_worker_cmd import build_cmd_head_python_exe
from src.core.schemas.op_result import OpResult, ok, err, print_op_result
from src.core.tools import show_notify_dialog
from src.services import process_manager_api
from src.services.path_manage import PathManage
from src.services.pipeline import MediaPipeline
import i18n
from pathlib import Path

from src.core.schemas.media_config import MediaType
from src.core.schemas.media_config import MediaConfig_Definitions as M_Defs

I18N_Prefix = "app.media_subpages.arcade_timing"
I18N_Simply_Align_Prefix = "app.media_subpages.simply_align"



class SimplyAlignPage(BaseOutputPage):
    def setup_content(self):

        self.content_layout = QVBoxLayout(self.content_area)
        self.content_layout.setContentsMargins(10, 10, 10, 10)

        self.reference_path_display = None
        self.target_media_input = None

        self.run_button = None
        self.offset_label = None

        self._active_runner_id = None
        self._active_media_runner_id = None
        self._media_output_path = None
        self._offset_action = None
        self._offset_value_ms = None
        self.generate_video_label = None
        self.generate_video_button = None

        self._build_file_section()
        self._build_action_section()

        process_manager_api.get_signals().runner_output.connect(self.output_widget.handle_process_output)
        process_manager_api.get_signals().runner_ended.connect(self.output_widget.handle_process_ended)
        process_manager_api.get_signals().runner_ended.connect(self._on_runner_ended)

        self.content_layout.addStretch()




    def _build_file_section(self) -> None:
        self.content_layout.addWidget(create_divider(i18n.t(f"{I18N_Prefix}.ui_select_file_divider")))

        reference_button, self.reference_path_display, reference_help = create_file_selection_row(
            button_text=i18n.t(f"{I18N_Prefix}.ui_reference_file_button"),
            help_text=i18n.t(f"{I18N_Simply_Align_Prefix}.ui_reference_file_help"),
        )
        self.create_row(reference_button, reference_help, self.reference_path_display)
        self.reference_path_display.textChanged.connect(self._hide_generate_controls)

        self.target_media_input = MediaInputProbeWidget(
            select_file_button_help=i18n.t(f"{I18N_Simply_Align_Prefix}.ui_target_file_help")
        )
        self.target_media_input.media_loaded.connect(self.on_target_input_selected)
        self.content_layout.addWidget(self.target_media_input)



    def _build_action_section(self) -> None:
        self.run_button = create_stated_button(i18n.t(f"{I18N_Prefix}.ui_run_button"), isbig=True)
        self.run_button.clicked.connect(self.on_run_clicked)

        self.offset_label = create_label(bold=True)
        self.offset_label.hide()

        self.content_layout.addSpacing(UI_Style.widget_spacing)
        self.create_row(self.run_button, self.offset_label, add_stretch=True)

        self.generate_video_label = create_label(
            i18n.t(f"{I18N_Simply_Align_Prefix}.ui_generate_video_label")
        )
        self.generate_video_button = create_stated_button(
            i18n.t(f"{I18N_Simply_Align_Prefix}.ui_generate_video_button")
        )
        self.generate_video_button.clicked.connect(self.on_generate_video_clicked)
        self.generate_video_label.hide()
        self.generate_video_button.hide()
        self.create_row(self.generate_video_label, self.generate_video_button, add_stretch=True)



    def on_target_input_selected(self, error_msg: str) -> None:
        self._hide_generate_controls()
        if len(error_msg) > 0:
            show_notify_dialog(i18n.t(f"{I18N_Simply_Align_Prefix}.dialog_title"), error_msg)



    def _parse_inputs(self) -> OpResult[dict]:
        reference_file = self.reference_path_display.text().strip()
        target_file = self.target_media_input.get_path().strip()

        if not reference_file:
            return err(i18n.t(f"{I18N_Prefix}.warning_reference_file_required"))
        if not target_file:
            return err(i18n.t(f"{I18N_Prefix}.warning_target_file_required"))

        return ok({
            "reference_file": reference_file,
            "target_file": target_file,
        })



    def on_run_clicked(self) -> None:
        if self._active_runner_id:
            return

        self.run_button.setEnabled(False)
        self.offset_label.setText("")
        self.offset_label.hide()
        self._hide_generate_controls()

        try:
            res = self._parse_inputs()
            if not res.is_ok:
                show_notify_dialog(i18n.t(f"{I18N_Simply_Align_Prefix}.dialog_title"), res.error_msg)
                return

            data = res.value
            cmd = build_cmd_head_python_exe(PathManage.AUDIO_ALIGN_WORKER_PATH)
            cmd.extend([
                "true",  # is_simply_align
                str(data["reference_file"]),
                str(data["target_file"]),
            ])

            self.output_widget.append_text(i18n.t(f"{I18N_Prefix}.notice_run_start"))

            result = process_manager_api.start(cmd)
            if not result.is_ok:
                show_notify_dialog(
                    i18n.t(f"{I18N_Simply_Align_Prefix}.dialog_title"),
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
            return

        # Handle media (generate video) task
        if self._active_media_runner_id and runner_id == self._active_media_runner_id:
            self._active_media_runner_id = None
            self.generate_video_button.setEnabled(True)

            if getattr(ended, "cancelled", False):
                self.output_widget.append_text(i18n.t(f"{I18N_Prefix}.notice_run_cancelled"))
                return

            failed = bool(getattr(ended, "crashed", False))
            exit_code = getattr(ended, "exit_code", None)
            if exit_code is None or exit_code != 0:
                failed = True

            if failed:
                self.output_widget.append_text(
                    i18n.t(f"{I18N_Simply_Align_Prefix}.warning_video_generate_failed_log")
                )
                return

            output_path_str = str(self._media_output_path) if self._media_output_path else "?"
            self.output_widget.append_text(
                i18n.t(
                    f"{I18N_Simply_Align_Prefix}.notice_video_generate_success",
                    output_path=output_path_str,
                )
            )
            return



    def _try_parse_offset(self) -> None:
        offset_action = None
        offset_value_ms = None
        recent_output = self.output_widget.get_recent_lines(6)

        for line in reversed(recent_output.splitlines()):
            line = line.strip()
            if not line:
                continue

            if line == "Audio files are perfectly aligned (offset < 10 ms)":
                offset_action = "aligned"
                offset_value_ms = 0
                break

            if line.startswith("Target file needs trim ") and line.endswith(" ms"):
                value_text = line[len("Target file needs trim "):-len(" ms")].strip()
                try:
                    offset_action = "trim"
                    offset_value_ms = int(value_text)
                    break
                except Exception:
                    continue

            if line.startswith("Target file needs delay ") and line.endswith(" ms"):
                value_text = line[len("Target file needs delay "):-len(" ms")].strip()
                try:
                    offset_action = "delay"
                    offset_value_ms = int(value_text)
                    break
                except Exception:
                    continue

        if offset_action in ("trim", "delay") and offset_value_ms is not None:
            self._offset_action = offset_action
            self._offset_value_ms = offset_value_ms
            self.offset_label.setText(f"  Offset: {offset_action} {offset_value_ms} ms ")
            self.offset_label.show()
            self._show_generate_controls()
        elif offset_action == "aligned":
            self._offset_action = "aligned"
            self._offset_value_ms = 0
            self.offset_label.hide()
            self._hide_generate_controls()
        else:
            self.output_widget.append_text("ui: failed to parse offset from output")
            self._offset_action = None
            self._offset_value_ms = None
            self.offset_label.hide()
            self._hide_generate_controls()



    def _show_generate_controls(self) -> None:
        target_type = self.target_media_input.selected_file_type
        if target_type not in (MediaType.VIDEO_WITH_AUDIO, MediaType.VIDEO_WITHOUT_AUDIO):
            return
        self.generate_video_label.show()
        self.generate_video_button.show()



    def _hide_generate_controls(self) -> None:
        self.generate_video_label.hide()
        self.generate_video_button.hide()



    @staticmethod
    def _parse_fps(raw_fps) -> float:
        try:
            if raw_fps is None:
                return 0.0
            s = str(raw_fps).strip()
            if "/" in s:
                num, denom = s.split("/")
                return float(num) / float(denom)
            return float(s)
        except Exception:
            return 0.0



    @staticmethod
    def _build_sync_output_path(target_path: Path) -> Path:
        for i in range(0, 1000):
            candidate_name = "sync" if i == 0 else f"sync_{i}"
            candidate = target_path.parent / f"{candidate_name}.mp4"
            if not candidate.exists():
                return candidate
        return target_path.parent / "sync.mp4"



    def on_generate_video_clicked(self) -> None:
        if not self._offset_action or self._offset_value_ms is None:
            return

        target_file = self.target_media_input.get_path().strip()
        if not target_file:
            return

        target_path = Path(target_file)
        if not target_path.is_file():
            return

        target_media_type = self.target_media_input.selected_file_type
        if target_media_type not in (MediaType.VIDEO_WITH_AUDIO, MediaType.VIDEO_WITHOUT_AUDIO):
            return

        target_duration = self.target_media_input.selected_file_duration

        raw_fps = self.target_media_input.selected_video_fps
        fps_float = self._parse_fps(raw_fps)
        video_fps = 60 if fps_float > 45 else 30

        output_path = self._build_sync_output_path(target_path)

        offset_sec = round(self._offset_value_ms / 1000.0, 3)
        pad_start = offset_sec if self._offset_action == "delay" else None
        start = offset_sec if self._offset_action == "trim" else None

        raw_data = {
            M_Defs.media_type.key: target_media_type,
            M_Defs.input_path.key: str(target_path),
            M_Defs.output_path.key: str(output_path),
            M_Defs.duration.key: target_duration,
            M_Defs.video_side_resolution.key: 480,
            M_Defs.video_fps.key: video_fps,
            M_Defs.video_gop_optimize.key: True,
            M_Defs.pad_start.key: pad_start,
            M_Defs.start.key: start,
        }

        self.generate_video_button.setEnabled(False)
        self._media_output_path = output_path
        self.output_widget.append_text(
            i18n.t(f"{I18N_Simply_Align_Prefix}.notice_video_generate_start")
        )

        try:
            result = MediaPipeline.submit_task(raw_data, f"simply_align {target_path.name}")
            if not result.is_ok:
                show_notify_dialog(
                    i18n.t(f"{I18N_Simply_Align_Prefix}.dialog_title"),
                    i18n.t(
                        f"{I18N_Simply_Align_Prefix}.warning_video_generate_failed",
                        error=print_op_result(result),
                    ),
                )
                self.output_widget.append_text(
                    i18n.t(f"{I18N_Simply_Align_Prefix}.warning_video_generate_failed_log")
                )
                return

            runner_id = result.value[0]
            self._active_media_runner_id = runner_id
            self.output_widget.bind_current_runner_id(runner_id)

            message = i18n.t("app.media_subpages.run_ffmpeg.notice_task_submit_success", task_id=runner_id)
            create_floating_notification(message, self.window())

        finally:
            if not self._active_media_runner_id:
                self.generate_video_button.setEnabled(True)
