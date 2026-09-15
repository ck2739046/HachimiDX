from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .collect import CollectedInput, collect_input_paths
from .parse import ParsedChartFile, parse_chart_file


REASON_INVALID_ENCODING = "invalid_encoding"
REASON_READ_FAILED = "read_failed"
REASON_NO_VALID_CHART = "no_valid_chart"


@dataclass(frozen=True, slots=True)
class ChartFileLoadResult:
    parsed: ParsedChartFile | None = None
    reason: str | None = None
    detail: str = ""


def load_chart_file(path: str | Path) -> ChartFileLoadResult:
    """校验并读取一个输入谱面文件.

    要求 UTF-8 / UTF-8-BOM 编码，且至少存在一个合法的 inote_x 谱面；
    共有参数可以缺失.
    """
    try:
        parsed = parse_chart_file(path)
    except UnicodeDecodeError:
        return ChartFileLoadResult(reason=REASON_INVALID_ENCODING)
    except OSError as exc:
        return ChartFileLoadResult(reason=REASON_READ_FAILED, detail=str(exc))

    if not parsed.charts:
        return ChartFileLoadResult(reason=REASON_NO_VALID_CHART)

    return ChartFileLoadResult(parsed=parsed)


def import_chart_inputs(
    paths: list[str | Path],
    existing_keys: set[str] | frozenset[str] = frozenset(),
) -> tuple[list[ParsedChartFile], list[CollectedInput]]:
    """按选择顺序处理一批输入项，返回可用谱面文件和逐项处理结果."""
    loaded: list[ParsedChartFile] = []
    results: list[CollectedInput] = []

    for entry in collect_input_paths(paths, existing_keys):
        if entry.reason is not None:
            results.append(entry)
            continue

        result = load_chart_file(entry.resolved_path)
        parsed = result.parsed
        if parsed is None:
            results.append(
                CollectedInput(
                    entry.input_path,
                    entry.resolved_path,
                    result.reason,
                    result.detail,
                )
            )
            continue

        loaded.append(parsed)
        results.append(entry)

    return loaded, results
