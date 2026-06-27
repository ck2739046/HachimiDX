from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Literal
from .op_result import OpResult, ok, err
from ..tools.validate_windows_filename import validate_windows_filename


class MediaType(str, Enum):
    AUDIO = "audio"
    VIDEO_WITH_AUDIO = "video_with_audio"
    VIDEO_WITHOUT_AUDIO = "video_without_audio"
    UNKNOWN = "unknown"



@dataclass(slots=True)
class MediaConfig_Definition:
    """
    Definition for MediaConfig

    Attributes:
        key: str
        type: Literal["int", "float", "path", "str", "bool", "enum(MediaType)"]
        group: Literal["audio", "video", "common"]
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
        For str:
            - "options": list of allowed strings
        For path:
            - "must_exist": bool
        For bool:
            - N/A
    """

    key: str
    type: Literal["int", "float", "path", "str", "bool", "enum"]
    group: Literal["audio", "video", "common"]
    default: any = None
    optional: bool = True
    constraints: dict | None = None
    


@dataclass(slots=True)
class MediaConfig_Definitions:

    # common

    media_type = MediaConfig_Definition(
        key="media_type",
        type="enum",
        group="common",
        optional=False, # 必选没有默认值
    )

    input_path = MediaConfig_Definition(
        key="input_path",
        type="path",
        group="common",
        optional=False, # 必选没有默认值
        constraints={
            "must_exist": True
        }
    )

    output_path = MediaConfig_Definition(
        key="output_path",
        type="path",
        group="common",
        optional=False, # 必选没有默认值
        constraints={
            "must_exist": False
        }
    )

    clear_metadata = MediaConfig_Definition(
        key="clear_metadata",
        type="bool",
        group="common",
        default=True
    )

    duration = MediaConfig_Definition(
        key="duration",
        type="float",
        group="common",
        default=None,
        constraints={
            "ge": 0.0
        }
    )

    pad_start = MediaConfig_Definition(
        key="pad_start",
        type="float",
        group="common",
        default=None,
        constraints={
            "ge": 0.0
        }
    )

    start = MediaConfig_Definition(
        key="start",
        type="float",
        group="common",
        default=None,
        constraints={
            "ge": 0.0
        }
    )

    end = MediaConfig_Definition(
        key="end",
        type="float",
        group="common",
        default=None,
    )





    # audio

    # see get_audio_format_by_media_type()
    audio_format = MediaConfig_Definition(
        key="audio_format",
        type="str",
        group="audio",
        default=None, # auto
    )

    @staticmethod
    def get_audio_format_by_media_type(media_type: MediaType) -> OpResult[tuple[str, list[str]]]:
        """return (default, options)"""
        if media_type == MediaType.AUDIO:
            return ok(("ogg", ["mp3", "ogg"]))
        elif media_type == MediaType.VIDEO_WITH_AUDIO or \
            media_type == MediaType.VIDEO_WITHOUT_AUDIO:
            return ok(("aac", ["aac"]))
        else:
            return err(f"No valid audio_format for the given media_type: {media_type}")

    audio_bitrate = MediaConfig_Definition(
        key="audio_bitrate",
        type="str",
        group="audio",
        default="192k",
        constraints={
            "options": ["320k", "288k", "256k", "224k", "192k", "160k", "128k"]
        }
    )

    audio_sample_rate = MediaConfig_Definition(
        key="audio_sample_rate",
        type="int",
        group="audio",
        default=44100,
        constraints={
            "options": [44100, 48000]
        }
    )

    audio_volume = MediaConfig_Definition(
        key="audio_volume",
        type="int",
        group="audio",
        default=100,
        constraints={
            "ge": 0,
            "le": 200
        }
    )










    # video

    video_quality = MediaConfig_Definition(
        key="video_quality",
        type="int",
        group="video",
        default=None, # auto
        constraints={
            "ge": 20,
            "le": 28,
            "options": list(range(20, 28+1))
        }
    )

    @staticmethod
    def get_default_video_quality_by_encoder(encoder: str) -> int:
        dict = {"CPU": 23, "Nvidia": 28, "Intel": 23}
        return dict.get(encoder, 23) # fallback

    video_side_resolution = MediaConfig_Definition(
        key="video_side_resolution",
        type="int",
        group="video",
        default=0, # original
        constraints={
            "options": [0, 480, 720, 1080, 1440, 2160]
        }
    )

    video_fps = MediaConfig_Definition(
        key="video_fps",
        type="int",
        group="video",
        default=0, # original
        constraints={
            "options": [0, 30, 60]
        }
    )

    video_gop_optimize = MediaConfig_Definition(
        key="video_gop_optimize",
        type="bool",
        group="video",
        default=False
    )

    delete_audio = MediaConfig_Definition(
        key="delete_audio",
        type="bool",
        group="video",
        default=False
    )

    delete_video = MediaConfig_Definition(
        key="delete_video",
        type="bool",
        group="video",
        default=False
    )

    video_crop_x = MediaConfig_Definition(
        key="video_crop_x",
        type="int",
        group="video",
        default=None,
        constraints={}
    )

    video_crop_y = MediaConfig_Definition(
        key="video_crop_y",
        type="int",
        group="video",
        default=None,
        constraints={}
    )

    video_crop_w = MediaConfig_Definition(
        key="video_crop_w",
        type="int",
        group="video",
        default=None,
        constraints={
            "gt": 0
        }
    )

    video_crop_h = MediaConfig_Definition(
        key="video_crop_h",
        type="int",
        group="video",
        default=None,
        constraints={
            "gt": 0
        }
    )

    video_perspective_tl_x = MediaConfig_Definition(
        key="video_perspective_tl_x",
        type="float",
        group="video",
        default=None
    )

    video_perspective_tl_y = MediaConfig_Definition(
        key="video_perspective_tl_y",
        type="float",
        group="video",
        default=None
    )

    video_perspective_tr_x = MediaConfig_Definition(
        key="video_perspective_tr_x",
        type="float",
        group="video",
        default=None
    )

    video_perspective_tr_y = MediaConfig_Definition(
        key="video_perspective_tr_y",
        type="float",
        group="video",
        default=None
    )

    video_perspective_bl_x = MediaConfig_Definition(
        key="video_perspective_bl_x",
        type="float",
        group="video",
        default=None
    )

    video_perspective_bl_y = MediaConfig_Definition(
        key="video_perspective_bl_y",
        type="float",
        group="video",
        default=None
    )

    video_perspective_br_x = MediaConfig_Definition(
        key="video_perspective_br_x",
        type="float",
        group="video",
        default=None
    )

    video_perspective_br_y = MediaConfig_Definition(
        key="video_perspective_br_y",
        type="float",
        group="video",
        default=None
    )

    video_brightness = MediaConfig_Definition(
        key="video_brightness",
        type="float",
        group="video",
        default=None,
        constraints={
            "ge": -1.0,
            "le": 1.0,
        }
    )




    @staticmethod
    def build_full_output_path(input_path: str, output_filename: str, audio_format: str) -> OpResult[tuple[str, str]]:

        """
        构建完整的输出文件路径

        Args:
            input_path: str，输入文件路径
            output_filename: str，输出文件名，仅文件名，不包含路径和扩展名
            audio_format: str，输出音频格式

        Returns:
            OpResult[tuple[str, str]]: (完整输出文件路径, 最终输出文件名)

        说明:
            - 首先检查 output_filename 是否符合 windows 标准
            - 如果 output_filename 为空，默认使用 input_filename_modified
            - 根据 audio_format 确定输出文件扩展名
            - 输出文件与输入文件在同一目录下
        """

        # 校验输出文件名 (如果有提供)
        if output_filename:
            result = validate_windows_filename(output_filename)
            if not result.is_ok:
                return err(
                    error_msg = result.error_msg,
                    inner = result
                )
            
        # 根据 audio_format 确定输出文件扩展名
        output_extension = {"mp3": ".mp3", "aac": ".mp4", "ogg": ".ogg"}.get(audio_format.lower())
        if not output_extension:
            return err(f"Unsupported audio_format for output extension: {audio_format}")
            
        # 构建最终输出文件路径
        input_dir = Path(input_path).resolve().parent

        if not output_filename:
            # 如果输入文件名为空，使用 文件名_modified
            input_stem = Path(input_path).stem
            output_filename = f"{input_stem}_modified"

        final_output_path = input_dir / f"{output_filename}{output_extension}"

        return ok((str(final_output_path), output_filename))
