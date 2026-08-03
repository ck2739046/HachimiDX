from dataclasses import dataclass
from typing import Literal


# 窗口尺寸硬性边界常量（不写入 settings.json，不在设置页配置）
MAIN_APP_W_MIN = 1240
MAIN_APP_W_MAX = 5000
MAIN_APP_H_MIN = 900
MAIN_APP_H_MAX = 4000


@dataclass(slots=True)
class SettingsConfig_Definition:
    """
    Definition for SettingsConfig

    Attributes:
        key: str
        type: Literal["str", "int"]
        group: Literal["model", "ffmpeg", "general", "window"]
        default: any
        constraints: dict | None
    """

    key: str
    type: Literal["str", "int", "bool"]
    group: Literal["model", "ffmpeg", "general", "window"]
    default: any = None
    constraints: dict | None = None


@dataclass(slots=True)
class SettingsConfig_Definitions:

    # model

    model_backend = SettingsConfig_Definition(
        key="model_backend",
        type="str",
        group="model",
        default="TensorRT",
        constraints={"options": ["PyTorch", "NCNN", "TensorRT"],
                 "options_tooltips": ["ui_model_backend_pytorch_tooltip",
                                          "ui_model_backend_ncnn_tooltip",
                                          "ui_model_backend_tensorrt_tooltip"]},
    )

    predict_batch_size_detect_obb = SettingsConfig_Definition(
        key="predict_batch_size_detect_obb",
        type="int",
        group="model",
        default=2,
        constraints={"gt": 0},
    )

    predict_batch_size_classify = SettingsConfig_Definition(
        key="predict_batch_size_classify",
        type="int",
        group="model",
        default=16,
        constraints={"gt": 0},
    )

    predict_batch_size_touch_hold = SettingsConfig_Definition(
        key="predict_batch_size_touch_hold",
        type="int",
        group="model",
        default=16,
        constraints={"gt": 0},
    )

    inference_device = SettingsConfig_Definition(
        key="inference_device",
        type="str",
        group="model",
        default="cuda",
        constraints={"options": ["cpu", "vulkan:0", "cuda"]},
    )

    @staticmethod
    def get_inference_device_by_backend(backend):
        if backend == "PyTorch":
            return "cpu"
        elif backend == "NCNN":
            return "vulkan:0"
        elif backend == "TensorRT":
            return "cuda"
        else:
            return "cpu" # default to cpu if unknown backend

    # ffmpeg

    ffmpeg_hw_encoder = SettingsConfig_Definition(
        key="ffmpeg_hw_encoder",
        type="str",
        group="ffmpeg",
        default="CPU",
        constraints={"options": ["CPU", "Intel", "Nvidia"],
                     "options_tooltips": ["ui_ffmpeg_encoder_cpu_tooltip",
                                          "ui_ffmpeg_encoder_intel_tooltip",
                                          "ui_ffmpeg_encoder_nvidia_tooltip"]},
    )

    # general

    language = SettingsConfig_Definition(
        key="language",
        type="str",
        group="general",
        default="en_US",
        constraints={"options": ["zh_CN", "en_US"],
                     "options_tooltips": ["ui_language_zh_cn_tooltip",
                                          "ui_language_en_us_tooltip"]},
    )

    check_update = SettingsConfig_Definition(
        key="check_update",
        type="bool",
        group="general",
        default=True,
    )

    last_check_update_time = SettingsConfig_Definition(
        key="last_check_update_time",
        type="str",
        group="general",
        default="",
    )

    # window

    main_app_w_default = SettingsConfig_Definition(
        key="main_app_w_default",
        type="int",
        group="window",
        default=1320,
        constraints={"ge": MAIN_APP_W_MIN, "le": MAIN_APP_W_MAX},
    )

    main_app_h_default = SettingsConfig_Definition(
        key="main_app_h_default",
        type="int",
        group="window",
        default=930,
        constraints={"ge": MAIN_APP_H_MIN, "le": MAIN_APP_H_MAX},
    )

    main_app_ui_scale = SettingsConfig_Definition(
        key="main_app_ui_scale",
        type="int",
        group="window",
        default=100,
        constraints={"ge": 50, "le": 200},
    )
