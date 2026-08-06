# sitecustomize.py
# this file was added by PythonEmbed4Win.ps1
# https://github.com/jtmoon79/PythonEmbed4Win/blob/0a2e24cc224743ecc199d51bd6f43bb5990bce25/PythonEmbed4Win.ps1

import os
from pathlib import Path
import site
import sys

# do not use user-wide site.USER_SITE path; it refers to a path location
# outside of this embed installation
site.ENABLE_USER_SITE = False

# remove site.USER_SITE and the realpath variation from sys.path
# XXX: somewhat time consuming to do on every startup but thorough
__sys_path_index_del = list()
"""index to delete from sys.path"""
__user_site_resolve = os.path.realpath(site.USER_SITE)
for __i, __path in enumerate(sys.path):
    __path_resolve = os.path.realpath(__path)
    if site.USER_SITE in (__path, __path_resolve):
        __sys_path_index_del.append(__i)
        continue
    if __user_site_resolve in (__path, __path_resolve):
        __sys_path_index_del.append(__i)
for __index_del in reversed(__sys_path_index_del):
    sys.path.pop(__index_del)
del __sys_path_index_del
del __user_site_resolve


__tensorrt_dll_directories = []
if os.name == "nt" and hasattr(os, "add_dll_directory"):
    try:
        __runtime_root = (Path(__file__).resolve().parent / "tensorrt_runtime").resolve()
        __marker_path = __runtime_root / "current.txt"
        if __marker_path.is_file():
            __runtime_version = __marker_path.read_text(encoding="utf-8").strip()
            __version_parts = __runtime_version.split(".")
            if 3 <= len(__version_parts) <= 4 and all(part.isdigit() for part in __version_parts):
                __runtime_lib = (__runtime_root / __runtime_version / "lib").resolve()
                if __runtime_lib.is_relative_to(__runtime_root) and __runtime_lib.is_dir():
                    __dll_paths = [__runtime_lib]
                    __torch_lib = Path(__file__).resolve().parent / "Lib" / "site-packages" / "torch" / "lib"
                    if __torch_lib.is_dir():
                        __dll_paths.append(__torch_lib.resolve())

                    __current_path = os.environ.get("PATH", "")
                    __path_entries = {
                        os.path.normcase(os.path.normpath(entry))
                        for entry in __current_path.split(os.pathsep)
                        if entry
                    }
                    __missing_paths = [
                        str(path)
                        for path in __dll_paths
                        if os.path.normcase(os.path.normpath(str(path))) not in __path_entries
                    ]
                    if __missing_paths:
                        os.environ["PATH"] = os.pathsep.join(
                            __missing_paths + ([__current_path] if __current_path else [])
                        )
                    for __dll_path in __dll_paths:
                        __tensorrt_dll_directories.append(os.add_dll_directory(str(__dll_path)))
    except (OSError, ValueError):
        pass


# redirect pip cache into the portable python folder
os.environ["PIP_CACHE_DIR"] = str((Path(__file__).resolve().parent / "pip-cache").resolve())

