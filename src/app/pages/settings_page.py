from dataclasses import dataclass
from datetime import datetime

from PyQt6.QtWidgets import QVBoxLayout, QMessageBox
from PyQt6.QtCore import Qt
import i18n

from .base_output_page import BaseOutputPage
from .settings_page_sub_model_infer import (
    InferenceDeviceItem,
    ModelInferenceView,
    inspect_model,
    parse_inference_device_results,
)
from ..widgets import *
from ..ui_style import UI_Style
from src.core.schemas.settings_config import SettingsConfig_Definitions as S_Defs
from src.services.model_inference_manage import ModelInferenceManage
from src.core.schemas.op_result import print_op_result, ok, err
from src.core.tools import show_notify_dialog
from src.core.build_worker_cmd import build_cmd_head_python_exe
from src.services import PathManage, SettingsManage, process_manager_api, check_update

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
    def can_cancel_check(self) -> bool:
        return self.is_busy and self.task_type == "check"

    @property
    def can_cancel_convert(self) -> bool:
        return self.is_busy and self.task_type == "convert"
 

class SettingsPage(BaseOutputPage):

    def setup_content(self):

        self.content_layout = QVBoxLayout(self.content_area)
        self.content_layout.setContentsMargins(10, 10, 10, 10)

        self.model_backend_combo_box = None
        self.check_model_button = None
        self.convert_model_button = None
        self.cancel_check_model_button = None
        self.cancel_convert_model_button = None
        self.environment_status_label = None
        self.model_status_label = None
        self.ffmpeg_hw_encoder_combo_box = None
        self.check_ffmpeg_hw_accel_button = None

        self._task_state = _SettingsTaskState()
        self._model_view: ModelInferenceView | None = None

        # 推理设备：缓存最近一次成功检查到的设备列表和当前已保存的设备 ID
        self.inference_device_label = None
        self.inference_device_combo_box = None
        self._cached_device_items: list[InferenceDeviceItem] = []
        self._saved_inference_device: str | None = None
        self._saved_inference_device_half = False
        self._last_checked_backend: str | None = None
        self._loaded_model_backend: str | None = None
        self._loaded_inference_device: str | None = None
        self._loaded_inference_device_half = False

        self.check_update_checkbox = None
        self.check_update_now_button = None
        self.language_combo_box = None

        self.default_width_line_edit = None
        self.default_height_line_edit = None
        self.min_width_line_edit = None
        self.min_height_line_edit = None
        self.ui_scale_slider = None
        self.ui_scale_display = None
        self.remember_window_state_checkbox = None
        self.reset_window_state_label = None
        self.reset_window_state_button = None

        self.save_button = None
        self.reset_button = None

        self._save_order_keys = [
            S_Defs.model_backend.key,
            S_Defs.inference_device.key,
            S_Defs.inference_device_half.key,
            S_Defs.ffmpeg_hw_encoder.key,
            S_Defs.language.key,
            S_Defs.check_update.key,
            S_Defs.main_app_w_default.key,
            S_Defs.main_app_h_default.key,
            S_Defs.main_app_ui_scale.key,
            S_Defs.main_app_remember_window_state.key,
        ]

        self._build_model_section()
        self._build_ffmpeg_section()
        self._build_common_section()
        self._build_window_section()
        self._build_actions()
        self.content_layout.addStretch()
        self.build_bottom_section()

        process_manager_api.get_signals().runner_output.connect(self.output_widget.handle_process_output)
        process_manager_api.get_signals().runner_ended.connect(self.output_widget.handle_process_ended)
        process_manager_api.get_signals().runner_ended.connect(self._on_runner_ended)

        self._load_settings_to_ui()




    def _build_model_section(self) -> None:
        self.content_layout.addWidget(create_divider(i18n.t(f"{I18N_Prefix}.ui_model_divider")))

        backend_label = create_label(i18n.t(f"{I18N_Prefix}.ui_model_backend_label"))
        self.model_backend_combo_box = self._create_combo_from_definition(S_Defs.model_backend, length=120)
        self.check_model_button = create_stated_button(i18n.t(f"{I18N_Prefix}.ui_check_model_button"))
        self.convert_model_button = create_stated_button(i18n.t(f"{I18N_Prefix}.ui_convert_model_button"))
        self.cancel_check_model_button = create_stated_button(i18n.t(f"{I18N_Prefix}.ui_cancel_check_model_button"))
        self.cancel_convert_model_button = create_stated_button(i18n.t(f"{I18N_Prefix}.ui_cancel_convert_model_button"))
        self.inference_device_label = create_label(i18n.t(f"{I18N_Prefix}.ui_inference_device_label"))
        self.inference_device_combo_box = create_combo_box(length=400)
        self.environment_status_label = create_label()
        self.model_status_label = create_label()
        self.convert_model_button.setVisible(False)        # 默认隐藏
        self.cancel_check_model_button.setVisible(False)   # 默认隐藏
        self.cancel_convert_model_button.setVisible(False) # 默认隐藏
        self.inference_device_label.setVisible(False)      # 默认隐藏
        self.inference_device_combo_box.setVisible(False)  # 默认隐藏
        self.environment_status_label.setVisible(False)    # 默认隐藏
        self.model_status_label.setVisible(False)          # 默认隐藏

        self.create_row(
            backend_label,
            self.model_backend_combo_box,
            self.check_model_button,
            self.cancel_check_model_button,
            self.environment_status_label,
            self.model_status_label,
            add_stretch = True,
        )
        self.create_row(
            self.inference_device_label,
            self.inference_device_combo_box,
            self.convert_model_button,
            self.cancel_convert_model_button,
            add_stretch = True,
        )

        self.check_model_button.clicked.connect(self.on_check_model_clicked)
        self.convert_model_button.clicked.connect(self.on_convert_model_clicked)
        self.cancel_check_model_button.clicked.connect(self.on_cancel_check_model_button_clicked)
        self.cancel_convert_model_button.clicked.connect(self.on_cancel_convert_model_button_clicked)
        self.model_backend_combo_box.currentTextChanged.connect(self._on_backend_changed)
        self.inference_device_combo_box.currentIndexChanged.connect(self._on_inference_device_changed)



    def _build_ffmpeg_section(self) -> None:
        self.content_layout.addWidget(create_divider(i18n.t(f"{I18N_Prefix}.ui_ffmpeg_divider")))

        encoder_label = create_label(i18n.t(f"{I18N_Prefix}.ui_ffmpeg_encoder_label"))
        self.ffmpeg_hw_encoder_combo_box = self._create_combo_from_definition(S_Defs.ffmpeg_hw_encoder, length=80)

        self.check_ffmpeg_hw_accel_button = create_stated_button(i18n.t(f"{I18N_Prefix}.ui_auto_detect_hw_button"))
        self.check_ffmpeg_hw_accel_button.clicked.connect(self.on_check_ffmpeg_hw_accel_clicked)

        self.create_row(
            encoder_label,
            self.ffmpeg_hw_encoder_combo_box,

            self.check_ffmpeg_hw_accel_button,
            add_stretch=True,
        )

        




    def _build_common_section(self) -> None:
        self.content_layout.addWidget(create_divider(i18n.t(f"{I18N_Prefix}.ui_general_divider")))

        language_label = create_label(i18n.t(f"{I18N_Prefix}.ui_language_label"))
        self.language_combo_box = self._create_combo_from_definition(S_Defs.language, length=80)

        check_update_label = create_label(i18n.t(f"{I18N_Prefix}.ui_check_update_label"))
        self.check_update_checkbox = create_check_box()
        check_update_now_label = create_label(i18n.t(f"{I18N_Prefix}.ui_check_update_now_label"))
        self.check_update_now_button = create_stated_button(i18n.t(f"{I18N_Prefix}.ui_check_update_now_button"))

        self.create_row(
            language_label, self.language_combo_box,
            check_update_label, self.check_update_checkbox,
            check_update_now_label, self.check_update_now_button,
            add_stretch=True,
        )

        self.check_update_now_button.clicked.connect(self._on_check_update_now_clicked)




    def _build_window_section(self) -> None:
        self.content_layout.addWidget(create_divider(i18n.t(f"{I18N_Prefix}.ui_window_divider")))

        default_label = create_label(i18n.t(f"{I18N_Prefix}.ui_default_size_label"))
        self.default_width_line_edit = create_line_edit(length=60, validator="int")
        self.default_height_line_edit = create_line_edit(length=60, validator="int")

        self.create_row(
            default_label,
            self.default_width_line_edit,
            create_label("×"),
            self.default_height_line_edit,
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

        remember_window_state_label = create_label(
            i18n.t(f"{I18N_Prefix}.ui_remember_window_state_label"))
        self.remember_window_state_checkbox = create_check_box()
        self.reset_window_state_label = create_label(
            i18n.t(f"{I18N_Prefix}.ui_reset_window_state_label"))
        self.reset_window_state_button = create_stated_button(
            i18n.t(f"{I18N_Prefix}.ui_reset_window_state_button"))
        self.create_row(
            remember_window_state_label,
            self.remember_window_state_checkbox,
            self.reset_window_state_label,
            self.reset_window_state_button,
            add_stretch=True,
        )
        self.reset_window_state_button.clicked.connect(self._on_reset_window_state_clicked)



    def _build_actions(self) -> None:
        self.content_layout.addSpacing(UI_Style.widget_spacing)
        self.save_button = create_stated_button(i18n.t(f"{I18N_Prefix}.ui_save_button"), isbig=True)
        self.reset_button = create_stated_button(i18n.t(f"{I18N_Prefix}.ui_reset_button"), isbig=True)

        self.create_row(self.save_button, self.reset_button, add_stretch=True)

        self.save_button.clicked.connect(self.on_save_clicked)
        self.reset_button.clicked.connect(self.on_reset_clicked)




    def build_bottom_section(self) -> None:
        from src.main import VERSION, REPO  # 避免循环依赖
        # 版本号（右下角灰色小字，点击可跳转仓库）
        version_label = create_clickable_label(
            label_text=f"v{VERSION}",
            tooltip_text=REPO,
            url=REPO,
            label_color=UI_Style.COLORS['text_secondary'],
            label_bold=True,
        )
        self.content_layout.addWidget(version_label, alignment=Qt.AlignmentFlag.AlignRight)




    def _create_combo_from_definition(self, definition, length: int):
        options = [str(item) for item in definition.constraints["options"]]
        default_value = str(definition.default)
        default_index = options.index(default_value)
        tooltips = definition.constraints.get("options_tooltips")
        if tooltips:
            tooltips = [None if key is None else i18n.t(f"{I18N_Prefix}.{key}") for key in tooltips]
        return create_combo_box(length=length, items=options,
                                default_index=default_index,
                                show_tooltip=tooltips is not None,
                                item_tooltips=tooltips)



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


    @staticmethod
    def _parse_inference_device_results(recent_output: str, backend: str) -> list[InferenceDeviceItem]:
        return parse_inference_device_results(recent_output, backend)


    def _reset_inference_device_combo(self) -> None:
        # 清空并隐藏设备控件
        if self.inference_device_combo_box is None:
            return
        self.inference_device_combo_box.blockSignals(True)
        self.inference_device_combo_box.clear()
        self.inference_device_combo_box.blockSignals(False)
        self.inference_device_label.setVisible(False)
        self.inference_device_combo_box.setVisible(False)


    def _populate_inference_device_combo(self, items: list[InferenceDeviceItem]) -> None:
        self.inference_device_combo_box.blockSignals(True)
        self.inference_device_combo_box.clear()
        for item in items:
            half_text = "FP16" if item.half_supported else "FP32"
            self.inference_device_combo_box.addItem(
                f"[{item.device_id}] {item.name} ({half_text})",
                item,
            )

        target_index = -1
        if self._saved_inference_device:
            for i in range(self.inference_device_combo_box.count()):
                data = self.inference_device_combo_box.itemData(i)
                if isinstance(data, InferenceDeviceItem) and data.device_id == self._saved_inference_device:
                    target_index = i
                    break

        if target_index < 0 and self.inference_device_combo_box.count() > 0:
            target_index = 0

        if target_index >= 0:
            self.inference_device_combo_box.setCurrentIndex(target_index)

        self.inference_device_combo_box.blockSignals(False)
        self.inference_device_label.setVisible(True)
        self.inference_device_combo_box.setVisible(True)


    def _refresh_inference_device_ui_after_check(self, backend: str) -> None:
        # 在环境检查成功后调用：解析设备结果并决定是否显示设备控件
        recent_output = self.output_widget.get_recent_lines(10)
        items = self._parse_inference_device_results(recent_output, backend)
        self._cached_device_items = items
        self._last_checked_backend = backend

        if items:
            self._populate_inference_device_combo(items)
        else:
            self._reset_inference_device_combo()




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
        self._saved_inference_device = str(settings.get(S_Defs.inference_device.key, "")).strip() or None
        self._saved_inference_device_half = bool(settings.get(S_Defs.inference_device_half.key, False))
        self._loaded_model_backend = str(settings[S_Defs.model_backend.key])
        self._loaded_inference_device = self._saved_inference_device
        self._loaded_inference_device_half = self._saved_inference_device_half

        if self._cached_device_items:
            self._populate_inference_device_combo(self._cached_device_items)
        else:
            self._reset_inference_device_combo()

        self._set_combo_value(self.ffmpeg_hw_encoder_combo_box, settings[S_Defs.ffmpeg_hw_encoder.key])
        self._set_combo_value(self.language_combo_box, settings[S_Defs.language.key])
        self.check_update_checkbox.setChecked(bool(settings[S_Defs.check_update.key]))

        self.default_width_line_edit.setText(str(settings[S_Defs.main_app_w_default.key]))
        self.default_height_line_edit.setText(str(settings[S_Defs.main_app_h_default.key]))
        self.ui_scale_slider.setValue(int(settings[S_Defs.main_app_ui_scale.key]))
        self.remember_window_state_checkbox.setChecked(
            bool(settings[S_Defs.main_app_remember_window_state.key])
        )
        self._sync_ui_state()




    def _collect_form_data(self) -> dict:

        data = {
            S_Defs.model_backend.key: self.model_backend_combo_box.currentText().strip(),
            S_Defs.ffmpeg_hw_encoder.key: self.ffmpeg_hw_encoder_combo_box.currentText().strip(),
            S_Defs.language.key: self.language_combo_box.currentText().strip(),
            S_Defs.check_update.key: self.check_update_checkbox.isChecked(),
            S_Defs.main_app_w_default.key: self.default_width_line_edit.text().strip(),
            S_Defs.main_app_h_default.key: self.default_height_line_edit.text().strip(),
            S_Defs.main_app_ui_scale.key: str(self.ui_scale_slider.value()),
            S_Defs.main_app_remember_window_state.key: self.remember_window_state_checkbox.isChecked(),
        }

        device_item = self.inference_device_combo_box.currentData() if self.inference_device_combo_box.isVisible() else None
        if isinstance(device_item, InferenceDeviceItem):
            data[S_Defs.inference_device.key] = device_item.device_id
            data[S_Defs.inference_device_half.key] = device_item.half_supported
        else:
            data[S_Defs.inference_device.key] = self._saved_inference_device or ""
            data[S_Defs.inference_device_half.key] = self._saved_inference_device_half

        return data




    def on_save_clicked(self) -> None:
        data = self._collect_form_data()

        if not self._can_save_inference_settings(data):
            show_notify_dialog(
                i18n.t(f"{I18N_Prefix}.dialog_title"),
                i18n.t(f"{I18N_Prefix}.warning_inference_settings_not_ready"),
            )
            return

        self.save_button.setEnabled(False)
        self.reset_button.setEnabled(False)

        try:
            for key in self._save_order_keys:
                result = SettingsManage.set(key, data[key])
                if not result.is_ok:
                    reason = print_op_result(result, only_parse_last=True)  # 保底
                    # 如果是 pydantic 报错，尝试仅打印错误信息
                    try:
                        inner = result.inner
                        if inner is not None and "pydantic validation failed" in str(inner.error_msg).lower():
                            reason = str(inner.error_raw)
                    except Exception:
                        pass
                    show_notify_dialog(
                        i18n.t(f"{I18N_Prefix}.dialog_title"),
                        i18n.t(f"{I18N_Prefix}.warning_save_item_failed", item_key=key, error=reason),
                    )
                    self.output_widget.append_text(
                        f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] " + \
                        i18n.t(f"{I18N_Prefix}.notice_save_failed")
                    )
                    return

            # 保存成功后刷新内存中的配置
            refresh_result = SettingsManage.refresh()
            if not refresh_result.is_ok:
                # 刷新失败，记录警告但继续
                self.output_widget.append_text(i18n.t(f"{I18N_Prefix}.warning_refresh_failed", error=refresh_result.error_msg))

            self.output_widget.append_text(
                f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] " + \
                i18n.t(f"{I18N_Prefix}.notice_save_success")
            )
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
        # 对话框关闭后，确保主窗口回到前台
        self.window().raise_()
        self.window().activateWindow()
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

            self.output_widget.append_text(
                f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] " + \
                i18n.t(f"{I18N_Prefix}.notice_reset_success")
            )
            self._load_settings_to_ui()
        finally:
            self.save_button.setEnabled(True)
            self.reset_button.setEnabled(True)




        




    def _sync_ui_state(self) -> None:
        is_busy = self._task_state.is_busy

        widgets = (
            self.model_backend_combo_box,
            self.check_model_button,
            self.inference_device_combo_box,
            self.ffmpeg_hw_encoder_combo_box,
            self.check_ffmpeg_hw_accel_button,
            self.check_update_checkbox,
            self.check_update_now_button,
            self.language_combo_box,
            self.default_width_line_edit,
            self.default_height_line_edit,
            self.ui_scale_slider,
            self.remember_window_state_checkbox,
            self.reset_window_state_button,
            self.save_button,
            self.reset_button,
        )
        for widget in widgets:
            widget.setEnabled(not is_busy)

        self.convert_model_button.setEnabled(not is_busy)
        self.convert_model_button.setVisible(bool(self._model_view and self._model_view.show_convert and not is_busy))
        self.cancel_check_model_button.setVisible(self._task_state.can_cancel_check)
        self.cancel_check_model_button.setEnabled(self._task_state.can_cancel_check)
        self.cancel_convert_model_button.setVisible(self._task_state.can_cancel_convert)
        self.cancel_convert_model_button.setEnabled(self._task_state.can_cancel_convert)


    def _on_backend_changed(self, _text: str) -> None:
        if not self._task_state.is_busy:
            self._model_view = None
        # 切换后端：清空缓存的设备列表并隐藏设备行
        self._last_checked_backend = None
        self._cached_device_items = []
        self._reset_inference_device_combo()
        self._hide_environment_state()
        self._hide_model_state()
        self._sync_ui_state()


    def _has_active_runner(self) -> bool:
        return self._task_state.is_busy


    def _start_worker_cmd(self, cmd: list[str], worker_type: str, backend: str | None = None) -> bool:

        if self._has_active_runner():
            return False
        if worker_type not in {"check", "convert", "ffmpeg_hw_accel_check"}:
            return False

        result = process_manager_api.start(cmd)
        if not result.is_ok:
            show_notify_dialog(
                i18n.t(f"{I18N_Prefix}.dialog_title"),
                i18n.t(f"{I18N_Prefix}.warning_worker_start_failed", error=result.error_msg),
            )
            return False

        runner_id = result.value
        self._task_state = _SettingsTaskState(task_type=worker_type, runner_id=runner_id, backend=backend)
        self.output_widget.bind_current_runner_id(runner_id)
        self._sync_ui_state()
        return True

    def _cancel_model_task(self, task_type: str) -> None:
        if self._task_state.task_type != task_type:
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

    def on_cancel_check_model_button_clicked(self) -> None:
        self._cancel_model_task("check")

    def _current_device_item(self) -> InferenceDeviceItem | None:
        data = self.inference_device_combo_box.currentData() if self.inference_device_combo_box.isVisible() else None
        return data if isinstance(data, InferenceDeviceItem) else None

    def _on_inference_device_changed(self, index: int) -> None:
        self._refresh_model_state()
        self._sync_ui_state()

    def _hide_model_state(self) -> None:
        if self.model_status_label is not None:
            self.model_status_label.setVisible(False)

    def _hide_environment_state(self) -> None:
        if self.environment_status_label is not None:
            self.environment_status_label.setVisible(False)

    def _show_environment_state(self, status_text: str) -> None:
        if self.environment_status_label is None:
            return
        self.environment_status_label.setText(
            i18n.t(f"{I18N_Prefix}.environment_status_{status_text}")
        )
        self.environment_status_label.setVisible(True)

    def _refresh_model_state(self) -> None:
        backend = self.model_backend_combo_box.currentText().strip()
        device_item = self._current_device_item()
        view = inspect_model(backend, device_item.half_supported if device_item else None)
        if view is None:
            self._hide_model_state()
            return
        self._model_view = view
        self.model_status_label.setText(
            i18n.t(f"{I18N_Prefix}.model_status_{view.status_text}")
        )
        self.model_status_label.setVisible(True)

    def _append_model_check_result(self, backend: str) -> None:
        result = PathManage.resolve_model_paths(backend)
        if not result.is_ok:
            # 模型文件存在可能会不兼容，为了避免复杂判断
            # 仅在检查模型文件缺失时，才在输出框中显示警告信息
            self.output_widget.append_text(
                i18n.t(
                    f"{I18N_Prefix}.warning_model_missing",
                    backend=backend,
                    error=print_op_result(result, only_parse_last=True),
                )
            )

    def _can_save_inference_settings(self, data: dict) -> bool:
        backend = data.get(S_Defs.model_backend.key, "")
        device = data.get(S_Defs.inference_device.key, "")
        device_half = data.get(S_Defs.inference_device_half.key)
        inference_changed = (
            self._loaded_model_backend != backend
            or self._loaded_inference_device != device
            or self._loaded_inference_device_half != device_half
        )
        if not inference_changed:
            return True
        if self._last_checked_backend != backend or not isinstance(device_half, bool):
            return False
        if not any(item.device_id == device for item in self._cached_device_items):
            return False
        view = inspect_model(backend, device_half)
        return view is not None and view.is_usable




    def on_check_model_clicked(self) -> None:
        if self._has_active_runner():
            return
        self._model_view = None
        # 开始新检查：清空缓存的设备列表并隐藏设备行
        self._last_checked_backend = None
        self._cached_device_items = []
        self._reset_inference_device_combo()
        self._hide_environment_state()
        self._hide_model_state()
        self._sync_ui_state()
        backend = self.model_backend_combo_box.currentText().strip()
        self.output_widget.append_text(i18n.t(f"{I18N_Prefix}.notice_check_start", backend=backend))
        cmd = build_cmd_head_python_exe(PathManage.CHECK_DEVICE_WORKER_PATH)
        backend_id = ModelInferenceManage.get_model_backend_id(backend)
        if backend_id is None:
            self._show_environment_state("unavailable")
            self._sync_ui_state()
            return
        cmd.append(backend_id)
        if not self._start_worker_cmd(cmd, "check", backend):
            self._show_environment_state("unavailable")
            self._sync_ui_state()



    def on_check_ffmpeg_hw_accel_clicked(self) -> None:
        if self._has_active_runner():
            return

        cmd = build_cmd_head_python_exe(PathManage.CHECK_FFMPEG_HW_ACCEL_WORKER_PATH)
        self._start_worker_cmd(cmd, "ffmpeg_hw_accel_check")




    def on_convert_model_clicked(self) -> None:
        if self._has_active_runner():
            return
        backend = self.model_backend_combo_box.currentText().strip()
        device_item = self._current_device_item()
        backend_id = ModelInferenceManage.get_model_backend_id(backend)
        if device_item is None or backend_id is None:
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
        cmd.extend([
            backend_id,
            str(detect_batch),
            str(cls_batch),
            str(touch_hold_batch),
            "true" if device_item.half_supported else "false",
        ])
        self._start_worker_cmd(cmd, "convert", backend)




    def on_cancel_convert_model_button_clicked(self) -> None:
        self._cancel_model_task("convert")




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

        # 用户主动取消
        if getattr(ended, "cancelled", False):
            self.output_widget.append_text(i18n.t(f"{I18N_Prefix}.notice_check_cancelled", backend=backend))
            self._hide_environment_state()
            self._hide_model_state()
            self._sync_ui_state()
            return

        # 进程异常结束
        failed = bool(getattr(ended, "crashed", False))
        exit_code = getattr(ended, "exit_code", None)
        if exit_code is None or exit_code != 0:
            failed = True

        if failed:
            self.output_widget.append_text(i18n.t(f"{I18N_Prefix}.warning_check_failed", backend=backend))
            self._show_environment_state("unavailable")
            self._hide_model_state()
            self._sync_ui_state()
            return

        # 进程正常结束
        self.output_widget.append_text(i18n.t(f"{I18N_Prefix}.notice_check_pass", backend=backend))

        # 解析设备列表并按需显示推理设备行
        self._refresh_inference_device_ui_after_check(backend)

        # 环境检查通过
        # 下一步，检查模型文件是否存在
        self._append_model_check_result(backend)
        self._show_environment_state("available")

        self._refresh_model_state()
        self._sync_ui_state()

        


    def _handle_convert_runner_ended(self, backend: str, ended) -> None:

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
            recent_output = self.output_widget.get_recent_lines(15)
            driver_error = 'Error Code 6: API Usage Error (CUDA initialization failure with error: 35. Please check your CUDA installation'
            if driver_error in recent_output:
                self.output_widget.append_text(i18n.t(f"{I18N_Prefix}.warning_cuda_driver_outdated"))
            self._refresh_model_state()
            self._sync_ui_state()
            return

        # 进程正常结束，二次复查模型文件是否存在
        path_result = PathManage.resolve_model_paths(backend)
        if not path_result.is_ok:
            model_error = (
                f"{path_result.error_msg}\n\n"
                f"{i18n.t(f'{I18N_Prefix}.warning_model_not_found_for_backend')}"
            )
            self.output_widget.append_text(
                i18n.t(
                    f"{I18N_Prefix}.warning_convert_incomplete",
                    backend=backend,
                    error=model_error,
                )
            )
            self._refresh_model_state()
            self._sync_ui_state()
            return

        # 模型转换成功
        self.output_widget.append_text(i18n.t(f"{I18N_Prefix}.notice_convert_success", backend=backend))
        device_item = self._current_device_item()
        if device_item is not None:
            result = ModelInferenceManage.set_model_half_for_backend(
                backend,
                device_item.half_supported,
            )
            if not result.is_ok:
                self.output_widget.append_text(
                    i18n.t(
                        f"{I18N_Prefix}.warning_model_half_save_failed",
                        error=result.error_msg,
                    )
                )
        self._refresh_model_state()
        self._sync_ui_state()



    def _on_check_update_now_clicked(self) -> None:
        check_update(force=True)


    def _on_reset_window_state_clicked(self) -> None:
        result = self.window().reset_window_to_default()
        if result.is_ok:
            self.output_widget.append_text(i18n.t(f"{I18N_Prefix}.log_window_state_reset"))
        else:
            self.output_widget.append_text(
                i18n.t(f"{I18N_Prefix}.log_window_state_reset_failed", error=result.error_msg))



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
