from typing import Optional, Literal, Any
import os
from pathlib import Path
from pydantic import BaseModel, Field, FilePath, model_validator

from .auto_rechart_config import AutoRechartConfig_Definitions as AC_Defs
from src.core.tools import validate_windows_filename
from src.core.measure_bpm.parse_config import parse_config
from .media_config import MediaType
import i18n



class AutoRechartModel(BaseModel):
    """
    AutoRechart configuration model for validation and processing.
    All fields have defaults as defined in auto_rechart_config.py.
    """


    # Common group

    is_standardize_enabled: Optional[bool] = Field(default=AC_Defs.is_standardize_enabled.default)
    is_detect_enabled: Optional[bool] = Field(default=AC_Defs.is_detect_enabled.default)
    is_analyze_enabled: Optional[bool] = Field(default=AC_Defs.is_analyze_enabled.default)


    # Standardize group

    standardize_input_video_path: Optional[FilePath] = Field(default=None) # 必需参数 没有默认值
    
    video_mode: Optional[str] = Field(default=AC_Defs.video_mode.default)

    duration: Optional[float] = Field(default=None) # 必需参数 没有默认值

    media_type: Optional[MediaType] = Field(default=None) # 必需参数 没有默认值

    start_sec: Optional[float] = Field(default=AC_Defs.start_sec.default, ge=AC_Defs.start_sec.constraints["ge"])

    end_sec: Optional[float] = Field(default=AC_Defs.end_sec.default)

    need_screen_rectification: Optional[bool] = Field(default=AC_Defs.need_screen_rectification.default)

    target_res: Optional[int] = Field(default=AC_Defs.target_res.default, gt=AC_Defs.target_res.constraints["gt"])

    ui_scale: Optional[int] = Field(
        default=AC_Defs.ui_scale.default,
        ge=AC_Defs.ui_scale.constraints["ge"],
        le=AC_Defs.ui_scale.constraints["le"],
    )




    # detect group

    skip_detect: Optional[bool] = Field(default=AC_Defs.skip_detect.default)

    skip_cls: Optional[bool] = Field(default=AC_Defs.skip_cls.default)

    skip_export_tracked_video: Optional[bool] = Field(default=AC_Defs.skip_export_tracked_video.default)

    # enable_reid: Optional[bool] = Field(default=AC_Defs.enable_reid.default)




    # analyze group

    bpm: Optional[float] = Field(default=None, gt=AC_Defs.bpm.constraints["gt"])

    # bpm_config：前端传「bpm 配置文件原路径」（FilePath 自动校验存在）；
    # validate_bpm_source 内调 parse_config 解析后，会被替换为「notify JSON 路径」，
    # 最终由 build_cmd 作为 --bpm_config 参数发送给 worker。
    bpm_config: Optional[FilePath] = Field(default=None)

    is_big_touch: Optional[bool] = Field(default=AC_Defs.is_big_touch.default)

    chart_lv: Optional[int] = Field(default=AC_Defs.chart_lv.default)

    base_denominator: Optional[int] = Field(default=AC_Defs.base_denominator.default)

    duration_denominator: Optional[int] = Field(default=AC_Defs.duration_denominator.default)





    # other
    
    song_name: Optional[str] = Field(default=AC_Defs.song_name.default)

    selected_folder: Optional[Path] = Field(default=None) # 必需参数 没有默认值




    # model validators

    # common

    # 至少要启用一个模块
    @model_validator(mode='after')
    def validate_at_least_one_module_enabled(self):
        if not (self.is_standardize_enabled or self.is_detect_enabled or self.is_analyze_enabled):
            raise ValueError(i18n.t("auto_rechart_model.error_at_least_one_module"))
        return self






    # standardize

    # 检查 input_video_path & song_name
    @model_validator(mode='after')
    def validate_video_path_and_name(self):
        
        if not self.is_standardize_enabled:
            return self
        
        # 验证 path 合法性
        input_path: Path = self.standardize_input_video_path
        if input_path is None:
            raise ValueError(i18n.t("auto_rechart_model.error_video_not_selected"))
        if not input_path.exists() or not input_path.is_file():
            raise ValueError(i18n.t("auto_rechart_model.error_video_not_exist", path=str(input_path)))
        if not os.access(input_path.parent, os.R_OK | os.W_OK):
            raise ValueError(i18n.t("auto_rechart_model.error_video_dir_not_accessible", path=str(input_path.parent)))
        
        # 验证 song_name 合法性
        if self.song_name is not None:
            res = validate_windows_filename(self.song_name)
            if res.is_ok:
                return self
            else:
                raise ValueError(i18n.t("auto_rechart_model.error_song_name_invalid", name=self.song_name))
        
        # 如果没有输入 song_name，使用输入文件名作为默认歌曲名称
        default_name = self.standardize_input_video_path.stem
        res = validate_windows_filename(default_name)
        if res.is_ok:
            self.song_name = default_name # update
            return self
        else:
            raise ValueError(i18n.t("auto_rechart_model.error_default_song_name_invalid", name=default_name))
    

    # 检查 video_mode
    @model_validator(mode='after')
    def validate_video_mode_options(self):
        if not self.is_standardize_enabled:
            return self
        if self.video_mode is None:
            raise ValueError(i18n.t("auto_rechart_model.error_video_mode_required"))
        allowed = AC_Defs.video_mode.constraints["options"]
        if self.video_mode not in allowed:
            raise ValueError(i18n.t("auto_rechart_model.error_video_mode_options", allowed=allowed, value=self.video_mode))
        return self
    

    # 检查 media_type
    @model_validator(mode='after')
    def validate_media_type_options(self):
        if not self.is_standardize_enabled:
            return self
        if self.media_type is None:
            raise ValueError(i18n.t("auto_rechart_model.error_media_type_required"))
        allowed = AC_Defs.media_type.constraints["options"]
        if self.media_type not in allowed:
            raise ValueError(i18n.t("auto_rechart_model.error_media_type_options", allowed=allowed, value=self.media_type))
        return self


    # 检查 duration & start_sec & end_sec
    @model_validator(mode='after')
    def validate_start_end_sec(self):
        
        if not self.is_standardize_enabled:
            return self
        
        set_start = self.start_sec is not None and self.start_sec !=  0
        set_end = self.end_sec is not None and self.end_sec != 0

        # 确保 duration > 0
        if self.duration is None or self.duration <= 0:
            raise ValueError(i18n.t("auto_rechart_model.error_duration_invalid", value=self.duration))
        
        if set_end:
            self.end_sec = self.duration + self.end_sec if self.end_sec < 0 else self.end_sec
        
        # 确保 start < end < duration
        if set_start and self.start_sec >= self.duration:
            raise ValueError(i18n.t("auto_rechart_model.error_start_sec_ge_duration"))
        if set_end and self.end_sec >= self.duration:
            raise ValueError(i18n.t("auto_rechart_model.error_end_sec_ge_duration"))
        if set_start and set_end and self.start_sec >= self.end_sec:
            raise ValueError(i18n.t("auto_rechart_model.error_start_sec_ge_end_sec"))

        # 统一设置为三位小数/None
        self.start_sec = round(self.start_sec, 3) if set_start else None
        self.end_sec   = round(self.end_sec, 3)   if set_end else None
        self.duration  = round(self.duration, 3)
        
        return self
        

    @model_validator(mode='after')
    def validate_bpm_source(self):
        """
        analyze 启用时的 BPM 来源二选一校验：
            - 两者都没给 → 报错
            - 两者都给 → 优先 bpm（bpm_config 置 None）
            - 仅 bpm   → 取三位小数
            - 仅 bpm_config → 调 parse_config 解析（fail fast）；成功则把 bpm_config
                              替换为 parse_config 返回的 notify JSON 路径，供 worker 消费
        """
        if not self.is_analyze_enabled:
            return self

        bpm_set = self.bpm is not None
        cfg_set = self.bpm_config is not None

        if not bpm_set and not cfg_set:
            raise ValueError(i18n.t("auto_rechart_model.error_bpm_source_missing"))

        if bpm_set:
            # 优先静态 bpm：丢弃 bpm_config
            if cfg_set:
                self.bpm_config = None
            # 取三位小数
            self.bpm = round(self.bpm, 3)
            return self

        # 仅 bpm_config：解析配置文件，把 bpm_config 替换为 notify JSON 路径。
        res = parse_config(self.bpm_config)
        if not res.is_ok:
            raise ValueError(i18n.t("auto_rechart_model.error_bpm_config_parse_failed", error=res.error_msg))
        self.bpm_config = res.value
        return self


    @model_validator(mode='after')
    def validate_chart_lv(self):
        if not self.is_analyze_enabled:
            return self
        if self.chart_lv is None:
            raise ValueError(i18n.t("auto_rechart_model.error_chart_lv_required"))
        allowed = AC_Defs.chart_lv.constraints["options"]
        if self.chart_lv not in allowed:
            raise ValueError(i18n.t("auto_rechart_model.error_chart_lv_options", allowed=allowed, value=self.chart_lv))
        return self


    @model_validator(mode='after')
    def validate_base_denominator(self):
        if not self.is_analyze_enabled:
            return self
        if self.base_denominator is None:
            raise ValueError(i18n.t("auto_rechart_model.error_base_denominator_required"))
        allowed = AC_Defs.base_denominator.constraints["options"]
        if self.base_denominator not in allowed:
            raise ValueError(i18n.t("auto_rechart_model.error_base_denominator_options", allowed=allowed, value=self.base_denominator))
        return self
    

    @model_validator(mode='after')
    def validate_duration_denominator(self):
        if not self.is_analyze_enabled:
            return self
        if self.duration_denominator is None:
            raise ValueError(i18n.t("auto_rechart_model.error_duration_denominator_required"))
        allowed = AC_Defs.duration_denominator.constraints["options"]
        if self.duration_denominator not in allowed:
            raise ValueError(i18n.t("auto_rechart_model.error_duration_denominator_options", allowed=allowed, value=self.duration_denominator))
        return self







    # other

    @model_validator(mode='after')
    def validate_selected_folder(self):

        # 两个模块均未启用
        if not self.is_detect_enabled and not self.is_analyze_enabled:
            return self
        # 俩模块启用并且前置模块 standardize 也启用
        if self.is_standardize_enabled:
            return self
        # 俩模块启用并且前置模块 standardize 未启用，需要 selected_folder 参数
        folder = self.selected_folder
        
        # 检查
        if folder is None:
            raise ValueError(i18n.t("auto_rechart_model.error_selected_folder_required"))
        if not folder.exists() or not folder.is_dir():
            raise ValueError(i18n.t("auto_rechart_model.error_selected_folder_not_exist", path=str(folder)))
        return self
