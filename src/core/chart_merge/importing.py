from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Collection

from .collect import CollectedInput, collect_input_paths
from .parse import ParsedChartFile, parse_chart_file


REASON_INVALID_ENCODING = "invalid_encoding"
REASON_READ_FAILED = "read_failed"
REASON_NO_VALID_CHART = "no_valid_chart"


def import_chart_inputs(
    paths: list[str | Path],
    existing_keys: Collection[str] = (),
) -> tuple[list[ParsedChartFile], list[CollectedInput]]:
    """按选择顺序处理一批输入项，返回可用谱面文件和逐项处理结果.

    谱面文件要求 UTF-8 / UTF-8-BOM 编码，且至少存在一个合法的 inote_x 谱面；
    共有参数可以缺失.
    """
    loaded: list[ParsedChartFile] = []
    results: list[CollectedInput] = []

    for entry in collect_input_paths(paths, existing_keys):
        if entry.reason is not None:
            results.append(entry)
            continue

        try:
            parsed = parse_chart_file(entry.resolved_path)
        except UnicodeDecodeError:
            results.append(replace(entry, reason=REASON_INVALID_ENCODING))
            continue
        except OSError as exc:
            results.append(
                replace(entry, reason=REASON_READ_FAILED, detail=str(exc))
            )
            continue

        if not parsed.charts:
            results.append(replace(entry, reason=REASON_NO_VALID_CHART))
            continue

        loaded.append(parsed)
        results.append(entry)

    return loaded, results
