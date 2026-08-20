from dataclasses import dataclass

from .detect_nvidia import NvidiaGpuInfo
from .op_result import OpResult, ok


@dataclass(slots=True, frozen=True)
class onnx_cuda_config:
    compute_capability: tuple[int, int]
    win_driver_ver: tuple[int, int]
    torch_ver: str
    torch_cuda_ver: str
    torchvision_ver: str
    onnxruntime_gpu_ver: str
    numpy_ver: str
    opencv_ver: str


@dataclass(slots=True, frozen=True)
class OnnxCudaGpuDetection:
    gpu_name: str
    compute_capability: tuple[int, int]
    driver_version: tuple[int, int]
    vram_mib: int
    is_available: bool
    reason: str | None = None
    config: onnx_cuda_config | None = None


onnx_cuda_config_list = [
    onnx_cuda_config(
        compute_capability=(7, 5),
        win_driver_ver=(580, 65),
        torch_ver="2.11.0",            # 首个正式支持 cu130 的版本
        torch_cuda_ver="cu130",
        torchvision_ver="0.26.0",
        onnxruntime_gpu_ver="1.28.0",
        numpy_ver="2.4.6",             # 最后支持 py 3.11 的版本
        opencv_ver="5.0.0.93",
    ),
    onnx_cuda_config(
        compute_capability=(5, 0),
        win_driver_ver=(520, 6),
        torch_ver="2.3.1",             # 最后 cudnn 8 的版本
        torch_cuda_ver="cu118",
        torchvision_ver="0.18.1",
        onnxruntime_gpu_ver="1.18.1",  # 最后默认 cuda 11 的版本
        numpy_ver="1.26.4",            # 最后 1.x 版本，旧版 onnxruntime-gpu 需要
        opencv_ver="4.11.0.86",        # 最后符合 numpy < 2.0 的 opencv
    ),
]


def detect_onnx_cuda_availability(
    T,
    gpus: list[NvidiaGpuInfo],
) -> OpResult[list[OnnxCudaGpuDetection]]:
    detections = []
    for gpu in gpus:
        config, reason = _check_gpu(
            T,
            gpu.compute_capability,
            gpu.driver_version,
        )
        detections.append(
            OnnxCudaGpuDetection(
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
) -> tuple[onnx_cuda_config | None, str | None]:
    compute_compatible = [
        config
        for config in onnx_cuda_config_list
        if compute_capability >= config.compute_capability
    ]
    if not compute_compatible:
        minimum = onnx_cuda_config_list[-1].compute_capability
        return None, T.detect_onnx_cuda.low_compute_cap.format(
            compute_cap=f"sm {compute_capability[0]}.{compute_capability[1]}",
            min_compute_cap=f"sm {minimum[0]}.{minimum[1]}",
        )

    for config in compute_compatible:
        if driver_version >= config.win_driver_ver:
            return config, None

    minimum_driver = compute_compatible[-1].win_driver_ver
    return None, T.detect_onnx_cuda.invalid_driver_version.format(
        driver_version=f"{driver_version[0]}.{driver_version[1]}",
        min_driver_version=f"{minimum_driver[0]}.{minimum_driver[1]}",
    )
