from dataclasses import dataclass

from src.core.schemas.model_inference_config import get_model_backend_id, get_model_group
from src.services.model_inference_manage import ModelInferenceManage


@dataclass(frozen=True, slots=True)
class InferenceDeviceItem:
    device_id: str
    name: str
    half_supported: bool


@dataclass(frozen=True, slots=True)
class ModelInferenceView:
    status_text: str
    is_usable: bool
    show_convert: bool
    half: bool | None
    device_half: bool
    model_group: str | None
    detail: str | None = None


def parse_inference_device_results(recent_output: str, backend: str) -> list[InferenceDeviceItem]:
    prefix = "INFERENCE_DEVICE_RESULT:"
    results: list[InferenceDeviceItem] = []
    seen_device_ids: set[str] = set()

    for raw_line in recent_output.splitlines():
        line = raw_line.strip()
        if not line.startswith(prefix):
            continue

        payload = line[len(prefix):].strip()
        device_part, separator, half_part = payload.rpartition("|half=")
        if not separator or "|" not in device_part:
            continue

        device_id, name = device_part.split("|", 1)
        device_id = device_id.strip()
        name = name.strip()
        half_text = half_part.strip().lower()
        if not device_id or not name or half_text not in {"true", "false"}:
            continue
        if not ModelInferenceManage.is_inference_device_supported_by_backend(backend, device_id):
            continue

        normalized_id = ModelInferenceManage.normalize_inference_device_id(device_id)
        if normalized_id is None or normalized_id in seen_device_ids:
            continue

        seen_device_ids.add(normalized_id)
        results.append(InferenceDeviceItem(
            device_id=normalized_id,
            name=name,
            half_supported=half_text == "true",
        ))

    return results


def get_backend_id(backend: str) -> str | None:
    return get_model_backend_id(backend)


def get_backend_model_group(backend: str) -> str | None:
    return get_model_group(backend)


def inspect_model(backend: str, device_half: bool | None) -> ModelInferenceView | None:
    if device_half is None:
        return None

    result = ModelInferenceManage.inspect(backend, device_half=device_half)
    if not result.is_ok:
        return ModelInferenceView(
            status_text="error",
            is_usable=False,
            show_convert=True,
            half=None,
            device_half=device_half,
            model_group=get_model_group(backend),
            detail=result.error_msg,
        )

    value = result.value
    return ModelInferenceView(
        status_text=value.status,
        is_usable=value.is_usable,
        show_convert=not value.is_usable,
        half=value.half,
        device_half=device_half,
        model_group=value.model_group,
    )
