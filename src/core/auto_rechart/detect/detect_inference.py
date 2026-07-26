import time
import traceback
import torch.multiprocessing as tmp
from queue import Empty, Full
from dataclasses import dataclass
from enum import Enum

from ...schemas.op_result import OpResult, ok, err
from .note_definition import *
from .detect_inference_worker import inference_worker_main



_FRAME_QUEUE_CAP = 20         # 输入: 待推理的视频帧 queue 上限 (detect/obb 各一条)

_RESULTS_QUEUE_CAP = 1000     # 输出: 推理结果 queue 上限
_PUT_BATCH_TIMEOUT = 0.5
_WORKER_EXIT_TIMEOUT = 10.0










@dataclass
class _InferencerDeps:
    """create_inferencer 装配好参数打包供 Inferencer.__init__ 消费"""
    process_detect: "tmp.Process"
    process_obb: "tmp.Process"
    input_queue_detect: "tmp.Queue"
    input_queue_obb: "tmp.Queue"
    output_queue: "tmp.Queue"
    control_queue_detect: "tmp.Queue"
    control_queue_obb: "tmp.Queue"
    stop_event: "tmp.Event"
    progress_ref_detect: "tmp.Value"
    progress_ref_obb: "tmp.Value"



def create_inferencer(detect_model_path, obb_model_path,
                      batch_size, inference_device, coord_scale,
                    ) -> OpResult:
    """构造 Inferencer (而不是直接调用 Inferencer.__init__)"""

    if batch_size <= 0:
        return err(f"[inferencer] batch_size 必须为正整数, got {batch_size}")
    if get_imgsz('detect') != get_imgsz('obb'):
        return err("detect/obb imgsz 不一致, 两者必须相同")

    # 构造进程间共享对象
    input_queue_detect = tmp.Queue(maxsize=_FRAME_QUEUE_CAP)
    input_queue_obb = tmp.Queue(maxsize=_FRAME_QUEUE_CAP)
    output_queue = tmp.Queue(maxsize=_RESULTS_QUEUE_CAP)
    control_queue_detect = tmp.Queue()
    control_queue_obb = tmp.Queue()
    stop_event = tmp.Event()
    progress_ref_detect = tmp.Value('i', 0)
    progress_ref_obb = tmp.Value('i', 0)

    # 创建推理 worker 进程 (detect/obb)
    process_detect = tmp.Process(
        target=inference_worker_main,
        args=(detect_model_path, 'detect', batch_size, inference_device,
              coord_scale,
              input_queue_detect, output_queue, control_queue_detect,
              progress_ref_detect, stop_event),
        daemon=True,
    )
    process_obb = tmp.Process(
        target=inference_worker_main,
        args=(obb_model_path, 'obb', batch_size, inference_device,
              coord_scale,
              input_queue_obb, output_queue, control_queue_obb,
              progress_ref_obb, stop_event),
        daemon=True,
    )

    # 启动 workers
    started = []
    try:
        process_detect.start()
        started.append(process_detect)
        process_obb.start()
        started.append(process_obb)
    except Exception as e:
        failed_name = 'obb' if process_detect in started else 'detect'
        for p in started:
            if p.is_alive():
                p.terminate()
        return err(f"[inferencer] failed to start {failed_name} model worker: {e}", error_raw=e)

    # 真正创建 Inferencer
    deps = _InferencerDeps(
        process_detect, process_obb,
        input_queue_detect, input_queue_obb,
        output_queue,
        control_queue_detect, control_queue_obb,
        stop_event,
        progress_ref_detect, progress_ref_obb,
    )
    inferencer = Inferencer(deps)

    return ok(inferencer)












class WorkerStatus(Enum):
    RUNNING = 'running'   # 未结束
    DONE    = 'done'      # 正常结束
    FAILED  = 'failed'    # 报错


class Inferencer:
    """
    api:
    - create_inferencer(...)  -> OpResult[Inferencer]  (模块级工厂, 非本类方法)
    - put_batch(batch)        -> OpResult[None]
    - get_results(timeout=0)  -> OpResult[List[Tuple[Note_Geometry, str]]]
    - send_eof()              -> None
    - stop()                  -> None

    只读属性: is_done, is_failed, progress, failures, status
    """

    def __init__(self, deps: _InferencerDeps):
        """正常使用不应直接调本构造函数, 请通过 create_inferencer() 外部工厂函数创建"""

        # 进程间共享对象 (来自工厂装配的 deps)
        self._process_detect = deps.process_detect
        self._process_obb = deps.process_obb
        self._input_queue_detect = deps.input_queue_detect
        self._input_queue_obb = deps.input_queue_obb
        self._output_queue = deps.output_queue
        self._control_queue_detect = deps.control_queue_detect
        self._control_queue_obb = deps.control_queue_obb
        self._stop_event = deps.stop_event
        self._progress_ref_detect = deps.progress_ref_detect
        self._progress_ref_obb = deps.progress_ref_obb

        # worker 状态机: RUNNING / DONE / FAILED
        # sticky: 仅在 RUNNING 时可转 DONE/FAILED, 终态不可回退
        self._status = {'detect': WorkerStatus.RUNNING,
                        'obb':    WorkerStatus.RUNNING,}

        self._class_force_closed = False  # 仅在用户主动关闭时为 True
        self._failures = []               # 失败事件 - list[OpResult]
        self._pending_results = []        # get_results 缓冲 - list[(Note_Geometry, task_name)]





    @property
    def progress(self) -> tuple:
        """tuple[detect_done_frames, obb_done_frames]"""
        return (self._progress_ref_detect.value, self._progress_ref_obb.value)

    @property
    def failures(self) -> list:
        """list[OpResult] — 失败事件"""
        return self._failures






    def _set_status(self, name, status):
        if self._status[name] == WorkerStatus.RUNNING:
            self._status[name] = status


    def _dispatch_control_queue_result(self, name, op_result):
        """
        处理 control queue 中的 OpResult, 更新 worker 状态机
        - ok()  → 该 worker 正常结束 → DONE
        - err() → 该 worker 失败     → FAILED
        """
        if self._status[name] != WorkerStatus.RUNNING:
            return
        if op_result.is_ok:
            self._set_status(name, WorkerStatus.DONE)
        else:
            self._failures.append(op_result)
            self._set_status(name, WorkerStatus.FAILED)


    def _check_health(self) -> bool:
        """
        检查 inferencer 健康状态, 处理控制队列, 更新状态机
        返回:
            True  — 无 worker failed (允许done/running)
            False — 有 worker failed
        """
        # 1. 排空输出队列，存进 _pending_results
        self._pending_results.extend(_drain_queue(self._output_queue))

        # 2. 排空两条控制队列 → dispatch result
        for item in _drain_queue(self._control_queue_detect):
            self._dispatch_control_queue_result('detect', item)
        for item in _drain_queue(self._control_queue_obb):
            self._dispatch_control_queue_result('obb', item)

        # 3. 检查进程是否存活
        for name, p in (('detect', self._process_detect), ('obb', self._process_obb)):
            status_is_running = bool(self._status[name] == WorkerStatus.RUNNING)
            if status_is_running and not p.is_alive():
                self._failures.append(err(format_exit_line(p, name)))
                self._set_status(name, WorkerStatus.FAILED)

        is_failed = any(s == WorkerStatus.FAILED for s in self._status.values())
        return not is_failed



    def _first_failure_msg(self):
        """生成首个失败原因的简短消息 (供 put_batch/get_results 的 err)。"""
        if self._failures:
            return f"[inferencer] {self._failures[0].error_msg}"
        return "[inferencer] unknown failure"

    # --- 对 main 的公开 API --------------------------------------------------




    def put_batch(self, batch) -> OpResult:
        """tee batch 到 detect/obb 两条 input_queue"""

        if self._class_force_closed:
            return err("[inferencer] put_batch: already closed.")
        if not self._check_health():
            return err(self._first_failure_msg())

        # 内部 tee: 把 batch 投到两条 input_queue, 每条带 _PUT_BATCH_TIMEOUT 重试
        # 仅在 Full 重试时周期性 _check_health (避免每次 put 都排空的开销)
        for q in (self._input_queue_detect, self._input_queue_obb):
            while True:
                try:
                    q.put(batch, block=True, timeout=_PUT_BATCH_TIMEOUT)
                    break
                except Full:
                    if self._stop_event.is_set():
                        return err("[inferencer] put_batch: stop_event set.")
                    if not self._check_health():
                        return err(self._first_failure_msg())
                    continue
                except Exception as e:
                    # 队列管道断裂 (worker 已死/被 terminate) → 无法归属到具体 worker,
                    # 将所有仍在 RUNNING 的 worker 判 FAILED 并记录诊断行
                    msg = f"put_batch [inferencer]: queue error: {e}"
                    self._failures.append(err(msg, error_raw=e))
                    for n in self._status:
                        self._set_status(n, WorkerStatus.FAILED)
                    return err(f"[inferencer] {msg}", error_raw=e)
        return ok()

    def get_results(self, timeout=0.0) -> OpResult:
        """收集 output_queue 中已就绪的推理结果。

        Args:
            timeout: 阻塞等待首个结果的超时 (秒)。0 = 非阻塞排空。

        Returns:
            ok(value=list)    — list[(Note_Geometry, task_name)], 可能为空
            err(value=list)   — worker 报错/判死; value 仍带回已收集的部分结果
        """
        if self._class_force_closed:
            return err("[inferencer] get_results: already closed.", value=None)

        if timeout > 0:
            try:
                item = self._output_queue.get(timeout=timeout)
                self._pending_results.append(item)   # output_queue 只存数据
            except Empty:
                pass

        healthy = self._check_health()
        snapshot = self._pending_results
        self._pending_results = []

        if not healthy:
            return err(self._first_failure_msg(), value=snapshot)
        return ok(value=snapshot)

    def send_eof(self):
        """best-effort 向两条 input_queue 投 None (EOF)。worker 收到即正常退出。

        void: 即使投递失败也不抛 (后续 get_results 的健康检查会兜底报错)。
        stop_event 已触发时先排空队列避免永久阻塞。
        """
        for q in (self._input_queue_detect, self._input_queue_obb):
            deadline = time.monotonic() + 5.0
            while True:
                if self._stop_event.is_set():
                    _drain_queue(q)
                try:
                    q.put(None, block=True, timeout=2.0)
                    break
                except Full:
                    if time.monotonic() > deadline:
                        break

    def stop(self):
        """幂等清理: stop_event.set() → 存活者 terminate() → join(timeout)。"""
        if self._class_force_closed:
            return
        self._class_force_closed = True
        self._stop_event.set()
        for p in (self._process_detect, self._process_obb):
            if p is not None and p.is_alive():
                p.terminate()
        for p in (self._process_detect, self._process_obb):
            if p is not None:
                p.join(timeout=_WORKER_EXIT_TIMEOUT)





def format_exit_line(p, model_name):
    exitcode = p.exitcode
    win_code = (exitcode & 0xFFFFFFFF) if exitcode is not None and exitcode < 0 else None
    win_str = f"0x{win_code:08X}" if win_code is not None else "N/A"
    return f"{model_name} model inferencer died, exitcode={exitcode} win_code={win_str}"


def _drain_queue(q):
    """非阻塞排空队列"""
    items = []
    while True:
        try:
            items.append(q.get_nowait())
        except Empty:
            break
    return items
