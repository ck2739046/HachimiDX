from ultralytics import YOLO
import sys
import time
from queue import Full

from ...schemas.op_result import OpResult, ok, err
from .note_definition import *
from ..tool import release_ncnn_vulkan, install_ort_cpu_thread_tuning
from src.core.tools import describe_exception, find_native_message, redirect_native_stderr



_PUT_TO_OUTPUT_QUEUE_TIMEOUT = 0.1
_OUTPUT_QUEUE_STALL_TIMEOUT = 60.0




def inference_worker_main(model_path, task_name, inference_device,
                          coord_scale,
                          half, model_backend,
                          input_queue, output_queue, control_queue,
                          progress_ref, stop_event):
    """
    模型推理 worker 主函数 (detect/obb 共用)

    循环流程:
    - 输入: 从 input_queue 取 batch
    - 处理: model.predict + 解析为 Note_Geometrys
    - 输出: (note_geometry, task_name) 放入 output_queue
    -       推进 progress_ref 数值

    会修改 output_queue 和 progress_ref.value, 其他参数均为只读
    """

    model = None
    results = None
    native_stderr = None
    try:
        # detect/obb 是两个兄弟进程, 必须各持一条私有管道:
        # 若共用父进程转发用的那条管道, 两边并发的 write 会互相插入, 字节序当场被破坏
        # (父进程即使已重定向, 也不会替子进程拆分)
        native_stderr = redirect_native_stderr(task_name)

        # 仅 ONNX CPU 后端关闭线程空转
        if model_backend == "ONNX CPU":
            install_ort_cpu_thread_tuning()

        last_frame_idx = 0  # 仅用于报错提示
        model = YOLO(model_path, task=task_name)
        imgsz_val = get_imgsz(task_name)

        while True:
            if stop_event is not None and stop_event.is_set():
                break
            batch = input_queue.get()
            if batch is None: break  # batch=None 表示 EOF

            # batch = List[(frame_idx, frame)]
            frame_indexes = [idx for idx, _ in batch]
            frames = [f for _, f in batch]
            last_frame_idx = frame_indexes[0]

            # 推理
            results = model.predict(
                source=frames,
                batch=len(frames),
                device=inference_device,
                half=half,
                imgsz=imgsz_val,
                max_det=50,
                verbose=False,
            )

            # 处理结果
            for i, result in enumerate(results):
                frame_number = frame_indexes[i]
                last_frame_idx = frame_number
                # 解析为 note_geometry
                note_geometrys = _parse_detections_to_note_geometrys(
                    result, frame_number, task_name, coord_scale
                )
                # 放入 output_queue
                for note_geometry in note_geometrys:
                    deadline = time.monotonic() + _OUTPUT_QUEUE_STALL_TIMEOUT
                    while True:
                        if stop_event is not None and stop_event.is_set():
                            return
                        try:
                            output_queue.put(
                                (note_geometry, task_name),
                                block=True,
                                timeout=_PUT_TO_OUTPUT_QUEUE_TIMEOUT,
                            )
                            break
                        except Full:
                            if time.monotonic() > deadline:
                                raise TimeoutError(
                                    f"{task_name} output queue remained full for "
                                    f"{_OUTPUT_QUEUE_STALL_TIMEOUT}s"
                                )
                            continue
                # 更新进度
                progress_ref.value = frame_number + 1

        # 正常结束
        time.sleep(0.1)
        control_queue.put(ok())

    except BaseException as e:  # 使用 base exception 捕获所有异常
        try:
            error_msg = f"{task_name} model inferencer failed to process frame {last_frame_idx}"
            # 原生日志的本地化消息只取结论一行; 非原生异常仍带栈
            control_queue.put(
                err(error_msg,
                    error_raw=find_native_message(e) or describe_exception(e))
            )
        except Exception:
            pass
        # 失败已经上报给 control_queue 了, 不要再 raise:
        # 那会让 multiprocessing._bootstrap 把同一份栈再打到 stderr 一次,
        # 且那份不经过错误还原, 末行只剩没有信息量的 UnicodeDecodeError
        sys.exit(1)
    finally:
        results = None
        model = None
        # 子进程可能在正常结束或 terminate 前走到这里, 都要恢复 fd 2 并收尾转发
        if native_stderr is not None:
            native_stderr.close()
        release_ncnn_vulkan(inference_device)



def _parse_detections_to_note_geometrys(result, frame_number, model_name, coord_scale):
    
    if model_name == 'detect':

        # 转换detect模型结果
        if result.boxes is None or len(result.boxes) == 0:
            return []
        # 转换为numpy批量获取数据
        boxes = result.boxes.cpu().numpy()
        xyxy = boxes.xyxy    # shape: (N, 4)
        xywh = boxes.xywh    # shape: (N, 4)
        conf = boxes.conf    # shape: (N, 1)
        raw_cls = boxes.cls  # shape: (N, 1)

        # 坐标从 decode_imgsz 空间还原到 _STD_VIDEO_SIZE 空间
        xyxy = xyxy * coord_scale
        xywh = xywh * coord_scale

        # 批量构建字典列表
        note_geometry_list = [
            Note_Geometry(
                frame=frame_number,
                note_type=map_model_class_to_note_type(model_name, int(raw_cls[i])),
                note_variant=NoteVariant.NORMAL, # 默认 normal
                conf=float(conf[i]),
                x1=float(xyxy[i, 0]),  # 左上角x
                y1=float(xyxy[i, 1]),  # 左上角y
                x2=float(xyxy[i, 2]),  # 右上角x
                y2=float(xyxy[i, 1]),  # 右上角y
                x3=float(xyxy[i, 2]),  # 右下角x
                y3=float(xyxy[i, 3]),  # 右下角y
                x4=float(xyxy[i, 0]),  # 左下角x
                y4=float(xyxy[i, 3]),  # 左下角y
                cx=float(xywh[i, 0]),
                cy=float(xywh[i, 1]),
                w=float(xywh[i, 2]),
                h=float(xywh[i, 3]),
                r=0.0
            )
            for i in range(len(boxes))
        ]
        return note_geometry_list
    
    else:

        # 转换obb模型结果
        if result.obb is None or len(result.obb) == 0:
            return [] 
        # 转换为numpy批量获取数据
        obb = result.obb.cpu().numpy()
        xyxyxyxy = obb.xyxyxyxy  # (N, 4, 2) -> N个框，每个框4个点，每个点(x,y)
        xywhr = obb.xywhr        # (N, 5)    -> N个框，每个框(x_center, y_center, w, h, r)
        conf = obb.conf          # (N, 1)
        raw_cls = obb.cls        # (N, 1)

        # 坐标从 decode_imgsz 空间还原到 _STD_VIDEO_SIZE 空间
        xyxyxyxy = xyxyxyxy * coord_scale
        xywhr[:, :4] = xywhr[:, :4] * coord_scale  # 旋转角 r 不缩放

        # 批量构建字典列表
        note_geometry_list = [
            Note_Geometry(
                frame=frame_number,
                note_type=map_model_class_to_note_type(model_name, int(raw_cls[i])),
                note_variant=NoteVariant.NORMAL, # 默认 normal
                conf=float(conf[i]),
                x1=float(xyxyxyxy[i, 0, 0]),  # 第1个点的x坐标
                y1=float(xyxyxyxy[i, 0, 1]),  # 第1个点的y坐标
                x2=float(xyxyxyxy[i, 1, 0]),  # 第2个点的x坐标
                y2=float(xyxyxyxy[i, 1, 1]),  # 第2个点的y坐标
                x3=float(xyxyxyxy[i, 2, 0]),  # 第3个点的x坐标
                y3=float(xyxyxyxy[i, 2, 1]),  # 第3个点的y坐标
                x4=float(xyxyxyxy[i, 3, 0]),  # 第4个点的x坐标
                y4=float(xyxyxyxy[i, 3, 1]),  # 第4个点的y坐标
                cx=float(xywhr[i, 0]),
                cy=float(xywhr[i, 1]),
                w=float(xywhr[i, 2]),
                h=float(xywhr[i, 3]),
                r=float(xywhr[i, 4]),         # rotation
            )
            for i in range(len(obb))
        ]
        return note_geometry_list
