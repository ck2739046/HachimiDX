import math
from typing import Optional
from src.services import PathManage, SettingsManage
from .schemas.media_config import MediaType
from .schemas.media_model import MediaModel
from src.core.schemas.op_result import OpResult, ok, err
from src.core.schemas.settings_config import SettingsConfig_Definitions as S_Defs
from src.core.schemas.media_config import MediaConfig_Definitions as M_Defs



# 编解码映射

ENCODER_MAP = {
    "CPU":    {"codec": "libx264",
               "quality_param": "-crf",
               "pix_fmt": "yuv420p"},
    "Nvidia": {"codec": "h264_nvenc",
               "quality_param": "-cq",
               "pix_fmt": "nv12"},
    "Intel":  {"codec": "h264_qsv",
               "quality_param": "-global_quality",
               "pix_fmt": "nv12"},
}


def _resolve_video_encoder() -> OpResult[dict]:
    res = SettingsManage.get(S_Defs.ffmpeg_hw_encoder.key)
    if not res.is_ok:
        return err("Failed to read ffmpeg_hw_encoder setting", inner=res)

    encoder_id = str(res.value).strip()
    entry = ENCODER_MAP.get(encoder_id)
    if entry is None:
        return err(f"Unknown ffmpeg_hw_encoder: {encoder_id}")

    return ok(entry)




def build_ffmpeg_cmd(data: MediaModel) -> OpResult[list[str]]:
    """
    主入口: 构建 FFmpeg 命令行参数列表

    输入:
        data (MediaModel)

    输出:
        OpResult[list[str]]: FFmpeg 命令行参数列表
    """

    result = _build_constant_args()
    if not result.is_ok:
        return err(
            error_msg = "Failed to build constant FFmpeg arguments.",
            inner = result
        )
    args = result.value

    result = _build_common_args(data)
    if not result.is_ok:
        return err(
            error_msg = "Failed to build common FFmpeg arguments.",
            inner = result
        )
    args.extend(result.value)

    result = _build_video_args(data)
    if not result.is_ok:
        return err(
            error_msg = "Failed to build video FFmpeg arguments.",
            inner = result
        )
    args.extend(result.value)

    result = _build_audio_args(data)
    if not result.is_ok:
        return err(
            error_msg = "Failed to build audio FFmpeg arguments.",
            inner = result
        )
    args.extend(result.value)

    # 最后添加输出文件路径
    args.append(str(data.output_path))

    return ok(args)





def _build_constant_args() -> OpResult[list[str]]:
    """构建 FFmpeg 固定的参数部分"""

    ffmpeg_exe = PathManage.FFMPEG_EXE_PATH
    if not ffmpeg_exe.is_file():
        return err(f"FFmpeg executable not found at: {ffmpeg_exe}")
    
    args = [
        str(ffmpeg_exe),
        "-y",                 # 覆盖输出文件
        "-hide_banner",       # 隐藏横幅信息
        "-stats",             # 显示进度统计信息
        "-loglevel", "error"  # 只显示错误信息
    ]

    return ok(args)




def _build_common_args(data: MediaModel) -> OpResult[list[str]]:
    """构建 FFmpeg 通用参数部分"""

    args = []

    # 输入文件
    args.extend(["-i", str(data.input_path)])

    # clear metadata
    if data.clear_metadata:
        args.extend(["-map_metadata", "-1"])

    # start/end 在滤镜中使用 trim/atrim 处理
    # 不知道 -ss/-to 的 seek 行为是否会有误差，反正先用滤镜处理
    # pad_start 也在滤镜中处理
    # output_path 要加在最后
    
    return ok(args)




def _build_video_args(data: MediaModel) -> OpResult[list[str]]:
    """构建 FFmpeg 视频参数部分"""

    args = []

    if not(data.media_type == MediaType.VIDEO_WITH_AUDIO or \
           data.media_type == MediaType.VIDEO_WITHOUT_AUDIO):
        return ok(args)  # 非视频类型，无需视频参数
    
    encoder_res = _resolve_video_encoder()
    if not encoder_res.is_ok:
        return err("Failed to resolve video encoder", inner=encoder_res)
    entry = encoder_res.value

    args.extend(["-c:v", entry["codec"]])
    args.extend(["-pix_fmt", entry["pix_fmt"]])
    args.extend([entry["quality_param"], str(data.video_quality)])

    if data.video_fps and data.video_fps > 0:
        args.extend(["-r", str(data.video_fps)])
    else:
        # Keep original frame pacing/timestamps when FPS is "original".
        args.extend(["-fps_mode:v", "passthrough"])
        args.extend(["-enc_time_base:v", "-1"])

    if data.video_gop_optimize:
        args.extend(["-g", "30"])

    vf = _build_video_filter(
        size = data.video_side_resolution,
        crop = (data.video_crop_w, data.video_crop_h, data.video_crop_x, data.video_crop_y),
        pad = data.pad_start,
        start = data.start,
        end = data.end,
        brightness = data.video_brightness,
        perspective = (
            data.video_perspective_tl_x,
            data.video_perspective_tl_y,
            data.video_perspective_tr_x,
            data.video_perspective_tr_y,
            data.video_perspective_bl_x,
            data.video_perspective_bl_y,
            data.video_perspective_br_x,
            data.video_perspective_br_y,
        ),
    )
    if vf:
        args.extend(["-vf", vf])

    # video_mute 在 audio 部分处理

    return ok(args)



def _build_video_filter(size: Optional[int],
                        crop: tuple[Optional[int], Optional[int], Optional[int], Optional[int]],
                        pad: Optional[float],
                        start: Optional[float],
                        end: Optional[float],
                        brightness: Optional[float],
                        perspective: tuple[Optional[float], Optional[float], Optional[float], Optional[float], Optional[float], Optional[float], Optional[float], Optional[float]] = None
                       ) -> Optional[str]:
    """构建视频滤镜"""

    filters = []

    # trim (decode-time cut, not keyframe dependent)
    if start is not None or end is not None:
        trim_kv = []
        if start is not None:
            trim_kv.append(f"start={start}")
        if end is not None:
            trim_kv.append(f"end={end}")
        filters.append(f"trim={':'.join(trim_kv)}")
        filters.append("setpts=PTS-STARTPTS")

    # Perspective correction using four points
    if perspective is not None and all(p is not None for p in perspective):
        tl_x, tl_y, tr_x, tr_y, bl_x, bl_y, br_x, br_y = perspective
        perspective_filter = (
            f"perspective="
            f"{tl_x:.6f}:{tl_y:.6f}:"
            f"{tr_x:.6f}:{tr_y:.6f}:"
            f"{bl_x:.6f}:{bl_y:.6f}:"
            f"{br_x:.6f}:{br_y:.6f}:sense=destination"
        )
        filters.append(perspective_filter)

    if brightness is not None and abs(brightness) > 1e-6:
        clamped_brightness = max(-1.0, min(1.0, float(brightness)))
        filters.append(f"eq=brightness={clamped_brightness:.6f}")

    # Crop (支持越界，超出部分用黑色填充)
    if all(v is not None for v in crop):
        w, h, x, y = crop
        pad_cmd, crop_cmd = (_build_crop_filter(w, h, x, y))
        filters.append(pad_cmd)
        filters.append(crop_cmd)
        
    # Resize
    if size:
        filters.append(_build_resize_filter(size, crop))

    # 有些神秘视频像素宽高比居然不是1:1
    # 此处强制设置为1:1
    if size:
        filters.append("setsar=1")

    # Pad start
    if pad:
        filters.append(f"tpad=start_duration={pad}:color=black")

    return ",".join(filters) if filters else None



def _build_crop_filter(w, h, x, y) -> tuple[str, str]:
    # 计算是否需要扩展画布以容纳整个 crop 区域
    # crop 区域范围: [x, x+w] 水平方向, [y, y+h] 垂直方向
    # 原视频范围: [0, iw] 水平方向, [0, ih] 垂直方向
    
    # 向左/上偏移量（当 x<0 或 y<0 时）
    left_pad = abs(min(x, 0))  # 如果 x<0, left_pad=-x; 否则为 0
    top_pad = abs(min(y, 0))   # 如果 y<0, top_pad=-y; 否则为 0
    
    # 构建 FFmpeg 表达式来处理动态边界计算
    # 向右扩展量 = max(0, x + w - iw)  当 x>=0
    # 向右扩展量 = max(0, x + w - iw + left_pad) 当 x<0 (因为 iw 在新画布中是 iw+left_pad，相对位置变了)
    # 实际上更简单：计算 crop 区域右边界超出原视频右边界的量
    # 新画布中，原视频位于 (left_pad, top_pad)，右边界是 left_pad + iw
    # crop 区域右边界是 left_pad + x + w
    # 超出量 = max(0, left_pad + x + w - (left_pad + iw)) = max(0, x + w - iw)
    right_pad_expr = f"max(0\\,{x}+{w}-iw)"
    bottom_pad_expr = f"max(0\\,{y}+{h}-ih)"
    
    # 计算 pad 后的画布大小
    pad_w_expr = f"{left_pad}+iw+{right_pad_expr}"
    pad_h_expr = f"{top_pad}+ih+{bottom_pad_expr}"
    
    # 原视频在新画布中的位置
    pad_x = left_pad
    pad_y = top_pad
    
    # 添加 pad 滤镜（使用表达式动态计算）
    pad_cmd = f"pad={pad_w_expr}:{pad_h_expr}:{pad_x}:{pad_y}:black"
    
    # 调整 crop 坐标到新画布坐标系
    x = x + left_pad
    y = y + top_pad
    
    crop_cmd = f"crop={w}:{h}:{x}:{y}"

    return pad_cmd, crop_cmd



def _build_resize_filter(size, crop) -> str:

    if all(v is not None for v in crop):
        w, h, x, y = crop
        if w != h:
            # 不是正方形，不保持宽高比，直接缩放
            return f"scale={size}:{size}"
    
    # 没有裁剪信息，保持宽高比缩放，然后填充到正方形
    scale_expr = f"if(gt(iw,ih),{size},-1):if(gt(iw,ih),-1,{size})".replace(",", r"\,") # 对逗号转义
    pad_expr = f"{size}:{size}:(ow-iw)/2:(oh-ih)/2:black"
    return f"scale={scale_expr},pad={pad_expr}"






def _build_audio_args(data: MediaModel) -> OpResult[list[str]]:
    """构建 FFmpeg 音频参数部分"""

    args = []

    # 音频导出任务强制仅保留音频流，避免把封面图/字幕/数据流写进输出容器。
    if data.media_type == MediaType.AUDIO:
        args.extend(["-vn", "-sn", "-dn", "-map", "0:a:0"])

    # 有音频考虑 video mute
    if data.media_type == MediaType.VIDEO_WITH_AUDIO:
        if data.video_mute:
            args.extend(["-an"])  # 无音频输出
            return ok(args)
    
    # 没音频直接静音
    if data.media_type in [MediaType.VIDEO_WITHOUT_AUDIO]:
        args.extend(["-an"])  # 无音频输出
        return ok(args)
    
    # audio_format
    if data.audio_format == "mp3":
        args.extend(["-c:a", "libmp3lame"])
    elif data.audio_format == "aac":
        args.extend(["-c:a", "aac"])
    elif data.audio_format == "ogg":
        args.extend(["-c:a", "libvorbis"])
    else:
        return err(f"Unsupported audio format: {data.audio_format}")
    
    # audio_bitrate
    mode, num = data.audio_bitrate.split(" ")[:2]
    if mode == "vbr":
        args.extend(["-q:a", str(num)])
    elif mode == "cbr":
        args.extend(["-b:a", str(num)])
    else:
        return err(f"Unsupported audio bitrate mode: {mode}")
    
    # sample_rate
    if data.audio_sample_rate:
        args.extend(["-ar", str(data.audio_sample_rate)])

    # always force stereo
    args.extend(["-ac", "2"])

    # audio filter
    af = _build_audio_filters(volume=data.audio_volume,
                              media_type=data.media_type,
                              mute=data.video_mute,
                              pad=data.pad_start,
                              start=data.start,
                              end=data.end)
    if af:
        args.extend(["-af", af])

    return ok(args)




def _build_audio_filters(volume: Optional[int],
                         media_type: MediaType,
                         mute: Optional[bool],
                         pad: Optional[float],
                         start: Optional[float],
                         end: Optional[float]
                        ) -> Optional[str]:
    """构建音频滤镜"""

    filters = []

    # trim (decode-time cut, not keyframe dependent)
    if start is not None or end is not None:
        atrim_kv = []
        if start is not None:
            atrim_kv.append(f"start={start}")
        if end is not None:
            atrim_kv.append(f"end={end}")
        filters.append(f"atrim={':'.join(atrim_kv)}")
        filters.append("asetpts=PTS-STARTPTS")

    # pad start
    if pad:
        pad_ms = int(round(pad * 1000.0))
        filters.append(f"adelay={pad_ms}|{pad_ms}") # "ms|ms" for stereo

    # volume
    if volume and volume != 100:
        filters.append(f"volume={(volume / 100.0):.2f}")

    # 音频同步
    if media_type == MediaType.VIDEO_WITH_AUDIO and not mute:
        filters.append("aresample=async=1")

    return ",".join(filters) if filters else None
