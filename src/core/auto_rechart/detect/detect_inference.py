import time
import traceback
import torch.multiprocessing as tmp
from queue import Empty, Full
from dataclasses import dataclass
from enum import Enum

from ...schemas.op_result import OpResult, ok, err
from .note_definition import *
from .detect_inference_worker import inference_worker_main
from src.services.watchdog import _kill_process_tree



_FRAME_QUEUE_CAP = 20         # 输入: 待推理的视频帧 queue 上限 (detect/obb 各一条)
_RESULTS_QUEUE_CAP = 1000     # 输出: 推理结果 queue 上限

_PUT_TO_INPUT_QUEUE_TIMEOUT = 0.1
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
    - get_results()           -> OpResult[List[Tuple[Note_Geometry, str]]]
    - send_eof()              -> OpResult[None]  (失败时调用方需自行 stop())
    - stop()                  -> None

    只读属性: progress, is_done
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
                                          # 只会在 stop() 写入
        self._failures = []               # 失败事件 - list[OpResult]
                                          # 只会在 check_health() 写入
        self._pending_results = []        # get_results 缓冲 - list[(Note_Geometry, task_name)]
                                          # 在结果收集时写入, 仅在 get_results() 清空


    @property
    def progress(self) -> tuple:
        """tuple[detect_done_frames, obb_done_frames]"""
        return (self._progress_ref_detect.value, self._progress_ref_obb.value)


    @property
    def is_done(self) -> bool:
        """两个 worker 是否都已离开 RUNNING (即 DONE 或 FAILED)"""
        return all(s != WorkerStatus.RUNNING for s in self._status.values())






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


    def _check_workers_health(self) -> bool:
        """
        检查 inference workers 健康状态, 处理控制队列, 更新状态机
        返回:
            True  — 无 worker failed (允许done/running)
            False — 有 worker failed
        """
        # 1. 排空两条控制队列 → dispatch result
        for item in _drain_queue(self._control_queue_detect):
            self._dispatch_control_queue_result('detect', item)
        for item in _drain_queue(self._control_queue_obb):
            self._dispatch_control_queue_result('obb', item)

        # 2. 检查进程是否存活
        for name, p, control_q in (
            ('detect', self._process_detect, self._control_queue_detect),
            ('obb', self._process_obb, self._control_queue_obb),
        ):
            status_is_running = bool(self._status[name] == WorkerStatus.RUNNING)
            # 状态是 running 但实际进程挂了
            # 可能1：进程异常退出, 没放 err() 到 control queue
            # 可能2：进程放了 err() 但还没被 dispatch 到状态机
            if status_is_running and not p.is_alive():
                # 非阻塞尝试一次回收子进程
                p.join(timeout=0)
                # 考虑可能2, 尝试 dispatch queue 中的 err()
                for item in _drain_queue(control_q):
                    self._dispatch_control_queue_result(name, item)
                # 仍是 running，考虑可能1
                if self._status[name] == WorkerStatus.RUNNING:
                    if p.exitcode == 0:
                        self._set_status(name, WorkerStatus.DONE)
                    else:
                        self._failures.append(err(_format_exit_line(p, name)))
                        self._set_status(name, WorkerStatus.FAILED)

        is_failed = any(s == WorkerStatus.FAILED for s in self._status.values())
        return not is_failed


    def _collect_ready_results(self):
        """将 output_queue 中已就绪的结果暂存到内部缓冲"""
        self._pending_results.extend(_drain_queue(self._output_queue))








    def put_batch(self, batch, timeout: float = 60.0) -> OpResult:
        """tee batch 到 detect/obb 两条 input_queue"""

        if self._class_force_closed:
            return err("[inferencer] put_batch: already closed.")
        if not self._check_workers_health():
            inner_err = _build_chain_OpResult(self._failures)
            return err("[inferencer] put_batch: health check failed.", inner=inner_err)

        # 内部 tee: 把 batch 投到两条 input_queue
        deadline = time.monotonic() + timeout
        for q in (self._input_queue_detect, self._input_queue_obb):
            while True:
                try:
                    q.put(batch, block=True, timeout=_PUT_TO_INPUT_QUEUE_TIMEOUT)
                    break
                except Full:
                    # 输入队列满时先消费输出，避免 worker 因输出队列反压无法继续消费输入
                    self._collect_ready_results()
                    # 队列满了, 检查健康状态再重试
                    if not self._check_workers_health():
                        inner_err = _build_chain_OpResult(self._failures)
                        return err("[inferencer] put_batch: health check failed.", inner=inner_err)
                    if time.monotonic() > deadline:
                        # 超时
                        inner_err = _build_chain_OpResult(self._failures)
                        return err("[inferencer] put_batch: timeout putting batch", inner=inner_err)
                    continue
                except Exception as e:
                    # 其他异常
                    for n in self._status:
                        self._set_status(n, WorkerStatus.FAILED)
                    inner_err = _build_chain_OpResult(self._failures)
                    msg = f"[inferencer] put_batch: other error: {e}"
                    return err(msg, inner=inner_err, error_raw=e)

        return ok()



    def get_results(self) -> OpResult:
        """
        收集 output_queue 中已就绪的推理结果
        value = list[(Note_Geometry, task_name)] 可能为空
        """
        if self._class_force_closed:
            return err("[inferencer] get_results: already closed.")
        if not self._check_workers_health():
            inner_err = _build_chain_OpResult(self._failures)
            return err("[inferencer] get_results: health check failed.", inner=inner_err)

        # 排空输出队列, 存进 _pending_results
        self._collect_ready_results()
        # 读取完毕后, 清空 _pending_results
        snapshot = self._pending_results
        self._pending_results = []

        return ok(value=snapshot)




    def send_eof(self, timeout: float = 60.0) -> OpResult:
        """
        通知 worker 不再有新的输入帧
        失败时返回 err(), 调用方应该自行调用 stop()
        """

        if self._class_force_closed:
            return err("[inferencer] send_eof: already closed.")
        if not self._check_workers_health():
            inner_err = _build_chain_OpResult(self._failures)
            return err("[inferencer] send_eof: health check failed.", inner=inner_err)

        for q in (self._input_queue_detect, self._input_queue_obb):
            deadline = time.monotonic() + timeout
            while True:
                if self._stop_event.is_set():
                    _drain_queue(q)
                try:
                    q.put(None, block=True, timeout=_PUT_TO_INPUT_QUEUE_TIMEOUT)
                    break
                except Full:
                    # 先消费输出以解除反压闭环
                    self._collect_ready_results()
                    if not self._check_workers_health():
                        inner_err = _build_chain_OpResult(self._failures)
                        return err("[inferencer] send_eof: health check failed.", inner=inner_err)
                    if time.monotonic() > deadline:
                        # 超时
                        return err("[inferencer] send_eof: timeout putting EOF")
                except Exception as e:
                    # 其他异常
                    return err(f"[inferencer] send_eof: error putting EOF: {e}", error_raw=e)

        return ok()



    def stop(self):
        """强制关闭推理"""
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
                # join 超时后, 使用 psutil 强杀整棵进程树
                if p.is_alive():
                    _kill_process_tree(p.pid)   





def _format_exit_line(p, model_name):
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


def _build_chain_OpResult(OpResult_list) -> OpResult:
    """
    将 failures 列表的多个 OpResult 构建为单个 OpResult

    通过 inner 链式嵌套 _failures 全部 (正序):
        failures[0].inner → failures[1].inner → ...
    """
    if not OpResult_list:
        return err("no failures to chain")

    def _copy_op_result(r: OpResult) -> OpResult:
        return OpResult(
            is_ok=r.is_ok,
            source=r.source,
            value=r.value,
            error_msg=r.error_msg,
            error_raw=r.error_raw,
            inner=None,
        )

    root = _copy_op_result(OpResult_list[0])
    cur = root
    for next in OpResult_list[1:]:
        cur.inner = _copy_op_result(next)
        cur = cur.inner
    return root
