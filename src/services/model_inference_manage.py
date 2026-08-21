from dataclasses import dataclass

from src.core.schemas.op_result import OpResult, ok, err
from src.core.schemas.model_inference_config import (
    get_directml_device_index,
    get_model_backend_id,
    get_model_backend_rule,
    get_model_group,
    get_runtime_inference_device,
    is_inference_device_supported_by_backend,
    normalize_inference_device_for_backend,
    normalize_inference_device_id,
    parse_inference_device,
    get_inference_device_by_backend,
)
from .path_manage import ModelPaths, PathManage


@dataclass(frozen=True, slots=True)
class ModelInferenceCheckResult:
    paths: ModelPaths | None
    model_group: str
    half: bool | None
    device_half: bool
    status: str
    artifacts_available: bool

    @property
    def is_usable(self) -> bool:
        return self.artifacts_available and self.status == "compatible"


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
        device_half: bool | None = None,
    ) -> OpResult[ModelInferenceCheckResult]:
        if device_half is None:
            from .settings_manage import SettingsManage

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

        paths_result = PathManage.resolve_model_paths(backend, device_half)
        if not paths_result.is_ok:
            return ok(ModelInferenceCheckResult(
                paths=None,
                model_group=model_group,
                half=None,
                device_half=device_half,
                status="not_converted",
                artifacts_available=False,
            ))

        return ok(ModelInferenceCheckResult(
            paths=paths_result.value.paths,
            model_group=model_group,
            half=paths_result.value.half,
            device_half=device_half,
            status="compatible",
            artifacts_available=True,
        ))
