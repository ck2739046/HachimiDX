from dataclasses import dataclass
import subprocess
import sys


@dataclass(frozen=True, slots=True)
class DeviceResult:
    device_id: str
    name: str
    half: bool


def check_torch_installed() -> tuple[bool, object | None]:
    try:
        import torch
        print(f"PyTorch installed, version {torch.__version__}")
        return True, torch
    except Exception as e:
        print(f"Failed to load PyTorch: {e!r}")
        return False, None




def get_windows_cpu_name() -> str:
    if sys.platform != "win32":
        return ""

    try:
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "Get-CimInstance Win32_Processor | Select-Object -First 1 -ExpandProperty Name",
            ],
            capture_output=True,
            check=False,
            encoding="utf-8",
            errors="replace",
            timeout=5,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""

