import sys

from src.services import PathManage


def build_cmd_head_module(module_path) -> list[str]:
    return [sys.executable, "-u", "-m", str(module_path).strip()]


def build_cmd_head_python_exe(worker_path) -> list[str]:
    # 需要传入 root_dir, 解决 worker 的间接导入问题
    return [sys.executable, "-u", str(worker_path).strip(), str(PathManage.ROOT_DIR)]
