from pathlib import Path
from typing import Tuple
import cv2
import shutil

from ...schemas.op_result import OpResult, ok, err, print_op_result
from ...schemas.media_config import MediaType
from ...schemas.media_config import MediaConfig_Definitions as M_Defs
from src.services import MediaPipeline




def main(input_video: Path,
         output_path: Path,
         circle_center: Tuple[int, int],
         circle_radius: int,
         scale_x: float,
         scale_y: float,
         perspective_points: Tuple[float, float, float, float, float, float, float, float] | None,
         brightness: float,
         media_type: MediaType,
         duration: float,
         start_sec: float = 0.0,
         end_sec: float = 0.0,
         target_res: int = 1080
        ) -> OpResult[None]:

    """
    生成标准化视频 主入口

    Args:
        input_video(Path): 输入视频路径
        output_path(Path): 输出视频路径
        circle_center(Tuple[int, int]): 圆心坐标
        circle_radius(int): 圆半径
        scale_x(float): X轴缩放系数
        scale_y(float): Y轴缩放系数
        perspective_points(Tuple[8 float] | None): 透视四点坐标
        brightness(float): 亮度（FFmpeg eq 语义，范围 -1.0~1.0）
        media_type(MediaType): 媒体类型 video_with_audio / video_without_audio
        duration(float): 视频总时长(秒)
        start_sec(float): 开始时间(秒)
        end_sec(float): 结束时间(秒)
        target_res(int): 目标分辨率(边长)，默认 1080

    Returns:
        OpResult[None]
    """

    try:

        print("Process video...")

        start_sec = start_sec if start_sec is not None else 0.0
        end_sec = end_sec if end_sec is not None else 0.0

        # 获取视频基本信息
        cap = cv2.VideoCapture(input_video)
        if not cap.isOpened():
            return err(f"Cannot open video file: {input_video}")
        video_width = round(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        video_height = round(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap.release()

        # 此处把 x/y scale 揉进 crop 里
        crop_w, crop_h, crop_x, crop_y = calculate_crop_params(circle_center, circle_radius, scale_x, scale_y)

        (is_input_std,
         need_crop,
         need_resize,
         need_trim_start,
         need_trim_end,
         need_perspective_correction,
         need_brightness
        ) = is_input_already_standardized(
            crop_w,
            crop_h,
            crop_x,
            crop_y,
            perspective_points,
            brightness,
            video_width,
            video_height,
            target_res,
            start_sec,
            end_sec
        )
        if is_input_std:
            # 如果输入已经标准了，直接复制到输出路径
            print("Input video already standardized, copy to output path.")
            try:
                # 如果输出文件已存在，先删除
                if output_path.exists():
                    output_path.unlink()
                # 复制输入文件到输出路径
                shutil.copy2(input_video, output_path)
                return ok(output_path)
            except Exception as e:
                return err(f"Failed to copy video file: {e}")
        




        # 构建参数
        params = {
            M_Defs.media_type.key: media_type,
            M_Defs.input_path.key: str(input_video.resolve()),
            M_Defs.output_path.key: str(output_path.resolve()),
            M_Defs.duration.key: duration,
            M_Defs.video_fps.key: 0,
        }

        if need_crop:
            params.update({
                M_Defs.video_crop_w.key: crop_w,
                M_Defs.video_crop_h.key: crop_h,
                M_Defs.video_crop_x.key: crop_x,
                M_Defs.video_crop_y.key: crop_y,
            })

        if need_perspective_correction:
            params.update({
                M_Defs.video_perspective_tl_x.key: perspective_points[0],
                M_Defs.video_perspective_tl_y.key: perspective_points[1],
                M_Defs.video_perspective_tr_x.key: perspective_points[2],
                M_Defs.video_perspective_tr_y.key: perspective_points[3],
                M_Defs.video_perspective_bl_x.key: perspective_points[4],
                M_Defs.video_perspective_bl_y.key: perspective_points[5],
                M_Defs.video_perspective_br_x.key: perspective_points[6],
                M_Defs.video_perspective_br_y.key: perspective_points[7],
            })

        if need_brightness:
            params.update({
                M_Defs.video_brightness.key: brightness,
            })


        if need_resize:
            params.update({
                M_Defs.video_side_resolution.key: target_res,
            })
        
        if need_trim_start:
            params.update({
                M_Defs.start.key: start_sec,
            })

        if need_trim_end:
            params.update({
                M_Defs.end.key: end_sec,
            })

        change_hint = ''

        if need_crop:
            change_hint += f'  crop to {crop_w}:{crop_h}:{crop_x}:{crop_y} (w:h:x:y)\n'
        if need_resize:
            change_hint += f'  resize to {target_res}x{target_res}\n'
        if need_trim_start:
            change_hint += f'  trim start to {start_sec}s\n'
        if need_trim_end:
            change_hint += f'  trim end to {end_sec}s\n'
        if need_perspective_correction:
            change_hint += f'  apply perspective correction\n'
        if need_brightness:
            change_hint += f'  apply brightness: {brightness:+.2f}\n'

        if change_hint:
            print(f"Process video with changes:\n{change_hint}")




        # 实际运行 ffmpeg
        run_res = MediaPipeline.run_now(params)
        if not run_res.is_ok:
            return err("Standardize video process failed.", inner=run_res)

        print("Process video...Ok")

        return ok()

    except Exception as e:
        return err(f"Unexcepted error in process_video", error_raw = e)
    





def calculate_crop_params(circle_center: Tuple[int, int],
                          circle_radius: int,
                          scale_x: float = 1.0,
                          scale_y: float = 1.0
                        ) -> Tuple[int, int, int, int]:

    # 根据 scale 计算水平和垂直方向的半长
    half_w = circle_radius / scale_x
    half_h = circle_radius / scale_y

    # 计算裁剪区域的宽度和高度
    crop_w = round(half_w * 2)
    crop_h = round(half_h * 2)

    # 计算裁剪区域左上角坐标（允许越界，由 ffmpeg 处理黑色填充）
    crop_x = round(circle_center[0] - half_w)
    crop_y = round(circle_center[1] - half_h)

    return crop_w, crop_h, crop_x, crop_y






def is_input_already_standardized(crop_w: int,
                                  crop_h: int,
                                  crop_x: int,
                                  crop_y: int,
                                  perspective_points: Tuple[float, float, float, float, float, float, float, float] | None,
                                  brightness: float,
                                  video_width: int,
                                  video_height: int,
                                  target_res: int,
                                  start_sec: float,
                                  end_sec: float
                                 ) -> tuple[bool, bool, bool, bool, bool, bool, bool]:

    video_size = min(video_width, video_height)
    tolerance = video_size / 360

    need_perspective_correction = True
    need_crop = True
    need_resize = True
    need_trim_start = True
    need_trim_end = True
    need_brightness = True


    # 透视矫正
    if perspective_points is None:
        need_perspective_correction = False

    # 如果裁剪画面尺寸≈实际视频尺寸，并且裁剪中心≈实际视频中心，则不裁剪
    # 使用 max(crop_w, crop_h) 来判断是否接近视频尺寸
    if abs(crop_w - video_size) < tolerance*2 and \
       abs(crop_h - video_size) < tolerance*2 and \
       crop_x < tolerance and crop_y < tolerance:
        need_crop = False

    # resize (如果 crop 后的尺寸等于目标分辨率，则不需要 resize)
    if crop_w == crop_h == target_res:
        need_resize = False

    # trim
    if start_sec <= 0:
        need_trim_start = False
    if end_sec <= 0:
        need_trim_end = False
    if abs(brightness) <= 1e-6:
        need_brightness = False

    if not need_crop and not need_resize and not need_trim_start and not need_trim_end and not need_perspective_correction and not need_brightness:
        print("Video already standardized.")
        return True, False, False, False, False, False, False

    return False, need_crop, need_resize, need_trim_start, need_trim_end, need_perspective_correction, need_brightness
