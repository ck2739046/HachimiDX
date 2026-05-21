import os
import librosa
import numpy as np
import warnings
from contextlib import contextmanager

from src.services import PathManage
from ..schemas.op_result import OpResult, ok, err

MATCH_DURATION_SEC = 10

STEP_MS = 1
ENVELOPE_SMOOTH_MS = 10.0


@contextmanager
def suppress_audio_warnings():
    """抑制音频加载时的警告和错误信息"""
    # 抑制 librosa FutureWarning
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=FutureWarning, module="librosa")
        warnings.filterwarnings("ignore", message='PySoundFile failed. Trying audioread instead.')
        yield




def main(file_path, bpm, click_times, start_time_sec) -> OpResult[dict]:
    """
    在视频中的音频起始时间 (ms)

    参数:
        file_path (str): 包含音频的文件的路径
        bpm (float|int): 启动拍的bpm
        click_times (int): 启动拍数量
        start_time_sec (float|int): 在 file_path 中的起始时间（秒），
            表示从该时间点开始截取音频用于匹配

    返回:
        OpResult[dict]:
            - match_time: 匹配时间 (ms) 
            - generated_click_template_audio: 生成的启动拍音频 (44100Hz)
            - graph_range_start: 波形图显示的起始时间 (ms)
            - graph_range_end: 波形图显示的结束时间 (ms)
    """

    try:
        bpm = float(bpm)
        click_times = int(click_times)
        start_time_sec = float(start_time_sec)

        # Load template and audio
        template_path = str(PathManage.CLICK_TEMPLATE_PATH)
        template_data, template_sr = _load_audio_file(template_path)
        audio_data, audio_sr = _load_audio_file(file_path)

        # 仅保留从起始时间开始的 10 秒音频用于匹配
        audio_data = _extract_segment(audio_data, audio_sr, start_time_sec, MATCH_DURATION_SEC)

        # Generate multi-beat template
        full_template = generate_template(bpm, click_times, template_data, template_sr)
        
        # Resample both to 44100 Hz
        target_sr = 44100 
        if template_sr != target_sr:
            full_template = librosa.resample(full_template, orig_sr=template_sr, target_sr=target_sr)
        if audio_sr != target_sr:
            audio_data = librosa.resample(audio_data, orig_sr=audio_sr, target_sr=target_sr)
        
        # Calculate offset using structured sliding-window + local refinement
        segment_match_time_ms = template_match(audio_data, full_template, target_sr)
        # 转换为相对于原始音频起点的时间轴
        match_time_ms = segment_match_time_ms + float(start_time_sec) * 1000

        # 计算波形图显示范围
        interval_ms = 60 / bpm * 1000
        # 往前一拍
        graph_range_start = match_time_ms - interval_ms
        # 大部分歌曲开始前会等待 4 拍，此处留个 5 拍
        graph_range_end = match_time_ms + interval_ms * (click_times + 5)
        graph_range_start = max(0, graph_range_start) # 不允许负数
        graph_range_end = max(graph_range_end, graph_range_start + 2000) # 至少显示2秒

        # 返回匹配时间，以及生成的模板音频用于可视化
        return ok({
            'match_time': match_time_ms,
            'generated_click_template_audio': full_template,
            'graph_range_start': graph_range_start,
            'graph_range_end': graph_range_end
        })    
    
    except Exception as e:
        return err("Error in detect_click_start.main()", error_raw=e)




def _load_audio_file(path):
    """
    加载音频文件
    """
    try:
        if not os.path.exists(path):
            raise FileNotFoundError(f"Audio file not found: {path}")
        with suppress_audio_warnings():
            data, sr = librosa.load(path, sr=None, mono=True)
            if data is None or len(data) == 0:
                raise ValueError(f"Cannot load audio data from: {path}")
            return data, sr
    except Exception as e:
        raise Exception(f"Error loading audio file '{path}': {e}")




def _extract_segment(audio_data, sr, start_time_sec, duration_sec):
    """
    从完整音频中截取 [start_time_sec, start_time_sec + duration_sec) 片段
    """

    start_time_sec = float(start_time_sec)
    if start_time_sec < 0:
        raise ValueError(f"start_time_sec must be >= 0, got {start_time_sec}")

    start_sample = int(round(start_time_sec * sr))
    duration_samples = int(round(float(duration_sec) * sr))
    end_sample = start_sample + duration_samples

    if start_sample >= len(audio_data):
        raise ValueError(
            f"start_time_sec ({start_time_sec}) exceeds audio length ({len(audio_data) / sr:.2f}s)"
        )

    segment = audio_data[start_sample:min(end_sample, len(audio_data))]
    if segment is None or len(segment) == 0:
        raise ValueError("Extracted segment is empty")

    return segment




def generate_template(bpm, click_times, template_data, template_sr):
    """
    基于 BPM 生成多个启动拍的完整模板
    """

    template_length = len(template_data)

    # 每个 click 的间隔 (以采样点为单位)
    sample_interval = round(60.0 / bpm * template_sr)

    # 完整的音频的长度 (以采样点为单位)
    total_length = sample_interval * click_times

    # 先生成全部静音
    full_template = np.zeros(total_length, dtype=template_data.dtype)

    # 添加 click 模板音频
    for i in range(click_times):
        start_pos = i * sample_interval
        end_pos = start_pos + template_length
        if end_pos <= total_length:
            full_template[start_pos:end_pos] = template_data
        else:
            # 如果最后一个 click 超出总长度，则只添加能放下的部分
            available_length = total_length - start_pos
            full_template[start_pos:] = template_data[:available_length]

    # 剔除结尾 20 ms，给 click 和后面的乐曲开始留点空间
    end_silence_samples = int(0.02 * template_sr)
    full_template = full_template[:-end_silence_samples]

    # 在开头增加0.5秒的静音
    # start_silence_samples = int(0.5 * template_sr)
    # full_template = np.concatenate((np.zeros(start_silence_samples, dtype=template_data.dtype), full_template))

    # 调试用：保存生成的模板音频到桌面
    # from scipy.io import wavfile
    # desktop_path = os.path.join(os.path.expanduser("~"), "Desktop")
    # output_file = os.path.join(desktop_path, "generated_template.wav")
    # wavfile.write(output_file, template_sr, full_template.astype(np.float32))

    return full_template




def template_match(y_target, y_template, sr):
    """
    双阶段音频对齐流程
    阶段一：普通滑窗粗匹配（窗口长度 = 模板长度）
    阶段二：局部波形精调
    """
    if len(y_target) < len(y_template):
        raise ValueError("Audio data too short for template matching")

    # 直接由原始波形计算能量包络
    target_env = compute_energy_envelope(y_target, sr, ENVELOPE_SMOOTH_MS)
    template_env = compute_energy_envelope(y_template, sr, ENVELOPE_SMOOTH_MS)

    offset_ms = match_sliding_window(
        target_env,
        template_env,
        sr,
        STEP_MS,
    )
    print(f"  -> Offset: {offset_ms:.2f} ms")

    return offset_ms




def match_sliding_window(target_env, template_env, sr, step_ms):
    """
    滑窗匹配：
    用模板长度作为窗口长度，按固定步进扫描，
    在每个窗口内计算包络相似度分数，取最大值对应的起点
    """

    if len(template_env) <= 0:
        raise ValueError("Template is empty")

    if len(target_env) < len(template_env):
        raise ValueError("Audio data too short for sliding window matching")

    template_norm = normalize_vector(template_env)
    template_len = len(template_env)

    max_start = len(target_env) - template_len
    step_samples = max(1, int(round(step_ms * sr / 1000.0)))

    best_score = -np.inf
    best_start = 0

    for start in range(0, max_start + 1, step_samples):
        seg = target_env[start:start + template_len]
        seg_norm = normalize_vector(seg)
        score = float(np.dot(seg_norm, template_norm))

        if score > best_score:
            best_score = score
            best_start = start

    return best_start * 1000.0 / sr




def compute_energy_envelope(y, sr, smooth_ms=8.0):
    """
    能量包络：先取平方能量，再做滑动平均平滑
    """
    if y is None or len(y) == 0:
        raise ValueError("Audio is empty")

    win_len = max(1, int(round(smooth_ms * sr / 1000.0)))
    kernel = np.ones(win_len, dtype=np.float64) / float(win_len)

    energy = np.asarray(y, dtype=np.float64) ** 2
    env = np.convolve(energy, kernel, mode='same')
    return env.astype(np.float64, copy=False)




def normalize_vector(x):
    """
    归一化: Min-Max 后再做 L2 归一化，提升幅度鲁棒性
    """
    x = np.asarray(x, dtype=np.float64)
    if x.size == 0:
        return x

    x_min = float(np.min(x))
    x_max = float(np.max(x))
    if x_max - x_min < 1e-12:
        return np.zeros_like(x)

    x = (x - x_min) / (x_max - x_min)
    norm = float(np.linalg.norm(x))
    if norm < 1e-12:
        return np.zeros_like(x)
    return x / norm
