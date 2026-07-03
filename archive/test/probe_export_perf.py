"""
export_track_video 性能探针: 分段计时主循环, 定位瓶颈所在。

三段计时:
  T_decode : cap.read()          视频解码
  T_draw   : 轨迹+音符框绘制     Python/CV2 计算
  T_write  : stdin.write()       FFmpeg 反压 (编码跟不上则阻塞在此)
  T_wait   : ffmpeg.wait()       尾部收尾编码

判断规则:
  - T_write 占比大  -> FFmpeg 编码是瓶颈 (管道反压)
  - T_draw  占比大  -> Python 绘制是瓶颈
  - T_decode 占比大 -> 视频解码是瓶颈

对照实验:
  --no-draw : 跳过所有绘制, 只读帧+喂 ffmpeg, 得到 FFmpeg baseline fps。
              若 --no-draw 的 fps 与完整流程接近 -> 瓶颈在 ffmpeg;
              若大很多 -> 瓶颈在 Python 绘制。

用法:
  python archive/test/probe_export_perf.py <std_video_path> [--no-draw] [--preset veryfast]
"""
import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# 私有函数仅供诊断用
from src.core.auto_rechart.detect.export_track_video import (  # noqa: E402
    _load_track_results, _build_manifests, _TrailBuilder, _color_for_id,
    _BATCH_FRAMES,
)
from src.core.auto_rechart.detect.export_track_video import main as export_main  # noqa: E402
from src.services import PathManage  # noqa: E402


def _fmt_pct(v: float, total: float) -> str:
    return f"{v:7.2f}s ({v / total * 100:5.1f}%)" if total > 0 else f"{v:7.2f}s (  -  )"


def probe(std_video_path: Path, no_draw: bool, preset: str,
          parallel: bool = False, synthetic_draw: int = 0) -> None:
    cap = cv2.VideoCapture(str(std_video_path))
    video_width = round(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    video_height = round(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    fps_for_calc = float(fps) if fps and fps > 0 else 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    # yuv420p 直传: 数据量减半 (1.5 B/px), 跳过 ffmpeg 内部 bgr->yuv 转换
    yuv = args.yuv
    bytes_per_pixel = 1.5 if yuv else 3
    frame_size = int(video_width * video_height * bytes_per_pixel)
    print(f"视频: {video_width}x{video_height} @ {fps_for_calc:.1f}fps, 共 {total_frames} 帧")

    # 纯解码上限: 只 cap.read, 不绘制不编码, 得到 decode 理论天花板
    if args.decode_only:
        t0 = time.perf_counter()
        n = 0
        while True:
            ret, _ = cap.read()
            if not ret:
                break
            n += 1
        dt = time.perf_counter() - t0
        cap.release()
        print(f"\n===== DECODE-ONLY (纯 cap.read 天花板) =====")
        print(f"{n} 帧 / {dt:.2f}s = {n / dt:.1f} fps  (这是任何流程都无法超越的解码上限)")
        return

    try:
        track_results = _load_track_results(std_video_path.parent)
    except FileNotFoundError:
        track_results = {}
        print("警告: 未找到 track_result.txt, 使用空追踪结果 (仅可测 FFmpeg baseline / 无绘制路径)")

    timeout_frames = max(1, int(round(fps_for_calc / 2.0)))

    # 预扫描
    t0 = time.perf_counter()
    note_manifest, center_manifest = _build_manifests(track_results, total_frames)
    print(f"预扫描(build_manifests): {time.perf_counter() - t0:.3f}s")

    # 输出路径 (探针输出到 temp, 避免覆盖正式产物)
    tag = 'nodraw' if no_draw else 'draw'
    if args.no_audio:
        tag += '_noaudio'
    if parallel:
        tag += '_par'
    if args.hwenc:
        tag += '_nvenc'
    if args.yuv:
        tag += '_yuv'
    if synthetic_draw:
        tag += f'_syn{synthetic_draw}'
    out_path = std_video_path.parent / f"_probe_{tag}.mp4"
    if out_path.exists():
        os.remove(out_path)

    ffmpeg_cmd = [
        str(PathManage.FFMPEG_EXE_PATH),
        '-y', '-hide_banner', '-loglevel', 'error',
        '-f', 'rawvideo', '-pix_fmt', 'yuv420p' if yuv else 'bgr24',
        '-s', f'{video_width}x{video_height}', '-r', str(fps_for_calc),
        '-i', '-',
    ]
    # 视频编码器: hwenc=True 用 h264_nvenc (GPU), 否则 libx264 (CPU, 按 preset)
    if args.hwenc:
        venc = ['-c:v', 'h264_nvenc', '-preset', 'p4', '-cq', '23', '-pix_fmt', 'yuv420p']
    else:
        venc = ['-c:v', 'libx264', '-preset', preset, '-crf', '23', '-pix_fmt', 'yuv420p']

    if args.no_audio:
        # 无音频对照: 去掉第二个输入, 隔离音频解复用/解码开销
        ffmpeg_cmd += venc + ['-map', '0:v:0', str(out_path)]
    else:
        ffmpeg_cmd += [
            '-i', str(std_video_path),
        ] + venc + [
            '-c:a', 'aac', '-b:a', '192k',
            '-map', '0:v:0', '-map', '1:a:0?', '-shortest',
            str(out_path),
        ]
    proc = subprocess.Popen(
        ffmpeg_cmd, stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        bufsize=_BATCH_FRAMES * frame_size,
    )
    stdin = proc.stdin
    batch = bytearray(_BATCH_FRAMES * frame_size)
    batch_mv = memoryview(batch)

    # 解码源: parallel=True 时后台线程解码, 主线程从队列取帧; 否则串行 cap.read
    # 注: cvtColor 不放此线程 —— 解码线程已是较慢方, 加 cvt 会反成瓶颈 (实测 58s > 47s)
    decode_thread = None
    if parallel:
        import threading as _threading
        import queue as _queue
        decode_queue: "_queue.Queue" = _queue.Queue(maxsize=10)

        def _dw(_cap, _q):
            try:
                while True:
                    r, f = _cap.read()
                    _q.put((r, f))
                    if not r:
                        return
            except Exception:
                _q.put((False, None))

        decode_thread = _threading.Thread(target=_dw, args=(cap, decode_queue), daemon=True)
        decode_thread.start()

        def get_frame():
            return decode_queue.get()
    else:
        def get_frame():
            return cap.read()

    builders: dict = {}
    last_seen: dict = {}

    t_decode = t_draw = t_write = t_cvt = 0.0
    off = 0
    count_in_batch = 0

    t_loop_start = time.perf_counter()
    for frame_number in range(total_frames):
        ts = time.perf_counter()
        ret, frame = get_frame()
        t_decode += time.perf_counter() - ts
        if not ret:
            break
        if not frame.flags['C_CONTIGUOUS']:
            frame = np.ascontiguousarray(frame)

        # 合成绘制负载: 模拟真实音符框+标签的绘制成本 (N 个/帧), 不依赖 track 数据
        if synthetic_draw > 0:
            ts = time.perf_counter()
            for i in range(synthetic_draw):
                x1, y1 = 100 + i * 20, 100 + (i % 5) * 30
                cv2.rectangle(frame, (x1, y1), (x1 + 60, y1 + 40), (0, 0, 190), 2)
                cv2.rectangle(frame, (x1, y1 - 22), (x1 + 90, y1), (0, 0, 190), -1)
                cv2.putText(frame, f'SLIDE.normal ID:{i}', (x1, y1 - 5),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
            t_draw += time.perf_counter() - ts

        if not no_draw:
            ts = time.perf_counter()
            active_now: set = set()
            for (tid, is_slide, cx, cy) in center_manifest[frame_number]:
                b = builders.get(tid)
                if b is None:
                    b = _TrailBuilder(is_slide)
                    builders[tid] = b
                b.add_point(cx, cy)
                last_seen[tid] = frame_number
                active_now.add(tid)
            evict = [tid for tid in builders
                     if tid not in active_now
                     and (frame_number - last_seen[tid]) > timeout_frames]
            for tid in evict:
                del builders[tid]
                del last_seen[tid]
            for tid, b in builders.items():
                poly = b.current_polyline()
                if poly is not None and len(poly) > 1:
                    color = _color_for_id(tid)
                    cv2.polylines(frame, [poly], False, color, 3)
                    cv2.circle(frame, b.start_pt, 3, color, -1)
            for nd in note_manifest[frame_number]:
                if nd.is_obb:
                    cv2.polylines(frame, [nd.obb_pts], True, nd.color, 2)
                else:
                    r = nd.rect
                    cv2.rectangle(frame, (r[0], r[1]), (r[2], r[3]), nd.color, 2)
                bg = nd.label_bg
                cv2.rectangle(frame, bg[0], bg[1], nd.color, -1)
                cv2.putText(frame, nd.label, nd.label_org, cv2.FONT_HERSHEY_SIMPLEX,
                            0.6, (255, 255, 255), 2)
            t_draw += time.perf_counter() - ts

        # yuv420p 直传: BGR -> YUV_I420 (内存布局即 yuv420p), 数据量减半
        # 始终在主线程做: 解码线程已满载 (decode 33s > 主线程无 cvt 18s), 放它那更慢
        if yuv:
            ts = time.perf_counter()
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2YUV_I420)
            t_cvt += time.perf_counter() - ts

        batch_mv[off:off + frame_size] = frame.reshape(-1)
        off += frame_size
        count_in_batch += 1

        if count_in_batch == _BATCH_FRAMES:
            ts = time.perf_counter()
            stdin.write(batch_mv[:off])
            t_write += time.perf_counter() - ts
            off = 0
            count_in_batch = 0

    if off > 0:
        ts = time.perf_counter()
        stdin.write(batch_mv[:off])
        t_write += time.perf_counter() - ts

    if decode_thread is not None:
        decode_thread.join()

    stdin.close()
    t_wait_start = time.perf_counter()
    rc = proc.wait()
    t_wait = time.perf_counter() - t_wait_start
    stderr = proc.stderr.read().decode('utf-8', 'ignore') if proc.stderr else ""
    cap.release()
    if rc != 0:
        print(f"FFmpeg 失败 rc={rc}: {stderr}")
        return

    t_total = time.perf_counter() - t_loop_start
    fps = total_frames / t_total if t_total > 0 else 0

    mode = "NO-DRAW (FFmpeg baseline)" if no_draw else "FULL (含绘制)"
    if parallel:
        mode += " +并行解码"
    if synthetic_draw:
        mode += f" +合成绘制x{synthetic_draw}"
    if yuv:
        mode += " +yuv420p直传"
    print(f"\n===== {mode}  preset={preset} =====")
    print(f"总耗时(主循环+wait): {t_total:.2f}s   平均 {fps:.1f} fps")
    print(f"  T_get    (取帧/阻塞): {_fmt_pct(t_decode, t_total)}  <- 并行模式下接近0=解码跑赢, 大=解码是瓶颈")
    print(f"  T_draw   (绘制)     : {_fmt_pct(t_draw, t_total)}")
    if yuv:
        print(f"  T_cvt    (BGR->YUV) : {_fmt_pct(t_cvt, t_total)}")
    print(f"  T_write  (反压)     : {_fmt_pct(t_write, t_total)}")
    print(f"  T_wait   (收尾)     : {_fmt_pct(t_wait, t_total)}")
    print(f"输出: {out_path}")


def run_real_main(std_video_path: Path) -> None:
    """直接调用真实 export_track_video.main(), 端到端计时 (含并行解码)。"""
    import cv2
    cap = cv2.VideoCapture(str(std_video_path))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    t0 = time.perf_counter()
    result = export_main(std_video_path, total_frames)
    dt = time.perf_counter() - t0
    fps = total_frames / dt if dt > 0 else 0
    print(f"\n===== REAL-MAIN (改后的真实 main, 含并行解码) =====")
    print(f"总耗时: {dt:.2f}s   平均 {fps:.1f} fps   结果 is_ok={result.is_ok}")
    if not result.is_ok:
        print(f"错误: {result.error_msg} | {result.error_raw}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("std_video_path", type=Path)
    ap.add_argument("--no-draw", action="store_true", help="跳过绘制, 测 FFmpeg baseline")
    ap.add_argument("--decode-only", action="store_true", help="只测 cap.read 解码上限, 不编码不绘制")
    ap.add_argument("--no-audio", action="store_true", help="去掉第二个音频输入, 隔离音频开销")
    ap.add_argument("--real-main", action="store_true", help="直接调用改后的真实 main() 端到端计时")
    ap.add_argument("--parallel", action="store_true", help="后台线程解码, 与绘制并行 (模拟改后的 main)")
    ap.add_argument("--synthetic-draw", type=int, default=0, help="每帧合成绘制 N 个框+标签, 模拟真实绘制负载")
    ap.add_argument("--hwenc", action="store_true", help="用 h264_nvenc 硬件编码 (GPU) 代替 libx264")
    ap.add_argument("--yuv", action="store_true", help="直传 yuv420p (Python 侧 cvtColor, 数据量减半)")
    ap.add_argument("--preset", default="veryfast", help="x264 preset (veryfast/fast/ultrafast...)")
    args = ap.parse_args()
    if args.real_main:
        run_real_main(args.std_video_path)
    else:
        probe(args.std_video_path, args.no_draw, args.preset,
              parallel=args.parallel, synthetic_draw=args.synthetic_draw)
        