from pathlib import Path
from dataclasses import dataclass
from src.core.schemas.op_result import OpResult, ok, err


@dataclass(frozen=True, slots=True)
class ModelPaths:
    detect: Path
    obb: Path
    cls_break: Path
    cls_ex: Path
    touch_hold: Path


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
    REID_PT_PATH: Path = MODELS_DIR / "re_id.pt"

    # worker 脚本

    AUTO_RECHART_WORKER_PATH: Path = WORKERS_DIR / "auto_rechart_worker.py"
    CHECK_DEVICE_WORKER_PATH: Path = WORKERS_DIR / "check_device_worker.py"
    MODEL_CONVERT_WORKER_PATH: Path = WORKERS_DIR / "model_convert_worker.py"
    AUDIO_ALIGN_WORKER_PATH: Path = WORKERS_DIR / "audio_align_worker.py"
    CHECK_FFMPEG_HW_ACCEL_WORKER_PATH: Path = WORKERS_DIR / "check_ffmpeg_hw_accel_worker.py"

    # 初始化时可以不存在的路径

    SETTINGS_PATH: Path = DATA_DIR / "settings.json"

    MajdataEdit_CONTROL_TXT_PATH: Path = RESOURCES_DIR / "majdata" / "HachimiDX_MajdataEdit_Control.txt"
    TEMP_WAV_IMAGE_PATH: Path = TEMP_DIR / "wav_image.png"

    DETECT_ENGINE_PATH: Path = MODELS_DIR / "detect.engine"
    OBB_ENGINE_PATH: Path = MODELS_DIR / "obb.engine"
    CLS_BREAK_ENGINE_PATH: Path = MODELS_DIR / "cls-break.engine"
    CLS_EX_ENGINE_PATH: Path = MODELS_DIR / "cls-ex.engine"
    TOUCH_HOLD_ENGINE_PATH: Path = MODELS_DIR / "detect-touch-hold.engine"

    DETECT_NCNN_PATH: Path = MODELS_DIR / "detect_ncnn_model"
    OBB_NCNN_PATH: Path = MODELS_DIR / "obb_ncnn_model"
    CLS_BREAK_NCNN_PATH: Path = MODELS_DIR / "cls-break_ncnn_model"
    CLS_EX_NCNN_PATH: Path = MODELS_DIR / "cls-ex_ncnn_model"
    TOUCH_HOLD_NCNN_PATH: Path = MODELS_DIR / "detect-touch-hold_ncnn_model"

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


    @classmethod
    def get_model_paths(cls, backend: str) -> OpResult[ModelPaths]:
        backend = str(backend).strip()
        if backend == "PyTorch":
            return ok(ModelPaths(
                detect=cls.DETECT_PT_PATH,
                obb=cls.OBB_PT_PATH,
                cls_break=cls.CLS_BREAK_PT_PATH,
                cls_ex=cls.CLS_EX_PT_PATH,
                touch_hold=cls.TOUCH_HOLD_PT_PATH,
            ))
        if backend == "TensorRT":
            return ok(ModelPaths(
                detect=cls.DETECT_ENGINE_PATH,
                obb=cls.OBB_ENGINE_PATH,
                cls_break=cls.CLS_BREAK_ENGINE_PATH,
                cls_ex=cls.CLS_EX_ENGINE_PATH,
                touch_hold=cls.TOUCH_HOLD_ENGINE_PATH,
            ))
        if backend == "NCNN":
            return ok(ModelPaths(
                detect=cls.DETECT_NCNN_PATH,
                obb=cls.OBB_NCNN_PATH,
                cls_break=cls.CLS_BREAK_NCNN_PATH,
                cls_ex=cls.CLS_EX_NCNN_PATH,
                touch_hold=cls.TOUCH_HOLD_NCNN_PATH,
            ))
        return err(f"Unknown model backend: {backend}")


    @classmethod
    def validate_model_paths(cls, paths: ModelPaths) -> OpResult[None]:
        for path in (
            paths.detect,
            paths.obb,
            paths.cls_break,
            paths.cls_ex,
            paths.touch_hold,
        ):
            if path.suffix:
                if not path.is_file():
                    return err(f"Model artifact not found: {path}")
                continue

            if not path.is_dir():
                return err(f"Model artifact not found: {path}")
            for file_name in cls.NCNN_REQUIRED_FILE_NAMES:
                required_path = path / file_name
                if not required_path.is_file():
                    return err(f"Model artifact incomplete: {required_path}")
        return ok()


    @classmethod
    def resolve_model_paths(cls, backend: str) -> OpResult[ModelPaths]:
        paths_result = cls.get_model_paths(backend)
        if not paths_result.is_ok:
            return err(f"Failed to get model paths for backend: {backend}", inner=paths_result)

        validation_result = cls.validate_model_paths(paths_result.value)
        if not validation_result.is_ok:
            return err(f"Model artifact validation failed for backend: {backend}", inner=validation_result)
        return ok(paths_result.value)



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
                          cls.REID_PT_PATH]:
            if not file_path.is_file():
                error_msg = f"Critical Error: Required file not found: {file_path}"
                return err(error_msg)

        model_result = cls.resolve_model_paths("PyTorch")
        if not model_result.is_ok:
            return err("Critical Error: Required PyTorch model artifact not found", inner=model_result)
            
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
    def _module_to_path(cls, module) -> Path:
        return cls.ROOT_DIR / f"{module.replace('.', '/')}.py"
