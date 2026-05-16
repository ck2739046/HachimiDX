import os
import traceback
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from ..base_output_page import BaseOutputPage, _create_row
from ...ui_style import UI_Style
from ...widgets import *

from src.services import process_manager_api
from src.services.pipeline import MediaPipeline
from src.core.tools import show_notify_dialog
from src.core.schemas.op_result import OpResult, ok, err, print_op_result
from src.core.schemas.media_config import MediaType, MediaConfig_Definition
from src.core.schemas.media_config import MediaConfig_Definitions as M_Defs
from src.core.schemas.settings_config import SettingsConfig_Definitions as S_Defs
from src.services.settings_manage import SettingsManage
import i18n



class RunFFmpegPage(BaseOutputPage):

    def setup_content(self):

        self.content_layout = QVBoxLayout(self.content_area)
        self.content_layout.setContentsMargins(10, 10, 10, 10)

        # 需要用到的公共变量
        self.media_input = None

        # video widgets
        self.video_quality_combo_box = None
        self.video_resolution_combo_box = None
        self.video_fps_combo_box = None
        self.video_gop_optimize_check_box = None
        self.video_mute_check_box = None
        self.video_overlay = None
        # audio widgets
        self.audio_format_combo_box = None
        self.audio_bitrate_combo_box = None
        self.audio_sample_rate_combo_box = None
        self.audio_volume_line_edit = None
        self.audio_overlay = None
        # common widgets
        self.common_adjust_start_line_edit = None
        self.common_end_line_edit = None
        self.common_clear_metadata_check_box = None

        self.output_filename_line_edit = None
        self.output_full_path_display = None

        self.taskname_line_edit = None
        self.submit_button = None





        # 第一/第二行: 输入文件选择与信息显示
        file_select_divider = create_divider(i18n.t("app.media_subpages.run_ffmpeg.ui_select_file_divider"))
        self.content_layout.addWidget(file_select_divider)
        
        self.media_input = MediaInputProbeWidget()
        self.media_input.media_loaded.connect(self.on_input_file_selected)
        self.content_layout.addWidget(self.media_input)
        



        self.init_ffmpeg_widgets() # 3-5行: 参数调整区域
        



        # 第三行: video 参数
        video_divider = create_divider(i18n.t("app.media_subpages.run_ffmpeg.ui_video_divider"))
        self.content_layout.addWidget(video_divider)
        # labels
        video_quality_label = create_label(i18n.t("app.media_subpages.run_ffmpeg.ui_video_quality_label"))
        video_resolution_label = create_label(i18n.t("app.media_subpages.run_ffmpeg.ui_video_resolution_label"))
        video_fps_label = create_label(i18n.t("app.media_subpages.run_ffmpeg.ui_video_fps_label"))
        video_gop_optimize_label = create_label(i18n.t("app.media_subpages.run_ffmpeg.ui_video_gop_optimize_label"))
        video_mute_label = create_label(i18n.t("app.media_subpages.run_ffmpeg.ui_video_mute_label"))
        # help icons
        video_quality_help = create_help_icon(i18n.t("app.media_subpages.run_ffmpeg.ui_video_quality_help"))
        video_resolution_help = create_help_icon(i18n.t("app.media_subpages.run_ffmpeg.ui_video_resolution_help"))
        video_fps_help = create_help_icon(i18n.t("app.media_subpages.run_ffmpeg.ui_video_fps_help"))
        video_gop_optimize_help = create_help_icon(i18n.t("app.media_subpages.run_ffmpeg.ui_video_gop_optimize_help"))
        video_mute_help = create_help_icon(i18n.t("app.media_subpages.run_ffmpeg.ui_video_mute_help"))
        # create video panel + row
        video_panel = QWidget()
        video_layout = QVBoxLayout(video_panel)
        video_layout.setContentsMargins(0, 0, 0, 0)
        row = _create_row(video_quality_label, self.video_quality_combo_box, video_quality_help,
                          video_resolution_label, self.video_resolution_combo_box, video_resolution_help,
                          video_fps_label, self.video_fps_combo_box, video_fps_help,
                          video_gop_optimize_label, self.video_gop_optimize_check_box, video_gop_optimize_help,
                          video_mute_label, self.video_mute_check_box, video_mute_help,
                          add_stretch=True)
        video_layout.addWidget(row)
        self.content_layout.addWidget(video_panel)
        self.video_overlay = OverlayWidget(video_panel)
        self.video_overlay.show()
        
        # 第四行: audio 参数
        audio_divider = create_divider(i18n.t("app.media_subpages.run_ffmpeg.ui_audio_divider"))
        self.content_layout.addWidget(audio_divider)
        # labels
        audio_format_label = create_label(i18n.t("app.media_subpages.run_ffmpeg.ui_audio_format_label"))
        audio_bitrate_label = create_label(i18n.t("app.media_subpages.run_ffmpeg.ui_audio_bitrate_label"))
        audio_sample_rate_label = create_label(i18n.t("app.media_subpages.run_ffmpeg.ui_audio_sample_rate_label"))
        audio_volume_label = create_label(i18n.t("app.media_subpages.run_ffmpeg.ui_audio_volume_label"))
        # help icons
        audio_format_help = create_help_icon(i18n.t("app.media_subpages.run_ffmpeg.ui_audio_format_help"))
        audio_bitrate_help = create_help_icon(i18n.t("app.media_subpages.run_ffmpeg.ui_audio_bitrate_help"))
        audio_sample_rate_help = create_help_icon(i18n.t("app.media_subpages.run_ffmpeg.ui_audio_sample_rate_help"))
        audio_volume_help = create_help_icon(i18n.t("app.media_subpages.run_ffmpeg.ui_audio_volume_help"))
        # create audio panel + row
        audio_panel = QWidget()
        audio_layout = QVBoxLayout(audio_panel)
        audio_layout.setContentsMargins(0, 0, 0, 0)
        row = _create_row(audio_format_label, self.audio_format_combo_box, audio_format_help,
                          audio_bitrate_label, self.audio_bitrate_combo_box, audio_bitrate_help,
                          audio_sample_rate_label, self.audio_sample_rate_combo_box, audio_sample_rate_help,
                          audio_volume_label, self.audio_volume_line_edit, audio_volume_help,
                          add_stretch=True)
        audio_layout.addWidget(row)
        self.content_layout.addWidget(audio_panel)
        self.audio_overlay = OverlayWidget(audio_panel)
        self.audio_overlay.show()
        
        # 第五行: common 参数
        common_divider = create_divider(i18n.t("app.media_subpages.run_ffmpeg.ui_common_divider"))
        self.content_layout.addWidget(common_divider)
        # labels
        adjust_start_label = create_label(i18n.t("app.media_subpages.run_ffmpeg.ui_adjust_start_label"))
        trim_end_label = create_label(i18n.t("app.media_subpages.run_ffmpeg.ui_trim_end_label"))
        clear_metadata_label = create_label(i18n.t("app.media_subpages.run_ffmpeg.ui_clear_metadata_label"))
        # help icons
        adjust_start_help = create_help_icon(i18n.t("app.media_subpages.run_ffmpeg.ui_adjust_start_help"))
        trim_end_help = create_help_icon(i18n.t("app.media_subpages.run_ffmpeg.ui_trim_end_help"))
        clear_metadata_help = create_help_icon(i18n.t("app.media_subpages.run_ffmpeg.ui_clear_metadata_help"))
        # create rows
        self.create_row(adjust_start_label, self.common_adjust_start_line_edit, adjust_start_help,
                        trim_end_label, self.common_end_line_edit, trim_end_help,
                        clear_metadata_label, self.common_clear_metadata_check_box, clear_metadata_help,
                        add_stretch=True)




        # 第六行: 输出文件名+完整输出路径显示
        output_filename_label = create_label(i18n.t("app.media_subpages.run_ffmpeg.ui_output_filename_label"))
        self.output_filename_line_edit = create_line_edit(length=280)
        output_filename_help = create_help_icon(i18n.t("app.media_subpages.run_ffmpeg.ui_output_filename_help"))
        self.output_full_path_display = create_path_display()
        self.create_row(output_filename_label,
                        self.output_filename_line_edit,
                        output_filename_help,
                        self.output_full_path_display)




        # 第七行：submit按钮 + taskname输入框
        self.taskname_line_edit = create_line_edit(
            length=200, placeholder=i18n.t("app.media_subpages.run_ffmpeg.ui_taskname_placeholder"))
        self.submit_button = create_stated_button(i18n.t("app.media_subpages.run_ffmpeg.ui_submit_button"), isbig=True)
        self.content_layout.addSpacing(UI_Style.widget_spacing)
        self.create_row(self.submit_button, self.taskname_line_edit, add_stretch=True)



        
        self.audio_format_combo_box.currentIndexChanged.connect(self.update_audio_bitrate_combo_box)
        self.video_mute_check_box.toggled.connect(self.update_media_panel_state)

        self.output_filename_line_edit.textChanged.connect(self.update_output_full_path_display)

        self.submit_button.clicked.connect(self.on_submit_clicked)
        
        # Connect runner output signals to our output widget
        process_manager_api.get_signals().runner_output.connect(self.output_widget.handle_process_output)
        process_manager_api.get_signals().runner_ended.connect(self.output_widget.handle_process_ended)

        self.content_layout.addStretch()  # 添加弹性空间，使内容从顶部开始显示









    def on_input_file_selected(self, err_msg: str) -> None:
        """
        第一行. 文件选择按钮 on clicked hanlder
        选择文件后检测媒体信息的后续逻辑
        """

        if len(err_msg) > 0:
            show_notify_dialog("app.media_subpages.run_ffmpeg", err_msg)

        # reset first
        self.video_mute_check_box.blockSignals(True)
        self.video_mute_check_box.setChecked(False)
        self.video_mute_check_box.blockSignals(False)
        self.video_overlay.show()
        self.audio_overlay.show()
        # 根据媒体类型和 mute 状态刷新启用关系。
        self.update_media_panel_state()

        # 更新音频codec/bitrate可选项
        self.update_audio_format_combo_box()
        # 更新完整输出路径显示
        res = self.update_output_full_path_display(use_empty=True) # reset
        # 因为默认输出文件名输入框是空的，更换文件后要更新一下提示用户
        if res.is_ok:
            final_output_filename = res.value
            self.output_filename_line_edit.setText(final_output_filename)



    def update_media_panel_state(self) -> None:
        """根据 media_type 和 mute 刷新 video/audio 参数区可用状态。"""

        media_type = self.media_input.selected_file_type

        enable_video = media_type in (MediaType.VIDEO_WITH_AUDIO, MediaType.VIDEO_WITHOUT_AUDIO)
        enable_audio = media_type in (MediaType.VIDEO_WITH_AUDIO, MediaType.AUDIO)

        if enable_video and self.video_mute_check_box.isChecked():
            enable_audio = False

        if enable_video:
            self.video_overlay.hide()
        else:
            self.video_overlay.show()

        if enable_audio:
            self.audio_overlay.hide()
        else:
            self.audio_overlay.show()






            


    def init_ffmpeg_widgets(self):

        # video quality combo box
        # 根据编码器覆盖默认值
        encoder_res = SettingsManage.get(S_Defs.ffmpeg_hw_encoder.key)
        default_quality = M_Defs.get_default_video_quality_by_encoder(
            str(encoder_res.value).strip()) if encoder_res.is_ok else ""
        options = M_Defs.video_quality.constraints["options"]
        default_index = options.index(default_quality)
        self.video_quality_combo_box = create_combo_box(
            length=50, items=options, default_index=default_index)

        # video resolution combo box
        self.video_resolution_combo_box = self._create_ffmpeg_widget(
            widget_type="combo_box", param=M_Defs.video_side_resolution, length=102, transfer_fn=self.transfer_res)
        # video fps combo box
        self.video_fps_combo_box = self._create_ffmpeg_widget(
            widget_type="combo_box", param=M_Defs.video_fps, length=80, transfer_fn=self.transfer_fps)
        # gop_optimize check box
        self.video_gop_optimize_check_box = self._create_ffmpeg_widget(
            widget_type="check_box", param=M_Defs.video_gop_optimize)
        # video mute check box
        self.video_mute_check_box = self._create_ffmpeg_widget(
            widget_type="check_box", param=M_Defs.video_mute)
        

        # audio format combo box
        self.audio_format_combo_box = create_combo_box(length=62)

        # audio bitrate combo box
        self.audio_bitrate_combo_box = create_combo_box(length=105)

        # audio sample_rate combo box
        self.audio_sample_rate_combo_box = self._create_ffmpeg_widget(
            widget_type="combo_box", param=M_Defs.audio_sample_rate, length=72)
        
        # audio volume line edit
        min, max, default = (
            M_Defs.audio_volume.constraints["ge"],
            M_Defs.audio_volume.constraints["le"],
            M_Defs.audio_volume.default)
        self.audio_volume_line_edit = create_line_edit(
            default_text=str(default), placeholder=f"{min}~{max}", length=60, validator='int')


        # common adjust_start line edit (正数=pad_start, 负数=trim_start)
        self.common_adjust_start_line_edit = create_line_edit(
            length=70, validator='float')
        # common end line edit
        self.common_end_line_edit = create_line_edit(
            length=70, validator='float')
        # common clear_metadata check box
        self.common_clear_metadata_check_box = self._create_ffmpeg_widget(
            widget_type="check_box", param=M_Defs.clear_metadata)
        

    def _create_ffmpeg_widget(self,
                           widget_type: str,
                           param: MediaConfig_Definition,
                           length: int = None,
                           transfer_fn = None):

        if widget_type == "combo_box":
            options = param.constraints["options"]
            default = param.default
            default_index = options.index(default)
            if transfer_fn:
                options = transfer_fn(options)
                default = transfer_fn(default)
            combo_box = create_combo_box(length = length,
                                         items = options,
                                         default_index = default_index)
            return combo_box
        
        elif widget_type == "check_box":
            default = param.default
            check_box = create_check_box(default_checked = default)
            return check_box
        
        return None # 不应该发生
        






    def update_audio_format_combo_box(self) -> None:
        """根据媒体类型，更新音频格式"""

        media_type = self.media_input.selected_file_type
        self.audio_format_combo_box.blockSignals(True)
        self.audio_format_combo_box.clear()

        result = M_Defs.get_audio_format_by_media_type(media_type)
        if not result.is_ok:
            show_notify_dialog("app.media_subpages.run_ffmpeg", result.error_msg)
            self.audio_format_combo_box.blockSignals(False)
            return
        
        default, options = result.value
        self.audio_format_combo_box.addItems(options)
        self.audio_format_combo_box.setCurrentText(default)
        self.update_audio_bitrate_combo_box() # 手动触发码率更新
        self.audio_format_combo_box.blockSignals(False)


    def update_audio_bitrate_combo_box(self) -> None:
        """根据音频格式，更新音频码率"""

        audio_format = self.audio_format_combo_box.currentText()
        self.audio_bitrate_combo_box.blockSignals(True)
        self.audio_bitrate_combo_box.clear()

        result = M_Defs.get_audio_bitrate_by_audio_format(audio_format)
        if not result.is_ok:
            show_notify_dialog("app.media_subpages.run_ffmpeg", result.error_msg)
            self.audio_bitrate_combo_box.blockSignals(False)
            return
        
        default, options = result.value
        self.audio_bitrate_combo_box.addItems(options)
        self.audio_bitrate_combo_box.setCurrentText(default)
        self.audio_bitrate_combo_box.blockSignals(False)


    def update_output_full_path_display(self, use_empty: bool = False) -> OpResult[str]:
        """
        根据输出文件名，更新完整输出路径显示
        返回内容：最终输出文件名（不带路径）
        """

        if use_empty is True:
            output_filename = ""
        else:
            output_filename = self.output_filename_line_edit.text().strip()

        result = M_Defs.build_full_output_path(
            input_path = self.media_input.get_path(),
            output_filename = output_filename,
            audio_format = self.audio_format_combo_box.currentText()
        )
        if not result.is_ok:
            show_notify_dialog("app.media_subpages.run_ffmpeg", result.error_msg)
            self.output_full_path_display.setText("")
            return err(result.error_msg, inner = result)
        
        final_output_path, final_output_filename = result.value
        self.output_full_path_display.setText(final_output_path)
        return ok(final_output_filename)


    def transfer_res(self, input_data):

        if str(input_data) == '0':
            return "original"
        if str(input_data) == "original":
            return 0
        if "×" in str(input_data):
            return str(input_data).split("×")[0]
        
        if isinstance(input_data, list):
            output_data = []
            for text in input_data:
                if str(text) == '0':
                    output_data.append("original")
                else:
                    output_data.append(f"{text}×{text}")
            
            return output_data
        
        return input_data
    

    def transfer_fps(self, input_data):

        if str(input_data) == '0':
            return "original"
        if str(input_data) == "original":
            return 0
        
        if isinstance(input_data, list):
            output_data = []
            for text in input_data:
                if str(text) == '0':
                    output_data.append("original")
                else:
                    output_data.append(str(text))

            return output_data
        
        return input_data
                





    def _resolve_adjust_start_pad(self) -> float | None:
        """正数 → pad_start, 其他 → None"""
        v = self.common_adjust_start_line_edit.text().strip()
        try:
            f = float(v)
            return round(f, 3) if f > 0 else None
        except Exception:
            return None

    def _resolve_adjust_start_trim(self) -> float | None:
        """负数 → start (绝对值), 其他 → None"""
        v = self.common_adjust_start_line_edit.text().strip()
        try:
            f = float(v)
            return round(abs(f), 3) if f < 0 else None
        except Exception:
            return None

    def on_submit_clicked(self) -> None:
        """
        submit button on clicked handler
        收集数据，提交任务到调度器
        """

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

            # 手动触发完整输出路径更新
            result = self.update_output_full_path_display()
            if not result.is_ok:
                return

            raw_data: dict = {
                # common
                M_Defs.media_type.key: self.media_input.selected_file_type,
                M_Defs.input_path.key: self.media_input.get_path() or "",
                M_Defs.output_path.key: self.output_full_path_display.text().strip() or "",
                # video stream
                M_Defs.video_quality.key: try_int(self.video_quality_combo_box.currentText().strip()),
                M_Defs.video_side_resolution.key: self.transfer_res(self.video_resolution_combo_box.currentText().strip()),
                M_Defs.video_fps.key: self.transfer_fps(self.video_fps_combo_box.currentText().strip()),
                M_Defs.video_gop_optimize.key: self.video_gop_optimize_check_box.isChecked(),
                M_Defs.video_mute.key: self.video_mute_check_box.isChecked(),
                # audio stream
                M_Defs.audio_format.key: self.audio_format_combo_box.currentText().strip(),
                M_Defs.audio_bitrate.key: self.audio_bitrate_combo_box.currentText().strip(),
                M_Defs.audio_sample_rate.key: try_int(self.audio_sample_rate_combo_box.currentText().strip()),
                M_Defs.audio_volume.key: try_int(self.audio_volume_line_edit.text().strip()),
                # common
                M_Defs.clear_metadata.key: self.common_clear_metadata_check_box.isChecked(),
                M_Defs.duration.key: try_float(self.media_input.selected_file_duration),
                M_Defs.pad_start.key: self._resolve_adjust_start_pad(),
                M_Defs.start.key: self._resolve_adjust_start_trim(),
                M_Defs.end.key: try_float(self.common_end_line_edit.text().strip()),
            }

            task_name = self.taskname_line_edit.text().strip()
            result = MediaPipeline.submit_task(raw_data, task_name)
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
            show_notify_dialog("app.media_subpages.run_ffmpeg",
                i18n.t("app.media_subpages.run_ffmpeg.warning_unexpected_submit_error", error=traceback.format_exc()))
        finally:
            self.submit_button.setEnabled(True)
