import traceback
from pathlib import Path
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from .base_output_page import BaseOutputPage, _create_row
from ..ui_style import UI_Style
from ..widgets import *
from src.services import process_manager_api
from src.services.pipeline import AutoConvertPipeline
from src.core.tools import show_confirm_dialog, show_notify_dialog
from src.core.schemas.op_result import OpResult, ok, err, print_op_result
from src.core.schemas.auto_convert_config import AutoConvertConfig_Definitions as AC_Defs
import i18n

I18N_Prefix = "app.auto_convert_page"


class AutoConvertPage(BaseOutputPage):

    def setup_content(self):

        self.content_layout = QVBoxLayout(self.content_area)
        self.content_layout.setContentsMargins(10, 10, 10, 10)

        # overlay
        # 覆盖在对应模块上，提示用户当前模块是否已被禁用
        self.overlay_standardize = None
        self.overlay_detect = None
        self.overlay_analyze = None

        # file selection panel
        self.chart_confirm_video_input = None
        self.select_output_dir_row = None # 包含button + display，std模块禁用时显示
        self.selected_output_dir_display = None # 由row控制

        # standardize panel
        self.song_name_line_edit = None
        self.video_mode_combo_box = None
        self.need_screen_rectification_check_box = None
        self.start_sec_line_edit = None
        self.end_sec_line_edit = None
        self.video_range_visualizer = None
        # target_res 暂时不设置

        # detect panel
        self.enable_reid_check_box = None
        self.skip_detect_label = None # adv 由row控制
        self.skip_detect_check_box = None # adv 由row控制
        self.skip_detect_help = None # adv 由row控制
        self.skip_cls_label = None # adv 由row控制
        self.skip_cls_check_box = None # adv 由row控制
        self.skip_cls_help = None # adv 由row控制
        self.skip_export_label = None # adv 由row控制
        self.skip_export_tracked_check_box = None # adv 由row控制
        self.skip_export_help = None # adv 由row控制

        # analyze panel
        self.bpm_line_edit = None
        self.is_big_touch_check_box = None
        self.chart_lv_combo_box = None
        self.base_denominator_combo_box = None
        self.duration_denominator_combo_box = None

        # common panel
        self.enable_modules_row = None # adv 包含以下三个勾选框
        self.enable_standardize_check_box = None # adv 由row控制
        self.enable_detect_check_box = None # adv 由row控制
        self.enable_analyze_check_box = None # adv 由row控制
        self.taskname_line_edit = None
        self.submit_button = None

        # advance mode
        self.advanced_mode_check_box = None



        # ------------------- UI builders -------------------

        self._build_file_selection_panel()
        self._build_standardize_panel()
        self._build_detect_panel()
        self._build_analyze_panel()
        self._build_common_panel()
        self._build_advanced_mode_panel()


        # ------------------- 业务事件绑定 -------------------
        
        process_manager_api.get_signals().runner_output.connect(self.output_widget.handle_process_output)
        process_manager_api.get_signals().runner_ended.connect(self.output_widget.handle_process_ended)

        # 初始化显示状态
        self._update_panels_visibility()
        # 默认关闭高级模式，隐藏相关设置
        self.swtich_advanced_mode()

    








    def _build_file_selection_panel(self):

        # divider
        file_selection_divider = create_divider(i18n.t(f"{I18N_Prefix}.ui_select_file_divider"))
        self.content_layout.addWidget(file_selection_divider)

        # select chart confirm
        self.chart_confirm_video_input = MediaInputProbeWidget(
            select_file_button_text=i18n.t(f"{I18N_Prefix}.ui_select_chart_confirm_video_button"),
            select_file_button_length=170)
        self.content_layout.addWidget(self.chart_confirm_video_input)

        # select output dir
        (select_output_dir_button,
         self.selected_output_dir_display,
         select_output_dir_help
        ) = create_directory_selection_row(
            button_text=i18n.t(f"{I18N_Prefix}.ui_selected_output_dir_button"),
            help_text=i18n.t(f"{I18N_Prefix}.ui_selected_output_dir_help"),
            on_button_clicked_handler=lambda path: self._sync_taskname_from_name(Path(path).name)
        )
        # 此处手动创建是要保存 row 引用，以便后续控制 显示/隐藏
        self.select_output_dir_row = self.create_row(
            select_output_dir_button,
            select_output_dir_help,
            self.selected_output_dir_display
        )

        # 连接信号
        self.chart_confirm_video_input.media_loaded.connect(self.on_std_input_selected)



    def on_std_input_selected(self, error_msg: str) -> None:
        # Show error in popup window
        if len(error_msg) > 0:
            show_notify_dialog("app.auto_convert", error_msg)
            return
        # 更新 Song Name
        self.song_name_line_edit.setText(Path(self.chart_confirm_video_input.get_path()).stem)
        # 同步 Task Name
        self._sync_taskname_from_name(Path(self.chart_confirm_video_input.get_path()).stem)
        # 更新视频范围可视化器
        self._update_video_range_visualizer()

    def _sync_taskname_from_name(self, name: str) -> None:
        """更新 task name 输入框内容为给定的名称（文件名/文件夹名）。"""
        if self.taskname_line_edit is None:
            return
        self.taskname_line_edit.setText(name)





    




    def _build_standardize_panel(self):

        standardize_panel = QWidget()
        layout = QVBoxLayout(standardize_panel)
        layout.setContentsMargins(0, 0, 0, 0)

        # divider
        standardize_divider = create_divider(i18n.t(f"{I18N_Prefix}.ui_standardize_divider"))
        layout.addWidget(standardize_divider)
        
        # Row 1
        song_name_label = create_label(i18n.t(f"{I18N_Prefix}.ui_song_name_label"))
        self.song_name_line_edit = create_line_edit()

        row = _create_row(song_name_label, self.song_name_line_edit)
        layout.addWidget(row)

        # Row 2
        video_mode_label = create_label(i18n.t(f"{I18N_Prefix}.ui_video_mode_label"))
        self.video_mode_combo_box = self._create_combobox_with_options(AC_Defs.video_mode, length=125)
        video_mode_help = create_help_icon(i18n.t(f"{I18N_Prefix}.ui_video_mode_help"))

        need_screen_rectification_label = create_label(i18n.t(f"{I18N_Prefix}.ui_need_screen_rectification_label"))
        self.need_screen_rectification_check_box = create_check_box(AC_Defs.need_screen_rectification.default)
        need_screen_rectification_help = create_help_icon(i18n.t(f"{I18N_Prefix}.ui_need_screen_rectification_help"))

        row = _create_row(video_mode_label,
                          self.video_mode_combo_box,
                          video_mode_help,

                          need_screen_rectification_label,
                          self.need_screen_rectification_check_box,
                          need_screen_rectification_help,

                          add_stretch=True)
        layout.addWidget(row)

        # Row 3
        start_sec_label = create_label(i18n.t(f"{I18N_Prefix}.ui_start_sec_label"))
        self.start_sec_line_edit = create_line_edit(length=60, validator='float')
        start_sec_help = create_help_icon(i18n.t(f"{I18N_Prefix}.ui_start_sec_help"))

        trim_end_label = create_label(i18n.t("app.media_subpages.run_ffmpeg.ui_trim_end_label"))
        self.end_sec_line_edit = create_line_edit(length=60, validator='float')
        trim_end_help = create_help_icon(i18n.t("app.media_subpages.run_ffmpeg.ui_trim_end_help"))

        self.video_range_visualizer = RangeVisualizer()

        row = _create_row(start_sec_label,
                          self.start_sec_line_edit,
                          start_sec_help,

                          trim_end_label,
                          self.end_sec_line_edit,
                          trim_end_help,
                          
                          self.video_range_visualizer,
                          add_stretch=True)
        layout.addWidget(row)

        self.content_layout.addWidget(standardize_panel)
        self.overlay_standardize = OverlayWidget(standardize_panel)

        # 连接输入框信号到可视化器更新
        self.start_sec_line_edit.textChanged.connect(self._update_video_range_visualizer)
        self.end_sec_line_edit.textChanged.connect(self._update_video_range_visualizer)

        

    def _update_video_range_visualizer(self):

        duration, start_sec, end_sec = None, None, None

        try: duration = float(self.chart_confirm_video_input.selected_file_duration)
        except Exception: duration = None
        try: start_sec = float(self.start_sec_line_edit.text().strip())
        except Exception: start_sec = None
        try: end_sec = float(self.end_sec_line_edit.text().strip())
        except Exception: end_sec = None

        self.video_range_visualizer.update_val(duration, start_sec, end_sec)
        





    








    def _build_detect_panel(self):

        detect_panel = QWidget()
        layout = QVBoxLayout(detect_panel)
        layout.setContentsMargins(0, 0, 0, 0)

        # divider
        detect_divider = create_divider(i18n.t(f"{I18N_Prefix}.ui_detect_divider"))
        layout.addWidget(detect_divider)

        # Settings
        enable_reid_label = create_label(i18n.t(f"{I18N_Prefix}.ui_enable_reid_label"))
        self.enable_reid_check_box = create_check_box(AC_Defs.enable_reid.default)
        enable_reid_help = create_help_icon(i18n.t(f"{I18N_Prefix}.ui_enable_reid_help"))

        self.skip_detect_label = create_label(i18n.t(f"{I18N_Prefix}.ui_skip_detect_label"))
        self.skip_detect_check_box = create_check_box(AC_Defs.skip_detect.default)
        self.skip_detect_help = create_help_icon(i18n.t(f"{I18N_Prefix}.ui_skip_detect_help"))

        self.skip_cls_label = create_label(i18n.t(f"{I18N_Prefix}.ui_skip_cls_label"))
        self.skip_cls_check_box = create_check_box(AC_Defs.skip_cls.default)
        self.skip_cls_help = create_help_icon(i18n.t(f"{I18N_Prefix}.ui_skip_cls_help"))

        self.skip_export_label = create_label(i18n.t(f"{I18N_Prefix}.ui_skip_export_tracked_label"))
        self.skip_export_tracked_check_box = create_check_box(AC_Defs.skip_export_tracked_video.default)
        self.skip_export_help = create_help_icon(i18n.t(f"{I18N_Prefix}.ui_skip_export_tracked_help"))

        # 此处手动创建是要保存 row 引用，以便后续控制 显示/隐藏
        row = _create_row(enable_reid_label, self.enable_reid_check_box, enable_reid_help,
                          self.skip_detect_label, self.skip_detect_check_box, self.skip_detect_help,
                          self.skip_cls_label, self.skip_cls_check_box, self.skip_cls_help,
                          self.skip_export_label, self.skip_export_tracked_check_box, self.skip_export_help,
                          add_stretch=True)
        layout.addWidget(row)

        self.content_layout.addWidget(detect_panel)
        self.overlay_detect = OverlayWidget(detect_panel)













    def _build_analyze_panel(self):

        analyze_panel = QWidget()
        layout = QVBoxLayout(analyze_panel)
        layout.setContentsMargins(0, 0, 0, 0)

        # divider
        analyze_divider = create_divider(i18n.t(f"{I18N_Prefix}.ui_analyze_divider"))
        layout.addWidget(analyze_divider)

        # Row 1
        bpm_label = create_label(i18n.t(f"{I18N_Prefix}.ui_bpm_label"))
        self.bpm_line_edit = create_line_edit(length=70, validator='float')
        bpm_help = create_help_icon(i18n.t(f"{I18N_Prefix}.ui_bpm_help"))

        is_big_touch_label = create_label(i18n.t(f"{I18N_Prefix}.ui_is_big_touch_label"))
        self.is_big_touch_check_box = create_check_box(AC_Defs.is_big_touch.default)
        is_big_touch_help = create_help_icon(i18n.t(f"{I18N_Prefix}.ui_is_big_touch_help"))
        
        row = _create_row(bpm_label, self.bpm_line_edit, bpm_help,
                          is_big_touch_label, self.is_big_touch_check_box, is_big_touch_help,
                          add_stretch=True)
        layout.addWidget(row)

        # Row 2
        chart_lv_label = create_label(i18n.t(f"{I18N_Prefix}.ui_chart_lv_label"))
        self.chart_lv_combo_box = self._create_combobox_with_options(AC_Defs.chart_lv, length=45)
        chart_lv_help = create_help_icon(i18n.t(f"{I18N_Prefix}.ui_chart_lv_help"))

        bd_label = create_label(i18n.t(f"{I18N_Prefix}.ui_base_denominator_label"))
        self.base_denominator_combo_box = self._create_combobox_with_options(AC_Defs.base_denominator, length=75, transfer_fn=self._transfer_base_denominator)
        bd_help = create_help_icon(i18n.t(f"{I18N_Prefix}.ui_base_denominator_help"))

        dd_label = create_label(i18n.t(f"{I18N_Prefix}.ui_duration_denominator_label"))
        self.duration_denominator_combo_box = self._create_combobox_with_options(AC_Defs.duration_denominator, length=45)
        dd_help = create_help_icon(i18n.t(f"{I18N_Prefix}.ui_duration_denominator_help"))

        row = _create_row(chart_lv_label, self.chart_lv_combo_box, chart_lv_help,
                          bd_label, self.base_denominator_combo_box, bd_help,
                          dd_label, self.duration_denominator_combo_box, dd_help,
                          add_stretch=True)
        layout.addWidget(row)

        self.content_layout.addWidget(analyze_panel)
        self.overlay_analyze = OverlayWidget(analyze_panel)

        # 连接信号
        self.chart_lv_combo_box.currentTextChanged.connect(self._on_chart_lv_changed)







    




    def _build_common_panel(self):

        # divider
        common_divider = create_divider(i18n.t(f"{I18N_Prefix}.ui_common_divider"))
        self.content_layout.addWidget(common_divider)

        # Row 1: Enable Modules
        enable_standardize_label = create_label(i18n.t(f"{I18N_Prefix}.ui_enable_standardize_label"))
        self.enable_standardize_check_box = create_check_box(default_checked=AC_Defs.is_standardize_enabled.default)
        enable_standardize_help = create_help_icon(i18n.t(f"{I18N_Prefix}.ui_enable_standardize_help"))
        
        enable_detect_label = create_label(i18n.t(f"{I18N_Prefix}.ui_enable_detect_label"))
        self.enable_detect_check_box = create_check_box(default_checked=AC_Defs.is_detect_enabled.default)
        enable_detect_help = create_help_icon(i18n.t(f"{I18N_Prefix}.ui_enable_detect_help"))

        enable_analyze_label = create_label(i18n.t(f"{I18N_Prefix}.ui_enable_analyze_label"))
        self.enable_analyze_check_box = create_check_box(default_checked=AC_Defs.is_analyze_enabled.default)
        enable_analyze_help = create_help_icon(i18n.t(f"{I18N_Prefix}.ui_enable_analyze_help"))

        # 此处手动创建是要保存 row 引用，以便后续控制 显示/隐藏
        self.enable_modules_row = self.create_row(
            enable_standardize_label, self.enable_standardize_check_box, enable_standardize_help,
            enable_detect_label, self.enable_detect_check_box, enable_detect_help,
            enable_analyze_label, self.enable_analyze_check_box, enable_analyze_help,
            add_stretch=True
        )

        # Row 2: Submit Button + Task Name Input
        self.content_layout.addSpacing(UI_Style.widget_spacing)
        self.taskname_line_edit = create_line_edit(
            length=200, placeholder=i18n.t("app.media_subpages.run_ffmpeg.ui_taskname_placeholder"))
        self.submit_button = create_stated_button(i18n.t("app.media_subpages.run_ffmpeg.ui_submit_button"), isbig=True)
        self.create_row(self.submit_button, self.taskname_line_edit, add_stretch=True)

        # 连接信号
        self.enable_standardize_check_box.stateChanged.connect(self._update_panels_visibility)
        self.enable_detect_check_box.stateChanged.connect(self._update_panels_visibility)
        self.enable_analyze_check_box.stateChanged.connect(self._update_panels_visibility)
        self.submit_button.clicked.connect(self.on_submit_clicked)



    def _update_panels_visibility(self):

        std_enabled = self.enable_standardize_check_box.isChecked()
        det_enabled = self.enable_detect_check_box.isChecked()
        ana_enabled = self.enable_analyze_check_box.isChecked()

        self.overlay_standardize.setVisible(not std_enabled)
        self.overlay_detect.setVisible(not det_enabled)
        self.overlay_analyze.setVisible(not ana_enabled)

        self.select_output_dir_row.setVisible(not std_enabled)
        self.chart_confirm_video_input.setVisible(std_enabled)

















    def _build_advanced_mode_panel(self):
        # 先 add stretch 让本模块始终在最底部
        self.content_layout.addStretch()

        advanced_label = create_label(i18n.t(f"{I18N_Prefix}.ui_advanced_mode_label"))
        self.advanced_mode_check_box = create_check_box(False)
        row = _create_row(advanced_label, self.advanced_mode_check_box)
        self.content_layout.addWidget(row, alignment=Qt.AlignmentFlag.AlignRight)

        self.advanced_mode_check_box.stateChanged.connect(self.swtich_advanced_mode)



    def swtich_advanced_mode(self):

        is_advanced_mode = self.advanced_mode_check_box.isChecked()

        # toggle advanced mode settings visibility
        # detect
        self.skip_detect_label.setVisible(is_advanced_mode)
        self.skip_detect_check_box.setVisible(is_advanced_mode)
        self.skip_detect_help.setVisible(is_advanced_mode)
        self.skip_cls_label.setVisible(is_advanced_mode)
        self.skip_cls_check_box.setVisible(is_advanced_mode)
        self.skip_cls_help.setVisible(is_advanced_mode)
        self.skip_export_label.setVisible(is_advanced_mode)
        self.skip_export_tracked_check_box.setVisible(is_advanced_mode)
        self.skip_export_help.setVisible(is_advanced_mode)
        # general
        self.enable_modules_row.setVisible(is_advanced_mode)

        # reset checkbox
        if not is_advanced_mode:
            # detect
            self.skip_detect_check_box.setChecked(AC_Defs.skip_detect.default)
            self.skip_cls_check_box.setChecked(AC_Defs.skip_cls.default)
            self.skip_export_tracked_check_box.setChecked(AC_Defs.skip_export_tracked_video.default)
            # general
            self.enable_standardize_check_box.setChecked(AC_Defs.is_standardize_enabled.default)
            self.enable_detect_check_box.setChecked(AC_Defs.is_detect_enabled.default)
            self.enable_analyze_check_box.setChecked(AC_Defs.is_analyze_enabled.default)

        





    





    def on_submit_clicked(self) -> None:

        def try_int(value) -> int | None:
            if value is None: return None
            try: return int(round(float(value)))
            except: return None
            
        def try_float(value) -> float | None:
            if value is None: return None
            try: return float(value)
            except: return None

        try:
            self.submit_button.setEnabled(False)

            raw_data = {
                # common
                AC_Defs.is_standardize_enabled.key: self.enable_standardize_check_box.isChecked(),
                AC_Defs.is_detect_enabled.key:      self.enable_detect_check_box.isChecked(),
                AC_Defs.is_analyze_enabled.key:     self.enable_analyze_check_box.isChecked(),
            }

            if raw_data[AC_Defs.is_standardize_enabled.key]:
                raw_data.update({
                    AC_Defs.standardize_input_video_path.key: self.chart_confirm_video_input.get_path() or None,
                    AC_Defs.song_name.key: self.song_name_line_edit.text().strip() or None,
                    AC_Defs.video_mode.key: self.video_mode_combo_box.currentText().strip(),
                    AC_Defs.media_type.key: self.chart_confirm_video_input.selected_file_type,
                    AC_Defs.duration.key: try_float(self.chart_confirm_video_input.selected_file_duration),
                    AC_Defs.start_sec.key: try_float(self.start_sec_line_edit.text().strip()),
                    AC_Defs.end_sec.key: try_float(self.end_sec_line_edit.text().strip()),
                    AC_Defs.need_screen_rectification.key: self.need_screen_rectification_check_box.isChecked(),
                    AC_Defs.target_res.key: 1080, # 暂时不修改
                })
            else:
                raw_data.update({
                    AC_Defs.selected_folder.key: self.selected_output_dir_display.text().strip() or None
                })

            if raw_data[AC_Defs.is_detect_enabled.key]:
                raw_data.update({
                    AC_Defs.skip_detect.key: self.skip_detect_check_box.isChecked(),
                    AC_Defs.skip_cls.key: self.skip_cls_check_box.isChecked(),
                    AC_Defs.skip_export_tracked_video.key: self.skip_export_tracked_check_box.isChecked(),
                    AC_Defs.enable_reid.key: self.enable_reid_check_box.isChecked(),
                })
                
            if raw_data[AC_Defs.is_analyze_enabled.key]:
                raw_data.update({
                    AC_Defs.bpm.key: try_float(self.bpm_line_edit.text().strip()),
                    AC_Defs.is_big_touch.key: self.is_big_touch_check_box.isChecked(),
                    AC_Defs.chart_lv.key: try_int(self.chart_lv_combo_box.currentText()),
                    AC_Defs.base_denominator.key: try_int(self._transfer_base_denominator(self.base_denominator_combo_box.currentText())),
                    AC_Defs.duration_denominator.key: try_int(self.duration_denominator_combo_box.currentText()),
                })

            # 如果启用音符分析模组，并且处于非高级模式下
            # 高等级谱面 + 低帧率视频 弹警告
            if raw_data[AC_Defs.is_analyze_enabled.key]:
                if not self.advanced_mode_check_box.isChecked():
                    chart_lv = try_int(self.chart_lv_combo_box.currentText())
                    fps = try_float(self.chart_confirm_video_input.selected_video_fps)
                    if chart_lv is not None and fps is not None:
                        if chart_lv >= 5 and fps < 58:
                            title = i18n.t(f"{I18N_Prefix}.ui_low_fps_warning_title")
                            text = i18n.t(f"{I18N_Prefix}.ui_low_fps_warning_text", level=chart_lv, fps=round(fps, 1))
                            if not show_confirm_dialog(title, text):
                                return

            task_name = self.taskname_line_edit.text().strip()
            result = AutoConvertPipeline.submit_task(raw_data, task_name)
            if not result.is_ok:
                reason = print_op_result(result) # 保底
                # 尝试直接访问普通 pydantic 错误
                try:
                    root_result = result.inner.inner
                    if "validate_pydantic()" in root_result.source.lower() and \
                       "pydantic validation failed" in root_result.error_msg.lower():
                        reason = root_result.error_raw
                except Exception:
                    pass
                error_msg = i18n.t("app.media_subpages.run_ffmpeg.warning_task_submit_failed", error = reason)
                show_notify_dialog("app.media_subpages.run_ffmpeg", error_msg)
                return

            runner_id, cmd_list = result.value
            self.output_widget.bind_current_runner_id(runner_id)
            
            # 显示悬浮通知
            message = i18n.t("app.media_subpages.run_ffmpeg.notice_task_submit_success", task_id=runner_id)
            create_floating_notification(message, self.window())

        except Exception as e:
            show_notify_dialog("app.auto_convert_page",
                i18n.t("app.media_subpages.run_ffmpeg.warning_unexpected_submit_error", error=traceback.format_exc()))
        finally:
            self.submit_button.setEnabled(True)



    def _on_chart_lv_changed(self, text: str):
        try: chart_lv = int(text)
        except: return
        preset = AC_Defs.CHART_LV_PRESETS.get(chart_lv, None)
        if preset is None: return

        # is_big_touch
        self.is_big_touch_check_box.setChecked(preset[AC_Defs.is_big_touch.key])

        # base_denominator — combo 显示 "16 (12)" 格式，用 transfer 函数反向翻译后匹配
        bd_value: int = preset[AC_Defs.base_denominator.key]
        for i in range(self.base_denominator_combo_box.count()):
            item_text = self.base_denominator_combo_box.itemText(i)
            raw = self._transfer_base_denominator(item_text)
            if int(raw) == bd_value:
                self.base_denominator_combo_box.setCurrentIndex(i)
                break

        # duration_denominator — 直接字符串匹配
        dd_value: int = preset[AC_Defs.duration_denominator.key]
        for i in range(self.duration_denominator_combo_box.count()):
            if int(self.duration_denominator_combo_box.itemText(i)) == dd_value:
                self.duration_denominator_combo_box.setCurrentIndex(i)
                break



    def _create_combobox_with_options(self, param, length = None, transfer_fn = None):
        options = param.constraints["options"]
        default_val = param.default
        default_index = options.index(default_val)
        if transfer_fn:
            options = transfer_fn(options)
        return create_combo_box(length=length, items=options, default_index=default_index)



    def _transfer_base_denominator(self, input):

        if "(12)" in str(input):
            return input.replace(" (12)", "").strip()
        
        if isinstance(input, list):
            output = []
            for item in input:
                if int(item) >= 12:
                    output.append(f"{item} (12)")
                else:
                    output.append(item)
            return output

        return input
