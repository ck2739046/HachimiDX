from __future__ import annotations

import json
from pathlib import Path

from PyQt6.QtWidgets import QVBoxLayout, QFileDialog

from ..base_output_page import BaseOutputPage, _create_row
from ...widgets import *

from src.services import PathManage, process_manager_api
from src.core.schemas.op_result import print_op_result
from src.core.schemas.media_config import MediaType
from src.core.tools import show_notify_dialog, generate_uid
from src.core.build_worker_cmd import build_cmd_head_python_exe
from src.core.build_bpm_measurer_cmd import build_launch_cmd
from src.core.measurer_bpm.edit_config import update_global_offset
from .simply_align import parse_offset_ms

import i18n



I18N_Prefix = "app.media_subpages.measure_bpm"
def _t(key: str, **kwargs) -> str:
    return i18n.t(f"{I18N_Prefix}.{key}", **kwargs)


class MeasureBpmPage(BaseOutputPage):
    """
    线性流程：
    1. 获取原始 BPM 配置 + 音频（测量模式 / 手动模式）
    2. 与谱面确认视频对齐，得到 offset_ms，合并生成最终 bpm 配置
    """

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

        self.audio_path_label = None
        self.audio_select_button = None
        self.audio_help = None
        self.audio_path_display = None
        
        # 2. align
        self.block2_divider = None
        self.chart_video_input = None  # row 1
        self.auto_align_button = None  # row 2
        self.align_result_label = None # row 2
        self.block2_row3 = None        # row 3
        self.offset_line_edit = None
        self.update_timing_config_button = None

        # state / runners
        self._align_runner_id = None
        self._bpm_measurer_runner_id = None
        self._notify_path = None

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

        # row1: 是否启用测量工具 + 启动按钮
        self.enable_bpm_measurer_label = create_label(_t("ui_enable_bpm_measurer_label"))
        self.enable_bpm_measurer_check_box = create_check_box(default_checked=True)
        self.open_bpm_measurer_button = create_stated_button(_t("ui_open_bpm_measurer_button"))
        self.manual_mode_hint_label = create_label(_t("ui_manual_mode_hint"))
        self.create_row(self.enable_bpm_measurer_label,
                        self.enable_bpm_measurer_check_box,
                        self.open_bpm_measurer_button,
                        self.manual_mode_hint_label,
                        add_stretch=True)

        # row2: 选择 bpm config
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
        self.create_row(self.config_path_label, self.config_select_button,
                        self.config_help, self.config_path_display)

        # row3: 选择 audio
        self.audio_path_label = create_label(_t("ui_audio_path_label"))
        (self.audio_select_button,
         self.audio_path_display,
         self.audio_help
        ) = create_file_selection_row(
            button_text=_t("ui_select_audio_button"),
            help_text=_t("ui_select_audio_help"),
            button_length=130,
            name_filter="audio (*.mp3 *.ogg *.wav *.aac *.flac *.m4a)",
        )
        self.create_row(self.audio_path_label, self.audio_select_button,
                        self.audio_help, self.audio_path_display)

        # connect
        self.enable_bpm_measurer_check_box.stateChanged.connect(self._on_enable_bpm_changed)
        self.open_bpm_measurer_button.clicked.connect(self._on_open_bpm_measurer_clicked)
        self.config_path_display.textChanged.connect(self._on_block1_input_changed)
        self.audio_path_display.textChanged.connect(self._on_block1_input_changed)


    def _on_enable_bpm_changed(self) -> None:
        # 测量工具模式（勾选）
        #   显示启动按钮
        #   显示两个 path_label
        #   隐藏两个 select_button + help
        # 手动模式（取消勾选）
        #   反过来
        is_checked = self.enable_bpm_measurer_check_box.isChecked()
        self.open_bpm_measurer_button.setVisible(is_checked)
        self.manual_mode_hint_label.setVisible(not is_checked)
        self.config_path_label.setVisible(is_checked)
        self.audio_path_label.setVisible(is_checked)
        self.config_select_button.setVisible(not is_checked)
        self.audio_select_button.setVisible(not is_checked)
        self.config_help.setVisible(not is_checked)
        self.audio_help.setVisible(not is_checked)


    def _on_open_bpm_measurer_clicked(self) -> None:
        # 防止重复启动
        if self._bpm_measurer_runner_id: return
        self.enable_bpm_measurer_check_box.setEnabled(False)
        self.open_bpm_measurer_button.setEnabled(False)
        # 构建 notify path
        self._notify_path = PathManage.TEMP_DIR / f"bpm_notify_{generate_uid()}.json"
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
        # 清空旧的 config/audio 路径
        self.config_path_display.setText("")
        self.audio_path_display.setText("")


    def _on_block1_input_changed(self) -> None:
        if self.config_path_display.text().strip():
            if self.audio_path_display.text().strip():
                self._toggle_block2(True)
                return
        self._toggle_block2(False)










    # Block 2
    def _build_block2(self) -> None:
        self.block2_divider = create_divider(_t("ui_block2_divider"))
        self.content_layout.addWidget(self.block2_divider)

        # row1: 谱面确认视频
        self.chart_video_input = MediaInputProbeWidget(
            select_file_button_text=_t("ui_select_chart_video_button"),
            select_file_button_length=170,
        )
        self.content_layout.addWidget(self.chart_video_input)
        
        # row2: 自动对齐按钮 + delay label
        self.auto_align_button = create_stated_button(_t("ui_auto_align_button"))
        self.align_result_label = create_label(bold=True)
        self.create_row(self.auto_align_button, self.align_result_label,
                        add_stretch=True)

        # row3: offset lineedit + 导出最终配置按钮
        offset_label = create_label(_t("ui_offset_label"))
        offset_help = create_help_icon(_t("ui_offset_help"))
        self.offset_line_edit = create_line_edit(length=120, validator='int')
        self.update_timing_config_button = create_stated_button(_t("ui_update_timing_config_button"))
        self.block2_row3 = _create_row(
            offset_label, self.offset_line_edit, offset_help,
            self.update_timing_config_button, add_stretch=True)
        self.content_layout.addWidget(self.block2_row3)

        # connect
        self.chart_video_input.media_loaded.connect(self._on_chart_video_loaded)
        self.auto_align_button.clicked.connect(self._on_auto_align_clicked)
        self.update_timing_config_button.clicked.connect(self._on_update_timing_config_clicked)
    


    def _on_chart_video_loaded(self, error_msg: str) -> None:
        # 如果 error_msg 非空，说明 media_loaded 失败
        if error_msg:
            self.auto_align_button.hide()
            return

        # 显示 auto align 按钮（如果有音频轨道）
        has_audio = self.chart_video_input.selected_file_type in (MediaType.AUDIO, MediaType.VIDEO_WITH_AUDIO)
        if has_audio:
            self
            self.auto_align_button.show()
        else:
            self.auto_align_button.hide()
            show_notify_dialog(_t("dialog_title"), _t("notice_no_audio_in_video"))


    def _on_auto_align_clicked(self) -> None:
        if self._align_runner_id: return # 防止多开
        # reference = 谱面确认视频，target = 测量音频
        reference_path = self.audio_path_display.text().strip()
        target_path = self.chart_video_input.get_path().strip()
        if not reference_path or not target_path:
            show_notify_dialog(_t("dialog_title"), _t("warning_align_missing_files"))
            return
        cmd = build_cmd_head_python_exe(PathManage.AUDIO_ALIGN_WORKER_PATH)
        cmd.extend(["true", reference_path, target_path])
        # 禁用页面所有交互控件，防止运行期间修改输入导致 _toggle_block2 误触发
        self._set_all_buttons_enabled(False)
        # reset
        self.align_result_label.setText("")
        self.offset_line_edit.setText("")
        self.block2_row3.hide()
        # 开始对齐
        self.output_widget.append_text(_t("notice_align_start"))
        result = process_manager_api.start(cmd)
        if not result.is_ok:
            show_notify_dialog(_t("dialog_title"), _t("warning_align_start_failed",
                                                      error=print_op_result(result)))
            self._set_all_buttons_enabled(True)
            return
        self._align_runner_id = result.value
        self.output_widget.bind_current_runner_id(self._align_runner_id)



    def _on_update_timing_config_clicked(self) -> None:
        self._set_all_buttons_enabled(False)
        config_path = self.config_path_display.text().strip()
        offset_text = self.offset_line_edit.text().strip()
        if not config_path or not offset_text:
            show_notify_dialog(_t("dialog_title"), _t("warning_export_prerequisite"))
            self._set_all_buttons_enabled(True)
            return

        try:
            offset_ms = int(offset_text)
        except ValueError:
            show_notify_dialog(_t("dialog_title"), _t("warning_offset_invalid"))
            self._set_all_buttons_enabled(True)
            return

        # 读原始配置
        try:
            raw_text = Path(config_path).read_text(encoding="utf-8")
        except Exception as e:
            show_notify_dialog(_t("dialog_title"), _t("warning_read_config_failed", error=str(e)))
            self._set_all_buttons_enabled(True)
            return

        res = update_global_offset(raw_text, offset_ms)
        if not res.is_ok:
            show_notify_dialog(_t("dialog_title"), _t("warning_merge_failed", error=res.error_msg))
            self._set_all_buttons_enabled(True)
            return

        # 选保存路径
        default_name = Path(config_path).stem + "_aligned.txt"
        out_path, _ = QFileDialog.getSaveFileName(
            self, _t("ui_update_timing_config_button"), default_name,
            f"{_t('ui_config_filter_name')} (*.txt)"
        )
        if not out_path:
            self._set_all_buttons_enabled(True)
            return

        try:
            Path(out_path).write_text(res.value, encoding="utf-8")
        except Exception as e:
            show_notify_dialog(_t("dialog_title"), _t("warning_export_failed", error=str(e)))
            self._set_all_buttons_enabled(True)
            return

        self.output_widget.append_text(_t("notice_export_success", output_path=out_path))
        self._set_all_buttons_enabled(True)






    def _set_all_buttons_enabled(self, enabled: bool) -> None:
        """启用/禁用页面上所有交互控件。"""
        self.enable_bpm_measurer_check_box.setEnabled(enabled)
        self.open_bpm_measurer_button.setEnabled(enabled)
        self.config_select_button.setEnabled(enabled)
        self.audio_select_button.setEnabled(enabled)
        self.config_path_display.setEnabled(enabled)
        self.audio_path_display.setEnabled(enabled)
        self.chart_video_input.setEnabled(enabled)
        self.auto_align_button.setEnabled(enabled)
        self.update_timing_config_button.setEnabled(enabled)
        self.offset_line_edit.setEnabled(enabled)


    def _toggle_block2(self, show: bool) -> None:
        """True = show, False = Hide"""
        if self._align_runner_id: return
        if self._bpm_measurer_runner_id: return
        self.block2_divider.setVisible(show)
        # row 1
        self.chart_video_input.setVisible(show)
        # row 2 默认隐藏，只有在选择谱面确认视频后才显示
        self.auto_align_button.hide()
        self.align_result_label.hide()
        # row3 默认隐藏，只有在自动对齐成功后才显示
        self.block2_row3.hide()
        # 始终 reset
        self.chart_video_input.reset()
        self.offset_line_edit.setText("")
        self.align_result_label.setText("")







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

        # ---- audio_align_worker ----
        if self._align_runner_id:
            if runner_id == self._align_runner_id:
                # 重置状态
                self._align_runner_id = None
                self._set_all_buttons_enabled(True)
                self.auto_align_button.show()
                # 解析 offset
                cancelled = bool(getattr(ended, "cancelled", False))
                exit_code = getattr(ended, "exit_code", None)
                if cancelled or exit_code is None or exit_code != 0:
                    self.output_widget.append_text(_t("warning_align_failed"))
                    return
                offset = parse_offset_ms(self.output_widget.get_recent_lines(8))
                if offset is None:
                    self.output_widget.append_text(_t("warning_parse_offset_failed"))
                    return
                # 成功解析
                self.output_widget.append_text(_t("notice_align_success", offset=offset))
                if offset > 0:
                    label_text = f"  Delay: {offset} ms"
                elif offset < 0:
                    label_text = f"  Trim: {abs(offset)} ms"
                else:
                    label_text = "  Aligned"
                # 显示 label
                self.align_result_label.setText(label_text)
                self.align_result_label.show()
                # 显示 row3
                self.offset_line_edit.setText(str(offset))
                self.block2_row3.show()
                return


    def _parse_bpm_measurer_manifest(self) -> None:
        if not self._notify_path or not self._notify_path.is_file():
            self.output_widget.append_text(_t("warning_manifest_missing"))
            return
        try:
            data = json.loads(self._notify_path.read_text(encoding="utf-8"))
            config_path = data.get("config_path", "")
            audio_path = data.get("audio_path", "")
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
        if audio_path:
            self.audio_path_display.setText(audio_path)
        self.output_widget.append_text(_t("notice_bpm_measurer_success"))
