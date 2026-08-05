from dataclasses import dataclass
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import urllib.request
import zipfile

from .op_result import OpResult, err, ok


@dataclass(frozen=True, slots=True)
class _LegacyTensorRTPackage:
    package_version: str
    archive_version: str
    filename: str
    wheel_filename: str
    url: str


_LEGACY_TRT_PACKAGES = {
    "8.6.1": _LegacyTensorRTPackage(
        package_version="8.6.1",
        archive_version="8.6.1.6",
        filename="TensorRT-8.6.1.6.Windows10.x86_64.cuda-11.8.zip",
        wheel_filename="tensorrt-8.6.1-cp311-none-win_amd64.whl",
        url=(
            "https://developer.nvidia.com/downloads/compute/machine-learning/"
            "tensorrt/secure/8.6.1/zip/"
            "TensorRT-8.6.1.6.Windows10.x86_64.cuda-11.8.zip"
        ),
    ),
    "8.5.3.1": _LegacyTensorRTPackage(
        package_version="8.5.3.1",
        archive_version="8.5.3.1",
        filename="TensorRT-8.5.3.1.Windows10.x86_64.cuda-11.8.cudnn8.6.zip",
        wheel_filename="tensorrt-8.5.3.1-cp311-none-win_amd64.whl",
        url=(
            "https://developer.nvidia.com/downloads/compute/machine-learning/"
            "tensorrt/secure/8.5.3/zip/"
            "TensorRT-8.5.3.1.Windows10.x86_64.cuda-11.8.cudnn8.6.zip"
        ),
    ),
}

_DOWNLOAD_CHUNK_SIZE = 1024 * 1024
_DOWNLOAD_TIMEOUT_SECONDS = 60


def install_legacy_tensorrt(
    T,
    root: Path,
    python_executable: str,
    tensorrt_version: str,
) -> OpResult[None]:
    package = _LEGACY_TRT_PACKAGES.get(tensorrt_version)
    if package is None:
        return err(T.legacy_trt.unsupported_version.format(version=tensorrt_version))

    tmp_dir = root / "_tmp_trt"
    archive_path = tmp_dir / package.filename
    wheel_path: Path | None = None

    try:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        tmp_dir.mkdir(parents=True, exist_ok=True)

        result = _download_archive(package, archive_path, T)
        if not result.is_ok:
            return result

        result = _prepare_archive(archive_path, tmp_dir, package, T)
        if not result.is_ok:
            return result
        wheel_path, staged_runtime_dir = result.value

        print(T.legacy_trt.install_wheel.format(filename=wheel_path.name))
        subprocess.run(
            [
                python_executable,
                "-m", "pip", "install",
                str(wheel_path),
                "--no-deps", "--force-reinstall",
                "--no-warn-script-location",
            ],
            check=True,
        )

        result = _commit_runtime(root, staged_runtime_dir, package.archive_version, T)
        if not result.is_ok:
            _uninstall_tensorrt_wheel(python_executable)
            return result

        result = _verify_installation(root, python_executable, package, T)
        if not result.is_ok:
            remove_legacy_tensorrt_runtime(root)
            _uninstall_tensorrt_wheel(python_executable)
            return result

        print(T.legacy_trt.success.format(version=package.archive_version))
        return ok()

    except Exception as e:
        remove_legacy_tensorrt_runtime(root)
        if wheel_path is not None:
            _uninstall_tensorrt_wheel(python_executable)
        return err(T.legacy_trt.install_failed.format(e=e), error_raw=e)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def remove_legacy_tensorrt_runtime(root: Path) -> OpResult[None]:
    runtime_root = root / "python" / "tensorrt_runtime"
    try:
        shutil.rmtree(runtime_root, ignore_errors=True)
        return ok()
    except Exception as e:
        return err("Failed to remove legacy TensorRT runtime.", error_raw=e)


def _download_archive(
    package: _LegacyTensorRTPackage,
    archive_path: Path,
    T,
) -> OpResult[None]:
    print(T.legacy_trt.download_start.format(filename=package.filename))
    try:
        request = urllib.request.Request(
            package.url,
            headers={"User-Agent": "HachimiDX-Installer/1.0"},
        )
        with (
            urllib.request.urlopen(request, timeout=_DOWNLOAD_TIMEOUT_SECONDS) as response,
            archive_path.open("wb") as output,
        ):
            try:
                total = int(response.headers.get("Content-Length", "0") or 0)
            except ValueError:
                total = 0
            downloaded = 0
            while chunk := response.read(_DOWNLOAD_CHUNK_SIZE):
                output.write(chunk)
                downloaded += len(chunk)
                _print_download_progress(downloaded, total, T)
        print()
        return ok()
    except Exception as e:
        return err(T.legacy_trt.download_failed.format(e=e), error_raw=e)


def _print_download_progress(downloaded: int, total: int, T) -> None:
    downloaded_mib = downloaded / (1024 * 1024)
    if total > 0:
        total_mib = total / (1024 * 1024)
        percent = downloaded * 100 / total
        message = T.legacy_trt.download_progress.format(
            downloaded=downloaded_mib,
            total=total_mib,
            percent=percent,
        )
    else:
        message = T.legacy_trt.download_progress_unknown.format(downloaded=downloaded_mib)
    print(f"\r{message}", end="", flush=True)


def _prepare_archive(
    archive_path: Path,
    tmp_dir: Path,
    package: _LegacyTensorRTPackage,
    T,
) -> OpResult[tuple[Path, Path]]:
    try:
        with zipfile.ZipFile(archive_path) as archive:
            archive_root = f"TensorRT-{package.archive_version}"
            wheel_member = f"{archive_root}/python/{package.wheel_filename}"
            archive.getinfo(wheel_member)
            archive.getinfo(f"{archive_root}/lib/nvinfer.dll")

            wheel_path = tmp_dir / package.wheel_filename
            with archive.open(wheel_member) as source, wheel_path.open("wb") as target:
                shutil.copyfileobj(source, target)

            staged_runtime_dir = tmp_dir / "runtime" / package.archive_version
            staged_lib_dir = staged_runtime_dir / "lib"
            staged_lib_dir.mkdir(parents=True, exist_ok=True)

            lib_prefix = f"{archive_root}/lib/"
            for info in archive.infolist():
                if info.is_dir() or not info.filename.startswith(lib_prefix):
                    continue
                if PurePosixPath(info.filename).suffix.lower() != ".dll":
                    continue
                filename = PurePosixPath(info.filename).name
                with archive.open(info) as source, (staged_lib_dir / filename).open("wb") as target:
                    shutil.copyfileobj(source, target)

            return ok((wheel_path, staged_runtime_dir))

    except (KeyError, OSError, zipfile.BadZipFile, RuntimeError) as e:
        return err(T.legacy_trt.invalid_archive, error_raw=e)


def _commit_runtime(
    root: Path,
    staged_runtime_dir: Path,
    archive_version: str,
    T,
) -> OpResult[None]:
    runtime_root = root / "python" / "tensorrt_runtime"
    target_dir = runtime_root / archive_version
    marker_path = runtime_root / "current.txt"

    try:
        shutil.rmtree(runtime_root, ignore_errors=True)
        target_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(staged_runtime_dir), str(target_dir))
        marker_path.write_text(archive_version, encoding="utf-8")
        return ok()
    except Exception as e:
        marker_path.unlink(missing_ok=True)
        shutil.rmtree(target_dir, ignore_errors=True)
        return err(T.legacy_trt.runtime_install_failed.format(e=e), error_raw=e)


def _verify_installation(
    root: Path,
    python_executable: str,
    package: _LegacyTensorRTPackage,
    T,
) -> OpResult[None]:
    runtime_lib = root / "python" / "tensorrt_runtime" / package.archive_version / "lib"
    torch_lib = root / "python" / "Lib" / "site-packages" / "torch" / "lib"
    env = os.environ.copy()
    if torch_lib.is_dir():
        _prepend_to_path(env, torch_lib)
    _prepend_to_path(env, runtime_lib)

    script = (
        "import tensorrt as trt; "
        f"expected={package.package_version!r}; "
        "actual=str(trt.__version__); "
        "assert actual == expected or actual.startswith(expected + '.'), "
        "f'expected TensorRT {expected}, got {actual}'; "
        "logger=trt.Logger(trt.Logger.ERROR); "
        "builder=trt.Builder(logger); "
        "assert builder is not None; "
        "print(actual)"
    )

    try:
        result = subprocess.run(
            [python_executable, "-c", script],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )
        actual_version = result.stdout.strip().splitlines()[-1]
        print(T.legacy_trt.verify_success.format(version=actual_version))
        return ok()
    except subprocess.CalledProcessError as e:
        detail = (e.stderr or e.stdout or str(e)).strip()
        return err(T.legacy_trt.verify_failed.format(e=detail), error_raw=e)
    except Exception as e:
        return err(T.legacy_trt.verify_failed.format(e=e), error_raw=e)


def _prepend_to_path(env: dict[str, str], directory: Path) -> None:
    directory_text = str(directory.resolve())
    current_path = env.get("PATH", "")
    normalized_directory = os.path.normcase(os.path.normpath(directory_text))
    normalized_entries = {
        os.path.normcase(os.path.normpath(entry))
        for entry in current_path.split(os.pathsep)
        if entry
    }
    if normalized_directory not in normalized_entries:
        env["PATH"] = directory_text + (os.pathsep + current_path if current_path else "")


def _uninstall_tensorrt_wheel(python_executable: str) -> None:
    subprocess.run(
        [python_executable, "-m", "pip", "uninstall", "tensorrt", "-y"],
        check=False,
    )
