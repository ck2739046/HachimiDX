from pathlib import Path
import shutil

from ...schemas.op_result import OpResult, ok, err, print_op_result
from ...schemas.media_model import MediaType

from . import detect_circle
from .perspective_correction import PerspectiveCorrection
from . import process_video




def main(input_video: Path,
         temp_output_path: Path,
         final_output_path: Path,
         video_mode: str,
         media_type: MediaType,
         duration: float,
         start_sec: float,
         end_sec: float,
         need_screen_rectification: bool,
         target_res: int
        ) -> OpResult[None]:

    """
    规范化视频 主入口

    Args:
        input_video(Path): 输入视频路径
        temp_output_path(Path): 临时输出视频路径
        final_output_path(Path): 最终输出视频路径
        video_mode(str): 视频模式 source video / camera footage
        media_type(MediaType): 媒体类型 video_with_audio / video_without_audio
        duration(float): 视频总时长(秒)
        start_sec(float): 开始时间(秒)
        end_sec(float): 结束时间(秒)
        need_screen_rectification(bool): 是否需要画面矫正
        target_res(int): 目标分辨率(边长)

    Returns:
        OpResult[None]
    """
    
    try:
        print("Standardize...")

        # 第一步：检测圆形判定线
        result = detect_circle.main(
            input_video=input_video,
            mode=video_mode,
            need_screen_rectification=need_screen_rectification,
            start_sec=start_sec,
        )
        if not result.is_ok:
            return err("Failed to detect circle.", inner=result)
        circle_center, circle_radius = result.value

        scale_x, scale_y = 1.0, 1.0
        perspective_points = None
        brightness = 0.0

        # 第二步：手动微调圆心和半径
        if need_screen_rectification:
            result = PerspectiveCorrection(
                input_video=input_video,
                circle_center=circle_center,
                circle_radius=circle_radius,
                start_sec=start_sec,
                end_sec=end_sec,
            ).main()
            if not result.is_ok:
                return err("Failed to manual adjust circle.", inner=result)
            circle_center, circle_radius, scale_x, scale_y, perspective_points, brightness = result.value

        # 第三步：处理视频
        result = process_video.main(
            input_video=input_video,
            output_path=temp_output_path,
            circle_center=circle_center,
            circle_radius=circle_radius,
            scale_x=scale_x,
            scale_y=scale_y,
            perspective_points = perspective_points,
            brightness=brightness,
            media_type=media_type,
            duration=duration,
            start_sec=start_sec,
            end_sec=end_sec,
            target_res=target_res
        )
        if not result.is_ok:
            return err("Failed to process video.", inner=result)

        # 第四步：移动到正式输出目录
        if temp_output_path != final_output_path:
            try:
                final_output_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(temp_output_path), str(final_output_path))
            except Exception as e:
                return err(f"Failed to move output video from temp dir to main output dir.", error_raw=e)

        return ok()
        
    except Exception as e:
        return err(f"Unexcepted error in Standardize.main().", error_raw = e)
