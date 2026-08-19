from dataclasses import dataclass
from typing import Literal

from src.core.schemas.op_result import OpResult, ok, err
from src.core.schemas.model_inference_config import (
    MODEL_HALF_KEYS,
    get_directml_device_index,
    get_model_backend_id,
    get_model_backend_rule,
    get_model_group,
    get_model_half_for_backend,
    get_runtime_inference_device,
    is_inference_device_supported_by_backend,
    normalize_inference_device_for_backend,
    normalize_inference_device_id,
    parse_inference_device,
    get_inference_device_by_backend,
)
from .path_manage import ModelPaths, PathManage


ModelHalfStatus = Literal[
    "not_converted",
    "compatible",
    "upgrade_available",
    "incompatible",
]


@dataclass(frozen=True, slots=True)
class ModelHalfEvaluation:
    status: ModelHalfStatus

    @property
    def is_usable(self) -> bool:
        return self.status in {"compatible", "upgrade_available"}

    @property
    def can_upgrade_to_half(self) -> bool:
        return self.status == "upgrade_available"



def evaluate_model_half(model_half: bool | None, device_half: bool) -> ModelHalfEvaluation:
    if model_half is None:
        return ModelHalfEvaluation("not_converted")
    if model_half and not device_half:
        return ModelHalfEvaluation("incompatible")
    if not model_half and device_half:
        return ModelHalfEvaluation("upgrade_available")
    return ModelHalfEvaluation("compatible")


@dataclass(frozen=True, slots=True)
class ModelInferenceCheckResult:
    paths: ModelPaths | None
    model_group: str
    model_half: bool | None
    device_half: bool
    half_evaluation: ModelHalfEvaluation
    artifacts_available: bool

    @property
    def is_usable(self) -> bool:
        return self.artifacts_available and self.half_evaluation.is_usable


class ModelInferenceManage:

    @classmethod
    def get_model_backend_rule(cls, backend) -> dict | None:
        return get_model_backend_rule(backend)

    @classmethod
    def get_model_backend_id(cls, backend) -> str | None:
        return get_model_backend_id(backend)

    @classmethod
    def get_model_group(cls, backend) -> str | None:
        return get_model_group(backend)

    @classmethod
    def get_model_half_for_backend(cls, model_half, backend) -> bool | None:
        return get_model_half_for_backend(model_half, backend)

    @classmethod
    def is_model_half_compatible(cls, model_half: bool | None, device_half: bool) -> bool:
        return model_half is not None and not (model_half and not device_half)

    @classmethod
    def can_upgrade_model_to_half(cls, model_half: bool | None, device_half: bool) -> bool:
        return model_half is False and device_half is True

    @classmethod
    def set_model_half_for_backend(cls, backend: str, value: bool | None) -> OpResult[None]:
        model_group = get_model_group(backend)
        if model_group is None:
            return err(f"Unknown model backend: {backend}")
        if value is not None and type(value) is not bool:
            return err("model_half value must be null, true, or false")

        from .settings_manage import SettingsManage

        result = SettingsManage.get("model_half")
        if not result.is_ok:
            return err("Failed to get model_half from settings", inner=result)
        current = result.value
        if hasattr(current, "model_dump"):
            current = current.model_dump(mode="python")
        if not isinstance(current, dict) or set(current) != MODEL_HALF_KEYS:
            return err("model_half must contain exactly onnx, ncnn, and trt")
        current[model_group] = value
        return SettingsManage.set("model_half", current)

    @classmethod
    def parse_inference_device(cls, value) -> tuple[str, int | None] | None:
        return parse_inference_device(value)

    @classmethod
    def normalize_inference_device_id(cls, value) -> str | None:
        return normalize_inference_device_id(value)

    @classmethod
    def is_inference_device_supported_by_backend(cls, backend, value) -> bool:
        return is_inference_device_supported_by_backend(backend, value)

    @classmethod
    def get_inference_device_by_backend(cls, backend) -> str:
        return get_inference_device_by_backend(backend)

    @classmethod
    def normalize_inference_device_for_backend(cls, backend, value) -> str:
        return normalize_inference_device_for_backend(backend, value)

    @classmethod
    def get_runtime_inference_device(cls, backend, value) -> str:
        return get_runtime_inference_device(backend, value)

    @classmethod
    def get_directml_device_index(cls, value) -> int | None:
        return get_directml_device_index(value)

    @classmethod
    def inspect(
        cls,
        backend: str,
        model_half: dict[str, bool | None] | None = None,
        device_half: bool | None = None,
    ) -> OpResult[ModelInferenceCheckResult]:
        if model_half is None or device_half is None:
            from .settings_manage import SettingsManage

            if model_half is None:
                model_half_result = SettingsManage.get("model_half")
                if not model_half_result.is_ok:
                    return err("Failed to get model_half from settings", inner=model_half_result)
                model_half = model_half_result.value
            if device_half is None:
                device_half_result = SettingsManage.get("inference_device_half")
                if not device_half_result.is_ok:
                    return err(
                        "Failed to get inference_device_half from settings",
                        inner=device_half_result,
                    )
                device_half = device_half_result.value

        model_group = cls.get_model_group(backend)
        if model_group is None:
            return err(f"Unknown model backend: {backend}")
        if type(device_half) is not bool:
            return err("inference_device_half must be a bool")
        if hasattr(model_half, "model_dump"):
            model_half = model_half.model_dump(mode="python")
        if not isinstance(model_half, dict):
            return err("model_half must be an object")
        if set(model_half) != MODEL_HALF_KEYS:
            return err(f"model_half keys must be exactly {sorted(MODEL_HALF_KEYS)}")
        if any(value is not None and type(value) is not bool for value in model_half.values()):
            return err("model_half values must be null, true, or false")

        recorded_half = model_half[model_group]
        paths_result = PathManage.resolve_model_paths(backend)
        if not paths_result.is_ok:
            clear_result = cls.set_model_half_for_backend(backend, None)
            if not clear_result.is_ok:
                return err("Failed to clear model_half after missing artifacts", inner=clear_result)
            return ok(ModelInferenceCheckResult(
                paths=None,
                model_group=model_group,
                model_half=None,
                device_half=device_half,
                half_evaluation=ModelHalfEvaluation("not_converted"),
                artifacts_available=False,
            ))

        evaluation = evaluate_model_half(recorded_half, device_half)
        return ok(ModelInferenceCheckResult(
            paths=paths_result.value,
            model_group=model_group,
            model_half=recorded_half,
            device_half=device_half,
            half_evaluation=evaluation,
            artifacts_available=True,
        ))
