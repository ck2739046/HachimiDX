import time
from dataclasses import dataclass
from enum import Enum
from queue import Empty

import i18n
import torch.multiprocessing as tmp

from src.services import kill_process_tree

from ...schemas.op_result import OpResult, err, ok
from .detect_inference_worker import inference_worker_main
from .note_definition import get_imgsz
from .shared_frame_buffer import SharedFrameBuffer

_FRAME_BUFFER_CAP = 30
_RESULTS_QUEUE_CAP = 1000  # 输出: 推理结果 queue 上限

_PUBLISH_WAIT_TIMEOUT = 0.1
_WORKER_EXIT_TIMEOUT = 10.0

# 共享缓冲满是正常反压控制流，不应被 OpResult 当作原始异常。
_NO_RAW_ERROR = ""


@dataclass
class _InferencerDeps:
    """create_inferencer 装配好参数供 Inferencer.__init__ 消费。"""

    process_detect: "tmp.Process"
    process_obb: "tmp.Process"
    frame_buffer: SharedFrameBuffer
    output_queue: "tmp.Queue"
    control_queue_detect: "tmp.Queue"
    control_queue_obb: "tmp.Queue"
    stop_event: "tmp.Event"
    progress_ref_detect: "tmp.Value"
    progress_ref_obb: "tmp.Value"


def create_inferencer(
    detect_model_path,
    obb_model_path,
    batch_size,
    inference_device,
    coord_scale,
    model_backend,
    half,
) -> OpResult:
    """构造 Inferencer (而不是直接调用 Inferencer.__init__)"""

    if batch_size <= 0:
        return err(
            i18n.t("detect_inference.error_batch_size_invalid", value=batch_size)
        )
    if get_imgsz("detect") != get_imgsz("obb"):
        return err(i18n.t("detect_inference.error_imgsz_mismatch"))

    try:
        frame_imgsz = get_imgsz("detect")
        frame_buffer = SharedFrameBuffer.create(
            frame_shape=(frame_imgsz, frame_imgsz, 3),
            capacity=_FRAME_BUFFER_CAP,
        )
    except Exception as e:
        return err("[inferencer] failed to create shared frame buffer", error_raw=e)

    started = []
    queues = []
    try:
        output_queue = tmp.Queue(maxsize=_RESULTS_QUEUE_CAP)
        control_queue_detect = tmp.Queue()
        control_queue_obb = tmp.Queue()
        queues.extend((output_queue, control_queue_detect, control_queue_obb))
        stop_event = tmp.Event()
        progress_ref_detect = tmp.Value("i", 0)
        progress_ref_obb = tmp.Value("i", 0)

        process_detect = tmp.Process(
            target=inference_worker_main,
            args=(
                detect_model_path,
                "detect",
                inference_device,
                coord_scale,
                half,
                model_backend,
                frame_buffer.spec,
                batch_size,
                output_queue,
                control_queue_detect,
                progress_ref_detect,
                stop_event,
            ),
            daemon=True,
        )
        process_obb = tmp.Process(
            target=inference_worker_main,
            args=(
                obb_model_path,
                "obb",
                inference_device,
                coord_scale,
                half,
                model_backend,
                frame_buffer.spec,
                batch_size,
                output_queue,
                control_queue_obb,
                progress_ref_obb,
                stop_event,
            ),
            daemon=True,
        )

        process_detect.start()
        started.append(process_detect)
        process_obb.start()
        started.append(process_obb)
    except Exception as e:
        failed_name = "obb" if len(started) == 1 else "detect"
        for process in started:
            if process.is_alive():
                process.terminate()
            process.join(timeout=_WORKER_EXIT_TIMEOUT)
        frame_buffer.close()
        frame_buffer.unlink()
        for queue in queues:
            queue.close()
        return err(
            f"[inferencer] failed to start {failed_name} model worker: {e}",
            error_raw=e,
        )

    deps = _InferencerDeps(
        process_detect=process_detect,
        process_obb=process_obb,
        frame_buffer=frame_buffer,
        output_queue=output_queue,
        control_queue_detect=control_queue_detect,
        control_queue_obb=control_queue_obb,
        stop_event=stop_event,
        progress_ref_detect=progress_ref_detect,
        progress_ref_obb=progress_ref_obb,
    )
    return ok(Inferencer(deps))


class WorkerStatus(Enum):
    RUNNING = "running"  # 未结束
    DONE = "done"  # 正常结束
    FAILED = "failed"  # 报错


class Inferencer:
    """
    api:
    - create_inferencer(...)  -> OpResult[Inferencer]
    - put_batch(batch)        -> OpResult[None]
    - get_results()           -> OpResult[List[Tuple[Note_Geometry, str]]]
    - send_eof()              -> OpResult[None]
    - stop()                  -> None

    只读属性: progress, is_done
    """

    def __init__(self, deps: _InferencerDeps):
        self._process_detect = deps.process_detect
        self._process_obb = deps.process_obb
        self._frame_buffer = deps.frame_buffer
        self._output_queue = deps.output_queue
        self._control_queue_detect = deps.control_queue_detect
        self._control_queue_obb = deps.control_queue_obb
        self._stop_event = deps.stop_event
        self._progress_ref_detect = deps.progress_ref_detect
        self._progress_ref_obb = deps.progress_ref_obb

        self._status = {
            "detect": WorkerStatus.RUNNING,
            "obb": WorkerStatus.RUNNING,
        }
        self._class_force_closed = False
        self._failures = []
        self._pending_results = []

    @property
    def progress(self) -> tuple:
        return (self._progress_ref_detect.value, self._progress_ref_obb.value)

    @property
    def is_done(self) -> bool:
        return all(s != WorkerStatus.RUNNING for s in self._status.values())

    def create_decoder(self, std_video_path, imgsz, total_frames):
        """创建直接向本 inferencer 共享缓冲发布帧的解码进程。"""

        from .detect_decode import Decoder

        return Decoder(
            std_video_path,
            imgsz,
            total_frames,
            frame_buffer=self._frame_buffer,
            stop_event=self._stop_event,
        )

    def _set_status(self, name, status):
        if self._status[name] == WorkerStatus.RUNNING:
            self._status[name] = status

    def _dispatch_control_queue_result(self, name, op_result):
        if self._status[name] != WorkerStatus.RUNNING:
            return
        if op_result.is_ok:
            self._set_status(name, WorkerStatus.DONE)
        else:
            self._failures.append(op_result)
            self._set_status(name, WorkerStatus.FAILED)

    def _check_workers_health(self) -> bool:
        """读取 worker 状态，并在失败时解除共享缓冲上的等待。"""

        for item in _drain_queue(self._control_queue_detect):
            self._dispatch_control_queue_result("detect", item)
        for item in _drain_queue(self._control_queue_obb):
            self._dispatch_control_queue_result("obb", item)

        for name, process, control_queue in (
            ("detect", self._process_detect, self._control_queue_detect),
            ("obb", self._process_obb, self._control_queue_obb),
        ):
            if self._status[name] != WorkerStatus.RUNNING or process.is_alive():
                continue
            process.join(timeout=0)
            for item in _drain_queue(control_queue):
                self._dispatch_control_queue_result(name, item)
            if self._status[name] == WorkerStatus.RUNNING:
                if process.exitcode == 0:
                    self._set_status(name, WorkerStatus.DONE)
                else:
                    self._failures.append(err(_format_exit_line(process, name)))
                    self._set_status(name, WorkerStatus.FAILED)

        is_failed = any(s == WorkerStatus.FAILED for s in self._status.values())
        if is_failed:
            self._stop_event.set()
            self._frame_buffer.wake_all()
        return not is_failed

    def _collect_ready_results(self):
        self._pending_results.extend(_drain_queue(self._output_queue))

    def put_batch(self, batch, timeout: float = 60.0) -> OpResult:
        """将解码 batch 发布到共享帧缓冲。"""

        if self._class_force_closed:
            return err("[inferencer] put_batch: already closed.")
        if not self._check_workers_health():
            return err(
                "[inferencer] put_batch: health check failed.",
                inner=_build_chain_OpResult(self._failures),
            )

        deadline = time.monotonic() + timeout
        try:
            iterator = iter(batch)
            for item in iterator:
                frame_index, frame = item
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        return err(
                            "[inferencer] put_batch: timeout publishing frame",
                            inner=_build_chain_OpResult(self._failures)
                            if self._failures
                            else None,
                            error_raw=_NO_RAW_ERROR,
                        )
                    published = self._frame_buffer.publish(
                        frame_index,
                        frame,
                        timeout=min(_PUBLISH_WAIT_TIMEOUT, remaining),
                        stop_event=self._stop_event,
                    )
                    if published:
                        break

                    self._collect_ready_results()
                    if not self._check_workers_health():
                        return err(
                            "[inferencer] put_batch: health check failed.",
                            inner=_build_chain_OpResult(self._failures),
                            error_raw=_NO_RAW_ERROR,
                        )
        except Exception as e:
            return err(f"[inferencer] put_batch: invalid frame batch: {e}", error_raw=e)

        return ok()

    def get_results(self) -> OpResult:
        if self._class_force_closed:
            return err("[inferencer] get_results: already closed.")
        if not self._check_workers_health():
            return err(
                "[inferencer] get_results: health check failed.",
                inner=_build_chain_OpResult(self._failures),
            )

        self._collect_ready_results()
        snapshot = self._pending_results
        self._pending_results = []
        return ok(value=snapshot)

    def send_eof(self, timeout: float = 60.0) -> OpResult:
        """发布 EOF；共享缓冲中已经写入的帧仍会被消费。"""

        _ = timeout
        if self._class_force_closed:
            return err("[inferencer] send_eof: already closed.")
        if not self._check_workers_health():
            return err(
                "[inferencer] send_eof: health check failed.",
                inner=_build_chain_OpResult(self._failures),
            )
        try:
            self._frame_buffer.finish_input()
        except Exception as e:
            return err(
                f"[inferencer] send_eof: failed to publish EOF: {e}", error_raw=e
            )
        return ok()

    def stop(self):
        if self._class_force_closed:
            return
        self._class_force_closed = True

        all_queues = (
            self._output_queue,
            self._control_queue_detect,
            self._control_queue_obb,
        )
        self._stop_event.set()
        self._frame_buffer.wake_all()
        for process in (self._process_detect, self._process_obb):
            if process is not None and process.is_alive():
                process.terminate()
        for process in (self._process_detect, self._process_obb):
            if process is not None:
                process.join(timeout=_WORKER_EXIT_TIMEOUT)
                if process.is_alive():
                    kill_process_tree(process.pid)

        for queue in all_queues:
            try:
                queue.close()
            except (AttributeError, OSError, ValueError):
                pass

        self._frame_buffer.close()
        self._frame_buffer.unlink()


def _format_exit_line(p, model_name):
    exitcode = p.exitcode
    win_code = (
        (exitcode & 0xFFFFFFFF) if exitcode is not None and exitcode < 0 else None
    )
    win_str = f"0x{win_code:08X}" if win_code is not None else "N/A"
    return f"{model_name} model inferencer died, exitcode={exitcode} win_code={win_str}"


def _drain_queue(q):
    items = []
    while True:
        try:
            items.append(q.get_nowait())
        except Empty:
            break
    return items


def _build_chain_OpResult(OpResult_list) -> OpResult:
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
    for next_result in OpResult_list[1:]:
        cur.inner = _copy_op_result(next_result)
        cur = cur.inner
    return root
