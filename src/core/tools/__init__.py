from importlib import import_module


# lazy export: 
# 调用方统一 from src.core.tools import <名字>, 不写具体模块名
# 必须惰性, 只在调用时才导入子模块, 避免循环导入

# 因为 validate_* / media_ffprobe_inspect 会导入 schemas.op_result,
# 而 op_result 反过来要用 native_stream, 在 __init__ 里立即导入会形成循环

# 模块名与导出名刻意不同, 导入子模块不会遮蔽包属性

_LAZY_EXPORTS: dict[str, str] = {
    # uid_generation.py
    "generate_uid": ".uid_generation",
    # pydantic_validation.py
    "validate_pydantic": ".pydantic_validation",
    # validate_windows_filename.py
    "validate_windows_filename": ".windows_filename_validation",
    # media_ffprobe_inspect.py
    "FFprobeInspect": ".media_ffprobe_inspect",
    "FFprobeInspectResult": ".media_ffprobe_inspect",
    # popup_dialog.py
    "show_confirm_dialog": ".popup_dialog",
    "show_notify_dialog": ".popup_dialog",
    # native_stream.py
    "OutputStreamDecoder": ".native_stream",
    "strip_ansi": ".native_stream",
    "redirect_native_stderr": ".native_stream",
    "describe_exception": ".native_stream",
    "find_native_message": ".native_stream",
    "rewrite_native_error_line": ".native_stream",
}


def __getattr__(name: str):
    module_name = _LAZY_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(import_module(module_name, __name__), name)


__all__ = list(_LAZY_EXPORTS)
