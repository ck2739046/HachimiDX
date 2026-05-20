from typing import Annotated
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .settings_config import SettingsConfig_Definitions as S_Defs


class SettingsModel(BaseModel):

    model_config = ConfigDict(extra="allow")

    # 模型推理相关
    model_backend: str = Field(default=S_Defs.model_backend.default)
    inference_device: str = Field(default=S_Defs.inference_device.default)
    predict_batch_size_detect_obb: Annotated[int, Field(gt=S_Defs.predict_batch_size_detect_obb.constraints["gt"])] = S_Defs.predict_batch_size_detect_obb.default
    predict_batch_size_classify: Annotated[int, Field(gt=S_Defs.predict_batch_size_classify.constraints["gt"])] = S_Defs.predict_batch_size_classify.default
    predict_batch_size_touch_hold: Annotated[int, Field(gt=S_Defs.predict_batch_size_touch_hold.constraints["gt"])] = S_Defs.predict_batch_size_touch_hold.default
    # FFmpeg 硬件加速相关
    ffmpeg_hw_encoder: str = Field(default=S_Defs.ffmpeg_hw_encoder.default)
    # 应用通用设置
    language: str = Field(default=S_Defs.language.default)
    # 窗口大小
    main_app_default_size: tuple[
        Annotated[int, Field(ge=S_Defs.main_app_default_size.constraints["item_ge"], le=S_Defs.main_app_default_size.constraints["item_le"])],
        Annotated[int, Field(ge=S_Defs.main_app_default_size.constraints["item_ge"], le=S_Defs.main_app_default_size.constraints["item_le"])],
    ] = S_Defs.main_app_default_size.default
    main_app_min_size: tuple[
        Annotated[int, Field(ge=S_Defs.main_app_min_size.constraints["item_ge"], le=S_Defs.main_app_min_size.constraints["item_le"])],
        Annotated[int, Field(ge=S_Defs.main_app_min_size.constraints["item_ge"], le=S_Defs.main_app_min_size.constraints["item_le"])],
    ] = S_Defs.main_app_min_size.default
    # 界面缩放
    main_app_ui_scale: Annotated[int, Field(ge=S_Defs.main_app_ui_scale.constraints["ge"], le=S_Defs.main_app_ui_scale.constraints["le"])] = S_Defs.main_app_ui_scale.default



    @field_validator("model_backend")
    @classmethod
    def validate_model_backend_options(cls, v: str) -> str:
        allowed = S_Defs.model_backend.constraints["options"]
        if v not in allowed:
            raise ValueError(f"model_backend must be one of {allowed}")
        return v



    @field_validator("inference_device")
    @classmethod
    def validate_inference_device_options(cls, v: str) -> str:
        allowed = S_Defs.inference_device.constraints["options"]
        if v not in allowed:
            raise ValueError(f"inference_device must be one of {allowed}")
        return v



    @field_validator("ffmpeg_hw_encoder")
    @classmethod
    def validate_ffmpeg_hw_encoder_options(cls, v: str) -> str:
        allowed = S_Defs.ffmpeg_hw_encoder.constraints["options"]
        if v not in allowed:
            raise ValueError(f"ffmpeg_hw_encoder must be one of {allowed}")
        return v




    @field_validator("language")
    @classmethod
    def validate_language_options(cls, v: str) -> str:
        allowed = S_Defs.language.constraints["options"]
        if v not in allowed:
            raise ValueError(f"language must be one of {allowed}")
        return v



    @model_validator(mode="after")
    def sync_inference_device_with_backend(self):
        self.inference_device = S_Defs.get_inference_device_by_backend(self.model_backend)
        return self

