from pathlib import Path

from src.services import PathManage

import i18n


def build_launch_cmd(notify_path, audio_path=None) -> list[str]:

    exe = PathManage.BPM_MEASURER_EXE_PATH
    cmd: list[str] = [str(exe)]

    cmd.append(f"--language={i18n.get('locale') or 'zh_CN'}")

    if audio_path:
        cmd.append(f"--audio={Path(audio_path).resolve()}")

    cmd.append(f"--notify={Path(notify_path).resolve()}")
    
    return cmd
