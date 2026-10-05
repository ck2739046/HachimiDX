import logging
import os
from pathlib import Path

import i18n
from ultralytics.utils import LOGGER

from ...schemas.op_result import OpResult, err, ok, print_op_result
from ...tools import FFprobeInspect
from .classify import main as classify_module
from .detect import main as detect_module
from .export_track_video import main as export_video_module
from .post_track import main as post_track_module
from .track import main as track_module

original_level = LOGGER.level
LOGGER.setLevel(logging.ERROR)  # 只显示错误信息，忽略 Warning


def _get_total_frames_by_ffprobe(std_video_path: Path) -> OpResult[int]:
    result = FFprobeInspect.inspect_video_frame_timestamps_msec(str(std_video_path))
    if not result.is_ok:
        return err("Failed to inspect frame timestamps", inner=result)

    total_frames = len(result.value)
    if total_frames <= 0:
        return err(f"Invalid frame count from ffprobe timestamps: {total_frames}")

    return ok(total_frames)


def main(
    std_video_path,
    batch_detect,
    batch_cls,
    inference_device,
    detect_model_path,
    obb_model_path,
    cls_ex_model_path,
    cls_break_model_path,
    model_backend,
    video_encoder: str,
    half=False,
    skip_detect=False,
    skip_cls=False,
    skip_export_tracked_video=False,
    # enable_reid=True
) -> OpResult[None]:
    try:
        # 检查输入文件
        paths = []
        for path in [
            std_video_path,
            detect_model_path,
            obb_model_path,
            cls_ex_model_path,
            cls_break_model_path,
        ]:
            path = os.path.abspath(path)
            path = os.path.normpath(path)
            if not os.path.exists(path):
                raise FileNotFoundError(
                    i18n.t("detect_main.error_model_not_found", path=str(path))
                )
            paths.append(path)
        (
            std_video_path,
            detect_model_path,
            obb_model_path,
            cls_ex_model_path,
            cls_break_model_path,
        ) = paths
        std_video_path = Path(std_video_path)

        # 检查模型配置
        if batch_detect <= 0 or batch_cls <= 0:
            raise ValueError(
                i18n.t(
                    "detect_main.error_batch_invalid",
                    batch_detect=batch_detect,
                    batch_cls=batch_cls,
                )
            )

        # 统一通过 ffprobe 逐帧时间戳计算总帧数，避免 VFR 下 OpenCV 帧数不准
        total_frames_result = _get_total_frames_by_ffprobe(std_video_path)
        if not total_frames_result.is_ok:
            detail = print_op_result(total_frames_result)
            return err(
                i18n.t("detect_main.error_read_total_frames_failed", detail=detail),
                inner=total_frames_result,
            )
        total_frames = total_frames_result.value

        # 检测模块
        if not skip_detect:
            result = detect_module(
                std_video_path,
                total_frames,
                batch_detect,
                inference_device,
                detect_model_path,
                obb_model_path,
                model_backend,
                half,
            )
            if not result.is_ok:
                return err("detect module failed", inner=result)
        else:
            print(i18n.t("detect_main.notice_skip_detect_existing"))

        # 追踪模块
        # result = track_module(std_video_path, total_frames, enable_reid)
        result = track_module(std_video_path, total_frames)
        if not result.is_ok:
            return err("track module failed", inner=result)

        # 追踪后处理模块
        result = post_track_module(std_video_path)
        if not result.is_ok:
            return err("post-track module failed", inner=result)

        # 分类模块
        if not skip_cls:
            result = classify_module(
                std_video_path,
                batch_cls,
                inference_device,
                cls_ex_model_path,
                cls_break_model_path,
                half=half,
            )
            if not result.is_ok:
                return err("classify module failed", inner=result)
        else:
            print(i18n.t("detect_main.notice_skip_classify"))

        # 导出追踪视频模块
        if not skip_export_tracked_video:
            result = export_video_module(std_video_path, total_frames, video_encoder)
            if not result.is_ok:
                return err("export track video module failed", inner=result)
        else:
            print(i18n.t("detect_main.notice_skip_export_video"))

        return ok()

    except KeyboardInterrupt:
        print("\n" + i18n.t("detect_main.notice_interrupted"))
        return err("Interrupted by user (KeyboardInterrupt)")
    except Exception as e:
        return err("Unexcepted error in auto_rechart > detect > main", e)
