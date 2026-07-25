from ultralytics import YOLO
import time
import traceback
import torch.multiprocessing as tmp
from queue import Empty, Full

from ...schemas.op_result import OpResult, ok, err
from .note_definition import *



_FRAME_QUEUE_CAP = 20         # 输入: 待推理的视频帧 queue 上限 (detect/obb 各一条)
_RESULTS_QUEUE_CAP = 1000     # 输出: 推理结果 queue 上限
_INFER_EOF = None             # 
_PUT_TIMEOUT = 0.5            # tee put 单次超时 (周期检查 worker 健康)
_WORKER_JOIN_TIMEOUT = 10.0   # actor Process join 超时


def format_exit_line(p, role):
    """统一格式化 actor 死亡行: 打印原始 exitcode + win_code (仅负值还原 Windows NT 状态码)。

    role: 显示前缀 (如 'detect' / 'obb')。
    exitcode=None 表示进程刚启动/尚未生成; >0=Python sys.exit; <0=native 硬崩溃 (finally 不执行)。

    win_code 还原: Python 负数 exitcode 实为 Windows NT 状态码的 int32 解释
    (如 -1073741819 = 0xC0000005 access violation)。
    直接用 exitcode & 0xFFFFFFFF 取无符号 32 位补码即可还原。
    """
    exitcode = p.exitcode
    win_code = (exitcode & 0xFFFFFFFF) if exitcode is not None and exitcode < 0 else None
    win_str = f"0x{win_code:08X}" if win_code is not None else "N/A"
    return f"[{role}] actor died, exitcode={exitcode} win_code={win_str}"


def _drain_queue(q):
    """非阻塞排空队列, 返回所有移除项 (调用方可丢弃)。get_nowait 跑空即止。"""
    items = []
    while True:
        try:
            items.append(q.get_nowait())
        except Empty:
            break
    return items


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


# ---------------------------------------------------------------------------
# 推理 worker (模块级函数, spawn pickle 友好)
# ---------------------------------------------------------------------------

def _infer_worker_target(model_path, task_name,
                         batch_size, device,
                         in_queue, results_queue,
                         progress_val, coord_scale, stop_event):
    """模型推理 actor。

    循环:
    - 从 in_queue 取 batch (None 哨兵即 EOF)
    - model.predict + 解析为 Note_Geometrys (帧序由 next_frame_idx 显式维护)
    - results_queue.put((note_geometry, task_name))
    - progress_val.value 推进

    异常: 捕获 BaseException (含 KeyboardInterrupt) 后把 traceback + 失败帧号
    经 results_queue 转发为 ("__error__", task_name, tb_str, next_frame_idx),
    再 raise 重抛以保留 exitcode 语义 (Python 异常→1, native 硬崩溃→负值, 后者走不到这里)。
    正常退出: results_queue.put(("__done__", task_name))。
    """
    next_frame_idx = 0
    try:
        model = YOLO(model_path, task=task_name)
        imgsz_val = get_imgsz(task_name)

        while True:
            if stop_event is not None and stop_event.is_set():
                break
            batch = in_queue.get()
            if batch is _INFER_EOF:
                break

            results = model.predict(
                source=batch,
                batch=batch_size,
                device=device,
                imgsz=imgsz_val,
                max_det=50,
                verbose=False,
                half=True,
            )
            for i, result in enumerate(results):
                frame_number = next_frame_idx + i
                note_geometrys = _parse_detections_to_note_geometrys(
                    result, frame_number, task_name, coord_scale)
                for ng in note_geometrys:
                    results_queue.put((ng, task_name))
                progress_val.value = frame_number + 1

            next_frame_idx += len(batch)

        results_queue.put(("__done__", task_name))
    except BaseException:
        # Python 异常 (含模型加载失败、predict 抛错、解析错误)。
        # 转发 traceback + 当前 next_frame_idx (= 即将处理的 batch 起始帧),
        # 便于父进程定位失败位置; 再 raise 让进程 exitcode 反映异常性质。
        tb_str = traceback.format_exc()
        try:
            results_queue.put(("__error__", task_name, tb_str, next_frame_idx))
        except Exception:
            pass  # 父进程已死 / 队列管道断裂, 不再二次崩溃
        raise


# ---------------------------------------------------------------------------
# Inferencer: 封装 detect/obb 双进程推理, 对 main 只暴露 put_batch/get_results
# ---------------------------------------------------------------------------

class Inferencer:
    """推理门面: 内部 tee 到 detect/obb 两个并行 worker, 对 main 屏蔽所有队列细节。

    与 main 的交互契约 (全部 OpResult):
    - create(...)            : 构造 (classmethod; __init__ 不能返回 OpResult)。
    - put_batch(batch)       : main 喂 batch; 生产阶段 worker 报错经此返回 err。
    - get_results(timeout)   : main 收集结果; 排空阶段 (EOF 后) worker 报错经此返回 err。
    - progress               : (detect_done_frames, obb_done_frames), 仅打印用。
    - send_eof()             : best-effort 投 None 到两条 in_queue, void。
    - stop()                 : 幂等 terminate + join, void。

    模型加载 (YOLO(...)) 在 worker 进程内完成 (spawn + CUDA 隔离),
    故 create() 只能捕获参数错/spawn 错, 模型加载失败需经 put_batch/get_results 才能暴露。

    进程间协议 (沿用旧实现):
    - in  EOF   : None
    - out data  : (Note_Geometry, task_name)
    - out ctrl  : ("__done__", name) / ("__error__", name, tb_str, frame_idx)
    """

    @classmethod
    def create(cls, detect_model_path, obb_model_path,
               batch_size, device, coord_scale) -> OpResult:
        """构造 Inferencer。仅校验参数 + 启动进程; 不等待模型加载完成。

        Args:
            detect_model_path / obb_model_path: 模型文件路径 (worker 内 YOLO 加载)。
            batch_size: 推理 batch 大小 (必须 >0, 且与 decoder 一致)。
            device: ultralytics device 字符串 (如 'cuda:0' / 'cpu')。
            coord_scale: 坐标还原系数 (decode_imgsz → 视频原始尺寸)。

        Returns:
            ok(value=Inferencer) 或 err。
        """
        if batch_size <= 0:
            return err(f"[inferencer] batch_size 必须为正整数, got {batch_size}")
        # detect/obb 共享解码 imgsz 必须一致 (decoder 只产一种分辨率)
        if get_imgsz('detect') != get_imgsz('obb'):
            return err("detect/obb imgsz 不一致, 共享解码需相同 imgsz")

        try:
            self = cls.__new__(cls)  # 绕过 __init__, 自定义构造
            self._batch_size = batch_size
            self._coord_scale = coord_scale
            self._q_detect = tmp.Queue(maxsize=_FRAME_QUEUE_CAP)
            self._q_obb = tmp.Queue(maxsize=_FRAME_QUEUE_CAP)
            self._results_queue = tmp.Queue(maxsize=_RESULTS_QUEUE_CAP)
            self._stop_event = tmp.Event()
            self._progress_detect = tmp.Value('i', 0)
            self._progress_obb = tmp.Value('i', 0)

            self._p_detect = tmp.Process(
                target=_infer_worker_target,
                args=(detect_model_path, 'detect', batch_size, device,
                      self._q_detect, self._results_queue,
                      self._progress_detect, coord_scale, self._stop_event),
                daemon=True,
            )
            self._p_obb = tmp.Process(
                target=_infer_worker_target,
                args=(obb_model_path, 'obb', batch_size, device,
                      self._q_obb, self._results_queue,
                      self._progress_obb, coord_scale, self._stop_event),
                daemon=True,
            )

            # 状态机标志 (sticky)
            self._finished = set()          # 已 done/error/判死的 task_name, 去重计数
            self._done_count = 0            # 已完成 worker 数, 达 2 即 is_done
            self._failed = False            # 任一 worker 报错/判死
            self._closed = False            # stop() 已调用
            self._errors = []               # list[(name, tb_str, frame_idx)]
            self._exit_lines = []           # list[str]  native 崩溃诊断行
            self._pending_results = []      # list[(Note_Geometry, task_name)]  get_results 缓冲

            self._p_detect.start()
            self._p_obb.start()
        except Exception as e:
            # spawn 失败兜底: 清理已起的进程
            try:
                self.stop()  # type: ignore[name-defined]
            except Exception:
                pass
            return err(f"[inferencer] create failed: {e}", error_raw=e)

        return ok(value=self)

    # --- 属性 ---------------------------------------------------------------

    @property
    def is_done(self) -> bool:
        """两个 worker 是否都已结束 (无论成功/失败)。"""
        return self._done_count >= 2

    @property
    def is_failed(self) -> bool:
        """是否发生过任何 worker 报错/判死。"""
        return self._failed

    @property
    def progress(self) -> tuple:
        """(detect_done_frames, obb_done_frames), 仅用于打印进度。"""
        return (self._progress_detect.value, self._progress_obb.value)

    @property
    def errors(self) -> list:
        """list[(name, tb_str, frame_idx)] — worker Python 异常列表。"""
        return self._errors

    @property
    def exit_lines(self) -> list:
        """list[str] — native 硬崩溃诊断行 (format_exit_line 输出)。"""
        return self._exit_lines

    # --- 内部: 派发一个 results_queue item -----------------------------------

    def _dispatch(self, item):
        """分类处理一个 results_queue item, 更新状态机标志。

        - ("__done__", name)  → 标记 worker 完成
        - ("__error__", name, tb_str, frame_idx) → Python 异常, 标记 worker 死亡
        - 其它 (Note_Geometry, task_name) → append 到 _pending_results
        """
        if isinstance(item, tuple) and len(item) >= 2:
            if item[0] == "__done__":
                _, name = item
                self._mark_finished(name)
                return
            if item[0] == "__error__":
                _, name, tb_str, frame_idx = item
                self._errors.append((name, tb_str, frame_idx))
                self._mark_finished(name)
                self._failed = True
                return
        self._pending_results.append(item)

    def _mark_finished(self, name):
        """标记一个 worker 已结束 (去重计数)。"""
        if name not in self._finished:
            self._finished.add(name)
            self._done_count += 1

    # --- 内部: 健康检查 (put_batch 与 get_results 共用) ----------------------

    def _check_health(self) -> bool:
        """非阻塞排空 results_queue + 进程存活兜底。返回是否仍健康 (not _failed)。

        进程存活兜底覆盖 native 硬崩溃 (worker 死了没来得及发 __error__);
        Python 异常已由 __error__ 先行处理, 这里只是兜底。
        """
        # 1. 非阻塞排空 results_queue
        for item in _drain_queue(self._results_queue):
            self._dispatch(item)

        # 2. 进程存活兜底: worker 已死但未登记 → 判死亡
        for name, p in (('detect', self._p_detect), ('obb', self._p_obb)):
            if name not in self._finished and not p.is_alive():
                self._exit_lines.append(format_exit_line(p, name))
                self._mark_finished(name)
                self._failed = True

        return not self._failed

    def _first_failure_msg(self):
        """生成首个失败原因的简短消息 (供 put_batch/get_results 的 err)。"""
        if self._errors:
            name, tb_str, frame_idx = self._errors[0]
            return f"[inferencer] {name} error @ frame={frame_idx}:\n{tb_str}"
        if self._exit_lines:
            return f"[inferencer] {self._exit_lines[0]}"
        return "[inferencer] unknown failure"

    # --- 对 main 的公开 API --------------------------------------------------

    def put_batch(self, batch) -> OpResult:
        """tee batch 到 detect/obb 两条 in_queue。生产阶段 worker 报错经此返回 err。

        Returns:
            ok()              — tee 成功
            err(...)          — worker 已报错/判死, 或 stop_event 已触发
        """
        if self._closed:
            return err("[inferencer] put_batch: already closed.")
        if not self._check_health():
            return err(self._first_failure_msg())

        # 内部 tee: 把 batch 投到两条 in_queue, 每条带 _PUT_TIMEOUT 重试
        # 仅在 Full 重试时周期性 _check_health (避免每次 put 都排空的开销)
        for q in (self._q_detect, self._q_obb):
            while True:
                try:
                    q.put(batch, block=True, timeout=_PUT_TIMEOUT)
                    break
                except Full:
                    if self._stop_event.is_set():
                        return err("[inferencer] put_batch: stop_event set.")
                    if not self._check_health():
                        return err(self._first_failure_msg())
                    continue
                except Exception as e:
                    # 队列管道断裂 (worker 已死/被 terminate) → 判失败
                    self._failed = True
                    return err(f"[inferencer] put_batch: queue error: {e}", error_raw=e)
        return ok()

    def get_results(self, timeout=0.0) -> OpResult:
        """收集 results_queue 中已就绪的推理结果。

        Args:
            timeout: 阻塞等待首个结果的超时 (秒)。0 = 非阻塞排空。

        Returns:
            ok(value=list)    — list[(Note_Geometry, task_name)], 可能为空
            err(value=list)   — worker 报错/判死; value 仍带回已收集的部分结果
        """
        if self._closed:
            return err("[inferencer] get_results: already closed.", value=None)

        if timeout > 0:
            try:
                item = self._results_queue.get(timeout=timeout)
                self._dispatch(item)
            except Empty:
                pass

        healthy = self._check_health()
        snapshot = self._pending_results
        self._pending_results = []

        if not healthy:
            return err(self._first_failure_msg(), value=snapshot)
        return ok(value=snapshot)

    def send_eof(self):
        """best-effort 向两条 in_queue 投 None (EOF)。worker 收到即正常退出。

        void: 即使投递失败也不抛 (后续 get_results 的健康检查会兜底报错)。
        stop_event 已触发时先排空队列避免永久阻塞。
        """
        for q in (self._q_detect, self._q_obb):
            deadline = time.monotonic() + 5.0
            while True:
                if self._stop_event.is_set():
                    _drain_queue(q)
                try:
                    q.put(_INFER_EOF, block=True, timeout=2.0)
                    break
                except Full:
                    if time.monotonic() > deadline:
                        break

    def stop(self):
        """幂等清理: stop_event.set() → 存活者 terminate() → join(timeout)。"""
        if self._closed:
            return
        self._closed = True
        self._stop_event.set()
        for p in (self._p_detect, self._p_obb):
            if p is not None and p.is_alive():
                p.terminate()
        for p in (self._p_detect, self._p_obb):
            if p is not None:
                p.join(timeout=_WORKER_JOIN_TIMEOUT)
