import sys
from pathlib import Path
import shutil
import subprocess
import os

root = Path(__file__).parents[3].resolve()
if root not in sys.path:
    sys.path.insert(0, str(root))

from src.services import PathManage


RELEASE_DIR = PathManage.ROOT_DIR / "HachimiDX"



def main():

    if RELEASE_DIR.is_dir():
        shutil.rmtree(RELEASE_DIR)
    RELEASE_DIR.mkdir(parents=True, exist_ok=True)

    # 将 src 目录下所有 .py 文件复制到 release 目录
    for src_file in (PathManage.ROOT_DIR / "src").rglob("*.py"):
        if "for_release_only" in src_file.parts: continue # 过滤
        relative_path = src_file.relative_to(PathManage.ROOT_DIR)
        dest_file = RELEASE_DIR / relative_path
        dest_file.parent.mkdir(parents=True, exist_ok=True)
        dest_file.write_bytes(src_file.read_bytes())

    copy_app_resources()

    copy_root()




def copy_app_resources():

    # /locales
    copy_to_release(PathManage.LOCALES_DIR)
    # icon
    copy_to_release(PathManage.APP_ICON_PATH)
    # click template
    copy_to_release(PathManage.CLICK_TEMPLATE_PATH)
    # test videos
    copy_to_release(PathManage.TEST_H264_PATH)

    # 解压 models
    models_dir = PathManage.RESOURCES_DIR / "for_release_only" / "models"
    for model_zip in models_dir.glob("*.zip"):
        target_dir = RELEASE_DIR / "src" / "resources" / "models"
        extract_with_bandizip(model_zip, target_dir, mode='file')

    # 解压 python 到目录
    python_path = PathManage.RESOURCES_DIR / "for_release_only" / "python portable" / "py3.13.11.zip"
    python_target_path = RELEASE_DIR / "python"
    extract_with_bandizip(python_path, python_target_path, mode='dir')

    # 解压 ffmpeg 到目录
    ffmpeg_path = PathManage.RESOURCES_DIR / "for_release_only" / "ffmpeg-8.0.1-essentials_build.7z"
    ffmpeg_target_path = RELEASE_DIR / "src" / "resources" / "ffmpeg"
    extract_with_bandizip(ffmpeg_path, ffmpeg_target_path, mode='dir')

    # 复制 majdata
    majdata_dir = PathManage.RESOURCES_DIR / "for_release_only" / "majdata"
    majdata_target_path = RELEASE_DIR / "src" / "resources" / "majdata"
    copy_to_release(majdata_dir, majdata_target_path)

    # 安装指南
    install_guide_cn = PathManage.RESOURCES_DIR / "for_release_only" / "1_安装指南.txt"
    copy_to_release(install_guide_cn, RELEASE_DIR / "1_安装指南.txt")
    install_guide_us = PathManage.RESOURCES_DIR / "for_release_only" / "1_Installation Guide.txt"
    copy_to_release(install_guide_us, RELEASE_DIR / "1_Installation Guide.txt")




def copy_root():
    
    # /install
    copy_to_release(PathManage.ROOT_DIR / "install")
    # readme
    copy_to_release(PathManage.ROOT_DIR / "README.md")
    copy_to_release(PathManage.ROOT_DIR / "README_zh_cn.md")
    # license
    copy_to_release(PathManage.ROOT_DIR / "LICENSE")
    # launcher
    copy_to_release(PathManage.ROOT_DIR / "HachimiDX.exe")
    copy_to_release(PathManage.ROOT_DIR / "main.py")





def extract_with_bandizip(archive_path: Path, extract_path: Path, mode: str):
    # Bandizip 智能解压到此处
    if mode == 'dir':
        # 因为会在目标文件夹内新建一个压缩包同名文件夹，所以解压地址要使用 extract_path.parent
        cmd = ["bandizip", "bx", f"-o:{extract_path.parent}", "-target:auto", str(archive_path)]
        result = subprocess.run(cmd, capture_output=True, text=True, shell=True)
        if result.returncode != 0:
            raise RuntimeError(f"Bandizip 解压失败: {result.stderr}")
        # 重命名文件夹
        real_extracted_dir = extract_path.parent / archive_path.stem
        os.rename(real_extracted_dir, extract_path)
    elif mode == 'file':
        # 解压到目标路径时不创建压缩包同名文件夹
        cmd = ["bandizip", "x", f"-o:{extract_path}", str(archive_path)]
        result = subprocess.run(cmd, capture_output=True, text=True, shell=True)
        if result.returncode != 0:
            raise RuntimeError(f"Bandizip 解压失败: {result.stderr}")
    else:
        print(f"extract_with_bandizip: Invalid mode: {mode}")




def copy_to_release(input_path: Path, target_path: Path = None):

    if input_path.is_dir():
        # 先删除文件夹内的 __pychache___
        for pycache in input_path.rglob("__pycache__"):
            if pycache.is_dir():
                shutil.rmtree(pycache)

        if target_path is None:
            # 用 root 下的相对路径构建目标路径
            relative_path = input_path.relative_to(PathManage.ROOT_DIR)
            dest_dir = RELEASE_DIR / relative_path
        else:
            dest_dir = target_path
        # 在 release 目录下创建相同的目录结构
        dest_dir.mkdir(parents=True, exist_ok=True)
        # 复制
        shutil.copytree(str(input_path), str(dest_dir), dirs_exist_ok=True)
    
    elif input_path.is_file():
        if target_path is None:
            # 用 root 下的相对路径构建目标路径
            relative_path = input_path.relative_to(PathManage.ROOT_DIR)
            dest_file = RELEASE_DIR / relative_path
        else:
            dest_file = target_path
        # 在 release 目录下创建相同的目录结构
        dest_file.parent.mkdir(parents=True, exist_ok=True)
        # 复制
        dest_file.write_bytes(input_path.read_bytes())

    else:
        print(f"copy_to_release: Warning: {input_path} is not a file or dir, skipping.")




if __name__ == "__main__":
    main()
