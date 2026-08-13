from dataclasses import dataclass

from .detect_nvidia import NvidiaGpuInfo
from .op_result import OpResult, ok


@dataclass(slots=True, frozen=True)
class pytorch_cuda_config:
    compute_capability: tuple[int, int]
    win_driver_ver: tuple[int, int]
    torch_ver: str
    torch_cuda_ver: str
    torchvision_ver: str


@dataclass(slots=True, frozen=True)
class PytorchCudaGpuDetection:
    gpu_name: str
    compute_capability: tuple[int, int]
    driver_version: tuple[int, int]
    vram_mib: int
    is_available: bool
    reason: str | None = None
    config: pytorch_cuda_config | None = None


pytorch_cuda_config_list = [
    pytorch_cuda_config(
        compute_capability=(7, 5),
        win_driver_ver=(572, 61),
        torch_ver="2.10.0",
        torch_cuda_ver="cu128",
        torchvision_ver="0.25.0",
    ),
    pytorch_cuda_config(
        compute_capability=(5, 0),
        win_driver_ver=(452, 39),
        torch_ver="2.3.1",
        torch_cuda_ver="cu118",
        torchvision_ver="0.18.1",
    ),
]


def detect_pytorch_cuda_availability(
    T,
    gpus: list[NvidiaGpuInfo],
) -> OpResult[list[PytorchCudaGpuDetection]]:
    detections = []
    for gpu in gpus:
        config, reason = _check_gpu(
            T,
            gpu.compute_capability,
            gpu.driver_version,
        )
        detections.append(
            PytorchCudaGpuDetection(
                gpu_name=gpu.gpu_name,
                compute_capability=gpu.compute_capability,
                driver_version=gpu.driver_version,
                vram_mib=gpu.vram_mib,
                is_available=config is not None,
                reason=reason,
                config=config,
            )
        )
    return ok(detections)


def _check_gpu(
    T,
    compute_capability: tuple[int, int],
    driver_version: tuple[int, int],
) -> tuple[pytorch_cuda_config | None, str | None]:
    target_config = None
    for config in pytorch_cuda_config_list:
        if compute_capability >= config.compute_capability:
            target_config = config
            break

    if target_config is None:
        minimum = pytorch_cuda_config_list[-1].compute_capability
        return None, T.detect_pytorch_cuda.low_compute_cap.format(
            compute_cap=f"sm {compute_capability[0]}.{compute_capability[1]}",
            min_compute_cap=f"sm {minimum[0]}.{minimum[1]}",
        )

    if driver_version < target_config.win_driver_ver:
        return None, T.detect_pytorch_cuda.invalid_driver_version.format(
            driver_version=f"{driver_version[0]}.{driver_version[1]}",
            min_driver_version=(
                f"{target_config.win_driver_ver[0]}."
                f"{target_config.win_driver_ver[1]}"
            ),
        )

    return target_config, None
