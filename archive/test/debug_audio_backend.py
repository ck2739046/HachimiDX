"""
诊断 audioread / librosa 的 ffmpeg 后端是否可用。
"""

import sys
import shutil
from pathlib import Path

# --- 注入项目根目录到 sys.path（与 worker 逻辑一致） ---
ROOT = str(Path(__file__).resolve().parents[2])
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.services import PathManage

print("=" * 60)
print("AUDIOREAD / LIBROSA FFMPEG 后端诊断")
print("=" * 60)

# ============================================================
# [1] 验证 FFMPEG_EXE_PATH 存在
# ============================================================
_ffmpeg_path = PathManage.FFMPEG_EXE_PATH
_ffmpeg_str = str(_ffmpeg_path)
_script_dir = Path(__file__).resolve().parent
_test_audio = str(_script_dir / "初音ミクの暴走_standardized.mp4")

print(f"\n[1] FFMPEG_EXE_PATH: {_ffmpeg_str}")
print(f"    文件存在: {_ffmpeg_path.is_file()}")
print(f"    测试文件: {_test_audio}")
print(f"    测试文件存在: {Path(_test_audio).is_file()}")

if not _ffmpeg_path.is_file():
    print("    [FAIL] ffmpeg.exe 不存在，终止。")
    sys.exit(1)

import audioread

# ============================================================
# [2] 注入前：COMMANDS、PATH 解析
# ============================================================
print(f"\n[2] 注入前")
print(f"    audioread.ffdec.COMMANDS: {audioread.ffdec.COMMANDS}")
print(f"    PATH 解析（shutil.which）：")
for cmd in audioread.ffdec.COMMANDS:
    resolved = shutil.which(cmd)
    if resolved:
        print(f"      '{cmd}' -> {resolved}")
    else:
        print(f"      '{cmd}' -> (在 PATH 中未找到)")

# ============================================================
# [3] 注入前测试：audio_open 打开测试文件
# ============================================================
print(f"\n[3] 注入前测试")
print(f"    audioread.audio_open() 测试：")
try:
    with audioread.audio_open(_test_audio) as f:
        print(f"      [OK] sr={f.samplerate}, ch={f.channels}, duration={f.duration:.3f}s")
except audioread.exceptions.NoBackendError:
    print(f"      [预期] NoBackendError —— 系统 PATH 中没有 ffmpeg，mp4 无法解码")
except Exception as e:
    print(f"      [异常] {type(e).__name__}: {e}")

# ============================================================
# [4] 注入（与 audio_align_worker.py L25-30 完全一致）
# ============================================================
print(f"\n[4] 注入")
if _ffmpeg_str not in audioread.ffdec.COMMANDS:
    audioread.ffdec.COMMANDS = (_ffmpeg_str,) + audioread.ffdec.COMMANDS
    print(f"    已写入: {_ffmpeg_str}")
else:
    print(f"    已在列表中，跳过")

# ============================================================
# [5] 注入后：COMMANDS、PATH 解析
# ============================================================
print(f"\n[5] 注入后")
print(f"    audioread.ffdec.COMMANDS: {audioread.ffdec.COMMANDS}")
print(f"    PATH 解析（shutil.which）：")
for cmd in audioread.ffdec.COMMANDS:
    resolved = shutil.which(cmd)
    if resolved:
        print(f"      '{cmd}' -> {resolved}")
    else:
        print(f"      '{cmd}' -> (在 PATH 中未找到)")

# ============================================================
# [6] 注入后测试：刷新缓存，audio_open + librosa.load
# ============================================================
audioread.available_backends(flush_cache=True)
backends = audioread.available_backends()

print(f"\n[6] 注入后测试")
print(f"    audioread 可用后端: {backends}")
print(f"    audioread.audio_open() 测试：")
try:
    with audioread.audio_open(_test_audio) as f:
        print(f"      [OK] sr={f.samplerate}, ch={f.channels}, duration={f.duration:.3f}s")
except audioread.exceptions.NoBackendError:
    print(f"      [FAIL] NoBackendError —— 注入后仍失败！")
except Exception as e:
    print(f"      [异常] {type(e).__name__}: {e}")

import librosa

print(f"    librosa.load() 测试：")
try:
    y, sr = librosa.load(_test_audio, sr=None, duration=1.0)
    print(f"      [OK] sr={sr}, samples={len(y)}, duration={len(y)/sr:.3f}s")
except audioread.exceptions.NoBackendError as e:
    print(f"      [FAIL] NoBackendError: {e}")
except Exception as e:
    print(f"      [异常] {type(e).__name__}: {e}")

print("\n" + "=" * 60)
print("诊断结束")
print("=" * 60)
