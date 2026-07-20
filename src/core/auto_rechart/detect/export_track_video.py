import os
import cv2
import time
import math
import numpy as np
from collections import defaultdict, deque
import subprocess
import atexit
from dataclasses import dataclass
from typing import Optional
from pathlib import Path

from ...schemas.op_result import OpResult, ok, err
from ..pipeline import Producer, Consumer, Pipeline
from .note_definition import *
from .track import _load_track_results
from ..tool import catmull_rom_spline
from .custom_oc_sort.oc_sort import _KalmanBoxTracker

from src.services import PathManage




_COLOR_PALETTE = [
    (0, 0, 190),    # RED
    (190, 0, 0),    # BLUE
    (0, 170, 0),    # GREEN
    (0, 100, 200),  # ORANGE
    (200, 0, 150),  # PURPLE
    (180, 130, 0),  # TEAL
    (160, 0, 210),  # MAGENTA
    (0, 150, 160),  # OLIVE
    (40, 80, 160),  # SIENNA
]

_LABEL_FONT = cv2.FONT_HERSHEY_SIMPLEX
_LABEL_SCALE = 0.6
_LABEL_THICK = 2
_LABEL_COLOR = (255, 255, 255)
_BOX_THICK = 2
_TRAIL_THICK = 3
_CIRCLE_RADIUS = 3

# SLIDE 候选框去重：坐标精确到 N 位小数相同视为同一框
_BOX_KEY_PRECISION = 2

# 轨迹历史长度上限，超过则前端裁剪
_MAX_TRACK_HISTORY_LEN = 3000

# FFmpeg 批量写入帧数
_BATCH_FRAMES = 30

# Catmull-Rom 样条参数
_SPLINE_SAMPLES = 4
_SPLINE_TENSION = 1.5

# 是否绘制 Kalman 预测框（灰色，仅 SLIDE）
_DRAW_KALMAN_PREDICTION = False

# 占位的空数组
_EMPTY_POLY = np.empty((0, 1, 2), dtype=np.int32)


def _color_for_id(track_id: int) -> tuple:
    return _COLOR_PALETTE[track_id % len(_COLOR_PALETTE)]






class ExportProducer(Producer):
    """生产者: 视频解码"""

    def __init__(self, std_video_path):
        self.std_video_path = str(std_video_path)
        self.cap = None

    def on_start(self, ctx):
        self.cap = cv2.VideoCapture(self.std_video_path)

    def on_cleanup(self, ctx, error):
        if self.cap is not None:
            try:
                self.cap.release()
            except Exception:
                pass
            self.cap = None

    def produce(self, q, stop, ctx):
        while True:
            if stop.is_set():
                return
            ret, frame = self.cap.read()
            if not ret:
                q.put(self.sentinel)
                return
            if not self._put_or_stop(q, frame, stop):
                return







class ExportConsumer(Consumer):
    """消费者: 绘制轨迹/音符框 + YUV 转换 + 批量写 ffmpeg"""

    def __init__(self, ffmpeg_cmd, video_width, video_height, frame_size,
                 total_frames, fps_for_calc, timeout_frames,
                 note_manifest, center_manifest, kalman_predictions,
                 final_track_video_path):
        self.ffmpeg_cmd = ffmpeg_cmd
        self.video_width = video_width
        self.video_height = video_height
        self.frame_size = frame_size
        self.total_frames = total_frames
        self.fps_for_calc = fps_for_calc
        self.timeout_frames = timeout_frames
        self.note_manifest = note_manifest
        self.center_manifest = center_manifest
        self.kalman_predictions = kalman_predictions
        self.final_track_video_path = final_track_video_path

        # ffmpeg 句柄
        self.ffmpeg_process = None
        self.stdin = None
        self.batch = None
        self.batch_mv = None

        # 绘制状态 (consume 增量维护)
        self.builders: dict = {}
        self.last_seen: dict = {}
        self._label_size_cache: dict = {}

        # 批量写状态
        self.off = 0
        self.count_in_batch = 0
        self._frame_number = 0

        # 进度/耗时
        self.start_time = 0.0
        self.last_start_time = 0.0
        self.last_frame_number = 0
        self.elapsed_time = 0.0


    def on_start(self, ctx):
        print("Running FFmpeg command:", " ".join(self.ffmpeg_cmd))
        self.ffmpeg_process = subprocess.Popen(
            self.ffmpeg_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            bufsize=_BATCH_FRAMES * self.frame_size,
        )
        if self.ffmpeg_process.stdin is None:
            raise Exception("FFmpeg stdin pipe is unavailable")
        atexit.register(_terminate_ffmpeg_on_exit, self.ffmpeg_process)
        self.stdin = self.ffmpeg_process.stdin

        # 批量写入缓冲 (memoryview 零拷贝)
        self.batch = bytearray(_BATCH_FRAMES * self.frame_size)
        self.batch_mv = memoryview(self.batch)

        self.start_time = time.time()
        self.last_start_time = self.start_time


    def consume(self, frame, stop, ctx):
        frame_number = self._frame_number
        self._frame_number += 1

        if not frame.flags['C_CONTIGUOUS']:
            frame = np.ascontiguousarray(frame)

        # 追加本帧中心点 + 标记活跃
        active_now: set = set()
        for (tid, is_slide, cx, cy) in self.center_manifest[frame_number]:
            b = self.builders.get(tid)
            if b is None:
                b = _TrailBuilder(is_slide)
                self.builders[tid] = b
            b.add_point(cx, cy)
            self.last_seen[tid] = frame_number
            active_now.add(tid)

        # 清理过期轨迹 (连续缺席 > timeout_frames 轨迹随之消失)
        evict = [tid for tid in self.builders
                 if tid not in active_now
                 and (frame_number - self.last_seen[tid]) > self.timeout_frames]
        for tid in evict:
            del self.builders[tid]
            del self.last_seen[tid]

        # 绘制轨迹线
        for tid, b in self.builders.items():
            poly = b.current_polyline()
            if poly is not None and len(poly) > 1:
                color = _color_for_id(tid)
                cv2.polylines(frame, [poly], False, color, _TRAIL_THICK)
                cv2.circle(frame, b.start_pt, _CIRCLE_RADIUS, color, -1)

        # 绘制音符框
        for nd in self.note_manifest[frame_number]:
            if nd.is_obb:
                cv2.polylines(frame, [nd.obb_pts], True, nd.color, _BOX_THICK)
            else:
                r = nd.rect
                cv2.rectangle(frame, (r[0], r[1]), (r[2], r[3]), nd.color, _BOX_THICK)
            bg = nd.label_bg
            cv2.rectangle(frame, bg[0], bg[1], nd.color, -1)
            cv2.putText(frame, nd.label, nd.label_org, _LABEL_FONT,
                        _LABEL_SCALE, _LABEL_COLOR, _LABEL_THICK)

        # 绘制 Kalman 预测框
        if _DRAW_KALMAN_PREDICTION:
            _draw_kalman_predictions(frame, self.kalman_predictions, frame_number, self._label_size_cache)

        # bgr24 转 yuv420p
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2YUV_I420)

        # 写入批量缓冲 (memoryview slice 赋值, 零拷贝 memcpy)
        self.batch_mv[self.off:self.off + self.frame_size] = frame.reshape(-1)
        self.off += self.frame_size
        self.count_in_batch += 1

        if self.count_in_batch == _BATCH_FRAMES:
            # 将这一批缓冲写入 FFmpeg stdin
            self.stdin.write(self.batch_mv[:self.off])
            # 打印进度
            self.last_start_time, self.last_frame_number = print_progress(
                "export", "fps",
                frame_number, self.total_frames,
                self.last_start_time, self.last_frame_number,
            )
            self.off = 0
            self.count_in_batch = 0


    def on_cleanup(self, ctx, error):
        """ffmpeg 生命周期收尾: 正常路径 flush + wait + 检查; 异常路径 kill"""
        is_normal = (error is None)

        if is_normal:
            # 正常结束: flush 残余批次
            try:
                if self.count_in_batch > 0 and self.stdin is not None:
                    self.stdin.write(self.batch_mv[:self.off])
                    print()
            except Exception:
                pass

            self.elapsed_time = time.time() - self.start_time

        # 公共收尾: close stdin + wait/kill + unregister + close stderr
        if self.stdin is not None:
            try:
                self.stdin.close()
            except Exception:
                pass

        ffmpeg_return_code = None
        ffmpeg_stderr = ""
        if self.ffmpeg_process is not None:
            try:
                if is_normal:
                    ffmpeg_return_code = self.ffmpeg_process.wait()
                else:
                    if self.ffmpeg_process.poll() is None:
                        self.ffmpeg_process.kill()
                    ffmpeg_return_code = self.ffmpeg_process.wait()
            except Exception:
                pass

            try:
                atexit.unregister(_terminate_ffmpeg_on_exit)
            except Exception:
                pass

            if self.ffmpeg_process.stderr is not None:
                try:
                    ffmpeg_stderr = self.ffmpeg_process.stderr.read().decode('utf-8', errors='ignore').strip()
                    self.ffmpeg_process.stderr.close()
                except Exception:
                    pass

        # 正常路径下 ffmpeg 失败要抛出 (异常路径不再追加错误)
        if is_normal and ffmpeg_return_code is not None and ffmpeg_return_code != 0:
            raise Exception(f"FFmpeg processing failed with code {ffmpeg_return_code}: {ffmpeg_stderr}")



def _terminate_ffmpeg_on_exit(proc: "subprocess.Popen") -> None:
    """atexit 兜底: 进程退出时确保 ffmpeg 子进程被终止, 避免孤儿进程"""
    try:
        if proc.poll() is None:
            proc.kill()
            try:
                proc.wait(timeout=5)
            except Exception:
                pass
    except Exception:
        pass








# 单段 Catmull-Rom：增量构建器的基础算子
# 给定一段的 4 个控制点 P0..P3
# 返回该段 t∈[0,1) 的 num_samples 个采样点 (num_samples,2) int32
def _catmull_segment(p0, p1, p2, p3,
                     num_samples: int = _SPLINE_SAMPLES,
                     s: float = _SPLINE_TENSION) -> np.ndarray:
    t = np.arange(num_samples, dtype=np.float32) / np.float32(num_samples)
    t2 = t * t
    t3 = t2 * t
    c0 = s * (-t + 2.0 * t2 - t3)
    c1 = 2.0 + (s - 6.0) * t2 + (4.0 - s) * t3
    c2 = s * t + (6.0 - 2.0 * s) * t2 + (s - 4.0) * t3
    c3 = s * (-t2 + t3)
    x = 0.5 * (c0 * p0[0] + c1 * p1[0] + c2 * p2[0] + c3 * p3[0])
    y = 0.5 * (c0 * p0[1] + c1 * p1[1] + c2 * p2[1] + c3 * p3[1])
    return np.stack([np.round(x), np.round(y)], axis=1).astype(np.int32)

# 增量轨迹构建器
#   核心：Catmull-Rom 第 i 段依赖控制点 i-1,i,i+1,i+2。
#   新增一个点时，只有 “上一段（原本 p3 被钳位，现可用真点 finalize）”
#   与 “新增的末段” 两段需要重算，其余段已定型存入 frozen。
class _TrailBuilder:
    __slots__ = ("is_slide", "pts", "frozen", "pending", "last_pt",
                 "n", "is_linear", "start_pt", "_overflow")

    def __init__(self, is_slide: bool):
        self.is_slide = is_slide
        self.pts: deque = deque(maxlen=_MAX_TRACK_HISTORY_LEN)
        self.frozen: np.ndarray = _EMPTY_POLY.reshape(-1, 2)  # 已定型段采样 (M,2)
        self.pending: Optional[np.ndarray] = None             # 末段(临时)采样 (k,2)
        self.last_pt: Optional[np.ndarray] = None             # 末控制点 (1,2)
        self.n = 0
        self.is_linear = False
        self.start_pt: Optional[tuple] = None
        # 轨迹超过 maxlen 后 deque 前端裁剪，索引对应关系被破坏，
        # 退化为每帧全量重算
        self._overflow = False

    def add_point(self, cx: float, cy: float) -> None:
        pt = (int(round(cx)), int(round(cy)))
        pts = self.pts
        pts.append(pt)
        if self.start_pt is None:
            self.start_pt = pt
        self.last_pt = np.array([[pt[0], pt[1]]], dtype=np.int32)
        self.n += 1
        n = self.n

        # 检测 maxlen 裁剪：长度不再增长
        if len(pts) < n:
            self._overflow = True

        if not self.is_slide:
            # 非 SLIDE：直线 polyline，仅保留原始点，绘制时直接转数组
            return

        if self._overflow:
            # 罕见长轨迹：退化为全量重算（等价于原实现）
            self.pending = catmull_rom_spline(list(pts)).reshape(-1, 2)
            self.frozen = _EMPTY_POLY.reshape(-1, 2)
            self.is_linear = False
            return

        if n == 1:
            return
        if n == 2:
            # 2 点：线性插值（与 catmull_rom_spline 的 n==2 分支一致）
            a = np.asarray(pts[0], dtype=np.float32)
            b = np.asarray(pts[1], dtype=np.float32)
            t = np.linspace(0.0, 1.0, _SPLINE_SAMPLES + 1, endpoint=True, dtype=np.float32)
            interp = a + (b - a) * t[:, None]
            self.pending = np.asarray(np.round(interp), dtype=np.int32)
            self.frozen = _EMPTY_POLY.reshape(-1, 2)
            self.is_linear = True
            return

        # n >= 3
        self.is_linear = False
        if n == 3:
            # 2→3 转换：丢弃线性结果，重建 seg0(frozen)+seg1(pending)
            self.frozen = _catmull_segment(pts[0], pts[0], pts[1], pts[2])
            self.pending = _catmull_segment(pts[0], pts[1], pts[2], pts[2])
            return

        # n >= 4：finalize 旧末段(seg n-3，用新点作真 p3)并入 frozen；算新末段(seg n-2，p3 钳位)
        p0 = pts[0] if n - 4 < 0 else pts[n - 4]
        finalized = _catmull_segment(p0, pts[n - 3], pts[n - 2], pts[n - 1])
        self.frozen = np.concatenate([self.frozen, finalized], axis=0)
        self.pending = _catmull_segment(pts[n - 3], pts[n - 2], pts[n - 1], pts[n - 1])

    def current_polyline(self) -> Optional[np.ndarray]:
        """返回当前完整 polyline (N,1,2) int32；不足 2 点返回 None。"""
        if self.n < 2:
            return None
        if not self.is_slide:
            arr = np.asarray(self.pts, dtype=np.int32)
            return arr.reshape(-1, 1, 2)
        if self._overflow or self.is_linear:
            arr = self.pending
        else:
            arr = np.concatenate([self.frozen, self.pending, self.last_pt], axis=0)
        return arr.reshape(-1, 1, 2)








# 预计算的绘制记录（主循环只读，零计算）
@dataclass(slots=True)
class _NoteDraw:
    color: tuple
    is_obb: bool
    obb_pts: Optional[np.ndarray]   # (4,1,2) int32
    rect: Optional[tuple]           # (x1,y1,x2,y2)
    label: str
    label_org: tuple                # putText 起点
    label_bg: tuple                 # ((x1,y1),(x2,y2))


def _build_note_draw(rep_id: int, note_type: "NoteType", note: "Note_Geometry",
                     display_id: str) -> _NoteDraw:
    """预计算一个音符的绘制数据: 颜色，标签，矩形坐标等"""
    color = _color_for_id(rep_id)
    is_obb_note = is_obb(note_type)  # NoteType.HOLD
    label = f'{note_type.name}.{note.note_variant.name} ID:{display_id}'
    label_size = cv2.getTextSize(label, _LABEL_FONT, _LABEL_SCALE, _LABEL_THICK)[0]
    lw, lh = label_size[0], label_size[1]

    if is_obb_note:
        obb_pts = np.array([
            [note.x1, note.y1],
            [note.x2, note.y2],
            [note.x3, note.y3],
            [note.x4, note.y4],
        ], dtype=np.int32).reshape(-1, 1, 2)
        ip = [
            (int(note.x1), int(note.y1)),
            (int(note.x2), int(note.y2)),
            (int(note.x3), int(note.y3)),
            (int(note.x4), int(note.y4)),
        ]
        lx, ly = min(ip, key=lambda p: (p[1], p[0]))  # 最上，并列 x 最小
        return _NoteDraw(color, True, obb_pts, None, label, (lx, ly - 5),
                         ((lx, ly - lh - 10), (lx + lw, ly)))
    else:
        x1, y1 = int(note.x1), int(note.y1)
        x2, y2 = int(note.x3), int(note.y3)
        return _NoteDraw(color, False, None, (x1, y1, x2, y2), label, (x1, y1 - 5),
                         ((x1, y1 - lh - 10), (x1 + lw, y1)))


def _compute_center(note: "Note_Geometry", is_obb_note: bool) -> tuple:
    if is_obb_note:
        return (int(round((note.x1 + note.x2 + note.x3 + note.x4) / 4.0)),
                int(round((note.y1 + note.y2 + note.y3 + note.y4) / 4.0)))
    else:
        return (int(round((note.x1 + note.x3) / 2.0)),
                int(round((note.y1 + note.y3) / 2.0)))


def _dedup_slide_notes(current_tracks: list) -> list:
    """
    SLIDE many-to-one 去重

    同一帧内, 坐标精确到 _BOX_KEY_PRECISION 位小数相同的 SLIDE 框视为同一框
    label 合并显示 ID 为 'id1/id2/...' 形式
    非 SLIDE 音符原样保留

    Args:
        current_tracks: [(track_id, note_type, note), ...] 单帧内全部音符

    Returns:
        [(rep_id, note_type, rep_note, ids, display_id), ...]
        其中 ids 为该框覆盖的所有 track_id, display_id 为合并后的显示文本。
    """
    slide_groups: dict = {}
    other: list = []
    for (track_id, note_type, note) in current_tracks:
        if note_type == NoteType.SLIDE:
            key = (
                round(note.x1, _BOX_KEY_PRECISION), round(note.y1, _BOX_KEY_PRECISION),
                round(note.x2, _BOX_KEY_PRECISION), round(note.y2, _BOX_KEY_PRECISION),
                round(note.x3, _BOX_KEY_PRECISION), round(note.y3, _BOX_KEY_PRECISION),
                round(note.x4, _BOX_KEY_PRECISION), round(note.y4, _BOX_KEY_PRECISION),
            )
            slide_groups.setdefault(key, []).append((track_id, note_type, note))
        else:
            other.append((track_id, note_type, note))

    dedup: list = []
    for group in slide_groups.values():
        rep_id = group[0][0]
        rep_type = group[0][1]
        rep_note = group[0][2]
        ids = [g[0] for g in group]
        display_id = '/'.join(str(i) for i in ids)
        dedup.append((rep_id, rep_type, rep_note, ids, display_id))
    for (track_id, note_type, note) in other:
        dedup.append((track_id, note_type, note, [track_id], str(track_id)))
    return dedup


def _build_manifests(track_results: dict, total_frames: int) -> tuple:
    """
    进入主循环前的一次性预扫描。

    返回 (note_manifest, center_manifest):
    - note_manifest[frame]: 该帧静态音符绘制记录列表（主循环只读 blit）。
    - center_manifest[frame]: 该帧要追加进轨迹构建器的中心点列表
      [(track_id, is_slide, cx, cy), ...]，仅几个标量、无 ndarray。

    轨迹本身不在此处构建/快照, 它在主循环里用 _TrailBuilder 增量维护
    """
    # 按帧组织音符
    frame_tracks: defaultdict = defaultdict(list)
    for (track_id, note_type), geo_list in track_results.items():
        if not geo_list:
            continue
        for note in geo_list:
            frame_tracks[note.frame].append((track_id, note_type, note))

    note_manifest: list = [[] for _ in range(total_frames)]
    center_manifest: list = [[] for _ in range(total_frames)]

    for frame_number in range(total_frames):
        current_tracks = frame_tracks.get(frame_number)
        if not current_tracks:
            continue

        # SLIDE many-to-one 去重
        dedup = _dedup_slide_notes(current_tracks)

        # 音符绘制数据（静态，主循环只读）
        note_manifest[frame_number] = [
            _build_note_draw(rep_id, note_type, note, display_id)
            for (rep_id, note_type, note, _ids, display_id) in dedup
        ]

        # 中心点数据（轻量，喂给主循环的轨迹构建器）
        centers: list = []
        for (_rep_id, note_type, note, ids, _display_id) in dedup:
            is_obb_note = is_obb(note_type)
            cx, cy = _compute_center(note, is_obb_note)
            is_slide = (note_type == NoteType.SLIDE)
            for tid in ids:
                centers.append((tid, is_slide, cx, cy))
        center_manifest[frame_number] = centers

    return note_manifest, center_manifest











# 主入口
def main(std_video_path: Path, total_frames: int) -> OpResult[Path]:

    print("开始导出视频模块...")

    try:
        # 读取追踪结果
        track_results = _load_track_results(std_video_path.parent)

        # 预计算全部 Kalman 预测（默认关闭）
        if _DRAW_KALMAN_PREDICTION:
            kalman_predictions = _compute_kalman_predictions(track_results)
        else:
            kalman_predictions: dict = {}

        # 获取视频信息
        cap = cv2.VideoCapture(str(std_video_path))
        try:
            video_width = round(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            video_height = round(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps = cap.get(cv2.CAP_PROP_FPS)
        finally:
            cap.release()

        fps_for_calc = float(fps) if fps and fps > 0 else 30.0
        timeout_frames = max(1, int(round(fps_for_calc / 2.0)))

        # 预计算 manifests (主循环只读 blit)
        note_manifest, center_manifest = _build_manifests(track_results, total_frames)

        # 输出视频设置
        output_dir = std_video_path.parent
        video_name = output_dir.name
        final_track_video_path = os.path.join(output_dir, f'{video_name}_tracked.mp4')
        if os.path.exists(final_track_video_path):
            os.remove(final_track_video_path)

        # FFmpeg 管道命令 (yuv420p 直传: Python 侧预先 cvtColor 将 bgr24 转 yuv420p)
        ffmpeg_exe = str(PathManage.FFMPEG_EXE_PATH)
        frame_size = video_width * video_height * 3 // 2
        ffmpeg_cmd = [
            ffmpeg_exe,
            '-y', '-hide_banner', '-loglevel', 'error',
            '-f', 'rawvideo',
            '-pix_fmt', 'yuv420p',
            '-s', f'{video_width}x{video_height}',
            '-r', str(fps_for_calc),
            '-i', '-',
            '-i', str(std_video_path),
            '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23',
            '-pix_fmt', 'yuv420p',
            '-c:a', 'aac', '-b:a', '192k',
            '-map', '0:v:0',
            '-map', '1:a:0?',
            '-shortest',
            final_track_video_path,
        ]

        # producer: 视频解码
        producer = ExportProducer(std_video_path)
        # consumer: 绘制 + ffmpeg 批量写
        consumer = ExportConsumer(
            ffmpeg_cmd=ffmpeg_cmd,
            video_width=video_width,
            video_height=video_height,
            frame_size=frame_size,
            total_frames=total_frames,
            fps_for_calc=fps_for_calc,
            timeout_frames=timeout_frames,
            note_manifest=note_manifest,
            center_manifest=center_manifest,
            kalman_predictions=kalman_predictions,
            final_track_video_path=final_track_video_path,
        )
        Pipeline(producer, consumer, queue_size=_BATCH_FRAMES * 2).run()

        # 正常结束: 打印耗时
        average_fps = total_frames / consumer.elapsed_time if consumer.elapsed_time > 0 else 0
        print(f"追踪视频导出完成，耗时{consumer.elapsed_time:.1f}s, 平均{average_fps:.2f}fps"
              f"               ")
        print(f"追踪视频已保存到：{final_track_video_path}")

        return ok(Path(final_track_video_path))

    except Exception as e:
        return err("Unexcepted error in auto_rechart > detect > export_track_video", e)




# Kalman 预测
def _compute_kalman_predictions(track_results) -> dict[int, list[dict]]:
    """对每条 SLIDE 轨迹逐帧重跑 Kalman 滤波器，返回 {frame: [pred_dict, ...]}"""
    kalman_predictions: dict[int, list[dict]] = defaultdict(list)
    for (track_id, note_type), geo_list in track_results.items():
        if note_type != NoteType.SLIDE:
            continue
        if len(geo_list) == 0:
            continue
        geo_list_sorted = sorted(geo_list, key=lambda g: g.frame)
        frame_to_geo = {g.frame: g for g in geo_list_sorted}
        first_f = geo_list_sorted[0].frame
        last_f = geo_list_sorted[-1].frame
        note_variant = geo_list_sorted[0].note_variant
        first_geo = geo_list_sorted[0]
        init_bbox = np.array([
            first_geo.x1, first_geo.y1,
            first_geo.x3, first_geo.y3,
            first_geo.conf,
            float(map_note_type_to_class_id(note_type)),
            0.0,
        ], dtype=np.float32)
        tracker = _KalmanBoxTracker(init_bbox)
        # 首帧：predict 后写入预测结果，若有检测框则 update
        pred = tracker.predict()[0]
        kalman_predictions[first_f].append({
            'track_id': track_id,
            'note_variant': note_variant,
            'x1': float(pred[0]), 'y1': float(pred[1]),
            'x2': float(pred[2]), 'y2': float(pred[3]),
        })
        tracker.update(init_bbox)
        for f in range(first_f + 1, last_f + 1):
            pred = tracker.predict()[0]
            kalman_predictions[f].append({
                'track_id': track_id,
                'note_variant': note_variant,
                'x1': float(pred[0]), 'y1': float(pred[1]),
                'x2': float(pred[2]), 'y2': float(pred[3]),
            })
            geo = frame_to_geo.get(f)
            if geo is not None:
                obs = np.array([
                    geo.x1, geo.y1,
                    geo.x3, geo.y3,
                    geo.conf,
                    float(map_note_type_to_class_id(note_type)),
                    0.0,
                ], dtype=np.float32)
                tracker.update(obs)
            else:
                tracker.update(None)
    return kalman_predictions



def _draw_kalman_predictions(frame, kalman_predictions, frame_number, label_size_cache):
    """在当前帧上绘制 Kalman 预测框（灰色，仅 SLIDE）"""
    kalman_grey = (160, 160, 160)
    for kp in kalman_predictions.get(frame_number, []):
        if math.isnan(kp['x1']) or math.isnan(kp['y1']):
            continue
        kp_x1, kp_y1 = int(kp['x1']), int(kp['y1'])
        kp_x2, kp_y2 = int(kp['x2']), int(kp['y2'])
        cv2.rectangle(frame, (kp_x1, kp_y1), (kp_x2, kp_y2), kalman_grey, 1)
        kp_label = f'{NoteType.SLIDE.name}.{kp["note_variant"].name} ID:{kp["track_id"]}'
        kp_label_size = label_size_cache.get(kp_label)
        if kp_label_size is None:
            kp_label_size = cv2.getTextSize(kp_label, _LABEL_FONT, _LABEL_SCALE, 1)[0]
            label_size_cache[kp_label] = kp_label_size
        cv2.rectangle(frame, (kp_x1, kp_y1 - kp_label_size[1] - 10),
                      (kp_x1 + kp_label_size[0], kp_y1), kalman_grey, -1)
        cv2.putText(frame, kp_label, (kp_x1, kp_y1 - 5),
                    _LABEL_FONT, _LABEL_SCALE, _LABEL_COLOR, 1)
