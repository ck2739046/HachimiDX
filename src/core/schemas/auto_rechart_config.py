from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .op_result import OpResult, ok, err
from ..tools.validate_windows_filename import validate_windows_filename
from .media_config import MediaType




@dataclass(slots=True)
class AutoRechartConfig_Definition:
    """
    Definition for AutoRechartConfig

    Attributes:
        key: str
        type: Literal["int", "float", "path", "str", "bool", "enum"]
        group: Literal["common", "standardize", "detect", "analyze", "other"]
        default: any
        optional: bool
        constraints: dict | None

    Constraints:
        For int/float:
            - "ge": int, minimum value (inclusive)
            - "gt": int, minimum value (exclusive)
            - "le": int, maximum value (inclusive)
            - "lt": int, maximum value (exclusive)
            - "options": list of allowed values
            - "options_tooltips": list of tooltips for each option
        For str:
            - "options": list of allowed strings
            - "options_tooltips": list of tooltips for each option
        For path:
            - "must_exist": bool
        For bool:
            - N/A
    """

    key: str
    type: Literal["int", "float", "path", "str", "bool", "enum"]
    group: Literal["common", "standardize", "detect", "analyze", "other"]
    default: any = None
    optional: bool = True
    constraints: dict | None = None




@dataclass(slots=True)
class AutoRechartConfig_Definitions:
      


    # common
    
    is_standardize_enabled = AutoRechartConfig_Definition(
        key="is_standardize_enabled",
        type="bool",
        group="common",
        default=True
    )
      
    is_detect_enabled = AutoRechartConfig_Definition(
        key="is_detect_enabled",
        type="bool",
        group="common",
        default=True
    )
      
    is_analyze_enabled = AutoRechartConfig_Definition(
        key="is_analyze_enabled",
        type="bool",
        group="common",
        default=True
    )
      



    # standardize
      
    standardize_input_video_path = AutoRechartConfig_Definition(
        key="standardize_input_video_path",
        type="path",
        group="standardize",
        optional=False, # 必选没有默认值
        constraints={"must_exist": True} # 输入视频必须存在
    )

    video_mode = AutoRechartConfig_Definition(
        key="video_mode",
        type="str",
        group="standardize",
        default = "source video", # 默认模式
        constraints={"options":["source video", "camera footage"],
                     "options_tooltips": ["ui_video_mode_source_tooltip",
                                          "ui_video_mode_camera_tooltip"]}
    )
      
    media_type = AutoRechartConfig_Definition(
        key="media_type",
        type="enum",
        group="standardize",
        optional=False, # 必选没有默认值
        constraints={"options": [MediaType.VIDEO_WITH_AUDIO, MediaType.VIDEO_WITHOUT_AUDIO]}
    )

    duration = AutoRechartConfig_Definition(
        key="duration",
        type="float",
        group="standardize",
        optional=False, # 必选没有默认值
        constraints={"gt": 0}
    )

    start_sec = AutoRechartConfig_Definition(
        key="start_sec",
        type="float",
        group="standardize",
        default=None,
        constraints={"ge": 0.0}
    )

    end_sec = AutoRechartConfig_Definition(
        key="end_sec",
        type="float",
        group="standardize",
        default=None
    )

    need_screen_rectification = AutoRechartConfig_Definition(
        key="need_screen_rectification",
        type="bool",
        group="standardize",
        default=False
    )

    target_res = AutoRechartConfig_Definition(
        key="target_res",
        type="int",
        group="standardize",
        default=1080,
        constraints={"gt": 0}
    )



    # detect

    skip_detect = AutoRechartConfig_Definition(
        key="skip_detect",
        type="bool",
        group="detect",
        default=False
    )

    skip_cls = AutoRechartConfig_Definition(
        key="skip_cls",
        type="bool",
        group="detect",
        default=False
    )

    skip_export_tracked_video = AutoRechartConfig_Definition(
        key="skip_export_tracked_video",
        type="bool",
        group="detect",
        default=False
    )

    enable_reid = AutoRechartConfig_Definition(
        key="enable_reid",
        type="bool",
        group="detect",
        default=True
    )

    # 当视频 FPS 达到此阈值时，自动关闭 ReID
    # 因为帧率已经够高了，ReID 的作用不大
    REID_MAX_FPS_THRESHOLD = 90.0




    # analyze

    bpm = AutoRechartConfig_Definition(
        key="bpm",
        type="float",
        group="analyze",
        optional=True,
        constraints={"gt": 0}
    )

    bpm_config = AutoRechartConfig_Definition(
        key="bpm_config",
        type="path",
        group="analyze",
        optional=True,
        constraints={"must_exist": True}
    )

    is_big_touch = AutoRechartConfig_Definition(
        key="is_big_touch",
        type="bool",
        group="analyze",
        default=False
    )

    chart_lv = AutoRechartConfig_Definition(
        key="chart_lv",
        type="int",
        group="analyze",
        default=5, # master
        constraints={"options": [2, 3, 4, 5, 6, 7],
                     "options_tooltips": ["ui_chart_lv_2_tooltip",
                                          "ui_chart_lv_3_tooltip",
                                          "ui_chart_lv_4_tooltip",
                                          "ui_chart_lv_5_tooltip",
                                          "ui_chart_lv_6_tooltip",
                                          "ui_chart_lv_7_tooltip"]}
    )

    base_denominator = AutoRechartConfig_Definition(
        key="base_denominator",
        type="int",
        group="analyze",
        default=32, # 匹配 CHART_LV_PRESETS
        constraints={"options": [4, 8, 16, 32, 64]}
    )

    duration_denominator = AutoRechartConfig_Definition(
        key="duration_denominator",
        type="int",
        group="analyze",
        default=32, # 匹配 CHART_LV_PRESETS
        constraints={"options": [4, 8, 16, 32, 64]}
     )

    CHART_LV_PRESETS = {
        2: {is_big_touch.key: True,  base_denominator.key: 8,  duration_denominator.key: 8},
        3: {is_big_touch.key: True,  base_denominator.key: 8,  duration_denominator.key: 8},
        4: {is_big_touch.key: False, base_denominator.key: 16, duration_denominator.key: 16},
        5: {is_big_touch.key: False, base_denominator.key: 32, duration_denominator.key: 32},
        6: {is_big_touch.key: False, base_denominator.key: 32, duration_denominator.key: 32},
        7: {is_big_touch.key: False, base_denominator.key: 32, duration_denominator.key: 32},
    }





    # 其他分类
    
    # ui 提供后会转变为其他参数，不是最终需要的
      
    song_name = AutoRechartConfig_Definition(
        key="song_name",
        type="str",
        group="other",
        optional=False, # 必选没有默认值
    )
      
    selected_folder = AutoRechartConfig_Definition(
        key="selected_folder",
        type="path",
        group="other",
        optional=False, # 必选没有默认值
        constraints={"must_exist": True} # 选择的文件夹必须存在
    )
      
    # 不由 ui 提供，但是方便统一 key
      
    std_video_path = AutoRechartConfig_Definition(
        key="std_video_path",
        type="path",
        group="other",
    )

    standardize_temp_output_path = AutoRechartConfig_Definition(
        key="standardize_temp_output_path",
        type="path",
        group="other",
    )
