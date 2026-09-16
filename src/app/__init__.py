from importlib import import_module

# lazy export:
# 调用方统一 from src.app import MainWindow, 不写具体模块名
# 必须惰性: main_window 会连带加载全部页面与 cv2 等重依赖,
# 在 __init__ 里立即导入会让 import src.app.<任意子模块> 都付出该成本

_LAZY_EXPORTS: dict[str, str] = {
    # main_window.py
    "MainWindow": ".main_window",
}


def __getattr__(name: str):
    module_name = _LAZY_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(import_module(module_name, __name__), name)


__all__ = list(_LAZY_EXPORTS)
