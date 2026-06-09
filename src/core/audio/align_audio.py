import librosa
import numpy as np
from scipy import signal
import os
import warnings
from contextlib import contextmanager

from audioread.exceptions import NoBackendError

from ..schemas.op_result import OpResult, ok, err


@contextmanager
def suppress_audio_warnings():
    """抑制音频加载时的警告和错误信息"""
    # 抑制 librosa FutureWarning
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=FutureWarning, module="librosa")
        warnings.filterwarnings("ignore", message='PySoundFile failed. Trying audioread instead.')
        yield


def find_best_alignment_offset(signal1, signal2):
    """
    计算两个音频信号之间的时间偏移
    
    参数:
        signal1: 基准音频信号
        signal2: 待对齐音频信号
            
    返回:
        int: 样本偏移量
        正值: signal 2 比 signal 1 更早，需要向后移动 (加延迟)
        负值: signal 2 比 signal 1 更晚，需要向前移动 (减延迟)
    """

    # --- 零均值标准化 (Zero-Mean / Z-Score) ---
    # 1. 减去均值：消除直流偏移（DC Offset）和低频背景噪音的影响
    # 2. 除以标准差：消除音量大小差异（游戏音效大或者音乐声音小都不受影响）
    
    def standardize(sig):
        # 减去均值 (Center)
        sig = sig - np.mean(sig)
        # 除以标准差 (Scale)，加 eps 防止除以零
        std = np.std(sig)
        return sig / (std + 1e-8)
    
    sig1_norm = standardize(signal1)
    sig2_norm = standardize(signal2)
    
    # 执行互相关 (FFT加速)
    correlation = signal.correlate(sig1_norm, sig2_norm, mode='full', method='fft')

    lag_index = np.argmax(correlation)
    offset = lag_index - (len(signal2) - 1)
    
    return offset


def main(file1_path, file2_path) -> OpResult[dict]:
    """
    计算两个音频文件之间的时间偏移
        
    参数:
        file1_path: 基准音频文件路径
        file2_path: 待对齐音频文件路径
            
    返回:
        OpResult[dict]:
            - offset_ms: file2 相对于 file1 的偏移（毫秒）
                         正值: file 2 比 file 1 更早，需要向后移动 (加延迟)
                         负值: file 2 比 file 1 更晚，需要向前移动 (减延迟)
            - reference_audio: 基准音频数据 (44100Hz)
            - target_audio: 目标音频数据 (44100Hz)
    """

    try:
        if not os.path.exists(file1_path):
            return err(f"File not found: {file1_path}")
        if not os.path.exists(file2_path):
            return err(f"File not found: {file2_path}")

        # 1. Load audio files
        try:
            with suppress_audio_warnings():
                y1, sr1 = librosa.load(file1_path, sr=None, mono=True) # 直接加载为 Mono
        except NoBackendError:
            return err(f"NoBackendError: {str(file1_path)}")
        except Exception as e:
            return err(f"Error loading audio from file: {file1_path}", error_raw=e)
        
        try:
            with suppress_audio_warnings():
                y2, sr2 = librosa.load(file2_path, sr=None, mono=True)
        except NoBackendError:
            return err(f"NoBackendError: {str(file2_path)}")
        except Exception as e:
            return err(f"Error loading audio from file: {file2_path}", error_raw=e)

        # 2. Resample to 44100 Hz
        target_sr = 44100
        if sr1 != target_sr:
            y1 = librosa.resample(y1, orig_sr=sr1, target_sr=target_sr)
        if sr2 != target_sr:
            y2 = librosa.resample(y2, orig_sr=sr2, target_sr=target_sr)
        
        # 3. Calculate offset
        offset_samples = find_best_alignment_offset(y1, y2)
        
        # 4. Convert to milliseconds
        offset_ms = (offset_samples / float(target_sr)) * 1000
        
        # 返回对齐结果和音频数据用于可视化
        data = {
            'offset_ms': offset_ms,
            'reference_audio': y1,
            'target_audio': y2
        }
        return ok(data)
    
    except Exception as e:
        return err(f"Error in align_audio.main", error_raw = e)
    