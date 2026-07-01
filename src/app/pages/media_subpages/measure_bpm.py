from __future__ import annotations

import json
from PyQt6.QtWidgets import QVBoxLayout
from PyQt6.QtCore import pyqtSignal

from ..base_output_page import BaseOutputPage
from ...widgets import *

from src.services import PathManage, process_manager_api
from src.core.schemas.op_result import print_op_result
from src.core.tools import show_notify_dialog
from src.core.build_bpm_measurer_cmd import build_launch_cmd
from src.core.measure_bpm.edit_config import export_aligned_config
from src.core.measure_bpm.parse_config import generate_notify_path

import i18n



I18N_Prefix = "app.media_subpages.measure_bpm"
def _t(key: str, **kwargs) -> str:
    return i18n.t(f"{I18N_Prefix}.{key}", **kwargs)


class MeasureBpmPage(BaseOutputPage):
    """
    线性流程：
    1. 获取原始 BPM 配置（测量模式 / 手动模式）
    2. 输入 first note appear 时间 + 该 note 的 beat_index
       计算新的 global_offset 导出最终 bpm 配置
    """

    # (bpm_config_path) — 发送到 Auto Rechart 页
    request_send_to_auto_rechart = pyqtSignal(str)


    def setup_content(self) -> None:
        self.content_layout = QVBoxLayout(self.content_area)
        self.content_layout.setContentsMargins(10, 10, 10, 10)

        # 1. measure bpm
        self.enable_bpm_measurer_label = None
        self.enable_bpm_measurer_check_box = None
        self.open_bpm_measurer_button = None
        self.manual_mode_hint_label = None

        self.config_path_label = None
        self.config_select_button = None
        self.config_help = None
        self.config_path_display = None

        # 2. compute global offset
        self.block2_divider = None
        self.block2_row1 = None  # 输入行
        self.block2_row2 = None  # 按钮行
        self.first_note_time_line_edit = None
        self.beat_index_line_edit = None
        self.update_timing_config_button = None
        self.send_to_auto_rechart_button = None

        # state / runners
        self._bpm_measurer_runner_id = None
        self._notify_path = None
        self._last_exported_config_path = None  # 最近一次导出的最终配置路径

        self._build_block1()
        self._build_block2()

        self.content_layout.addStretch()

        # 进程信号
        process_manager_api.get_signals().runner_output.connect(self.output_widget.handle_process_output)
        process_manager_api.get_signals().runner_ended.connect(self.output_widget.handle_process_ended)
        process_manager_api.get_signals().runner_ended.connect(self._on_runner_ended)

        self._toggle_block2(False) # block2 默认隐藏，需满足条件才显示
        self._on_enable_bpm_changed()







    def _build_block1(self) -> None:
        self.content_layout.addWidget(create_divider(_t("ui_block1_divider")))

        # row1: 是否启用测量工具
        self.enable_bpm_measurer_label = create_label(_t("ui_enable_bpm_measurer_label"))
        self.enable_bpm_measurer_check_box = create_check_box(default_checked=True)
        self.open_bpm_measurer_button = create_stated_button(_t("ui_open_bpm_measurer_button"))
        self.manual_mode_hint_label = create_label(_t("ui_manual_mode_hint"))
        self.create_row(self.enable_bpm_measurer_label,
                        self.enable_bpm_measurer_check_box,
                        self.manual_mode_hint_label,
                        add_stretch=True)

        # row2: 启动按钮 + 选择 bpm config
        self.config_path_label = create_label(_t("ui_config_path_label"))
        (self.config_select_button,
         self.config_path_display,
         self.config_help
        ) = create_file_selection_row(
            button_text=_t("ui_select_config_button"),
            help_text=_t("ui_select_config_help"),
            button_length=130,
            name_filter=f"bpm config (*.txt)",
        )
        self.create_row(self.open_bpm_measurer_button,
                        self.config_path_label, self.config_select_button, self.config_help,
                        self.config_path_display)

        # connect
        self.enable_bpm_measurer_check_box.stateChanged.connect(self._on_enable_bpm_changed)
        self.open_bpm_measurer_button.clicked.connect(self._on_open_bpm_measurer_clicked)
        self.config_path_display.textChanged.connect(self._on_block1_input_changed)


    def _on_enable_bpm_changed(self) -> None:
        # 测量工具模式（勾选）
        #   显示启动按钮 + config path_label
        #   隐藏 config select_button + help
        # 手动模式（取消勾选）
        #   反过来
        is_checked = self.enable_bpm_measurer_check_box.isChecked()
        self.open_bpm_measurer_button.setVisible(is_checked)
        self.manual_mode_hint_label.setVisible(not is_checked)
        self.config_path_label.setVisible(is_checked)
        self.config_select_button.setVisible(not is_checked)
        self.config_help.setVisible(not is_checked)


    def _on_open_bpm_measurer_clicked(self) -> None:
        # 防止重复启动
        if self._bpm_measurer_runner_id: return
        self.enable_bpm_measurer_check_box.setEnabled(False)
        self.open_bpm_measurer_button.setEnabled(False)
        # 构建 notify path
        self._notify_path = generate_notify_path()
        if self._notify_path.exists():
            try:
                self._notify_path.unlink()
            except Exception:
                pass
        # 启动 bpm measurer
        cmd = build_launch_cmd(self._notify_path, audio_path=None)
        self.output_widget.append_text(_t("notice_bpm_measurer_start"))
        result = process_manager_api.start(cmd)
        if not result.is_ok:
            show_notify_dialog(_t("dialog_title"),
                               _t("warning_bpm_measurer_start_failed",
                                  error=print_op_result(result)))
            # 失败后恢复按钮
            self.enable_bpm_measurer_check_box.setEnabled(True)
            self.open_bpm_measurer_button.setEnabled(True)
            return
        self._bpm_measurer_runner_id = result.value
        self.output_widget.bind_current_runner_id(self._bpm_measurer_runner_id)
        # 清空旧的 config 路径
        self.config_path_display.setText("")


    def _on_block1_input_changed(self) -> None:
        if self.config_path_display.text().strip():
            self._toggle_block2(True)
            return
        self._toggle_block2(False)










    # Block 2
    def _build_block2(self) -> None:
        self.block2_divider = create_divider(_t("ui_block2_divider"))
        self.content_layout.addWidget(self.block2_divider)

        # row1: first note 时间 + beat_index 输入
        first_note_time_label = create_label(_t("ui_first_note_time_label"))
        first_note_time_help = create_help_icon(_t("ui_first_note_time_help"))
        self.first_note_time_line_edit = create_line_edit(
            length=120, validator='float')

        beat_index_label = create_label(_t("ui_beat_index_label"))
        beat_index_help = create_help_icon(_t("ui_beat_index_help"))
        self.beat_index_line_edit = create_line_edit(
            length=100, validator='float')

        self.block2_row1 = self.create_row(
            first_note_time_label, self.first_note_time_line_edit, first_note_time_help,
            beat_index_label, self.beat_index_line_edit, beat_index_help,
            add_stretch=True)

        # row2: 计算并导出 + 填入自动抄谱
        self.update_timing_config_button = create_stated_button(_t("ui_update_timing_config_button"))
        self.send_to_auto_rechart_button = create_stated_button(_t("ui_send_to_auto_rechart_button"))
        self.block2_row2 = self.create_row(
            self.update_timing_config_button,
            self.send_to_auto_rechart_button,
            add_stretch=True)

        # connect
        self.update_timing_config_button.clicked.connect(self._on_compute_and_export_clicked)
        self.send_to_auto_rechart_button.clicked.connect(self._on_send_to_auto_rechart_clicked)


    def _on_compute_and_export_clicked(self) -> None:
        # reset
        self._last_exported_config_path = None
        self.send_to_auto_rechart_button.hide()
        self._set_all_buttons_enabled(False)

        config_path = self.config_path_display.text().strip()
        first_note_text = self.first_note_time_line_edit.text().strip()
        beat_index_text = self.beat_index_line_edit.text().strip()
        if not config_path or not first_note_text or not beat_index_text:
            show_notify_dialog(_t("dialog_title"), _t("warning_compute_prerequisite"))
            self._set_all_buttons_enabled(True)
            return

        try:
            first_note_time_ms = float(first_note_text)
        except ValueError:
            show_notify_dialog(_t("dialog_title"), _t("warning_first_note_invalid"))
            self._set_all_buttons_enabled(True)
            return

        try:
            beat_index = float(beat_index_text)
        except ValueError:
            show_notify_dialog(_t("dialog_title"), _t("warning_beat_index_invalid"))
            self._set_all_buttons_enabled(True)
            return

        # 读 → 修正 global_offset → 保存对话框 → 写，统一由 edit_config 完成
        res = export_aligned_config(config_path, first_note_time_ms, beat_index, parent=self)
        if not res.is_ok:
            # 用户取消保存对话框时静默恢复
            if res.error_msg != "user cancelled save dialog":
                show_notify_dialog(_t("dialog_title"), _t("warning_compute_failed", error=res.error_msg))
            self._set_all_buttons_enabled(True)
            return

        out_path = res.value
        self.output_widget.append_text(_t("notice_compute_success", output_path=out_path))
        self._last_exported_config_path = str(out_path)
        self.send_to_auto_rechart_button.show()
        self._set_all_buttons_enabled(True)


    def _on_send_to_auto_rechart_clicked(self) -> None:
        config_path = self._last_exported_config_path
        if not config_path:
            show_notify_dialog(_t("dialog_title"), _t("warning_compute_prerequisite"))
            return
        self.request_send_to_auto_rechart.emit(config_path)


    def _set_all_buttons_enabled(self, enabled: bool) -> None:
        """启用/禁用页面上所有交互控件。"""
        self.enable_bpm_measurer_check_box.setEnabled(enabled)
        self.open_bpm_measurer_button.setEnabled(enabled)
        self.config_select_button.setEnabled(enabled)
        self.config_path_display.setEnabled(enabled)
        self.first_note_time_line_edit.setEnabled(enabled)
        self.beat_index_line_edit.setEnabled(enabled)
        self.update_timing_config_button.setEnabled(enabled)
        self.send_to_auto_rechart_button.setEnabled(enabled)


    def _toggle_block2(self, show: bool) -> None:
        """True = show, False = Hide"""
        if self._bpm_measurer_runner_id: return
        self.block2_divider.setVisible(show)
        self.block2_row1.setVisible(show)
        self.block2_row2.setVisible(show)
        # send 按钮默认隐藏，仅在导出成功后显示
        self.send_to_auto_rechart_button.hide()
        # 始终 reset
        self.first_note_time_line_edit.setText("")
        self.beat_index_line_edit.setText("")
        self._last_exported_config_path = None







    def _on_runner_ended(self, runner_id: str, ended) -> None:

        # ---- Bpm-Measurer ----
        if self._bpm_measurer_runner_id:
            if runner_id == self._bpm_measurer_runner_id:
                # 重置状态
                self._bpm_measurer_runner_id = None
                self.enable_bpm_measurer_check_box.setEnabled(True)
                self.open_bpm_measurer_button.setEnabled(True)
                # 0 = 已导出；1 = 用户未导出即关闭；其它/2 = 异常
                exit_code = getattr(ended, "exit_code", None)
                if exit_code == 0:
                    # 解析 bpm measurer 回传信息
                    self._parse_bpm_measurer_manifest()
                elif exit_code == 1:
                    self.output_widget.append_text(_t("notice_bpm_measurer_cancelled"))
                    return
                else:
                    self.output_widget.append_text(_t("warning_bpm_measurer_failed", code=exit_code))
                    return


    def _parse_bpm_measurer_manifest(self) -> None:
        if not self._notify_path or not self._notify_path.is_file():
            self.output_widget.append_text(_t("warning_manifest_missing"))
            return
        try:
            data = json.loads(self._notify_path.read_text(encoding="utf-8"))
            config_path = data.get("config_path", "")
        except Exception as e:
            self.output_widget.append_text(_t("warning_manifest_read_failed", error=str(e)))
            return
        finally:
            try:
                self._notify_path.unlink()
            except Exception:
                pass

        if config_path:
            self.config_path_display.setText(config_path)
        self.output_widget.append_text(_t("notice_bpm_measurer_success"))
