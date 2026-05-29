from importlib import import_module

# 全量 lazy loading
# 所有可导入符号均通过 __getattr__ 延迟导入；不再有任何 eager import。
# 用法：from src.services import PathManage, SettingsManage, ...

_LAZY_MAP: dict[str, str] = {
    # 核心管理
    "PathManage":       ".path_manage",
    "SettingsManage":   ".settings_manage",
    "I18nManage":       ".i18n_manage",

    # majdata
    "MajdataSession":   ".majdata_session",
    "stop_majdata":     ".majdata_session",
    "VideoSyncServer":  ".majdata_sync_server",

    # 聚合入口
    "AllServices":      ".all_services",

    # pipeline
    "AutoRechartPipeline": ".pipeline.auto_rechart_pipeline",
    "MediaPipeline":       ".pipeline.media_pipeline",

    # 调度器数据模型
    "TaskInfo":   ".task_scheduler",
    "TaskStatus": ".task_scheduler",
}


def __getattr__(name: str):
    # 子模块命名空间（用于区分同名函数，如 cancel / get_signals）
    if name in ("process_manager_api", "task_scheduler_api"):
        module = import_module(f".{name}", __name__)
        return module

    if name in _LAZY_MAP:
        module = import_module(_LAZY_MAP[name], __name__)
        return getattr(module, name)

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "AllServices",
    "PathManage",
    "SettingsManage",
    "I18nManage",
    "MajdataSession", "stop_majdata",
    "VideoSyncServer",
    "AutoRechartPipeline",
    "MediaPipeline",
    "TaskInfo", "TaskStatus",
    "process_manager_api",
    "task_scheduler_api",
]
