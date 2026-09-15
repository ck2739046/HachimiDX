from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


REASON_UNRESOLVED = "unresolved"
REASON_NOT_TXT = "not_txt"
REASON_MAIDATA_MISSING = "maidata_missing"
REASON_INVALID_PATH = "invalid_path"
REASON_DUPLICATE = "duplicate"


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


def collect_input_paths(
    paths: list[str | Path],
    seen_keys: Iterable[str] = (),
) -> list[CollectedInput]:
    """按选择顺序归一输入路径，重复项标记为 REASON_DUPLICATE.

    seen_keys 为调用方已持有的路径键，使跨批次去重与批内去重共用同一规则.
    """
    entries: list[CollectedInput] = []
    seen: set[str] = set(seen_keys)

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

    return entries
