import cv2
from ultralytics import YOLO
import os
import numpy as np
import time


def detect_video(
    model_path: str,
    video_path: str,
    output_path: str,
    device: str,
    show_progress: bool,
    task: str,
    batch: int
):
    """
    使用YOLO模型对视频进行目标检测，并在原始视频上绘制检测框后输出新视频。

    Args:
        model_path (str): YOLO模型文件的路径（例如：'best.pt'）
        video_path (str): 输入视频文件的路径
        output_path (str, optional): 输出视频文件的路径。如果为None，则自动生成：
            <视频目录>/<视频名>_detected.mp4
        conf_threshold (float): 置信度阈值，低于此阈值的检测框将被过滤
        device (str): 运行设备，例如 'cpu', 'cuda', 'cuda:0'
        show_progress (bool): 是否在控制台显示处理进度

    Returns:
        str: 输出视频的路径

    Raises:
        FileNotFoundError: 如果模型文件或视频文件不存在
        RuntimeError: 如果视频处理过程中出现错误
    """
    # 1. 检查输入文件是否存在
    if not os.path.exists(model_path):
        raise FileNotFoundError(f"模型文件不存在: {model_path}")
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"视频文件不存在: {video_path}")

    # 2. 加载YOLO模型
    if show_progress:
        print(f"加载模型: {model_path}")
    model = YOLO(model_path, task=task)

    # 3. 打开视频文件
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"无法打开视频文件: {video_path}")

    # 获取视频属性
    fps = int(cap.get(cv2.CAP_PROP_FPS))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()

    # 4. 设置输出路径
    if output_path is None:
        video_dir = os.path.dirname(video_path)
        video_name = os.path.splitext(os.path.basename(video_path))[0]
        output_path = os.path.join(video_dir, f"{video_name}_detected.mp4")

    # 确保输出目录存在
    output_dir = os.path.dirname(output_path)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir)

    # 5. 创建视频写入器
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')  # MP4编码
    out = cv2.VideoWriter(output_path, fourcc, fps, (width, height))
    if not out.isOpened():
        raise RuntimeError(f"无法创建输出视频文件: {output_path}")

    if show_progress:
        print(f"开始处理视频: {video_path}")
        print(f"视频信息: {width}x{height}, {fps} FPS, 总帧数: {total_frames}")
        print(f"输出路径: {output_path}")

    frame_count = 0
    start_time = time.time()
    try:
        # 使用YOLO直接对视频进行流式推理
        yolo_results_generator = model.predict(
            source=video_path,
            stream=True,
            batch=batch,
            imgsz=960,
            device=device,
            verbose=False,
            half=True
        )

        for result in yolo_results_generator:
            if result.orig_img is None:
                continue

            # 使用原始图像帧进行绘制
            frame = np.copy(result.orig_img)

            # 根据任务类型处理不同的结果格式
            if task == "obb":
                # OBB模型结果（带旋转的四边形）
                if result.obb is not None and len(result.obb) > 0:
                    # 转换为numpy批量获取数据
                    obb = result.obb.cpu().numpy()
                    xyxyxyxy = obb.xyxyxyxy  # (N, 4, 2) -> N个框，每个框4个点，每个点(x,y)
                    confs = obb.conf          # (N, 1)
                    cls_ids = obb.cls        # (N, 1)
                    
                    # 绘制四边形
                    for i in range(len(obb)):
                        # 获取四个点的坐标并提取出明确的 x1,y1~x4,y4
                        x1, y1 = float(xyxyxyxy[i, 0, 0]), float(xyxyxyxy[i, 0, 1])
                        x2, y2 = float(xyxyxyxy[i, 1, 0]), float(xyxyxyxy[i, 1, 1])
                        x3, y3 = float(xyxyxyxy[i, 2, 0]), float(xyxyxyxy[i, 2, 1])
                        x4, y4 = float(xyxyxyxy[i, 3, 0]), float(xyxyxyxy[i, 3, 1])
                        
                        points = np.array([
                            [x1, y1],
                            [x2, y2],
                            [x3, y3],
                            [x4, y4]
                        ], dtype=np.int32)
                        
                        conf = float(confs[i])
                        cls_id = int(cls_ids[i])
                        
                        # 根据类别ID选择颜色
                        color = (0, 255, 0)  # 绿色
                        # 绘制多边形
                        cv2.polylines(frame, [points], True, color, 2)
                        # 添加标签（类别和置信度）
                        label = f"{model.names[cls_id]} {conf:.2f}"
                        # 找到多边形最上方的点作为标签位置
                        label_x, label_y = min(points, key=lambda p: (p[1], p[0]))
                        cv2.putText(frame, label, (int(label_x), int(label_y) - 10),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
            else:
                # 标准检测模型结果（矩形框）
                if result.boxes is not None and len(result.boxes) > 0:
                    # 转换为numpy批量获取数据
                    boxes = result.boxes.cpu().numpy()
                    xyxy = boxes.xyxy    # shape: (N, 4)
                    confs = boxes.conf    # shape: (N, 1)
                    cls_ids = boxes.cls  # shape: (N, 1)
                    
                    # 绘制矩形框（转换为四个点）
                    for i in range(len(boxes)):
                        # 提取明确的 bbox 边界坐标构建四点
                        bx1, by1, bx2, by2 = map(float, xyxy[i])
                        
                        x1, y1 = bx1, by1
                        x2, y2 = bx2, by1
                        x3, y3 = bx2, by2
                        x4, y4 = bx1, by2
                        
                        # 将矩形转换为四个点
                        points = np.array([
                            [x1, y1],  # 左上角
                            [x2, y2],  # 右上角
                            [x3, y3],  # 右下角
                            [x4, y4]   # 左下角
                        ], dtype=np.int32)
                        
                        conf = float(confs[i])
                        cls_id = int(cls_ids[i])
                        
                        # 根据类别ID选择颜色
                        color = (0, 255, 0)  # 绿色
                        # 绘制多边形（四边形）
                        cv2.polylines(frame, [points], True, color, 2)
                        # 添加标签（类别和置信度）
                        label = f"{model.names[cls_id]} {conf:.2f}"
                        cv2.putText(frame, label, (int(x1), int(y1) - 10),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

            # 写入输出视频
            out.write(frame)

            frame_count += 1
            if show_progress and frame_count % 30 == 0:
                elapsed_time = time.time() - start_time
                current_fps = frame_count / elapsed_time if elapsed_time > 0 else 0
                print(f"已处理 {frame_count}/{total_frames} 帧 ({frame_count/total_frames*100:.1f}%) | 速度: {current_fps:.1f} FPS", end='\r')

    except Exception as e:
        raise RuntimeError(f"视频处理过程中出现错误: {e.__str__()}")

    finally:
        # 释放资源
        out.release()
        cv2.destroyAllWindows()

    if show_progress:
        print(f"处理完成！输出视频已保存至: {output_path}")
        print(f"总处理帧数: {frame_count}")

    return output_path


if __name__ == "__main__":

    try:
        output_path = detect_video(
            model_path=r"D:\git\aaa-HachimiDX-Convert\src\resources\models\detect1.onnx",
            video_path=r"D:\git\aaa-HachimiDX-Convert\test\初音ミクの暴走_standardized.mp4",
            output_path=r"D:\git\aaa-HachimiDX-Convert\test\初音ミクの暴走_standardized_out.mp4",
            device="0",
            show_progress=True,
            task="detect",
            batch=2
        )
        print(f"检测完成，输出视频: {output_path}")
    except Exception as e:
        print(f"错误: {e}")
        exit(1)



# 笔记本 12700h + rtx 3060 6g, 处理进度20%

# detect
# pt batch1, 27.2 fps, 0.8g
# pt batch2, 28.3 fps, 1.5g
# pt batch8, 27.5 fps, 2.7g
# pt batch24, 25.5 fps, 5.2g

# onnx_dml batch1, 21.4 fps, 1.3g
# onnx_dml batch2, 23.9 fps, 1.7g (导出batch1的模型)
# onnx_dml batch2, 22.7 fps, 1.7g (导出batch2的模型)
# onnx_dml batch2, 24.0 fps, 1.7g (导出batch4的模型)
# onnx_dml batch4, 23.7 fps, 2.2g

# engine batch1, 41.1 fps, 1.9g
# engine batch2, 47.0 fps, 2.0g
# engine batch4, 45.2 fps, 3.6g

# obb
# pt batch1, 49.3 fps, 1.1g
# pt batch2, 52.3 fps, 1.2g
# pt batch4, 50.9 fps, 1.4g

# engine batch1, 60.6 fps, 1.3g
# engine batch2, 64.4 fps, 1.6g
# engine batch4, 59.3 fps, 3.1g
# engine batch6, 60.3 fps, 3.1g

# 结论
# detect/obb 在 pt/engine 下都使用 batch 2
# export 需求显存 4g
# 在 onnx_dml 下使用 batch2 (export batch1)

