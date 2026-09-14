from __future__ import annotations

from pathlib import Path


class PathCollection:
    def __init__(self, files: list[Path], ignored: list[tuple[Path, str]]) -> None:
        self.files = files
        self.ignored = ignored


def collect_input_paths(paths: list[str | Path]) -> PathCollection:
    files: list[Path] = []
    ignored: list[tuple[Path, str]] = []
    seen: set[str] = set()

    def add_file(path: Path) -> None:
        key = str(path.resolve()).casefold()
        if key not in seen:
            seen.add(key)
            files.append(path)

    for raw_path in paths:
        path = Path(raw_path)
        try:
            resolved = path.resolve()
        except OSError:
            ignored.append((path, "unresolved"))
            continue

        if resolved.is_file():
            if resolved.suffix.casefold() == ".txt":
                add_file(resolved)
            else:
                ignored.append((resolved, "not_txt"))
        elif resolved.is_dir():
            maidata_path = resolved / "maidata.txt"
            if maidata_path.is_file():
                add_file(maidata_path.resolve())
            else:
                ignored.append((resolved, "maidata_missing"))
        else:
            ignored.append((resolved, "invalid_path"))

    return PathCollection(files, ignored)
