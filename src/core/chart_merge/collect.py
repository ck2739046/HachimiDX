from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


REASON_UNRESOLVED = "unresolved"
REASON_NOT_TXT = "not_txt"
REASON_MAIDATA_MISSING = "maidata_missing"
REASON_INVALID_PATH = "invalid_path"
REASON_DUPLICATE = "duplicate"

# 页面按 ignore_<reason> 取翻译的既有原因码
_IGNORED_REASONS = frozenset(
    {
        REASON_UNRESOLVED,
        REASON_NOT_TXT,
        REASON_MAIDATA_MISSING,
        REASON_INVALID_PATH,
    }
)


def path_key(path: Path) -> str:
    return str(path.resolve()).casefold()


@dataclass(frozen=True, slots=True)
class CollectedInput:
    """一次输入项的处理结果.

    input_path 是用户选择项，resolved_path 是实际读取的 txt 路径
    （文件夹输入为 <folder>\\maidata.txt，无法解析时回落为 input_path）.
    reason 为 None 表示该输入项可用.
    """

    input_path: Path
    resolved_path: Path
    reason: str | None = None
    detail: str = ""


class PathCollection:
    def __init__(self, entries: list[CollectedInput]) -> None:
        self.entries = entries
        self.files = [
            entry.resolved_path for entry in entries if entry.reason is None
        ]
        self.ignored = [
            (entry.resolved_path, entry.reason)
            for entry in entries
            if entry.reason in _IGNORED_REASONS
        ]


def collect_input_paths(paths: list[str | Path]) -> PathCollection:
    entries: list[CollectedInput] = []
    seen: set[str] = set()

    for raw_path in paths:
        input_path = Path(raw_path)
        try:
            resolved = input_path.resolve()
        except OSError:
            entries.append(
                CollectedInput(input_path, input_path, REASON_UNRESOLVED)
            )
            continue

        if resolved.is_file():
            if resolved.suffix.casefold() != ".txt":
                entries.append(
                    CollectedInput(input_path, resolved, REASON_NOT_TXT)
                )
                continue
            candidate = resolved
        elif resolved.is_dir():
            maidata_path = resolved / "maidata.txt"
            if not maidata_path.is_file():
                entries.append(
                    CollectedInput(input_path, resolved, REASON_MAIDATA_MISSING)
                )
                continue
            candidate = maidata_path.resolve()
        else:
            entries.append(
                CollectedInput(input_path, resolved, REASON_INVALID_PATH)
            )
            continue

        key = path_key(candidate)
        if key in seen:
            entries.append(
                CollectedInput(input_path, candidate, REASON_DUPLICATE)
            )
            continue

        seen.add(key)
        entries.append(CollectedInput(input_path, candidate))

    return PathCollection(entries)
