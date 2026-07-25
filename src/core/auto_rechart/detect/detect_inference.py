from ultralytics import YOLO
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

    只读属性: is_done, is_failed, progress, errors, exit_lines, status
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
        self._errors = []                 # list[(name, error_msg, frame_idx)]
        self._exit_lines = []             # list[str]  硬失败诊断行 (native 崩溃 / 队列断裂)
        self._pending_results = []        # list[(Note_Geometry, task_name)]  get_results 缓冲



    @property
    def is_done(self) -> bool:
        """两个 worker 是否都已结束 (无论成功/失败)。"""
        return all(s != WorkerStatus.RUNNING for s in self._status.values())

    @property
    def is_failed(self) -> bool:
        """是否发生过任何 worker 报错/判死。"""
        return WorkerStatus.FAILED in self._status.values()

    @property
    def status(self) -> dict:
        """dict[str, WorkerStatus] 副本 — {'detect': ..., 'obb': ...}, 仅用于观察/调试。"""
        return dict(self._status)

    @property
    def progress(self) -> tuple:
        """(detect_done_frames, obb_done_frames), 仅用于打印进度。"""
        return (self._progress_ref_detect.value, self._progress_ref_obb.value)

    @property
    def errors(self) -> list:
        """list[(name, error_msg, frame_idx)] — worker 失败列表 (仅失败者)。"""
        return self._errors

    @property
    def exit_lines(self) -> list:
        """list[str] — 硬失败诊断行 (format_exit_line 输出 / 队列断裂)。"""
        return self._exit_lines

    # --- 内部: 派发 (数据/控制分离) -------------------------------------------

    def _dispatch_control(self, name, op_result):
        """处理一个 worker 的控制 OpResult, 更新状态机。

        - ok(value=last_frame_idx)  → 该 worker 正常结束 → DONE
        - err(error_msg, value=last_frame_idx) → 该 worker 失败 → FAILED, 记录错误

        sticky: 已进入终态的 worker 收到重复派发直接忽略 (不重复 append _errors)。
        """
        if self._status[name] != WorkerStatus.RUNNING:
            return
        if op_result.is_ok:
            self._set_status(name, WorkerStatus.DONE)
        else:
            self._errors.append((name, op_result.error_msg, op_result.value))
            self._set_status(name, WorkerStatus.FAILED)

    def _set_status(self, name, status):
        """更新某 worker 状态 (sticky: 仅 RUNNING 可转 DONE/FAILED, 终态不可回退)。

        等价原 _mark_finished 的去重计数语义: 终态下重复调用为 no-op,
        也防止 _check_health 兜底 / _dispatch_control 重复 append _errors / _exit_lines。
        """
        if self._status[name] == WorkerStatus.RUNNING:
            self._status[name] = status

    # --- 内部: 健康检查 (put_batch 与 get_results 共用) ----------------------

    def _check_health(self) -> bool:
        """非阻塞排空 output_queue (数据) + 两条 control_queue (控制) + 进程存活兜底。

        返回是否仍健康 (not is_failed)。

        进程存活兜底覆盖 native 硬崩溃 (worker 死了没来得及发 err);
        Python 异常已由 err 先行处理, 这里只是兜底。
        """
        # 1. 排空数据队列 → 直接进 _pending_results (output_queue 只存数据)
        self._pending_results.extend(_drain_queue(self._output_queue))

        # 2. 排空两条控制队列 → dispatch (name 由队列身份决定)
        for item in _drain_queue(self._control_queue_detect):
            self._dispatch_control('detect', item)
        for item in _drain_queue(self._control_queue_obb):
            self._dispatch_control('obb', item)

        # 3. 进程存活兜底: worker 已死但未登记 → 判死亡
        for name, p in (('detect', self._process_detect), ('obb', self._process_obb)):
            if self._status[name] == WorkerStatus.RUNNING and not p.is_alive():
                self._exit_lines.append(format_exit_line(p, name))
                self._set_status(name, WorkerStatus.FAILED)

        return not self.is_failed

    def _first_failure_msg(self):
        """生成首个失败原因的简短消息 (供 put_batch/get_results 的 err)。"""
        if self._errors:
            name, error_msg, frame_idx = self._errors[0]
            return f"[inferencer] {name} failed @ frame={frame_idx}:\n{error_msg}"
        if self._exit_lines:
            return f"[inferencer] {self._exit_lines[0]}"
        return "[inferencer] unknown failure"

    # --- 对 main 的公开 API --------------------------------------------------

    def put_batch(self, batch) -> OpResult:
        """tee batch 到 detect/obb 两条 input_queue。生产阶段 worker 报错经此返回 err。

        Returns:
            ok()              — tee 成功
            err(...)          — worker 已报错/判死, 或 stop_event 已触发
        """
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
                    msg = f"put_batch: queue error: {e}"
                    self._exit_lines.append(msg)
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
