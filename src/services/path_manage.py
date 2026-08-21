from pathlib import Path
from dataclasses import dataclass
import re
from src.core.schemas.op_result import OpResult, ok, err


@dataclass(frozen=True, slots=True)
class ModelPaths:
    detect: Path
    obb: Path
    cls_break: Path
    cls_ex: Path
    touch_hold: Path


@dataclass(frozen=True, slots=True)
class ResolvedModels:
    paths: ModelPaths
    half: bool


class PathManage:
    """
    所有的路径属性都是 pathlib.Path 对象，而不是字符串。
    """

    # 以下是静态路径，因为不会变，所以设置为常量

    # 初始化时必须存在的路径

    ROOT_DIR: Path = Path(__file__).resolve().parents[2] # 往上三级目录
    DATA_DIR: Path = ROOT_DIR / "data"
    TEMP_DIR: Path = DATA_DIR / "temp" # 如果为空自动创建
    RESOURCES_DIR: Path = ROOT_DIR / "src" / "resources"
    LOCALES_DIR: Path = RESOURCES_DIR / "locales"
    WORKERS_DIR: Path = ROOT_DIR / "src" / "services" / "workers"

    # 资源文件
    
    APP_ICON_PATH: Path = RESOURCES_DIR / "icon.ico"
    CLICK_TEMPLATE_PATH: Path = RESOURCES_DIR / "click_template.wav"
    # https://test-videos.co.uk/vids/bigbuckbunny/mp4/h264/1080/Big_Buck_Bunny_1080_10s_1MB.mp4
    TEST_H264_PATH: Path = RESOURCES_DIR / "test_h264.mp4"

    FFMPEG_EXE_PATH: Path = RESOURCES_DIR / "ffmpeg" / "bin" / "ffmpeg.exe"
    FFPROBE_EXE_PATH: Path = RESOURCES_DIR / "ffmpeg" / "bin" / "ffprobe.exe"

    MajdataView_EXE_PATH: Path = RESOURCES_DIR / "majdata" / "MajdataView.exe"
    MajdataEdit_EXE_PATH: Path = RESOURCES_DIR / "majdata" / "MajdataEdit.exe"

    BPM_MEASURER_EXE_PATH: Path = RESOURCES_DIR / "Bpm Measurer" / "Bpm Measurer.exe"

    MODELS_DIR: Path = DATA_DIR / "models"
    DETECT_PT_PATH: Path = MODELS_DIR / "detect.pt"
    OBB_PT_PATH: Path = MODELS_DIR / "obb.pt"
    CLS_BREAK_PT_PATH: Path = MODELS_DIR / "cls-break.pt"
    CLS_EX_PT_PATH: Path = MODELS_DIR / "cls-ex.pt"
    TOUCH_HOLD_PT_PATH: Path = MODELS_DIR / "detect-touch-hold.pt"
    # REID_PT_PATH: Path = MODELS_DIR / "re_id.pt"

    # worker 脚本

    AUTO_RECHART_WORKER_PATH: Path = WORKERS_DIR / "auto_rechart_worker.py"
    CHECK_DEVICE_WORKER_PATH: Path = WORKERS_DIR / "check_device" / "main.py"
    MODEL_CONVERT_WORKER_PATH: Path = WORKERS_DIR / "model_convert_worker.py"
    AUDIO_ALIGN_WORKER_PATH: Path = WORKERS_DIR / "audio_align_worker.py"
    CHECK_FFMPEG_HW_ACCEL_WORKER_PATH: Path = WORKERS_DIR / "check_ffmpeg_hw_accel_worker.py"

    # 初始化时可以不存在的路径

    SETTINGS_PATH: Path = DATA_DIR / "settings.json"

    MajdataEdit_CONTROL_TXT_PATH: Path = RESOURCES_DIR / "majdata" / "HachimiDX_MajdataEdit_Control.txt"
    TEMP_WAV_IMAGE_PATH: Path = TEMP_DIR / "wav_image.png"

    NCNN_PARAM_FILE_NAME = "model.ncnn.param"
    NCNN_BIN_FILE_NAME = "model.ncnn.bin"
    NCNN_METADATA_FILE_NAME = "metadata.yaml"
    NCNN_REQUIRED_FILE_NAMES = (
        NCNN_PARAM_FILE_NAME,
        NCNN_BIN_FILE_NAME,
        NCNN_METADATA_FILE_NAME,
    )

    TEMP_TRT_DETECT_ONNX_PATH: Path = MODELS_DIR / "detect.onnx"
    TEMP_TRT_OBB_ONNX_PATH: Path = MODELS_DIR / "obb.onnx"
    TEMP_TRT_CLS_BREAK_ONNX_PATH: Path = MODELS_DIR / "cls-break.onnx"
    TEMP_TRT_CLS_EX_ONNX_PATH: Path = MODELS_DIR / "cls-ex.onnx"
    TEMP_TRT_TOUCH_HOLD_ONNX_PATH: Path = MODELS_DIR / "detect-touch-hold.onnx"

    _MODEL_STEMS = {
        "detect": "detect",
        "obb": "obb",
        "cls_break": "cls-break",
        "cls_ex": "cls-ex",
        "touch_hold": "detect-touch-hold",
    }
    _MODEL_PRECISION_PATTERN = re.compile(r"^.+\.(fp16|fp32)\.[^.]+$")
    _NCNN_PRECISION_PATTERN = re.compile(r"^.+\.(fp16|fp32)\.ncnn_model$")


    @classmethod
    def get_source_model_paths(cls) -> ModelPaths:
        return ModelPaths(
            detect=cls.DETECT_PT_PATH,
            obb=cls.OBB_PT_PATH,
            cls_break=cls.CLS_BREAK_PT_PATH,
            cls_ex=cls.CLS_EX_PT_PATH,
            touch_hold=cls.TOUCH_HOLD_PT_PATH,
        )


    @classmethod
    def _get_precision_text(cls, half: bool) -> str:
        return "fp16" if half else "fp32"


    @classmethod
    def _get_artifact_paths(cls, half: bool) -> dict[str, Path]:
        precision = cls._get_precision_text(half)
        return {
            "onnx": {
                name: cls.MODELS_DIR / f"{stem}.{precision}.onnx"
                for name, stem in cls._MODEL_STEMS.items()
            },
            "trt": {
                name: cls.MODELS_DIR / f"{stem}.{precision}.engine"
                for name, stem in cls._MODEL_STEMS.items()
            },
            "ncnn": {
                name: cls.MODELS_DIR / f"{stem}.{precision}.ncnn_model"
                for name, stem in cls._MODEL_STEMS.items()
            },
        }


    @classmethod
    def get_model_paths(cls, backend: str, half: bool) -> OpResult[ModelPaths]:
        if type(half) is not bool:
            return err(f"Model precision must be a bool, got: {half!r}")
        backend = str(backend).strip()
        artifact_paths = cls._get_artifact_paths(half)
        if backend in {"ONNX CPU", "ONNX DML", "ONNX Cuda"}:
            return ok(ModelPaths(
                detect=artifact_paths["onnx"]["detect"],
                obb=artifact_paths["onnx"]["obb"],
                cls_break=artifact_paths["onnx"]["cls_break"],
                cls_ex=artifact_paths["onnx"]["cls_ex"],
                touch_hold=artifact_paths["onnx"]["touch_hold"],
            ))
        if backend == "TensorRT":
            return ok(ModelPaths(
                detect=artifact_paths["trt"]["detect"],
                obb=artifact_paths["trt"]["obb"],
                cls_break=artifact_paths["trt"]["cls_break"],
                cls_ex=artifact_paths["trt"]["cls_ex"],
                touch_hold=artifact_paths["trt"]["touch_hold"],
            ))
        if backend == "NCNN":
            return ok(ModelPaths(
                detect=artifact_paths["ncnn"]["detect"],
                obb=artifact_paths["ncnn"]["obb"],
                cls_break=artifact_paths["ncnn"]["cls_break"],
                cls_ex=artifact_paths["ncnn"]["cls_ex"],
                touch_hold=artifact_paths["ncnn"]["touch_hold"],
            ))
        return err(f"Unknown model backend: {backend}")


    @classmethod
    def parse_model_precision(cls, path: Path, ncnn: bool = False) -> OpResult[bool]:
        pattern = cls._NCNN_PRECISION_PATTERN if ncnn else cls._MODEL_PRECISION_PATTERN
        match = pattern.fullmatch(path.name)
        if match is None:
            return err(f"Model artifact name must contain .fp16. or .fp32.: {path}")
        return ok(match.group(1) == "fp16")


    @classmethod
    def read_model_precision(cls, paths: ModelPaths, backend: str) -> OpResult[bool]:
        is_ncnn = str(backend).strip() == "NCNN"
        actual_precisions: set[bool] = set()
        for path in (paths.detect, paths.obb, paths.cls_break, paths.cls_ex, paths.touch_hold):
            precision_result = cls.parse_model_precision(path, ncnn=is_ncnn)
            if not precision_result.is_ok:
                return err("Model artifact precision validation failed", inner=precision_result)
            actual_precisions.add(precision_result.value)

        if len(actual_precisions) != 1:
            return err("Model artifacts must all use the same precision")
        return ok(actual_precisions.pop())


    @classmethod
    def validate_model_paths(cls, paths: ModelPaths, backend: str, half: bool) -> OpResult[bool]:
        is_ncnn = str(backend).strip() == "NCNN"
        for path in (paths.detect, paths.obb, paths.cls_break, paths.cls_ex, paths.touch_hold):
            if is_ncnn:
                if not path.is_dir():
                    return err(f"Model artifact not found: {path}")
                for file_name in cls.NCNN_REQUIRED_FILE_NAMES:
                    required_path = path / file_name
                    if not required_path.is_file():
                        return err(f"Model artifact incomplete: {required_path}")
            elif not path.is_file():
                return err(f"Model artifact not found: {path}")

        precision_result = cls.read_model_precision(paths, backend)
        if not precision_result.is_ok:
            return err("Failed to read model artifact precision", inner=precision_result)
        if precision_result.value != half:
            return err(
                f"Model artifact precision mismatch: expected {'fp16' if half else 'fp32'}"
            )
        return ok(precision_result.value)


    @classmethod
    def resolve_model_paths(cls, backend: str, half: bool) -> OpResult[ResolvedModels]:
        paths_result = cls.get_model_paths(backend, half)
        if not paths_result.is_ok:
            return err(f"Failed to get model paths for backend: {backend}", inner=paths_result)

        validation_result = cls.validate_model_paths(paths_result.value, backend, half)
        if not validation_result.is_ok:
            return err(f"Model artifact validation failed for backend: {backend}", inner=validation_result)
        return ok(ResolvedModels(paths=paths_result.value, half=validation_result.value))



    @classmethod
    def init(cls) -> OpResult[None]:
        """初始化检查一些必须存在的路径"""
        
        # 检查必须存在的目录
        for dir_path in [cls.RESOURCES_DIR, cls.MODELS_DIR, cls.LOCALES_DIR, cls.WORKERS_DIR, cls.DATA_DIR]:
            if not dir_path.is_dir():
                error_msg = f"Critical Error: Required directory not found: {dir_path}"
                return err(error_msg)
        
        # 创建可自动创建的目录
        for dir_path in [cls.TEMP_DIR]:
            if not dir_path.is_dir():
                dir_path.mkdir(parents=True, exist_ok=True)
        
        # 检查资源文件是否存在
        for file_path in [cls.APP_ICON_PATH, cls.CLICK_TEMPLATE_PATH,
                          cls.TEST_H264_PATH,
                          cls.FFMPEG_EXE_PATH, cls.FFPROBE_EXE_PATH,
                          cls.MajdataView_EXE_PATH, cls.MajdataEdit_EXE_PATH,
                          cls.BPM_MEASURER_EXE_PATH,
                          # cls.REID_PT_PATH
                          ]:
            if not file_path.is_file():
                error_msg = f"Critical Error: Required file not found: {file_path}"
                return err(error_msg)

        model_result = cls.validate_source_model_paths(cls.get_source_model_paths())
        if not model_result.is_ok:
            return err("Critical Error: Required source model artifact not found", inner=model_result)
            
        # 检查 worker 是否存在
        for file_path in [cls.AUTO_RECHART_WORKER_PATH,
                          cls.CHECK_DEVICE_WORKER_PATH,
                          cls.MODEL_CONVERT_WORKER_PATH,
                          cls.CHECK_FFMPEG_HW_ACCEL_WORKER_PATH]:
            if not file_path.is_file():
                error_msg = f"Critical Error: Required worker script not found: {file_path}"
                return err(error_msg)

        return ok()

    @classmethod
    def validate_source_model_paths(cls, paths: ModelPaths) -> OpResult[None]:
        for path in (paths.detect, paths.obb, paths.cls_break, paths.cls_ex, paths.touch_hold):
            if not path.is_file():
                return err(f"Source model artifact not found: {path}")
        return ok()

    @classmethod
    def _module_to_path(cls, module) -> Path:
        return cls.ROOT_DIR / f"{module.replace('.', '/')}.py"
