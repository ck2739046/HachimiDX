from dataclasses import dataclass
from typing import Literal

from src.services import PathManage
from .op_result import OpResult, ok, err


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
        constraints={"options": ["CPU", "TensorRT", "DirectML"]},
    )

    @staticmethod
    def get_path_by_backend(backend) -> OpResult[dict]:
        if backend == "CPU":
            paths = {
                "detect": PathManage.DETECT_PT_PATH,
                "obb": PathManage.OBB_PT_PATH,
                "cls_break": PathManage.CLS_BREAK_PT_PATH,
                "cls_ex": PathManage.CLS_EX_PT_PATH,
                "touch_hold": PathManage.TOUCH_HOLD_PT_PATH,
            }
        elif backend == "TensorRT":
            paths = {
                "detect": PathManage.DETECT_ENGINE_PATH,
                "obb": PathManage.OBB_ENGINE_PATH,
                "cls_break": PathManage.CLS_BREAK_ENGINE_PATH,
                "cls_ex": PathManage.CLS_EX_ENGINE_PATH,
                "touch_hold": PathManage.TOUCH_HOLD_ENGINE_PATH,
            }
        elif backend == "DirectML":
            paths = {
                "detect": PathManage.DETECT_ONNX_PATH,
                "obb": PathManage.OBB_ONNX_PATH,
                "cls_break": PathManage.CLS_BREAK_ONNX_PATH,
                "cls_ex": PathManage.CLS_EX_ONNX_PATH,
                "touch_hold": PathManage.TOUCH_HOLD_ONNX_PATH,
            }
        else:
            paths = {}

        if not paths:
            return err(f"Unknown model backend: {backend}")
        for path in paths.values():
            if not path.exists():
                return err(f"Model file not found for backend {backend}: {path}")
        return ok(paths)


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
        constraints={"options": ["cpu", "cuda"]},
    )

    @staticmethod
    def get_inference_device_by_backend(backend):
        if backend == "CPU":
            return "cpu"
        elif backend == "TensorRT":
            return "cuda"
        elif backend == "DirectML":
            return "cpu" # 虽然写的cpu但实际上会自动选择显卡
        else:
            return "cpu" # default to cpu if unknown backend

    # ffmpeg

    ffmpeg_hw_encoder = SettingsConfig_Definition(
        key="ffmpeg_hw_encoder",
        type="str",
        group="ffmpeg",
        default="CPU",
        constraints={"options": ["CPU", "Intel", "Nvidia"]},
    )

    # general

    language = SettingsConfig_Definition(
        key="language",
        type="str",
        group="general",
        default="en_US",
        constraints={"options": ["zh_CN", "en_US"]},
    )

    check_update_on_startup = SettingsConfig_Definition(
        key="check_update_on_startup",
        type="bool",
        group="general",
        default=True,
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
