from typing import Optional, Literal, Any
import os
from pathlib import Path
from pydantic import BaseModel, Field, FilePath, model_validator

from .auto_convert_config import AutoConvertConfig_Definitions as AC_Defs
from src.core.tools.validate_windows_filename import validate_windows_filename
from .media_config import MediaType



class AutoConvertModel(BaseModel):
    """
    AutoConvert configuration model for validation and processing.
    All fields have defaults as defined in auto_convert_config.py.
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




    # detect group

    skip_detect: Optional[bool] = Field(default=AC_Defs.skip_detect.default)

    skip_cls: Optional[bool] = Field(default=AC_Defs.skip_cls.default)

    skip_export_tracked_video: Optional[bool] = Field(default=AC_Defs.skip_export_tracked_video.default)

    enable_reid: Optional[bool] = Field(default=AC_Defs.enable_reid.default)




    # analyze group

    bpm: Optional[float] = Field(default=None) # 必需参数 没有默认值

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
            raise ValueError("At least one of standardize, detect, or analyze must be enabled.")
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
            raise ValueError("chart confirmation video not selected")
        if not input_path.exists() or not input_path.is_file():
            raise ValueError(f"chart confirmation video does not exist: '{input_path}'")
        if not os.access(input_path.parent, os.R_OK | os.W_OK):
            raise ValueError(f"Directory of chart confirmation video is not readable or writable: '{input_path.parent}'")
        
        # 验证 song_name 合法性
        if self.song_name is not None:
            res = validate_windows_filename(self.song_name)
            if res.is_ok:
                return self
            else:
                raise ValueError(f"song_name '{self.song_name}' contains invalid characters for Windows filenames.")
        
        # 如果没有输入 song_name，使用输入文件名作为默认歌曲名称
        default_name = self.standardize_input_video_path.stem
        res = validate_windows_filename(default_name)
        if res.is_ok:
            self.song_name = default_name # update
            return self
        else:
            raise ValueError(f"Derived default song name '{default_name}' from chart confirmation video is not a valid Windows filename.")
    

    # 检查 video_mode
    @model_validator(mode='after')
    def validate_video_mode_options(self):
        if not self.is_standardize_enabled:
            return self
        if self.video_mode is None:
            raise ValueError("video_mode is required when standardize is enabled.")
        allowed = AC_Defs.video_mode.constraints["options"]
        if self.video_mode not in allowed:
            raise ValueError(f"video_mode must be one of {allowed}, got {self.video_mode}")
        return self
    

    # 检查 media_type
    @model_validator(mode='after')
    def validate_media_type_options(self):
        if not self.is_standardize_enabled:
            return self
        if self.media_type is None:
            raise ValueError("media_type is required when standardize is enabled.")
        allowed = AC_Defs.media_type.constraints["options"]
        if self.media_type not in allowed:
            raise ValueError(f"media_type must be one of {allowed}, got {self.media_type}")
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
            raise ValueError(f"duration must be greater than 0, got {self.duration}")
        
        if set_end:
            self.end_sec = self.duration + self.end_sec if self.end_sec < 0 else self.end_sec
        
        # 确保 start < end < duration
        if set_start and self.start_sec >= self.duration:
            raise ValueError("'start_sec' must be less than 'duration'.")
        if set_end and self.end_sec >= self.duration:
            raise ValueError("'end_sec' must be less than 'duration'.")
        if set_start and set_end and self.start_sec >= self.end_sec:
            raise ValueError("'start_sec' must be less than 'end_sec'.")

        # 统一设置为三位小数/None
        self.start_sec = round(self.start_sec, 3) if set_start else None
        self.end_sec   = round(self.end_sec, 3)   if set_end else None
        self.duration  = round(self.duration, 3)
        
        return self
        





    # analyze

    @model_validator(mode='after')
    def validate_bpm(self):
        if not self.is_analyze_enabled:
            return self
        if self.bpm is None:
            raise ValueError("bpm is required when analyze is enabled.")
        if self.bpm <= 0:
            raise ValueError(f"bpm must be greater than 0, got {self.bpm}")
        # 统一设置为三位小数
        self.bpm = round(self.bpm, 3)
        return self


    @model_validator(mode='after')
    def validate_chart_lv(self):
        if not self.is_analyze_enabled:
            return self
        if self.chart_lv is None:
            raise ValueError("chart_lv is required when analyze is enabled.")
        allowed = AC_Defs.chart_lv.constraints["options"]
        if self.chart_lv not in allowed:
            raise ValueError(f"chart_lv must be one of {allowed}, got {self.chart_lv}")
        return self


    @model_validator(mode='after')
    def validate_base_denominator(self):
        if not self.is_analyze_enabled:
            return self
        if self.base_denominator is None:
            raise ValueError("base_denominator is required when analyze is enabled.")
        allowed = AC_Defs.base_denominator.constraints["options"]
        if self.base_denominator not in allowed:
            raise ValueError(f"base_denominator must be one of {allowed}, got {self.base_denominator}")
        return self
    

    @model_validator(mode='after')
    def validate_duration_denominator(self):
        if not self.is_analyze_enabled:
            return self
        if self.duration_denominator is None:
            raise ValueError("duration_denominator is required when analyze is enabled.")
        allowed = AC_Defs.duration_denominator.constraints["options"]
        if self.duration_denominator not in allowed:
            raise ValueError(f"duration_denominator must be one of {allowed}, got {self.duration_denominator}")
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
            raise ValueError("selected_folder is required.")
        if not folder.exists() or not folder.is_dir():
            raise ValueError(f"selected_folder does not exist: '{folder}'")
        return self
