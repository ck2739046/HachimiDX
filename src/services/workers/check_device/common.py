from dataclasses import dataclass
from pathlib import Path
import subprocess
import sys

import numpy as np

from src.services.path_manage import PathManage


TEST_FP16_ONNX_PATH = PathManage.CHECK_DEVICE_TEST_FP16_ONNX_PATH
TEST_FP32_ONNX_PATH = PathManage.CHECK_DEVICE_TEST_FP32_ONNX_PATH


@dataclass(frozen=True, slots=True)
class DeviceResult:
    device_id: str
    name: str
    half: bool
    error: str | None = None


def _run_onnx_model(ort, model_path: Path, providers, require_provider: str) -> None:
    ort.set_default_logger_severity(4)
    options = ort.SessionOptions()
    options.log_severity_level = 4
    options.enable_mem_pattern = False
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    options.add_session_config_entry("session.intra_op.allow_spinning", "0")
    options.add_session_config_entry("session.inter_op.allow_spinning", "0")
    session = ort.InferenceSession(
        str(model_path),
        sess_options=options,
        providers=providers,
    )
    if require_provider not in session.get_providers():
        raise RuntimeError(f"{require_provider} was not activated")

    model_input = session.get_inputs()[0]
    dtype = np.float16 if model_input.type == "tensor(float16)" else np.float32
    input_shape = (1, 3, 224, 224)
    outputs = session.run(None, {model_input.name: np.zeros(input_shape, dtype=dtype)})
    if not outputs:
        raise RuntimeError("model returned no outputs")
    if any(np.issubdtype(output.dtype, np.floating) and not np.isfinite(output).all() for output in outputs):
        raise RuntimeError("model returned non-finite outputs")


def test_onnx_models(
    ort,
    providers,
    require_provider: str,
    fp16_supported: bool,
    fp32_supported: bool,
) -> tuple[bool | None, str | None]:
    if fp16_supported:
        try:
            if not TEST_FP16_ONNX_PATH.is_file():
                raise FileNotFoundError(TEST_FP16_ONNX_PATH)
            _run_onnx_model(ort, TEST_FP16_ONNX_PATH, providers, require_provider)
            return True, None
        except Exception:
            pass

    if not fp32_supported:
        return None, "FP32 is not supported"

    try:
        if not TEST_FP32_ONNX_PATH.is_file():
            raise FileNotFoundError(TEST_FP32_ONNX_PATH)
        _run_onnx_model(ort, TEST_FP32_ONNX_PATH, providers, require_provider)
        return False, None
    except Exception as e:
        return None, f"FP32 model test failed: {e!r}"


def print_device_results(title: str, devices: list[DeviceResult]) -> None:
    print(title)
    for device in devices:
        if device.error is not None:
            print(f"  - {device.device_id}: {device.name}, failed: {device.error}")
        else:
            print(f"  - {device.device_id}: {device.name}, half={device.half}")


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

