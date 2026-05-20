from dataclasses import dataclass

from PyQt6.QtWidgets import QVBoxLayout, QMessageBox
import i18n

from .base_output_page import BaseOutputPage
from ..widgets import *
from src.core.schemas.settings_config import SettingsConfig_Definitions as S_Defs
from src.core.schemas.op_result import print_op_result, ok, err
from src.core.tools import show_notify_dialog
from src.core.build_worker_cmd import build_cmd_head_python_exe
from src.services import SettingsManage, process_manager_api
from src.services.path_manage import PathManage

I18N_Prefix = "app.settings_page"


@dataclass(slots=True)
class _SettingsTaskState:
    task_type: str | None = None
    runner_id: str | None = None
    backend: str | None = None

    @property
    def is_busy(self) -> bool:
        return self.runner_id is not None

    @property
    def is_model_task(self) -> bool:
        return self.task_type in {"check", "convert"}

    @property
    def can_cancel(self) -> bool:
        return self.is_busy and self.is_model_task
 

class SettingsPage(BaseOutputPage):

    def setup_content(self):

        self.content_layout = QVBoxLayout(self.content_area)
        self.content_layout.setContentsMargins(10, 10, 10, 10)

        self.model_backend_combo_box = None
        self.check_model_button = None
        self.convert_model_button = None
        self.cancel_convert_model_button = None
        self.ffmpeg_hw_encoder_combo_box = None
        self.check_ffmpeg_hw_accel_button = None

        self._task_state = _SettingsTaskState()
        self._show_convert_model_button = False

        self.language_combo_box = None

        self.default_width_line_edit = None
        self.default_height_line_edit = None
        self.min_width_line_edit = None
        self.min_height_line_edit = None
        self.ui_scale_slider = None
        self.ui_scale_display = None

        self.save_button = None
        self.reset_button = None

        self._save_order_keys = [
            S_Defs.model_backend.key,
            S_Defs.ffmpeg_hw_encoder.key,
            S_Defs.language.key,
            S_Defs.main_app_default_size.key,
            S_Defs.main_app_min_size.key,
            S_Defs.main_app_ui_scale.key,
        ]

        self._build_model_section()
        self._build_ffmpeg_section()
        self._build_common_section()
        self._build_window_section()
        self._build_actions()

        process_manager_api.get_signals().runner_output.connect(self.output_widget.handle_process_output)
        process_manager_api.get_signals().runner_ended.connect(self.output_widget.handle_process_ended)
        process_manager_api.get_signals().runner_ended.connect(self._on_runner_ended)

        self.content_layout.addStretch()
        self._load_settings_to_ui()




    def _build_model_section(self) -> None:
        self.content_layout.addWidget(create_divider(i18n.t(f"{I18N_Prefix}.ui_model_divider")))

        backend_label = create_label(i18n.t(f"{I18N_Prefix}.ui_model_backend_label"))
        self.model_backend_combo_box = self._create_combo_from_definition(S_Defs.model_backend, length=100)
        backend_help = create_help_icon(i18n.t(f"{I18N_Prefix}.ui_model_backend_help"))
        self.check_model_button = create_stated_button(i18n.t(f"{I18N_Prefix}.ui_check_model_button"))
        self.convert_model_button = create_stated_button(i18n.t(f"{I18N_Prefix}.ui_convert_model_button"), width=120)
        self.cancel_convert_model_button = create_stated_button(i18n.t(f"{I18N_Prefix}.ui_cancel_convert_model_button"))
        self.convert_model_button.setVisible(False)        # 默认隐藏
        self.cancel_convert_model_button.setVisible(False) # 默认隐藏

        self.create_row(
            backend_label,
            self.model_backend_combo_box,
            backend_help,
            self.check_model_button,
            self.convert_model_button,
            self.cancel_convert_model_button,
            add_stretch=True,
        )

        self.check_model_button.clicked.connect(self.on_check_model_clicked)
        self.convert_model_button.clicked.connect(self.on_convert_model_clicked)
        self.cancel_convert_model_button.clicked.connect(self.on_cancel_convert_model_button_clicked)
        self.model_backend_combo_box.currentTextChanged.connect(self._on_backend_changed)



    def _build_ffmpeg_section(self) -> None:
        self.content_layout.addWidget(create_divider(i18n.t(f"{I18N_Prefix}.ui_ffmpeg_divider")))

        encoder_label = create_label(i18n.t(f"{I18N_Prefix}.ui_ffmpeg_encoder_label"))
        self.ffmpeg_hw_encoder_combo_box = self._create_combo_from_definition(S_Defs.ffmpeg_hw_encoder, length=80)
        encoder_help = create_help_icon(i18n.t(f"{I18N_Prefix}.ui_ffmpeg_encoder_help"))

        self.check_ffmpeg_hw_accel_button = create_stated_button(i18n.t(f"{I18N_Prefix}.ui_auto_detect_hw_button"))
        self.check_ffmpeg_hw_accel_button.clicked.connect(self.on_check_ffmpeg_hw_accel_clicked)

        self.create_row(
            encoder_label,
            self.ffmpeg_hw_encoder_combo_box,
            encoder_help,

            self.check_ffmpeg_hw_accel_button,
            add_stretch=True,
        )

        




    def _build_common_section(self) -> None:
        self.content_layout.addWidget(create_divider(i18n.t(f"{I18N_Prefix}.ui_general_divider")))

        language_label = create_label(i18n.t(f"{I18N_Prefix}.ui_language_label"))
        self.language_combo_box = self._create_combo_from_definition(S_Defs.language, length=80)

        self.create_row(
            language_label,
            self.language_combo_box,
            add_stretch=True,
        )




    def _build_window_section(self) -> None:
        self.content_layout.addWidget(create_divider(i18n.t(f"{I18N_Prefix}.ui_window_divider")))

        default_label = create_label(i18n.t(f"{I18N_Prefix}.ui_default_size_label"))
        self.default_width_line_edit = create_line_edit(length=60, validator="int")
        self.default_height_line_edit = create_line_edit(length=60, validator="int")

        min_label = create_label(i18n.t(f"{I18N_Prefix}.ui_min_size_label"))
        self.min_width_line_edit = create_line_edit(length=60, validator="int")
        self.min_height_line_edit = create_line_edit(length=60, validator="int")

        self.create_row(
            default_label,
            self.default_width_line_edit,
            create_label("x"),
            self.default_height_line_edit,
            add_stretch=True,
        )
        self.create_row(
            min_label,
            self.min_width_line_edit,
            create_label("x"),
            self.min_height_line_edit,
            add_stretch=True,
        )

        ui_scale_label = create_label(i18n.t(f"{I18N_Prefix}.ui_ui_scale_label"))
        self.ui_scale_slider, self.ui_scale_display = create_slider(
            min_val=S_Defs.main_app_ui_scale.constraints["ge"],
            max_val=S_Defs.main_app_ui_scale.constraints["le"],
            step=5,
            default_value=S_Defs.main_app_ui_scale.default,
            slider_length=250,
            text_transform=lambda v: f" {v}%",
        )

        self.create_row(
            ui_scale_label,
            self.ui_scale_slider,
            self.ui_scale_display,
            add_stretch=True,
        )



    def _build_actions(self) -> None:
        self.content_layout.addWidget(create_divider(i18n.t(f"{I18N_Prefix}.ui_actions_divider")))

        self.save_button = create_stated_button(i18n.t(f"{I18N_Prefix}.ui_save_button"), isbig=True)
        self.reset_button = create_stated_button(i18n.t(f"{I18N_Prefix}.ui_reset_button"), isbig=True)

        self.create_row(self.save_button, self.reset_button, add_stretch=True)

        self.save_button.clicked.connect(self.on_save_clicked)
        self.reset_button.clicked.connect(self.on_reset_clicked)




    def _create_combo_from_definition(self, definition, length: int):
        options = [str(item) for item in definition.constraints["options"]]
        default_value = str(definition.default)
        default_index = options.index(default_value)
        return create_combo_box(length=length, items=options, default_index=default_index)



    def _set_combo_value(self, combo_box, value: str) -> None:
        idx = combo_box.findText(str(value))
        if idx >= 0:
            combo_box.setCurrentIndex(idx)



    def _refresh_combo_options(self, combo_box, definition, selected_value: str | None = None) -> None:
        options = [str(item) for item in definition.constraints["options"]]
        current_value = combo_box.currentText().strip()

        combo_box.blockSignals(True)
        combo_box.clear()
        combo_box.addItems(options)

        if selected_value is not None:
            self._set_combo_value(combo_box, selected_value)
        elif current_value:
            self._set_combo_value(combo_box, current_value)

        if combo_box.currentIndex() < 0 and options:
            combo_box.setCurrentIndex(0)

        combo_box.blockSignals(False)



    def _refresh_ffmpeg_hw_accel_ui(self, encoder_value: str | None = None) -> None:
        self._refresh_combo_options(self.ffmpeg_hw_encoder_combo_box, S_Defs.ffmpeg_hw_encoder, encoder_value)



    @staticmethod
    def _parse_ffmpeg_hw_accel_results(recent_output: str) -> str | None:
        encoder_value = None

        for line in recent_output.splitlines():
            line = line.strip()
            if not line:
                continue

            if line.startswith("FFMPEG_HW_ENCODER_RESULT:"):
                encoder_value = line.partition(":")[2].strip() or None

        return encoder_value




    def _load_settings_to_ui(self) -> None:
        settings = {}

        for key in self._save_order_keys:
            result = SettingsManage.get(key)
            if not result.is_ok:
                show_notify_dialog(
                    i18n.t(f"{I18N_Prefix}.dialog_title"),
                    i18n.t(f"{I18N_Prefix}.warning_load_failed", item_key=key, error=result.error_msg),
                )
                return
            settings[key] = result.value

        self._set_combo_value(self.model_backend_combo_box, settings[S_Defs.model_backend.key])
        self._set_combo_value(self.ffmpeg_hw_encoder_combo_box, settings[S_Defs.ffmpeg_hw_encoder.key])
        self._set_combo_value(self.language_combo_box, settings[S_Defs.language.key])

        default_size = settings[S_Defs.main_app_default_size.key]
        min_size = settings[S_Defs.main_app_min_size.key]

        self.default_width_line_edit.setText(str(default_size[0]))
        self.default_height_line_edit.setText(str(default_size[1]))
        self.min_width_line_edit.setText(str(min_size[0]))
        self.min_height_line_edit.setText(str(min_size[1]))
        self.ui_scale_slider.setValue(int(settings[S_Defs.main_app_ui_scale.key]))
        self._sync_ui_state()




    def _collect_form_data(self) -> dict:

        return {
            S_Defs.model_backend.key: self.model_backend_combo_box.currentText().strip(),
            S_Defs.ffmpeg_hw_encoder.key: self.ffmpeg_hw_encoder_combo_box.currentText().strip(),
            S_Defs.language.key: self.language_combo_box.currentText().strip(),
            S_Defs.main_app_default_size.key: (
                self.default_width_line_edit.text().strip(),
                self.default_height_line_edit.text().strip(),
            ),
            S_Defs.main_app_min_size.key: (
                self.min_width_line_edit.text().strip(),
                self.min_height_line_edit.text().strip(),
            ),
            S_Defs.main_app_ui_scale.key: str(self.ui_scale_slider.value()),
        }




    def on_save_clicked(self) -> None:
        data = self._collect_form_data()

        self.save_button.setEnabled(False)
        self.reset_button.setEnabled(False)

        try:
            for key in self._save_order_keys:
                result = SettingsManage.set(key, data[key])
                if not result.is_ok:
                    reason = print_op_result(result, only_parse_last=True)
                    show_notify_dialog(
                        i18n.t(f"{I18N_Prefix}.dialog_title"),
                        i18n.t(f"{I18N_Prefix}.warning_save_item_failed", item_key=key, error=reason),
                    )
                    return

            # 保存成功后刷新内存中的配置
            refresh_result = SettingsManage.refresh()
            if not refresh_result.is_ok:
                # 刷新失败，记录警告但继续
                self.output_widget.append_text(i18n.t(f"{I18N_Prefix}.warning_refresh_failed", error=refresh_result.error_msg))

            self.output_widget.append_text(i18n.t(f"{I18N_Prefix}.notice_save_success"))
            self._load_settings_to_ui()
        finally:
            self.save_button.setEnabled(True)
            self.reset_button.setEnabled(True)




    def on_reset_clicked(self) -> None:
        reply = QMessageBox.question(
            self,
            i18n.t(f"{I18N_Prefix}.ui_reset_confirm_title"),
            i18n.t(f"{I18N_Prefix}.ui_reset_confirm_text"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.save_button.setEnabled(False)
        self.reset_button.setEnabled(False)

        try:
            result = SettingsManage.reset()
            if not result.is_ok:
                reason = print_op_result(result, only_parse_last=True)
                show_notify_dialog(
                    i18n.t(f"{I18N_Prefix}.dialog_title"),
                    i18n.t(f"{I18N_Prefix}.warning_reset_failed", error=reason),
                )
                return

            self.output_widget.append_text(i18n.t(f"{I18N_Prefix}.notice_reset_success"))
            self._load_settings_to_ui()
        finally:
            self.save_button.setEnabled(True)
            self.reset_button.setEnabled(True)




        




    def _sync_ui_state(self) -> None:
        is_busy = self._task_state.is_busy

        self.model_backend_combo_box.setEnabled(not is_busy)
        self.check_model_button.setEnabled(not is_busy)
        self.convert_model_button.setEnabled(not is_busy)
        self.ffmpeg_hw_encoder_combo_box.setEnabled(not is_busy)
        self.check_ffmpeg_hw_accel_button.setEnabled(not is_busy)
        self.save_button.setEnabled(not is_busy)
        self.reset_button.setEnabled(not is_busy)

        self.convert_model_button.setVisible(self._show_convert_model_button and not is_busy)
        self.cancel_convert_model_button.setVisible(self._task_state.can_cancel)
        self.cancel_convert_model_button.setEnabled(self._task_state.can_cancel)


    def _on_backend_changed(self, _text: str) -> None:
        if not self._task_state.is_busy:
            self._show_convert_model_button = False
        self._sync_ui_state()


    def _has_active_runner(self) -> bool:
        return self._task_state.is_busy


    def _start_worker_cmd(self, cmd: list[str], worker_type: str, backend: str | None = None):

        if self._has_active_runner():
            return
        if worker_type not in {"check", "convert", "ffmpeg_hw_accel_check"}:
            return

        result = process_manager_api.start(cmd)
        if not result.is_ok:
            show_notify_dialog(
                i18n.t(f"{I18N_Prefix}.dialog_title"),
                i18n.t(f"{I18N_Prefix}.warning_worker_start_failed", error=result.error_msg),
            )
            return None

        runner_id = result.value
        self._task_state = _SettingsTaskState(task_type=worker_type, runner_id=runner_id, backend=backend)
        self.output_widget.bind_current_runner_id(runner_id)
        self._sync_ui_state()
        return




    def on_check_model_clicked(self) -> None:
        if self._has_active_runner():
            return
        self._show_convert_model_button = False
        self._sync_ui_state()
        backend = self.model_backend_combo_box.currentText().strip()
        self.output_widget.append_text(i18n.t(f"{I18N_Prefix}.notice_check_start", backend=backend))
        cmd = build_cmd_head_python_exe(PathManage.CHECK_DEVICE_WORKER_PATH)
        cmd.append(backend.lower())
        self._start_worker_cmd(cmd, "check", backend)



    def on_check_ffmpeg_hw_accel_clicked(self) -> None:
        if self._has_active_runner():
            return

        cmd = build_cmd_head_python_exe(PathManage.CHECK_FFMPEG_HW_ACCEL_WORKER_PATH)
        self._start_worker_cmd(cmd, "ffmpeg_hw_accel_check")




    def on_convert_model_clicked(self) -> None:
        if self._has_active_runner():
            return
        backend = self.model_backend_combo_box.currentText().strip()

        # 特例：cpu 不应该触发转换按钮
        if backend == "CPU":
            self.output_widget.append_text(i18n.t(f"{I18N_Prefix}.notice_cpu_don't_need_convert_model"))
            return

        detect_batch_result = SettingsManage.get(S_Defs.predict_batch_size_detect_obb.key)
        if not detect_batch_result.is_ok:
            show_notify_dialog(
                i18n.t(f"{I18N_Prefix}.dialog_title"),
                i18n.t(
                    f"{I18N_Prefix}.warning_load_failed",
                    item_key=S_Defs.predict_batch_size_detect_obb.key,
                    error=detect_batch_result.error_msg,
                ),
            )
            return

        cls_batch_result = SettingsManage.get(S_Defs.predict_batch_size_classify.key)
        if not cls_batch_result.is_ok:
            show_notify_dialog(
                i18n.t(f"{I18N_Prefix}.dialog_title"),
                i18n.t(
                    f"{I18N_Prefix}.warning_load_failed",
                    item_key=S_Defs.predict_batch_size_classify.key,
                    error=cls_batch_result.error_msg,
                ),
            )
            return

        touch_hold_batch_result = SettingsManage.get(S_Defs.predict_batch_size_touch_hold.key)
        if not touch_hold_batch_result.is_ok:
            show_notify_dialog(
                i18n.t(f"{I18N_Prefix}.dialog_title"),
                i18n.t(
                    f"{I18N_Prefix}.warning_load_failed",
                    item_key=S_Defs.predict_batch_size_touch_hold.key,
                    error=touch_hold_batch_result.error_msg,
                ),
            )
            return

        detect_batch = detect_batch_result.value
        cls_batch = cls_batch_result.value
        touch_hold_batch = touch_hold_batch_result.value

        self.output_widget.append_text(
            i18n.t(
                f"{I18N_Prefix}.notice_convert_start",
                backend=backend
            )
        )

        cmd = build_cmd_head_python_exe(PathManage.MODEL_CONVERT_WORKER_PATH)
        cmd.extend([str(backend), str(detect_batch), str(cls_batch), str(touch_hold_batch)])
        self._start_worker_cmd(cmd, "convert", backend)




    def on_cancel_convert_model_button_clicked(self) -> None:
        if not self._task_state.can_cancel:
            return

        runner_id = self._task_state.runner_id
        if not runner_id:
            return

        result = process_manager_api.cancel(runner_id)
        if not result.is_ok:
            show_notify_dialog(
                i18n.t(f"{I18N_Prefix}.dialog_title"),
                i18n.t(f"{I18N_Prefix}.warning_cancel_failed", error=result.error_msg),
            )
            return

        self.output_widget.append_text(i18n.t(f"{I18N_Prefix}.notice_cancel_requested"))




    def _on_runner_ended(self, runner_id: str, ended) -> None:

        if self._task_state.runner_id != runner_id:
            return

        task_state = self._task_state
        self._task_state = _SettingsTaskState()
        self._sync_ui_state()

        if task_state.task_type == "check":
            self._handle_check_runner_ended(task_state.backend, ended)
        elif task_state.task_type == "convert":
            self._handle_convert_runner_ended(task_state.backend, ended)
        elif task_state.task_type == "ffmpeg_hw_accel_check":
            self._handle_ffmpeg_hw_accel_runner_ended(ended)




    def _handle_check_runner_ended(self, backend: str, ended) -> None:

        self._show_convert_model_button = False

        # 用户主动取消
        if getattr(ended, "cancelled", False):
            self.output_widget.append_text(i18n.t(f"{I18N_Prefix}.notice_check_cancelled", backend=backend))
            self._sync_ui_state()
            return

        # 进程异常结束
        failed = bool(getattr(ended, "crashed", False))
        exit_code = getattr(ended, "exit_code", None)
        if exit_code is None or exit_code != 0:
            failed = True

        if failed:
            self.output_widget.append_text(i18n.t(f"{I18N_Prefix}.warning_check_failed", backend=backend))
            self._sync_ui_state()
            return

        # 进程正常结束
        self.output_widget.append_text(i18n.t(f"{I18N_Prefix}.notice_check_pass", backend=backend))

        # 环境检查通过
        # 下一步，检查模型文件是否存在

        # 模型检查通过
        path_result = S_Defs.get_path_by_backend(backend)
        if path_result.is_ok:
            self.output_widget.append_text(i18n.t(f"{I18N_Prefix}.notice_model_ready", backend=backend))
            # 特例 cpu 提示无需转换
            if backend == "CPU":
                self.output_widget.append_text(i18n.t(f"{I18N_Prefix}.notice_cpu_don't_need_convert_model"))
                self._sync_ui_state()
            return

        # 模型检查失败
        self.output_widget.append_text(
            i18n.t(
                f"{I18N_Prefix}.warning_model_missing",
                backend=backend,
                error=path_result.error_msg,
            )
        )

        # 特例：cpu 不显示转换按钮，直接报错
        if backend == "CPU":
            show_notify_dialog(
                i18n.t(f"{I18N_Prefix}.dialog_title"),
                i18n.t(f"{I18N_Prefix}.warning_cpu_model_missing", error=path_result.error_msg),
            )
            self._sync_ui_state()
            return
        
        # 其他情况下，显示转换按钮，允许用户转换模型
        self._show_convert_model_button = True
        self._sync_ui_state()

        


    def _handle_convert_runner_ended(self, backend: str, ended) -> None:

        self._show_convert_model_button = True

        # 用户主动取消
        if getattr(ended, "cancelled", False):
            self.output_widget.append_text(i18n.t(f"{I18N_Prefix}.notice_convert_cancelled", backend=backend))
            self._sync_ui_state()
            return

        # 进程异常结束
        failed = bool(getattr(ended, "crashed", False))
        exit_code = getattr(ended, "exit_code", None)
        if exit_code is None or exit_code != 0:
            failed = True

        if failed:
            self.output_widget.append_text(i18n.t(f"{I18N_Prefix}.warning_convert_failed", backend=backend))
            self._sync_ui_state()
            return

        # 进程正常结束，二次复查模型文件是否存在
        path_result = S_Defs.get_path_by_backend(backend)
        if not path_result.is_ok:
            self.output_widget.append_text(
                i18n.t(
                    f"{I18N_Prefix}.warning_convert_incomplete",
                    backend=backend,
                    error=path_result.error_msg,
                )
            )
            self._sync_ui_state()
            return

        # 模型转换成功
        self._show_convert_model_button = False
        self.output_widget.append_text(i18n.t(f"{I18N_Prefix}.notice_convert_success", backend=backend))
        self._sync_ui_state()



    def _handle_ffmpeg_hw_accel_runner_ended(self, ended) -> None:
        if getattr(ended, "cancelled", False):
            return

        failed = bool(getattr(ended, "crashed", False))
        exit_code = getattr(ended, "exit_code", None)
        if exit_code is None or exit_code != 0:
            failed = True

        if failed:
            return

        self.output_widget.flush_buffer()
        encoder_value = self._parse_ffmpeg_hw_accel_results(self.output_widget.get_recent_lines(7))
        self._refresh_ffmpeg_hw_accel_ui(encoder_value)
