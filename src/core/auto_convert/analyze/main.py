from pathlib import Path
import os

from ..detect.note_definition import *
from ...schemas.op_result import OpResult, ok, err
from .tool import *
from .shared_context import *

from .preprocess_tap import preprocess_tap_data
from .preprocess_touch import preprocess_touch_data
from .preprocess_hold import preprocess_hold_data
from .preprocess_touch_hold import preprocess_touch_hold_data
from .preprocess_slide import preprocess_slide_data

from .estimate_tap_speed import estimate_tap_DefaultMsec
from .estimate_touch_speed import estimate_touch_DefaultMsec

from .analyze_tap import analyze_tap_time
from .analyze_touch import analyze_touch_time
from .analyze_hold import analyze_hold_time
from .analyze_touch_hold import analyze_touch_hold_time
from .analyze_slide import analyze_slide_time

from .generate_maidata import generate_maidata




def main(std_video_path: Path,
         bpm: float,
         is_big_touch: bool,
         chart_lv: int,
         base_denominator: int,
         duration_denominator: int,
         inference_device,
         batch_touch_hold: int,
         touch_hold_model_path: Path,
         batch_cls: int = 16,
         cls_break_model_path: Path = None,
         cls_ex_model_path: Path = None,
        ) -> OpResult[None]:
    
    try:
        print('开始音符分析...')
        shared_context = create_shared_context(std_video_path, is_big_touch)
        tap_speed_print_info = "tap speed not estimated (no tap data)"
        touch_speed_print_info = "touch speed not estimated (no touch data)"

        note_SpeedIndex = None
        touch_SpeedIndex = None

        tap_info = {}
        touch_info = {}
        hold_info = {}
        touch_hold_info = {}
        slide_info = {}

        # preprocess data
        tap_data = preprocess_tap_data(shared_context)
        touch_data = preprocess_touch_data(shared_context)
        hold_data = preprocess_hold_data(shared_context)
        touch_hold_data = preprocess_touch_hold_data(
            shared_context,
            inference_device,
            batch_touch_hold,
            touch_hold_model_path,
        )
        slide_head_data, slide_tail_data = preprocess_slide_data(shared_context)

        # 分析音符流速
        if tap_data:
            shared_context.note_DefaultMsec, shared_context.note_OptionNotespeed, note_SpeedIndex, tap_speed_print_info = estimate_tap_DefaultMsec(shared_context, tap_data)
        if touch_data:
            shared_context.touch_DefaultMsec, shared_context.touch_OptionNotespeed, touch_SpeedIndex, touch_speed_print_info = estimate_touch_DefaultMsec(shared_context, touch_data)

        # 分析音符时间
        tap_info = analyze_tap_time(shared_context, tap_data)    
        touch_info = analyze_touch_time(shared_context, touch_data)
        hold_info = analyze_hold_time(shared_context, hold_data)
        touch_hold_info = analyze_touch_hold_time(shared_context, touch_hold_data)
        slide_info = analyze_slide_time(
            shared_context, slide_head_data, slide_tail_data, bpm,
            cls_ex_model_path, cls_break_model_path,
            inference_device, batch_cls
        )

        # merge/sort/save preprocess info
        final_note_info = merge_preprocess_info(std_video_path, tap_info, slide_info, touch_info, hold_info, touch_hold_info)
        # 如果没有检测到任何音符，提前返回
        if not final_note_info:
            print("No notes detected, skipping maidata.txt generation")
            return ok()

        # generate maidata
        generate_maidata(shared_context, bpm, chart_lv,
                         base_denominator, duration_denominator, final_note_info,
                         note_SpeedIndex, touch_SpeedIndex)

        print(tap_speed_print_info)
        print(touch_speed_print_info)
        
        return ok()
    
    except Exception as e:
        return err(f"Unexpected error in auto_convert > analyze > main", e)






def merge_preprocess_info(std_video_path, tap_info, slide_info, touch_info, hold_info, touch_hold_info):

    # 合并所有info
    all_notes_info = {**tap_info, **slide_info, **touch_info, **hold_info, **touch_hold_info}
    
    # 按时间排序                                              kv = (key, value), kv[1] = value
    # 这里排序后是一个 list of tuple (key, value)
    sorted_notes = sorted(all_notes_info.items(), key=lambda kv: kv[1][0] if isinstance(kv[1], tuple) else kv[1])

    # 保存合并后的整体预处理数据到文件
    note_preprocess_result_path = std_video_path.parent / 'note_preprocess_result.txt'
    if os.path.exists(note_preprocess_result_path):
        os.remove(note_preprocess_result_path)

    with open(note_preprocess_result_path, 'w', encoding='utf-8') as f:
        for (track_id, note_type, note_variant, position), time in sorted_notes:
            # 将time元组转为字符串
            if isinstance(time, tuple):
                time = ','.join(str(item) for item in time)

            # 写入格式：track_id, note_type, note_variant, position, time
            f.write(f"{track_id}, {note_type}, {note_variant}, {position}, {time}\n")

    print(f"note preprocess data saved to {note_preprocess_result_path}")

    return sorted_notes
