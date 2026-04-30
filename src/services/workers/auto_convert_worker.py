import sys
import traceback
from pathlib import Path
import io

# 解决 Windows 控制台 Unicode 编码问题
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', write_through=True)
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace', write_through=True)


if len(sys.argv) <= 1:
    print("No root args provided. Exiting.")
    sys.exit(1)

# 第一个参数是项目根目录
# 确保能正确使用间接导入
root = str(Path(sys.argv[1]).resolve())
if root not in sys.path:
    sys.path.insert(0, root)

# 2026.03.20

# see https://github.com/pytorch/pytorch/issues/166628
# 当前最新版 pytorch + pyqt6 在一起使用时有问题
# 如果 pyqt6 比 torch 先导入，会产生 winerror1114 (dll加载失败)
# 解决方法是先导入 torch 再导入 pyqt6
import torch



from src.core.auto_convert.standardize.main import main as standardize_main
from src.core.auto_convert.detect.main import main as detect_main
from src.core.auto_convert.analyze.main import main as analyze_main
from src.core.schemas.media_config import MediaType
from src.core.schemas.op_result import print_op_result



def _as_bool(raw: str) -> bool:
    text = str(raw).strip().lower()
    if text == "true":
        return True
    elif text == "false":
        return False
    else:
        raise ValueError(f"Invalid bool value: {raw}")


def _fail(message: str) -> bool:
    print(f"[AUTO_CONVERT_WORKER][ERROR] {message}")
    return False


def _get_cfg(cfg: dict[str, str], key: str, parser=None):
    raw = cfg.get(key)
    if raw is None:
        return None
    if parser is None:
        return raw
    return parser(raw)


def main(args: list[str]) -> bool:
    try:
        # --key value 成对输入
        cfg = {args[i][2:]: args[i + 1] for i in range(0, len(args), 2)}

        is_standardize_enabled = _as_bool(cfg["is_standardize_enabled"])
        is_detect_enabled = _as_bool(cfg["is_detect_enabled"])
        is_analyze_enabled = _as_bool(cfg["is_analyze_enabled"])
        std_video_path = _get_cfg(cfg, "std_video_path", Path)



        if is_standardize_enabled:
            result = standardize_main(
                input_video=_get_cfg(cfg, "standardize_input_video_path", Path),
                temp_output_path=_get_cfg(cfg, "standardize_temp_output_path", Path),
                final_output_path=std_video_path,
                video_mode=_get_cfg(cfg, "video_mode"),
                media_type=_get_cfg(cfg, "media_type", MediaType),
                duration=_get_cfg(cfg, "duration", float),
                start_sec=_get_cfg(cfg, "start_sec", float),
                end_sec=_get_cfg(cfg, "end_sec", float),
                need_screen_rectification=_get_cfg(cfg, "need_screen_rectification", _as_bool),
                target_res=_get_cfg(cfg, "target_res", int),
            )
            if not result.is_ok:
                return _fail(print_op_result(result))     



        if is_detect_enabled:

            result = detect_main(
                std_video_path=std_video_path,
                batch_detect=_get_cfg(cfg, "predict_batch_size_detect_obb", int),
                batch_cls=_get_cfg(cfg, "predict_batch_size_classify", int),
                inference_device=_get_cfg(cfg, "inference_device"),
                detect_model_path=_get_cfg(cfg, "detect_model_path", Path),
                obb_model_path=_get_cfg(cfg, "obb_model_path", Path),
                cls_ex_model_path=_get_cfg(cfg, "cls_ex_model_path", Path),
                cls_break_model_path=_get_cfg(cfg, "cls_break_model_path", Path),
                skip_detect=_get_cfg(cfg, "skip_detect", _as_bool),
                skip_cls=_get_cfg(cfg, "skip_cls", _as_bool),
                skip_export_tracked_video=_get_cfg(cfg, "skip_export_tracked_video", _as_bool),
            )
            if not result.is_ok:
                return _fail(print_op_result(result))



        if is_analyze_enabled:

            result = analyze_main(
                std_video_path=std_video_path,
                bpm=_get_cfg(cfg, "bpm", float),
                is_big_touch=_get_cfg(cfg, "is_big_touch", _as_bool),
                chart_lv=_get_cfg(cfg, "chart_lv", int),
                base_denominator=_get_cfg(cfg, "base_denominator", int),
                duration_denominator=_get_cfg(cfg, "duration_denominator", int),
                inference_device=_get_cfg(cfg, "inference_device"),
                batch_touch_hold=_get_cfg(cfg, "predict_batch_size_touch_hold", int),
                touch_hold_model_path=_get_cfg(cfg, "touch_hold_model_path", Path),
                batch_cls=_get_cfg(cfg, "predict_batch_size_classify", int),
                cls_break_model_path=_get_cfg(cfg, "cls_break_model_path", Path),
                cls_ex_model_path=_get_cfg(cfg, "cls_ex_model_path", Path),
            )
            if not result.is_ok:
                return _fail(print_op_result(result))

        return True

    except Exception:
        return _fail(traceback.format_exc())


if __name__ == "__main__":
    # 跳过第一个参数（脚本路径）和第二个参数（root路径）
    result = main(sys.argv[2:])
    sys.exit(0 if result else 1)
