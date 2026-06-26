"""Single-file media inspection using ffprobe.

Public API:
- inspect_media(input_path) -> FFprobeInspectResult

Notes:
- Uses subprocess.run (not QProcess).
- Parses ffprobe JSON output.
- If multiple video/audio streams exist, selects the FIRST of each.
- Does not parse rationals; stream dicts are returned as-is.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from typing import Any, Dict
import time

import i18n

from ..schemas.op_result import OpResult, ok, err, print_op_result
from src.services import PathManage
from ..schemas.media_config import MediaType


_STREAM_ENTRIES = (
    "stream=index,codec_type,codec_name,width,height,avg_frame_rate, \
     duration,bit_rate,nb_frames,sample_rate,channels,channel_layout \
     :stream_tags=DURATION \
     :format=duration"
)


@dataclass(slots=True)
class FFprobeInspectResult:
    """
    FFprobeInspect.inspect_media() 返回的 OpResult 中的结果对象
    Args:
        media_type: 媒体类型 (TaskContract.MediaType)
        video_stream: 视频流信息字典 (Dict)
        audio_stream: 音频流信息字典 (Dict)
        duration: 总时长 (float)
    """
    media_type: MediaType
    video_stream: Dict[str, Any]
    audio_stream: Dict[str, Any]
    duration: str



class FFprobeInspect:

    @staticmethod
    def _precheck_input_path_and_ffprobe(input_path: str) -> OpResult[tuple[str, str]]:
        input_path = os.path.normpath(os.path.abspath(str(input_path)))
        ffprobe_exe = str(PathManage.FFPROBE_EXE_PATH)

        if not os.path.exists(input_path):
            return err(f"File not found: {input_path}")
        if not os.path.isfile(ffprobe_exe):
            return err(f"ffprobe.exe not found: {ffprobe_exe}")

        return ok((input_path, ffprobe_exe))




    @classmethod
    def inspect_media(cls, input_path: str) -> OpResult[FFprobeInspectResult]:
        """Inspect one media file using ffprobe.

        Args:
            input_path: Path to a single media file.

        Returns:
            OpResult: FFprobeInspectResult
        """

        # pre check
        precheck_res = cls._precheck_input_path_and_ffprobe(input_path)
        if not precheck_res.is_ok:
            return err(precheck_res.error_msg, inner=precheck_res)
        input_path, ffprobe_exe = precheck_res.value

        
        # run ffprobe、
        args = ["-v", "error",
                "-show_entries", _STREAM_ENTRIES,
                "-of", "json",
                input_path]
        result = cls._run_ffprobe(ffprobe_exe, args, parse_json=True)
        if not result.is_ok:
            return result
        raw = result.value


        # parse ffprobe output
        result = cls._filter_valid_streams(raw)
        if not result.is_ok:
            return result
        duration_format, streams = result.value

        result = cls._select_first_stream(streams, "video")
        if not result.is_ok:
            has_video = False
            first_video_stream = {}
        else:
            has_video = True
            first_video_stream = result.value
            
        result = cls._select_first_stream(streams, "audio")
        if not result.is_ok:
            has_audio = False
            first_audio_stream = {}
        else:
            has_audio = True
            first_audio_stream = result.value

        result = cls._pick_duration(duration_format, first_video_stream, first_audio_stream)
        if not result.is_ok:
            return result
        duration = result.value

        if has_video and has_audio:
            media_type = MediaType.VIDEO_WITH_AUDIO
        elif has_video and not has_audio:
            media_type = MediaType.VIDEO_WITHOUT_AUDIO
        elif not has_video and has_audio:
            media_type = MediaType.AUDIO
        else:
            media_type = MediaType.UNKNOWN
            return err("no video or audio streams after select first", error_raw=raw)

        if has_video:
            first_video_stream["final_duration"] = duration
            stream_info = cls._build_stream_info_str(first_video_stream)
            first_video_stream["info_str"] = stream_info
            
        if has_audio:
            first_audio_stream["final_duration"] = duration
            stream_info = cls._build_stream_info_str(first_audio_stream)
            first_audio_stream["info_str"] = stream_info

        return ok(FFprobeInspectResult(
                    media_type=media_type,
                    video_stream=first_video_stream,
                    audio_stream=first_audio_stream,
                    duration=duration)
                )






    @classmethod
    def inspect_video_frame_timestamps_msec(cls, input_path: str) -> OpResult[list[float]]:
        """Inspect frame-level timestamps for video stream only.

        Notes:
        - This function is intentionally separated from inspect_media so UI
          widgets keep their lightweight default probe behavior.
        - Returned timestamps are normalized to the first decoded frame (0 ms).

        Returns:
            OpResult: list[float] where index is frame number and value is ms.
        """

        start_time = time.time()

        precheck_res = cls._precheck_input_path_and_ffprobe(input_path)
        if not precheck_res.is_ok:
            return err(precheck_res.error_msg, inner=precheck_res)
        input_path, ffprobe_exe = precheck_res.value

        # CFR 快速路径: 仅读取容器头部不解码，CFR 视频直接计算时间戳
        cfr_result = cls._check_if_cfr(ffprobe_exe, input_path)
        if not cfr_result.is_ok:
            print(f"Video CFR check failed: \n{print_op_result(cfr_result)}")
        else:
            is_cfr, avg_frame_rate, nb_frames = cfr_result.value
            if is_cfr:
                # 如果是 CFR, 直接构建列表
                interval_msec = 1000.0 / avg_frame_rate
                return ok([i * interval_msec for i in range(nb_frames)])


        # 如果 CFR 解析失败, 或者解析成功但视频为 VFR, 精确解析每帧时间戳
        print("开始精确逐帧解析视频帧时间戳...")
        args = ["-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "frame=best_effort_timestamp_time,pkt_pts_time",
                "-of", "csv=p=0",
                input_path]
        frame_result = cls._run_ffprobe(ffprobe_exe, args, parse_json=False)
        if not frame_result.is_ok:
            return err("ffprobe frame timestamp inspect failed", inner=frame_result)

        sec_list: list[float] = []
        for raw_line in (frame_result.value or "").splitlines():
            line = raw_line.strip()
            if not line:
                continue

            parsed_sec = None
            for token in line.split(","):
                token = token.strip()
                if not token or token == "N/A":
                    continue
                try:
                    parsed_sec = float(token)
                    break
                except Exception:
                    continue

            if parsed_sec is not None:
                sec_list.append(parsed_sec)

        if len(sec_list) == 0:
            return err("ffprobe returned no valid frame timestamps")

        base_sec = sec_list[0]
        msec_list = [max((sec - base_sec) * 1000.0, 0.0) for sec in sec_list]

        # Keep timestamp sequence monotonic to avoid tiny negative drift from float noise.
        for i in range(1, len(msec_list)):
            if msec_list[i] < msec_list[i - 1]:
                msec_list[i] = msec_list[i - 1]

        end_time = time.time()
        print(f'视频帧时间戳分析完成，耗时: {end_time - start_time:.1f}s')

        return ok(msec_list)
    



    @classmethod
    def _check_if_cfr(cls, ffprobe_exe: str, input_path: str) -> OpResult[tuple[bool, float, int]]:
        """
        Lightweight header-only probe to check CFR.
        Only reads container headers, does NOT decode any frames.

        Returns:
            OpResult[tuple[bool, float, int]]:
                is_cfr, avg_frame_rate, nb_frames.
        """

        def _parse_float(value: str) -> float | None:
            try:
                if "/" in str(value):
                    num, denom = str(value).split("/")
                    return float(num) / float(denom)
                return float(value)
            except Exception:
                return None

        args = ["-v", "error",
                "-show_entries", "stream=avg_frame_rate,r_frame_rate,nb_frames",
                "-of", "json",
                input_path]
        result = cls._run_ffprobe(ffprobe_exe, args, parse_json=True)
        if not result.is_ok:
            return err("CFR 探测失败", inner=result)
        data = result.value

        streams = data.get("streams", [])
        if not streams:
            return err("CFR 探测失败: 未找到视频流")

        stream = streams[0]
        avg_frame_rate_raw = stream.get("avg_frame_rate", "N/A")
        r_frame_rate_raw = stream.get("r_frame_rate", "N/A")
        nb_frames_raw = stream.get("nb_frames", "N/A")

        # Parse avg_frame_rate
        fps = _parse_float(avg_frame_rate_raw)
        if fps is None or fps <= 0:
            return err(f"CFR 探测失败: 无法解析 avg_frame_rate={avg_frame_rate_raw}")

        # Parse r_frame_rate
        r_fps = _parse_float(r_frame_rate_raw)
        if r_fps is None or r_fps <= 0:
            return err(f"CFR 探测失败: 无法解析 r_frame_rate={r_frame_rate_raw}")

        # CFR 判定: avg_frame_rate == r_frame_rate
        if abs(fps - r_fps) > 0.001:
            return ok((False, 0, 0))

        # Parse nb_frames
        try:
            nb_frames = int(nb_frames_raw)
        except Exception:
            return err(f"CFR 探测失败: 无法解析 nb_frames={nb_frames_raw}")

        if nb_frames <= 0:
            return err(f"CFR 探测失败: nb_frames={nb_frames} <= 0")

        return ok((True, fps, nb_frames))





    @classmethod
    def _run_ffprobe(cls, ffprobe_exe: str, args: list[str], *, parse_json: bool = True) -> OpResult[any]:
        """Run ffprobe and return structured result.

        Args:
            ffprobe_exe: Path to ffprobe executable.
            args: Arguments to pass to ffprobe (excluding exe path).
            parse_json: If True, parse stdout as JSON; if False, return raw text.

        Returns:
            OpResult[dict] when parse_json=True, OpResult[str] when parse_json=False.
        """
        try:
            result = subprocess.run([ffprobe_exe] + args,
                                    capture_output=True,
                                    text=True,
                                    encoding="utf-8",
                                    errors="replace",)
        except Exception as e:
            return err(str(e), error_raw=e)

        if result.returncode != 0:
            error_msg = f"ffprobe failed: exit_code={result.returncode}"
            raw = ""
            stderr = (result.stderr or "").strip()
            stdout = (result.stdout or "").strip()
            if stderr:
                raw += f"stderr=\n{stderr}"
            if stdout:
                raw += f"\nstdout=\n{stdout}"
            return err(error_msg, error_raw=raw)

        if not parse_json:
            return ok(result.stdout) # success

        try:
            raw = json.loads(result.stdout)
            return ok(raw) # success
        except Exception as e:
            error_msg = f"ffprobe output parse failed: {str(e)}"
            raw = ""
            stderr = (result.stderr or "").strip()
            stdout = (result.stdout or "").strip()
            if stderr:
                raw += f"stderr=\n{stderr}"
            if stdout:
                raw += f"\nstdout=\n{stdout}"
            return err(error_msg, error_raw=raw)
    
    

    @classmethod
    def _filter_valid_streams(cls, raw: any) -> OpResult[tuple[str, list[dict]]]:
        """
        Returns:
            OpResult: tuple( duration_format: str, valid_streams: list[dict] )
        """

        streams = raw.get("streams", [])
        if not isinstance(streams, list) or len(streams) == 0:
            error_msg="ffprobe output missing 'streams' list"
            return err(error_msg, error_raw=raw)
        
        try:
            duration_format = raw["format"]["duration"]
        except Exception:
            duration_format = "N/A"
        
        valid_streams = []
        for s in streams:
            if not isinstance(s, dict):
                continue
            codec_type = s.get("codec_type", 'N/A')

            if codec_type == "video":
                index = s.get("index", 'N/A')
                codec_name = s.get("codec_name", 'N/A')
                w = s.get("width", 'N/A')
                h = s.get("height", 'N/A')
                fps = s.get("avg_frame_rate", 'N/A')
                duration_stream = s.get("duration", 'N/A')
                bit_rate = s.get("bit_rate", 'N/A')
                frames = s.get("nb_frames", 'N/A')
                duration_tag = s.get("tags").get("DURATION", 'N/A') if s.get("tags") else 'N/A'

                # 如果duration_stream, duration_tag, duration_format全部为 N/A，视为 invalid
                if duration_stream == 'N/A' and duration_tag == 'N/A' and duration_format == 'N/A':
                    print(i18n.t("media_ffprobe_inspect.notice_ignore_invalid_video_stream_no_duration", stream_info=str(s)))
                    continue  # invalid
                # 允许 bit_rate/frames 缺失
                if 'N/A' in [index, codec_name, w, h, fps]:
                    na_fields = ",".join([f for f in [index, codec_name, w, h, fps] if f == 'N/A'])
                    print(i18n.t("media_ffprobe_inspect.notice_ignore_invalid_video_stream", na_fields=na_fields, stream_info=str(s)))
                    continue  # invalid
                # 有时候 mp3 封面会被识别为视频流
                if codec_name in ["png", "mjpeg"]:
                    print(i18n.t("media_ffprobe_inspect.notice_ignore_invalid_video_stream_cover", stream_info=str(s)))
                    continue  # invalid

            if codec_type == "audio":
                index = s.get("index", 'N/A')
                codec_name = s.get("codec_name", 'N/A')
                sample_rate = s.get("sample_rate", 'N/A')
                channels = s.get("channels", 'N/A')
                channel_layout = s.get("channel_layout", 'N/A')
                duration_stream = s.get("duration", 'N/A')
                bit_rate = s.get("bit_rate", 'N/A')
                duration_tag = s.get("tags").get("DURATION", 'N/A') if s.get("tags") else 'N/A'

                # 如果duration_stream, duration_tag, duration_format全部为 N/A，视为 invalid
                if duration_stream == 'N/A' and duration_tag == 'N/A' and duration_format == 'N/A':
                    print(i18n.t("media_ffprobe_inspect.notice_ignore_invalid_audio_stream_no_duration", stream_info=str(s)))
                    continue  # invalid
                # 允许 bit_rate 缺失
                # 允许 channel_layout 缺失（PCM WAV 等格式通常不提供 channel_layout）
                if 'N/A' in [index, codec_name, sample_rate, channels]:
                    na_fields = ",".join([f for f in [index, codec_name, sample_rate, channels] if f == 'N/A'])
                    print(i18n.t("media_ffprobe_inspect.notice_ignore_invalid_audio_stream", na_fields=na_fields, stream_info=str(s)))
                    continue  # invalid

            valid_streams.append(s)

        if len(valid_streams) == 0:
            error_msg="no valid streams"
            return err(error_msg, error_raw=raw)
        
        return ok( (duration_format, valid_streams) )
    



    @classmethod
    def _select_first_stream(cls, streams: list[dict], codec_type: str) -> OpResult[dict]:
        """
        Returns:
            OpResult: first_stream: dict
        """

        target_streams = {}
        for s in streams:
            if isinstance(s, dict) and s.get("codec_type") == codec_type:
                try:
                    index = int(s.get("index"))
                    target_streams[index] = s
                except:
                    pass

        if len(target_streams) == 0:
            error_msg = f"failed to select the first {codec_type} stream"
            return err(error_msg)
        
        selected_index = min(target_streams.keys()) 
        if len(target_streams) != 1:
            print(i18n.t("media_ffprobe_inspect.notice_multiple_streams_detected", codec_type=codec_type, selected_index=selected_index)) 

        return ok(target_streams[selected_index])
    



    @staticmethod
    def _build_stream_info_str(stream: Dict[str, Any]) -> str:

        def try_round(value: any, decimal: int) -> str:
            try:
                if "/" in str(value):
                    num, denom = str(value).split("/")
                    return str(round(float(num) / float(denom), decimal))
                return str(round(float(value), decimal))
            except Exception:
                return "N/A"
            
        def try_divide(value: any, divider: any) -> str:
            try:
                if "/" in str(value):
                    num, denom = str(value).split("/")
                    return str(round((float(num) / float(denom)) / divider))
                return str(round(float(value) / divider))
            except Exception:
                return "N/A"
            
        if stream.get("codec_type") == "video":
            video_codec = stream.get("codec_name", "N/A")
            video_bit_rate = stream.get("bit_rate", "N/A")
            if video_bit_rate != "N/A":
                video_bit_rate = try_divide(video_bit_rate, 1000) + "kbps"
            duration = stream.get("final_duration", "N/A")
            if duration != "N/A":
                duration = try_round(duration, 3) + "s"
            resolution = f"{stream.get('width', 'N/A')}x{stream.get('height', 'N/A')}"
            fps = stream.get("avg_frame_rate", "N/A")
            if fps != "N/A":
                fps = try_round(fps, 2)

            stream_info = i18n.t("media_ffprobe_inspect.ui_video_stream_info",
                                 codec = video_codec,
                                 bit_rate = video_bit_rate,
                                 duration = duration,
                                 resolution = resolution,
                                 fps = fps)
        
        if stream.get("codec_type") == "audio":
            audio_codec = stream.get("codec_name", "N/A")
            audio_bit_rate = stream.get("bit_rate", "N/A")
            if audio_bit_rate != "N/A":
                audio_bit_rate = try_divide(audio_bit_rate, 1000) + "kbps"
            duration = stream.get("final_duration", "N/A")
            if duration != "N/A":
                duration = try_round(duration, 3) + "s"
            sample_rate = stream.get("sample_rate", "N/A")
            if sample_rate != "N/A":
                sample_rate = sample_rate + "Hz"

            stream_info = i18n.t("media_ffprobe_inspect.ui_audio_stream_info",
                                 codec = audio_codec,
                                 bit_rate = audio_bit_rate,
                                 duration = duration,
                                 sample_rate = sample_rate)
            
        return stream_info


    @staticmethod
    def _pick_duration(duration_format: str, video_stream: Dict[str, Any], audio_stream: Dict[str, Any]) -> OpResult[str]:
        """
        优先级: format > max(stream) > max(tag)
        """

        error_msg = []

        # 1. 尝试 format duration
        try:
            return ok(str(float(duration_format)))
        except Exception:
            error_msg.append(f"format duration parse failed: {duration_format}")

        # 2. 尝试 video/audio stream duration
        v_raw = video_stream.get("duration", "N/A")
        a_raw = audio_stream.get("duration", "N/A")

        try:
            v = float(v_raw)
        except Exception:
            v = None

        try:
            a = float(a_raw)
        except Exception:
            a = None

        has_v = v is not None
        has_a = a is not None

        if has_v and has_a: return ok(str(max(v, a)))
        if has_v and not has_a: return ok(str(v))
        if not has_v and has_a: return ok(str(a))
        
        error_msg.append(f"stream duration parse failed, v={v_raw}, a={a_raw}")

        # 3. 尝试 video/audio tag duration
        v_tag_raw = video_stream.get("tags").get("DURATION", "N/A") if video_stream.get("tags") else "N/A"
        a_tag_raw = audio_stream.get("tags").get("DURATION", "N/A") if audio_stream.get("tags") else "N/A"

        try:
            try:
                # 先尝试直接转float
                v_tag = float(v_tag_raw)
            except Exception:
                # 再尝试 hh:mm:ss.micro -> float seconds
                hms = v_tag_raw.split(":")
                hours = float(hms[0])
                minutes = float(hms[1])
                seconds = float(hms[2])
                v_tag = float(hours * 3600 + minutes * 60 + seconds)
                if v_tag <= 0: v_tag = None
        except Exception:
            v_tag = None
        
        try:
            try:
                # 先尝试直接转float
                a_tag = float(a_tag_raw)
            except Exception:
                # hh:mm:ss.micro -> float seconds
                hms = a_tag_raw.split(":")
                hours = float(hms[0])
                minutes = float(hms[1])
                seconds = float(hms[2])
                a_tag = float(hours * 3600 + minutes * 60 + seconds)
                if a_tag <= 0: a_tag = None
        except Exception:
            a_tag = None
        
        has_v_tag = v_tag is not None
        has_a_tag = a_tag is not None

        if has_v_tag and has_a_tag: return ok(str(max(v_tag, a_tag)))
        if has_v_tag and not has_a_tag: return ok(str(v_tag))
        if not has_v_tag and has_a_tag: return ok(str(a_tag))

        error_msg.append(f"tag duration parse failed, v={v_tag_raw}, a={a_tag_raw}")

        # 全部失败了
        return err("\n".join(error_msg))
