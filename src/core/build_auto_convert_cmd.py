import sys
from pathlib import Path
import cv2

from src.services.path_manage import PathManage
from src.services.settings_manage import SettingsManage

from .schemas.auto_convert_model import AutoConvertModel
from .schemas.auto_convert_config import AutoConvertConfig_Definitions as AC_Defs
from .schemas.auto_convert_config import AutoConvertConfig_Definition
from .schemas.op_result import OpResult, ok, err
from .schemas.settings_config import SettingsConfig_Definitions as SC_Defs
from .tools.media_ffprobe_inspect import FFprobeInspect
from .tools.popup_dialog import show_confirm_dialog
from .build_worker_cmd import build_cmd_head_python_exe





def _try_unload_majdata_video_if_matches(target_path: Path) -> None:
    """如果目标路径正被 MajdataPage 播放器加载，则先卸载。"""
    try:
        from src.app.pages.majdata_page import MajdataPage

        MajdataPage.try_unload_video_if_matches(target_path)
    except Exception:
        return


def build_auto_convert_cmd(data: AutoConvertModel) -> OpResult[list[str]]:
    """
    主入口: 构建 AutoConvert 命令行参数列表

    输入:
        data (AutoConvertModel)

    输出:
        OpResult[list[str]]: AutoConvert 命令行参数列表
    """

    try:
        cmd = build_cmd_head_python_exe(PathManage.AUTO_CONVERT_WORKER_PATH)

        # add common args
        cmd.append(f"--{AC_Defs.is_detect_enabled.key}")
        cmd.append("true" if data.is_detect_enabled else "false")
        cmd.append(f"--{AC_Defs.is_analyze_enabled.key}")
        cmd.append("true" if data.is_analyze_enabled else "false")

        std_video_path = None

        # standardize
        if data.is_standardize_enabled:
            # 检查输出路径
            res = _build_standardize_output_path(data)
            if not res.is_ok:
                return err("Failed to build standardize output path arg", inner=res)
            is_enable_standardize, temp_output, std_video_path = res.value
            if is_enable_standardize:
                # 启用标准化模块
                cmd.append(f"--{AC_Defs.is_standardize_enabled.key}")
                cmd.append("true")
                # 正常写入其他参数
                cmd.extend(_parse_fields(data, "standardize"))
                # 将 temp_output 加入参数
                cmd.append(f"--{AC_Defs.standardize_temp_output_path.key}")
                cmd.append(str(temp_output.resolve()))
            else:
                # 禁用标准化模块
                cmd.append(f"--{AC_Defs.is_standardize_enabled.key}")
                cmd.append("false")
        else:
            # 禁用标准化模块
            cmd.append(f"--{AC_Defs.is_standardize_enabled.key}")
            cmd.append("false")



        # add shared inference args
        if data.is_detect_enabled or data.is_analyze_enabled:
            res = _get_inference_args_from_settings()
            if not res.is_ok:
                return err("Failed to get inference args from settings", inner=res)
            cmd.extend(res.value)



        # add detect args
        if data.is_detect_enabled:
            cmd.extend(_parse_fields(data, "detect"))

            # 增加模型路径
            res = _get_detect_model_paths()
            if not res.is_ok:
                return err("Failed to get detect model paths", inner=res)
            cmd.extend(res.value)



        # add analyze args
        if data.is_analyze_enabled:
            cmd.extend(_parse_fields(data, "analyze"))

            # 增加 touch-hold 分析模型路径
            res = _get_analyze_model_paths()
            if not res.is_ok:
                return err("Failed to get analyze model paths", inner=res)
            cmd.extend(res.value)



        # handle std video path
        if std_video_path is None:
            filename = f"{data.selected_folder.name}_std.mp4"
            std_video_path = data.selected_folder / filename
            if not _is_video_already_standardized(std_video_path, data):
                return err(f"Selected folder doesn't contain a valid standardized video, should be: {std_video_path}")

        cmd.append(f"--{AC_Defs.std_video_path.key}")
        cmd.append(str(std_video_path.resolve()))

        return ok(cmd)
    
    except Exception as e:
        return err("Unexpected error in build_auto_convert_cmd", e)





def _parse_fields(data: AutoConvertModel, group: str) -> list[str]:
    """
    通用字段解析函数，根据字段定义自动构建命令行参数列表
    """
    args = []

    for definition in vars(AC_Defs).values():
        if not isinstance(definition, AutoConvertConfig_Definition):
            continue

        if definition.group != group:
            continue

        value = getattr(data, definition.key)
        if value is None:
            continue
        
        arg_key = f"--{definition.key}"
        if definition.type == "bool":
            arg_value = "true" if value else "false"
        elif definition.type == "enum":
            arg_value = value.value
        else:
            arg_value = str(value)
        
        args.append(arg_key)
        args.append(arg_value)

    return args










def _build_standardize_output_path(data: AutoConvertModel) -> OpResult[tuple[bool, list]]:

    """构建并检查标准化模块的输出路径参数，返回 OpResult: (是否启用标准化模块, temp_output, final_output)"""

    try:
        # 构建 temp output path
        output_filename = f"{data.song_name}_std.mp4"
        standardize_temp_output_path = PathManage.TEMP_DIR / output_filename
        # 如果已存在，删除
        if standardize_temp_output_path.exists():
            try:
                standardize_temp_output_path.unlink()
            except Exception as e:
                return err(f"Failed to delete existing temp standardized video: {standardize_temp_output_path}", e)

        # 构建 standardize_final_output_path
        output_dir = data.standardize_input_video_path.parent
        standardize_final_output_path = output_dir / data.song_name / output_filename

        if _use_existing_standardized_video(standardize_final_output_path, data):
            # 如果使用已有视频，禁用标准化模块
            return ok((False, standardize_temp_output_path, standardize_final_output_path))
        else:
            # 如果不用已有视频，启用标准化模块
            return ok((True, standardize_temp_output_path, standardize_final_output_path))
    
    except Exception as e:
        return err("Unexpected error in _build_standardize_output_path", e)




def _use_existing_standardized_video(file_path, data) -> bool:

    # 检查该视频是否有效
    if _is_video_already_standardized(file_path, data):
        # 询问用户是否删除
        is_delete = show_confirm_dialog(
            title="Auto Convert",
            prompt_text=f"Standardized video already exists:\n\n{file_path}\n\nDo you want to delete it and generate a new one?"
        )
        if is_delete:
            # 用户选择删除文件
            try:
                _try_unload_majdata_video_if_matches(file_path)
                file_path.unlink()
            except Exception as e:
                print(f'Failed to delete "{file_path}": {e}')
            # 视为不使用已有文件
            return False
        else:
            # 用户选择不删除
            print("Standardized module will be disabled.")
            print(f'Using existing standardized video: {file_path}')
            # 视为使用已有文件
            return True
    
    # 视为不使用已有文件
    if file_path.exists() and file_path.is_file():
        try:
            file_path.unlink()
        except Exception as e:
            print(f'Failed to delete "{file_path}": {e}')

    return False
    



def _is_video_already_standardized(video_path: Path, data: AutoConvertModel) -> bool:

    if not video_path.exists() or not video_path.is_file(): return False

    # 获取视频数据
    try:
        cap = cv2.VideoCapture(str(video_path))
        video_width = round(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        video_height = round(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap.release()
    except Exception as e:
        print(f"Failed to read video file: {video_path}, error: {e}")
        return False

    # 检查分辨率
    if video_width != data.target_res or video_height != data.target_res:
        print(f'video resolution mismatch, expect {data.target_res}x{data.target_res}, got {video_width}x{video_height}.')
        return False

    # 计算时长
    set_duration = data.duration is not None and data.duration != 0
    if not set_duration:
        return True # 如果没有设置时长，就不检查时长
    
    set_start = data.start_sec is not None and data.start_sec !=  0
    set_end = data.end_sec is not None and data.end_sec != 0
    if set_start and set_end:
        expect_duration = data.end_sec - data.start_sec
    elif set_start and not set_end:
        expect_duration = data.duration - data.start_sec
    elif not set_start and set_end:
        expect_duration = data.end_sec
    else:
        expect_duration = data.duration

    # 使用 FFprobe 获取视频时长
    res = FFprobeInspect.inspect_media(str(video_path))
    if not res.is_ok:
        print(f"Failed to inspect video by ffprobe: {res.error_msg}")
        return False
    try:
        _aaa = float(res.value.duration)
        if _aaa <= 0:
            print(f"Invalid video duration from ffprobe: {_aaa}")
            return False
    except Exception as e:
        print(f"Failed to parse video duration: {res.value.duration}. Error: {e}")
        return False
    video_duration = float(res.value.duration)

    # 允许时长相差半秒
    if abs(video_duration - expect_duration) > 0.5:
        print(f'video duration mismatch, expect {expect_duration}s, got {video_duration}s.')
        return False

    return True




def _get_inference_args_from_settings() -> OpResult[list]:
                
    cmd = []

    res = SettingsManage.get(SC_Defs.inference_device.key)
    if not res.is_ok:
        return err(f"Failed to get {SC_Defs.inference_device.key} from settings", inner=res)
    cmd.append(f"--{SC_Defs.inference_device.key}")
    cmd.append(str(res.value))

    res = SettingsManage.get(SC_Defs.predict_batch_size_detect_obb.key)
    if not res.is_ok:
        return err(f"Failed to get {SC_Defs.predict_batch_size_detect_obb.key} from settings", inner=res)
    cmd.append(f"--{SC_Defs.predict_batch_size_detect_obb.key}")
    cmd.append(str(res.value))

    res = SettingsManage.get(SC_Defs.predict_batch_size_classify.key)
    if not res.is_ok:
        return err(f"Failed to get {SC_Defs.predict_batch_size_classify.key} from settings", inner=res)
    cmd.append(f"--{SC_Defs.predict_batch_size_classify.key}")
    cmd.append(str(res.value))

    res = SettingsManage.get(SC_Defs.predict_batch_size_touch_hold.key)
    if not res.is_ok:
        return err(f"Failed to get {SC_Defs.predict_batch_size_touch_hold.key} from settings", inner=res)
    cmd.append(f"--{SC_Defs.predict_batch_size_touch_hold.key}")
    cmd.append(str(res.value))

    return ok(cmd)





def _get_detect_model_paths() -> OpResult[list]:

    cmd = []

    res = SettingsManage.get(SC_Defs.model_backend.key)
    if not res.is_ok:
        return err(f"Failed to get {SC_Defs.model_backend.key} from settings", inner=res)
    model_backend = res.value

    res = SC_Defs.get_path_by_backend(model_backend)
    if not res.is_ok:
        return err(f"Failed to get model paths for backend: {model_backend}", inner=res)
    paths = res.value

    cmd.append(f"--detect_model_path")
    cmd.append(str(paths["detect"]))
    cmd.append(f"--obb_model_path")
    cmd.append(str(paths["obb"]))
    cmd.append(f"--cls_break_model_path")
    cmd.append(str(paths["cls_break"]))
    cmd.append(f"--cls_ex_model_path")
    cmd.append(str(paths["cls_ex"]))

    return ok(cmd)




def _get_analyze_model_paths() -> OpResult[list]:

    cmd = []

    res = SettingsManage.get(SC_Defs.model_backend.key)
    if not res.is_ok:
        return err(f"Failed to get {SC_Defs.model_backend.key} from settings", inner=res)
    model_backend = res.value

    res = SC_Defs.get_path_by_backend(model_backend)
    if not res.is_ok:
        return err(f"Failed to get model paths for backend: {model_backend}", inner=res)
    paths = res.value

    cmd.append(f"--touch_hold_model_path")
    cmd.append(str(paths["touch_hold"]))

    cmd.append(f"--cls_break_model_path")
    cmd.append(str(paths["cls_break"]))
    cmd.append(f"--cls_ex_model_path")
    cmd.append(str(paths["cls_ex"]))

    return ok(cmd)
