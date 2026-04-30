import sys
from pathlib import Path
import io
import os
import subprocess

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', write_through=True)
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace', write_through=True)


if len(sys.argv) <= 1:
    print("No root args provided. Exiting.")
    sys.exit(1)

root = str(Path(sys.argv[1]).resolve())
if root not in sys.path:
    sys.path.insert(0, root)

from src.services.path_manage import PathManage






FFMPEG = str(PathManage.FFMPEG_EXE_PATH)
TEST_INPUT = str(PathManage.TEST_H264_PATH)

# 编码器测试定义 — 按优先级排序
ENCODER_TESTS = [
    {
        "id": "Nvidia",
        "desc": "h264_nvenc",
        "args": ["-i", TEST_INPUT, "-t", "1", "-c:v", "h264_nvenc", "-f", "null", "-"]
    },
    {
        "id": "Intel",
        "desc": "h264_qsv",
        "args": ["-i", TEST_INPUT, "-t", "1", "-c:v", "h264_qsv", "-f", "null", "-"]
    },
]




def _run_ffmpeg(args: list[str]) -> bool:
    try:
        cmd = [FFMPEG, "-hide_banner", "-loglevel", "error"] + args
        result = subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        return result.returncode == 0
    except Exception as e:
        print(f"  Error: {e}")
        return False




def _test_list(test_defs: list[dict]) -> str | None:
    """按优先级测试列表，返回第一个成功的 id"""
    for test in test_defs:
        print(f"  Testing {test['desc']} ... ", end="")
        ok = _run_ffmpeg(test["args"])
        print("OK" if ok else "FAIL")
        if ok:
            return test["id"]
    return None




def main():
    if not os.path.exists(FFMPEG):
        print(f"FFmpeg not found: {FFMPEG}")
        sys.exit(1)

    if not os.path.exists(TEST_INPUT):
        print(f"Test video not found: {TEST_INPUT}")
        sys.exit(1)

    print("FFmpeg Hardware Acceleration Detection")
    print(f"  FFmpeg: {FFMPEG}")
    print(f"  Test input: {TEST_INPUT}")
    print()

    # 编码器检测
    print("Encoder detection (priority: Nvidia > Intel > CPU):")
    encoder_id = _test_list(ENCODER_TESTS)
    if encoder_id is None:
        encoder_id = "CPU"
    print(f"  => Best encoder: {encoder_id}")

    # 输出结果
    print()
    print(f"FFMPEG_HW_ENCODER_RESULT:{encoder_id}")


if __name__ == "__main__":
    main()
