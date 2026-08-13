from dataclasses import dataclass
import subprocess

from .op_result import OpResult, err, ok


@dataclass(slots=True, frozen=True)
class NvidiaGpuInfo:
    gpu_name: str
    compute_capability: tuple[int, int]
    driver_version: tuple[int, int]
    vram_mib: int


def get_nvidia_gpu_info() -> OpResult[list[NvidiaGpuInfo]]:
    try:
        cmd = [
            "nvidia-smi",
            "--query-gpu=name,compute_cap,driver_version,memory.total",
            "--format=csv,noheader,nounits",
        ]
        try:
            result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        except Exception as e:
            stdout = getattr(e, "stdout", None)
            stderr = getattr(e, "stderr", None)
            if stdout and stderr:
                output = f"stdout: {stdout}\nstderr: {stderr}"
            elif stdout:
                output = stdout
            elif stderr:
                output = stderr
            else:
                output = "no output"
            return err(f"Failed to run nvidia-smi command: {output}", error_raw=e)

        lines = [line for line in result.stdout.splitlines() if line.strip()]
        if not lines:
            return err("No output from nvidia-smi command.")

        gpus = []
        for line in lines:
            gpu_name, compute_cap_text, driver_text, vram_text = (
                part.strip() for part in line.split(",", 3)
            )
            compute_cap_parts = compute_cap_text.split(".")
            driver_parts = driver_text.split(".")
            gpus.append(
                NvidiaGpuInfo(
                    gpu_name=gpu_name,
                    compute_capability=(
                        int(compute_cap_parts[0]),
                        int(compute_cap_parts[1]),
                    ),
                    driver_version=(
                        int(driver_parts[0]),
                        int(driver_parts[1]),
                    ),
                    vram_mib=int(vram_text),
                )
            )

        return ok(gpus)
    except Exception as e:
        return err("Failed to get NVIDIA GPU info.", error_raw=e)
