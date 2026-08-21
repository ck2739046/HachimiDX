from typing import Final


MODEL_BACKEND_OPTIONS: Final[tuple[str, ...]] = (
    "ONNX CPU",
    "NCNN",
    "ONNX DML",
    "ONNX Cuda",
    "TensorRT",
)
_INFERENCE_DEVICE_SCHEMES = {
    "cpu": False,
    "cuda": True,
    "dml": True,
    "vulkan": True,
}
_MODEL_BACKEND_RULES = {
    "ONNX CPU": {
        "backend_id": "onnx_cpu",
        "schemes": frozenset({"cpu"}),
        "default_device": "cpu",
        "model_group": "onnx",
    },
    "NCNN": {
        "backend_id": "ncnn",
        "schemes": frozenset({"vulkan"}),
        "default_device": "vulkan:0",
        "model_group": "ncnn",
    },
    "ONNX DML": {
        "backend_id": "onnx_dml",
        "schemes": frozenset({"dml"}),
        "default_device": "dml:0",
        "model_group": "onnx",
    },
    "ONNX Cuda": {
        "backend_id": "onnx_cuda",
        "schemes": frozenset({"cuda"}),
        "default_device": "cuda:0",
        "model_group": "onnx",
    },
    "TensorRT": {
        "backend_id": "tensorrt",
        "schemes": frozenset({"cuda"}),
        "default_device": "cuda:0",
        "model_group": "trt",
    },
}



def get_model_backend_rule(backend) -> dict | None:
    return _MODEL_BACKEND_RULES.get(str(backend).strip())



def get_model_backend_id(backend) -> str | None:
    rule = get_model_backend_rule(backend)
    return rule["backend_id"] if rule is not None else None



def get_model_group(backend) -> str | None:
    rule = get_model_backend_rule(backend)
    return rule["model_group"] if rule is not None else None



def parse_inference_device(value) -> tuple[str, int | None] | None:
    device_id = str(value or "").strip()
    requires_index = _INFERENCE_DEVICE_SCHEMES.get(device_id)
    if requires_index is False:
        return device_id, None

    scheme, separator, index_text = device_id.partition(":")
    if separator != ":" or _INFERENCE_DEVICE_SCHEMES.get(scheme) is not True:
        return None
    if not index_text.isdigit():
        return None
    return scheme, int(index_text)



def normalize_inference_device_id(value) -> str | None:
    parsed = parse_inference_device(value)
    if parsed is None:
        return None
    scheme, index = parsed
    return scheme if index is None else f"{scheme}:{index}"



def is_inference_device_supported_by_backend(backend, value) -> bool:
    parsed = parse_inference_device(value)
    rule = get_model_backend_rule(backend)
    return parsed is not None and rule is not None and parsed[0] in rule["schemes"]



def get_inference_device_by_backend(backend) -> str:
    rule = get_model_backend_rule(backend)
    return rule["default_device"] if rule is not None else "cpu"



def normalize_inference_device_for_backend(backend, value) -> str:
    if not is_inference_device_supported_by_backend(backend, value):
        return get_inference_device_by_backend(backend)
    return normalize_inference_device_id(value)



def get_runtime_inference_device(backend, value) -> str:
    normalized = normalize_inference_device_for_backend(backend, value)
    return "cpu" if str(backend).strip() == "ONNX DML" else normalized



def get_directml_device_index(value) -> int | None:
    parsed = parse_inference_device(value)
    if parsed is None or parsed[0] != "dml":
        return None
    return parsed[1]
