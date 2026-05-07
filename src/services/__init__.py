from importlib import import_module

from .path_manage import PathManage
from .settings_manage import SettingsManage
from .i18n_manage import I18nManage
from .majdata_session import MajdataSession, stop_majdata
from .majdata_sync_server import VideoSyncServer

# 暴露接口模块作为命名空间，以区分同名函数（如 cancel, get_signals）
from . import process_manager_api
from . import task_scheduler_api


# lazy loading，避免循环依赖
def __getattr__(name: str):
    if name == "AllServices":
        module = import_module(".all_services", __name__)
        return module.AllServices
    if name == "AutoConvertPipeline":
        module = import_module(".pipeline.auto_convert_pipeline", __name__)
        return module.AutoConvertPipeline
    if name == "MediaPipeline":
        module = import_module(".pipeline.media_pipeline", __name__)
        return module.MediaPipeline
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "AllServices",
    "PathManage",
    "SettingsManage",
    "I18nManage",
    "MajdataSession", "stop_majdata",
    "VideoSyncServer",

    "AutoConvertPipeline",
    "MediaPipeline",

    "process_manager_api",
    "task_scheduler_api",
]
