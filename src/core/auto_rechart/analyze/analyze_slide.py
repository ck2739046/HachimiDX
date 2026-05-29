import numpy as np
from collections import defaultdict

from ultralytics import YOLO

from ..detect.note_definition import *
from ..detect.classify import classify_note_path
from .shared_context import *
from .analyze_tap import analyze_tap_time

from .analyze_slide_time import analyze_slide_tail_start_end_time
from .analyze_slide_movement import analyze_slide_tail_movement_syntax, is_line_pass_a_zone_endpoint



def analyze_slide_time(shared_context, slide_head_data, slide_tail_data, bpm,
                       cls_ex_model_path, cls_break_model_path,
                       inference_device, batch_cls):

    # 处理星星头的时间，视为 tap 处理
    slide_head_info = analyze_tap_time(shared_context, slide_head_data)
    # 处理星星尾的时间
    slide_tail_info = analyze_slide_tail_time(shared_context, slide_tail_data)

    # slide delay
    delay_index = 0.25 # 标准延迟是0.25拍
    one_beat_Msec = 60 / bpm * 1000 * 4
    std_delay = one_beat_Msec * delay_index
    max_delay = std_delay * 1.2
    min_delay = std_delay * 0.8
    split_delay_tolerance = one_beat_Msec / 16 # 16分
    
    # 第一轮头尾匹配
    matched_tails_by_head, unmatched_heads = slide_head_tail_match_by_time(
        shared_context, slide_head_info, slide_tail_info, std_delay, min_delay, max_delay
    )
    
    if unmatched_heads:
        # 一笔画的多个星星尾可能会被视为一条，可能需要分割
        matched_tails_by_head, unmatched_heads = try_split_slide_tail(
            shared_context, matched_tails_by_head, unmatched_heads,
            std_delay, split_delay_tolerance,
            cls_ex_model_path, cls_break_model_path,
            inference_device, batch_cls,
        )

    # 合并头尾，生成最终slide信息
    final_slide_info = merge_slide_info(shared_context, matched_tails_by_head, unmatched_heads)

    return final_slide_info





def analyze_slide_tail_time(shared_context, slide_tail_data):
    '''
    返回格式:
    dict{
        key: 同 preprocess_slide_tail_data,
        value: (start_time, end_time, note_path)
    }
    '''
    slide_tail_info = {}
    for key, note_path in slide_tail_data.items():

        start_time, end_time = analyze_slide_tail_start_end_time(shared_context, note_path, f'A{key[3]}', f'A{key[4]}')
        if start_time is None or end_time is None:
            print(f"analyze_slide_tail_time: failed to analyze start/end time for track id {key[0]}")
            continue

        slide_tail_info[key] = (start_time, end_time, note_path)
    
    return slide_tail_info







def slide_head_tail_match_by_time(shared_context, slide_head_info, slide_tail_info,
                                  std_delay, min_delay, max_delay):
    '''
    匹配slide头尾

    输入:
        slide_head_info: dict{
            key: (head_track_id, note_type, note_variant, head_position),
            value: head_end_time
        }
        slide_tail_info: dict{
            key: (tail_track_id, note_type, note_variant, tail_start_position_id, tail_end_position_id),
            value: (tail_start_time, tail_end_time, note_path)
        }

    delay = tail_start_time - head_end_time
    匹配规则1：一个tail最多只能匹配到一个head，但是一个head可以匹配多个tail
    匹配规则2：head_position = tail_start_position
    匹配规则3：min_delay < delay < max_delay
    匹配规则4：如果tail与多个head都符合匹配条件，选择delay与std_delay最接近的head

    返回:
        matched_tails_by_head: dict{
            key: (head_key, head_value),
            value: list of (tail_key, tail_value)
        }
        unmatched_heads: list of (head_key, head_value)
    '''
    # print(f"\n=== Matching Parameters ===")
    # print(f"BPM: {bpm}, One Beat: {one_beat_Msec:.2f} ms")
    # print(f"Std Delay: {std_delay:.2f} ms")
    # print(f"Min Delay: {min_delay:.2f} ms")
    # print(f"Max Delay: {max_delay:.2f} ms")
    # print(f"===========================\n")

    # 先按位置分组head数据
    # 这样后续tail查找head时，只会在对应位置的head中查找，减少计算量
    head_by_position = defaultdict(list)
    for head_key, head_value in slide_head_info.items():
        head_track_id, note_type, note_variant, head_position = head_key
        head_end_time = head_value
        # 此处 head_position 是带有 variant 后缀的，如 1bx，需要去除后缀
        pos_id = str(head_position[0])
        head_by_position[pos_id].append((head_key, head_value))

    # 收集每个 head 匹配到的 tail 列表
    matched_tails_by_head = defaultdict(list)

    # 匹配规则1: 一个tail最多只能匹配到一个head
    # 所以是遍历所有tail，寻找匹配的head
    for tail_key, tail_value in slide_tail_info.items():

        tail_track_id, note_type, note_variant, tail_start_position_id, tail_end_position_id = tail_key
        tail_start_time, tail_end_time, note_path = tail_value

        # 匹配规则2: head_position = tail_start_position
        tail_start_position = str(tail_start_position_id)
        if tail_start_position not in head_by_position.keys():
            print(f"[{tail_track_id}] Tail not match: No heads at position {tail_start_position}")
            continue

        # 如果有在 tail_start_pos 有相同位置的 head
        # 遍历这些 head，寻找能匹配上 tail 的 head
        best_head = None
        best_delay_diff = float('inf')
        for head_key, head_value in head_by_position[tail_start_position]:
            # 匹配规则3: min_delay < delay < max_delay
            head_end_time = head_value
            delay = tail_start_time - head_end_time
            if not (min_delay < delay < max_delay):
                continue
            # 匹配规则4: 与std_delay最接近
            delay_diff = abs(delay - std_delay)
            if delay_diff < best_delay_diff:
                best_delay_diff = delay_diff
                best_head = (head_key, head_value)

        if best_head is None:
            print(f"[{tail_track_id}] Tail not match: No heads match delay at position {tail_start_position}")
            continue

        # 找到了匹配的head，写入匹配结果
        matched_tails_by_head[best_head].append((tail_key, tail_value))


    # 收集所有未匹配的星星头
    unmatched_heads = []
    for head_key, head_value in slide_head_info.items():
        # 看看这个 head 是否已匹配
        _ = matched_tails_by_head.get((head_key, head_value), None)
        if _ is None:
            unmatched_heads.append((head_key, head_value))

    return matched_tails_by_head, unmatched_heads









def try_split_slide_tail(shared_context, matched_tails_by_head: dict, unmatched_heads: list,
                         std_delay: float, split_delay_tolerance: float,
                         cls_ex_model_path, cls_break_model_path,
                         inference_device, batch_cls):
    '''
    一笔画的多个星星尾可能会被视为一条，可能需要分割

    输入:
        matched_tails_by_head: dict{
            key: (head_key, head_value),
            value: list of (tail_key, tail_value)
        }
        unmatched_heads: list of (head_key, head_value)

    说明:
        head_key: (head_track_id, note_type, note_variant, head_position),
        head_value: head_end_time
        tail_key: (tail_track_id, note_type, note_variant, tail_start_position_id, tail_end_position_id)
        tail_value: (tail_start_time, tail_end_time, note_path)

    分割:
        unmatched_heads 按 head_end_time 从大到小排序
        这样 later head 触发 tail 分割后，新的 tail 还能继续被 earlier head 触发分割

        规则1: 找到时间戳在 head_end_time + std_delay ± split_delay_tolerance 内的视频帧
               tail 必须在这些视频帧内经过了 head_position A 区, 触发分割
        规则2: 如果一个 slide 触发多个 tail 分割, 则全部都分割
               因为一个 head 可以匹配多个 tail (对应 head_tail_match 匹配规则1)
        # 规则3: 一个 tail 在一个 unit 中只能被分割一次
               # unit 是指从一个 A 区移动到另一个 A 区
               # 如果一个 unit 被多个 head 触发分割, 选取与 std_delay 最接近的 head 分割
               # 此规则暂不考虑，现实中不会遇到

    返回:
        matched_tails_by_head: dict{
            key: (head_key, head_value),
            value: list of (tail_key, tail_value)
        }
        unmatched_heads: list of (head_key, head_value)
    '''
    
    print(f"try_split_slide_tail: trying to split tails for {len(unmatched_heads)} unmatched heads")

    # 加载模型
    cls_ex_model = YOLO(cls_ex_model_path, task="classify")
    cls_break_model = YOLO(cls_break_model_path, task="classify")

    next_track_id = shared_context.max_track_id + 1

    # 按 head_end_time 从大到小排序
    unmatched_heads = sorted(unmatched_heads, key=lambda x: x[1], reverse=True)

    for unmatched_head_key, unmatched_head_value in list(unmatched_heads):
        head_track_id, note_type, note_variant, head_position = unmatched_head_key
        head_end_time = unmatched_head_value

        head_position_A_zone = f"A{head_position[0]}"

        # 规则1: 找到时间戳在 head_end_time + std_delay ± split_delay_tolerance 内的视频帧
        target_time = head_end_time + std_delay
        split_start_Msec = target_time - split_delay_tolerance
        split_end_Msec = target_time + split_delay_tolerance
        try:
            target_frames = shared_context.get_frames_in_msec_range(split_start_Msec, split_end_Msec)
        except Exception as e:
            print(f"try_split_slide_tail: Error occurred while fetching frames: {e}")
            continue

        print(f"try_split_slide_tail: unmatched head {head_track_id} looking for tails in frames {target_frames[0]} to {target_frames[-1]}")
        
        # 遍历所有 tail
        is_head_matched = False
        for (matched_head_key, matched_head_value), tail_list in list(matched_tails_by_head.items()):
            for matched_tail_key, matched_tail_value in tail_list:
                tail_track_id, tail_note_type, tail_note_variant, tail_start_position_id, tail_end_position_id = matched_tail_key
                tail_start_time, tail_end_time, note_path = matched_tail_value

                # 规则1: tail 必须在这些视频帧内经过了 head_position A 区, 才能触发分割
                frame_num = None
                for k in range(1, len(note_path)):
                    curr = note_path[k]
                    if curr['frame'] in target_frames:
                        prev = note_path[k - 1]
                        is_pass, A_zone = is_line_pass_a_zone_endpoint(
                            prev['cx'], prev['cy'],
                            curr['cx'], curr['cy'],
                            shared_context
                        )
                        if is_pass and A_zone == head_position_A_zone:
                            frame_num = curr['frame']
                            break
                
                if frame_num is None:
                    continue # 这个 tail 在触发分割的时间窗口内没有经过 head_position A 区，未触发分割

                # print(f"try_split_slide_tail: - head {head_track_id} triggered split of tail {tail_track_id} at frame {frame_num}")

                # 触发分割，生成新的 tail note_path
                new_note_path_early = [note for note in note_path if note['frame'] <= frame_num]
                new_note_path_late = [note for note in note_path if note['frame'] >= frame_num]

                # 检查分割: 两个路径必须都离开当前 A 区
                def is_valid_split(path):
                    has_left_a_zone = False
                    for note in path:
                        if note['position'] != head_position_A_zone:
                            has_left_a_zone = True
                            break
                    return has_left_a_zone
                
                if not is_valid_split(new_note_path_early) or not is_valid_split(new_note_path_late):
                    continue

                # 对这两个 tail 重新计算时间
                new_tail_start_time_early, new_tail_end_time_early = analyze_slide_tail_start_end_time(
                    shared_context, new_note_path_early, f"A{tail_start_position_id}", head_position_A_zone
                )
                if new_tail_start_time_early is None or new_tail_end_time_early is None:
                    print(f"try_split_slide_tail: - failed to analyze start/end time for tail {tail_track_id} at split {frame_num} frame")
                    continue

                new_tail_start_time_late, new_tail_end_time_late = analyze_slide_tail_start_end_time(
                    shared_context, new_note_path_late, head_position_A_zone, f"A{tail_end_position_id}"
                )
                if new_tail_start_time_late is None or new_tail_end_time_late is None:
                    print(f"try_split_slide_tail: - failed to analyze start/end time for tail {tail_track_id} at split {frame_num} frame")
                    continue

                # 分配新的 tail_track_id
                new_tail_track_id_early = tail_track_id
                new_tail_track_id_late = next_track_id
                next_track_id += 1 # update

                # 对新的 tail note paths 重新分裂
                new_tail_note_variant_early = _classify_note_path(
                    shared_context, new_note_path_early, (tail_track_id, tail_note_type),
                    cls_ex_model, cls_break_model, inference_device, batch_cls
                ) or tail_note_variant # fallback
                # if new_tail_note_variant_early:
                #     print(f"try_split_slide_tail: - re-classified early tail {new_tail_track_id_early} -> {new_tail_note_variant_early}")
                # else:
                #     new_tail_note_variant_early = tail_note_variant

                new_tail_note_variant_late = _classify_note_path(
                    shared_context, new_note_path_late, (tail_track_id, tail_note_type),
                    cls_ex_model, cls_break_model, inference_device, batch_cls
                ) or tail_note_variant # fallback
                # if new_tail_note_variant_late:
                #     print(f"try_split_slide_tail: - re-classified late tail {new_tail_track_id_late} -> {new_tail_note_variant_late}")
                # else:
                #     new_tail_note_variant_late = tail_note_variant

                # 生成新的 tail_key 和 tail_value
                new_tail_key_early = (new_tail_track_id_early, tail_note_type, new_tail_note_variant_early, tail_start_position_id, head_position[0])
                new_tail_value_early = (new_tail_start_time_early, new_tail_end_time_early, new_note_path_early)

                new_tail_key_late = (new_tail_track_id_late, tail_note_type, new_tail_note_variant_late, head_position[0], tail_end_position_id)
                new_tail_value_late = (new_tail_start_time_late, new_tail_end_time_late, new_note_path_late)

                # 更新 matched_tails_by_head
                matched_tails_by_head[(matched_head_key, matched_head_value)].remove((matched_tail_key, matched_tail_value))
                matched_tails_by_head[(matched_head_key, matched_head_value)].append((new_tail_key_early, new_tail_value_early))
                matched_tails_by_head[(unmatched_head_key, unmatched_head_value)].append((new_tail_key_late, new_tail_value_late))
                is_head_matched = True
                print(f"try_split_slide_tail: - split tail {tail_track_id} at frame {frame_num} triggered by head {head_track_id} -> {new_tail_track_id_early}/{new_tail_track_id_late}")

        if is_head_matched:
            unmatched_heads.remove((unmatched_head_key, unmatched_head_value))
        else:
            print(f"try_split_slide_tail: - unmatched head {head_track_id} not split any tail")

    return matched_tails_by_head, unmatched_heads









def _classify_note_path(shared_context, note_path, tract_data_key,
                       cls_ex_model, cls_break_model,
                       inference_device, batch_cls):

    try:
        note_geometry_list = shared_context.track_data.get(tract_data_key, None)
        if note_geometry_list:
            frames = {n['frame'] for n in note_path}
            target_geometry_list = [geo for geo in note_geometry_list if geo.frame in frames]
            target_geometry_list.sort(key=lambda g: g.frame)
            if target_geometry_list:
                variant = classify_note_path(
                    target_geometry_list,
                    shared_context.std_video_path,
                    cls_ex_model, cls_break_model,
                    inference_device, batch_cls,
                )
                if variant:
                    return variant
        
        return None
    except Exception as e:
        print(f"try_split_slide_tail: failed to re-classify tail {tract_data_key[0]}: {e}")
        return None







def merge_slide_info(shared_context, matched_tails_by_head: dict, unmatched_heads: list):
    '''
    合并slide头尾信息

    输入:
        matched_tails_by_head: dict{
            key: (head_key, head_value),
            value: list of (tail_key, tail_value)
        }
        unmatched_heads: list of (head_key, head_value)

    说明:
        head_key: (head_track_id, note_type, note_variant, head_position),
        head_value: head_end_time
        tail_key: (tail_track_id, note_type, note_variant, tail_start_position_id, tail_end_position_id)
        tail_value: (tail_start_time, tail_end_time, note_path)

    返回格式:
    dict{
        # 匹配的 head_tail 组合（同 head 多 tail 用 * 聚合）
        key: (head_track_id, note_type, note_variant, merged_movement_syntax),
        value: (time, duration_1, duration_2, ...)

        # 未匹配的head
        key: (head_track_id, note_type, note_variant, head_position),
        value: time
    }
    '''

    def get_suffix(note_variant: NoteVariant):

        if note_variant == NoteVariant.NORMAL:
            suffix = ''
        elif note_variant == NoteVariant.BREAK:
            suffix = 'b'
        elif note_variant == NoteVariant.EX:
            suffix = 'x'
        elif note_variant == NoteVariant.BREAK_EX:
            suffix = 'bx'
        else:
            suffix = '?'
        
        return suffix




    final_slide_info = {}

    # 将匹配成功的 head/tail 聚合写入 final_slide_info
    for (head_key, head_value), tail_list in matched_tails_by_head.items():
        head_track_id, note_type, note_variant, head_position = head_key
        head_end_time = head_value

        head_start_pos = str(head_position[0])
        head_prefix = f"{head_start_pos}{get_suffix(note_variant)}"

        segment_syntax_list = []
        segment_durations = []
        for tail_key, tail_value in tail_list:
            tail_track_id, tail_note_type, tail_note_variant, tail_start_position_id, tail_end_position_id = tail_key
            tail_start_time, tail_end_time, note_path = tail_value

            # 分析 tail 运动语法
            tail_movement_syntax = analyze_slide_tail_movement_syntax(
                shared_context, note_path, f"A{tail_start_position_id}", f"A{tail_end_position_id}", tail_track_id
            )
            if not tail_movement_syntax:
                print(f"merge_slide_info: failed to analyze movement syntax for tail track id {tail_track_id}")
                continue

            seg_full_syntax = f"{head_start_pos}{get_suffix(note_variant)}{tail_movement_syntax}{get_suffix(tail_note_variant)}"
            segment_syntax_list.append(seg_full_syntax)
            segment_durations.append(tail_end_time - tail_start_time)

        if not segment_syntax_list:
            # 所有 tail 均未生成有效语法，跳过此 head
            continue

        # 组装链式语法（仅语法，不含时值）
        merged_movement_syntax = segment_syntax_list[0] # 第一个segment完整保留
        for seg_full_syntax in segment_syntax_list[1:]:
            # 尝试删除后续的同头星星的的起始头
            seg_tail_syntax = None
            if seg_full_syntax.startswith(head_prefix):
                seg_tail_syntax = seg_full_syntax[len(head_prefix):]
            if not seg_tail_syntax:
                # 前缀剥离失败，回退为 '/' 连接整段语法
                merged_movement_syntax += f"/{seg_full_syntax}"
                continue
            merged_movement_syntax += f"*{seg_tail_syntax}"

        key = (head_track_id, note_type, note_variant, merged_movement_syntax)
        value = (head_end_time, *segment_durations)
        final_slide_info[key] = value

    

    # 将未匹配的 head 直接写入 final_slide_info
    for head_key, head_value in unmatched_heads:
        head_track_id, note_type, note_variant, head_position = head_key
        head_end_time = head_value

        full_movement_syntax = f"{head_position}$"
        key = (head_track_id, note_type, note_variant, full_movement_syntax)
        value = head_end_time
        final_slide_info[key] = value



    # # 打印final_slide_info
    # print("\n=== Final Slide Info ===")
    # for (track_id, class_id, movement_syntax), time_info in final_slide_info.items():
    #     if isinstance(time_info, tuple):
    #         head_end_time, tail_start_time, tail_end_time = time_info
    #         print(f"Slide Note: Track ID {track_id}, Class ID {class_id}, Movement {movement_syntax}, Head End Time {head_end_time:.2f} ms, Tail Start Time {tail_start_time:.2f} ms, Tail End Time {tail_end_time:.2f} ms")
    #     else:
    #         head_end_time = time_info
    #         print(f"Single Slide Note: Track ID {track_id}, Class ID {class_id}, Movement {movement_syntax}, Head End Time {head_end_time:.2f} ms")

    return final_slide_info
