import sys
from dataclasses import dataclass, fields
from typing import Any, Callable

from .detect_dml import detect_dml_availability
from .detect_ncnn import detect_ncnn_availability
from .detect_nvidia import get_nvidia_gpu_info
from .detect_pytorch_cuda import (
    PytorchCudaGpuDetection,
    detect_pytorch_cuda_availability,
    pytorch_cuda_config as PytorchCudaConfig,
)
from .detect_trt import (
    TensorRTGpuDetection,
    detect_trt_availability,
    tensorrt_config as TensorRTConfig,
)
from .op_result import OpResult, err, ok
from .console_input import ask


@dataclass(slots=True, frozen=True)
class BackendChoice:
    backend: str
    tensorrt_config: TensorRTConfig | None = None
    pytorch_cuda_config: PytorchCudaConfig | None = None


def choose_backend(T) -> OpResult[BackendChoice]:
    print("\n-----\n")
    print(T.choose_backend.detect_start)

    nvidia_result = get_nvidia_gpu_info()
    if nvidia_result.is_ok and nvidia_result.value is not None:
        gpus = nvidia_result.value
        trt_result = _safe_detect(
            T,
            "TensorRT",
            lambda current_text: detect_trt_availability(current_text, gpus),
        )
        pytorch_cuda_result = _safe_detect(
            T,
            "PyTorch CUDA",
            lambda current_text: detect_pytorch_cuda_availability(current_text, gpus),
        )
    else:
        trt_result = err("Failed to get NVIDIA GPU info.", inner=nvidia_result)
        pytorch_cuda_result = err("Failed to get NVIDIA GPU info.", inner=nvidia_result)
    dml_result = _safe_detect(
        T,
        "DirectML",
        detect_dml_availability,
    )
    ncnn_result = _safe_detect(
        T,
        "NCNN",
        detect_ncnn_availability,
    )

    availability = {
        "trt": _has_available_gpu(trt_result),
        "pytorch_cuda": _has_available_gpu(pytorch_cuda_result),
        "dml": _has_available_gpu(dml_result),
        "ncnn": _has_available_gpu(ncnn_result),
        "cpu": True,
    }
    reasons = {
        "trt": _get_backend_error(T, trt_result),
        "pytorch_cuda": _get_backend_error(T, pytorch_cuda_result),
        "dml": _get_backend_error(T, dml_result),
        "ncnn": _get_backend_error(T, ncnn_result),
    }

    _print_summary(
        T,
        trt_result,
        pytorch_cuda_result,
        dml_result,
        ncnn_result,
        availability,
        reasons,
    )

    backend_result = _ask_backend(T, availability, reasons)
    if not backend_result.is_ok:
        return backend_result

    backend = backend_result.value
    if backend is None:
        return err(T.choose_backend.backend_selection_failed)
    if backend == "pytorch_cuda":
        config_result = _choose_pytorch_cuda_config(T, pytorch_cuda_result)
        if not config_result.is_ok:
            return err(T.choose_backend.pytorch_cuda_selection_failed, inner=config_result)
        return ok(
            BackendChoice(
                backend="pytorch_cuda",
                pytorch_cuda_config=config_result.value,
            )
        )
    if backend != "trt":
        return ok(BackendChoice(backend=backend))

    # 特例: TensorRT 可能需要进一步选择 GPU 配置
    config_result = _choose_tensorrt_config(T, trt_result)
    if not config_result.is_ok:
        return err(T.choose_backend.trt_selection_failed, inner=config_result)

    return ok(BackendChoice(backend="trt",
                            tensorrt_config=config_result.value))




def _safe_detect(
    T,
    backend_name: str,
    detector: Callable[[Any], OpResult[Any]],
) -> OpResult[Any]:
    try:
        return detector(T)
    except Exception as e:
        return err(
            T.choose_backend.detection_exception.format(
                backend=backend_name,
                error=e,
            ),
            error_raw=e,
        )


def _has_available_gpu(result: OpResult[Any]) -> bool:
    if not result.is_ok or result.value is None:
        return False
    return any(item.is_available for item in result.value)


def _get_backend_error(T, result: OpResult[Any]) -> str | None:
    if result.is_ok:
        if result.value:
            unavailable_reasons = [
                item.reason
                for item in result.value
                if not item.is_available and item.reason
            ]
            if unavailable_reasons:
                return T.choose_backend.no_available_gpu
            return None
        return T.choose_backend.no_gpu_detected
    return result.error_msg or T.choose_backend.unknown_detection_error


def _print_summary(
    T,
    trt_result: OpResult[Any],
    pytorch_cuda_result: OpResult[Any],
    dml_result: OpResult[Any],
    ncnn_result: OpResult[Any],
    availability: dict[str, bool],
    reasons: dict[str, str | None],
) -> None:
    print("\n-----\n")
    print(T.choose_backend.summary_title)
    print()

    _print_backend_status(
        T,
        T.choose_backend.trt_backend,
        availability["trt"],
        reasons["trt"] if not availability["trt"] else None,
    )
    _print_gpu_results(T, trt_result, "trt")

    _print_backend_status(
        T,
        T.choose_backend.pytorch_cuda_backend,
        availability["pytorch_cuda"],
        reasons["pytorch_cuda"] if not availability["pytorch_cuda"] else None,
    )
    _print_gpu_results(T, pytorch_cuda_result, "pytorch_cuda")

    _print_backend_status(
        T,
        T.choose_backend.dml_backend,
        availability["dml"],
        reasons["dml"] if not availability["dml"] else None,
    )
    _print_gpu_results(T, dml_result, "dml")

    _print_backend_status(
        T,
        T.choose_backend.ncnn_backend,
        availability["ncnn"],
        reasons["ncnn"] if not availability["ncnn"] else None,
    )
    _print_gpu_results(T, ncnn_result, "ncnn")

    _print_backend_status(
        T,
        T.choose_backend.cpu_backend,
        availability["cpu"],
        None,
    )


def _print_backend_status(T, backend_name: str, is_available: bool, reason: str | None) -> None:
    status = T.choose_backend.available if is_available else T.choose_backend.unavailable
    print(T.choose_backend.backend_status.format(backend=backend_name, status=status))
    if reason:
        print(T.choose_backend.backend_reason.format(reason=reason))


def _print_gpu_results(T, result: OpResult[Any], backend: str) -> None:
    if not result.is_ok or result.value is None:
        return

    for index, gpu in enumerate(result.value):
        if backend in {"trt", "pytorch_cuda"}:
            details = T.choose_backend.nvidia_gpu_details.format(
                vram=_format_vram(gpu.vram_mib),
                compute_cap=_format_compute_cap(gpu.compute_capability),
                driver=_format_driver(gpu.driver_version),
                config=_format_config(backend, gpu.config),
            )
        else:
            details = ""

        status = T.choose_backend.available
        if not gpu.is_available:
            status = T.choose_backend.gpu_unavailable.format(reason=gpu.reason)
        print(
            T.choose_backend.gpu_status.format(
                index=index,
                gpu_name=gpu.gpu_name,
                details=details,
                status=status,
            )
        )


def _format_vram(vram_mib: int) -> str:
    text = f"{vram_mib / 1024:.1f}"
    return text[:-2] if text.endswith(".0") else text


def _format_compute_cap(compute_capability: tuple[int, int]) -> str:
    return f"{compute_capability[0]}.{compute_capability[1]}"


def _format_driver(driver_version: tuple[int, int]) -> str:
    return f"{driver_version[0]}.{driver_version[1]}"


def _format_config(
    backend: str,
    config: TensorRTConfig | PytorchCudaConfig | None,
) -> str:
    if config is None:
        return "-"
    if backend == "trt":
        return f"TensorRT {config.tensorRT_ver}"
    return f"PyTorch {config.torch_ver} ({config.torch_cuda_ver})"


def _ask_backend(
    T,
    availability: dict[str, bool],
    reasons: dict[str, str | None],
) -> OpResult[str]:
    backend_order = ["trt", "pytorch_cuda", "dml", "ncnn", "cpu"]
    labels = {
        "trt": T.choose_backend.trt_backend,
        "pytorch_cuda": T.choose_backend.pytorch_cuda_backend,
        "dml": T.choose_backend.dml_backend,
        "ncnn": T.choose_backend.ncnn_backend,
        "cpu": T.choose_backend.cpu_backend,
    }
    default_backend = next(backend for backend in backend_order if availability[backend])

    print("\n-----\n")
    print(T.choose_backend.backend_menu_title)
    print()
    for index, backend in enumerate(backend_order, start=1):
        status = T.choose_backend.available
        if not availability[backend]:
            status = T.choose_backend.unavailable
            if reasons.get(backend):
                status = T.choose_backend.unavailable_with_reason.format(
                    reason=reasons[backend]
                )
        print(
            T.choose_backend.backend_option.format(
                index=index,
                backend=labels[backend],
                status=status,
            )
        )
    print(T.choose_backend.exit_option)
    print()
    print(T.choose_backend.backend_recommendation.format(backend=labels[default_backend]))
    print()

    while True:
        content = ask(T.choose_backend.backend_prompt)
        if content == "":
            return ok(default_backend)
        if content == "6":
            sys.exit(0)
        try:
            selected_index = int(content)
        except ValueError:
            print(T.choose_backend.invalid_backend_choice)
            continue
        if selected_index < 1 or selected_index > len(backend_order):
            print(T.choose_backend.invalid_backend_choice)
            continue

        selected_backend = backend_order[selected_index - 1]
        if not availability[selected_backend]:
            print(T.choose_backend.backend_not_available)
            continue
        return ok(selected_backend)


def _choose_tensorrt_config(
    T,
    result: OpResult[Any],
) -> OpResult[TensorRTConfig]:
    if not result.is_ok or result.value is None:
        return err(T.choose_backend.trt_not_available)

    candidates: list[TensorRTGpuDetection] = [
        gpu for gpu in result.value
        if gpu.is_available and gpu.config is not None
    ]
    if not candidates:
        return err(T.choose_backend.trt_not_available)

    config_groups: dict[tuple[Any, ...], list[TensorRTGpuDetection]] = {}
    for gpu in candidates:
        key = tuple(getattr(gpu.config, field.name) for field in fields(TensorRTConfig))
        config_groups.setdefault(key, []).append(gpu)

    if len(config_groups) == 1:
        return ok(candidates[0].config)

    print("\n-----\n")
    print(T.choose_backend.trt_gpu_menu_title)
    print()
    for index, gpu in enumerate(candidates):
        print(
            T.choose_backend.trt_gpu_option.format(
                index=index,
                gpu_name=gpu.gpu_name,
                vram=_format_vram(gpu.vram_mib),
                compute_cap=_format_compute_cap(gpu.compute_capability),
                driver=_format_driver(gpu.driver_version),
                config=_format_config("trt", gpu.config),
            )
        )
    print(T.choose_backend.exit_option)
    print()

    while True:
        content = ask(T.choose_backend.trt_gpu_prompt)
        if content == "6":
            sys.exit(0)
        try:
            selected_index = int(content)
        except ValueError:
            print(T.choose_backend.invalid_gpu_choice)
            continue
        if selected_index < 0 or selected_index >= len(candidates):
            print(T.choose_backend.invalid_gpu_choice)
            continue
        return ok(candidates[selected_index].config)


def _choose_pytorch_cuda_config(
    T,
    result: OpResult[Any],
) -> OpResult[PytorchCudaConfig]:
    if not result.is_ok or result.value is None:
        return err(T.choose_backend.pytorch_cuda_not_available)

    candidates: list[PytorchCudaGpuDetection] = [
        gpu for gpu in result.value
        if gpu.is_available and gpu.config is not None
    ]
    if not candidates:
        return err(T.choose_backend.pytorch_cuda_not_available)

    config_groups: dict[tuple[Any, ...], list[PytorchCudaGpuDetection]] = {}
    for gpu in candidates:
        key = tuple(
            getattr(gpu.config, field.name)
            for field in fields(PytorchCudaConfig)
        )
        config_groups.setdefault(key, []).append(gpu)

    if len(config_groups) == 1:
        return ok(candidates[0].config)

    print("\n-----\n")
    print(T.choose_backend.pytorch_cuda_gpu_menu_title)
    print()
    for index, gpu in enumerate(candidates):
        print(
            T.choose_backend.pytorch_cuda_gpu_option.format(
                index=index,
                gpu_name=gpu.gpu_name,
                vram=_format_vram(gpu.vram_mib),
                compute_cap=_format_compute_cap(gpu.compute_capability),
                driver=_format_driver(gpu.driver_version),
                config=_format_config("pytorch_cuda", gpu.config),
            )
        )
    print(T.choose_backend.exit_option)
    print()

    while True:
        content = ask(T.choose_backend.pytorch_cuda_gpu_prompt)
        if content == "6":
            sys.exit(0)
        try:
            selected_index = int(content)
        except ValueError:
            print(T.choose_backend.invalid_gpu_choice)
            continue
        if selected_index < 0 or selected_index >= len(candidates):
            print(T.choose_backend.invalid_gpu_choice)
            continue
        return ok(candidates[selected_index].config)
