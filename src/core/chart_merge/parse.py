from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


_INOTE_RE = re.compile(r"^&inote_(\d+)=(.*)$")
_PARAMETER_RE = re.compile(r"^&([a-zA-Z]+(?:_\d+)?)=(.*)$")

# 谱面文件级共有参数，按此顺序写入输出
HEADER_KEYS = ("title", "artist", "first", "des")


@dataclass(frozen=True, slots=True)
class ChartBlock:
    level: int
    inote_value: str
    body_lines: tuple[str, ...]
    designer: str
    level_value: str
    source_path: Path


@dataclass(frozen=True, slots=True)
class ParsedChartFile:
    path: Path
    header_candidates: dict[str, tuple[str, ...]]
    charts: tuple[ChartBlock, ...]


@dataclass(frozen=True, slots=True)
class _OpenChart:
    level: int
    inote_value: str
    body_start: int


@dataclass(frozen=True, slots=True)
class _ChartRange:
    level: int
    inote_value: str
    body_start: int
    body_end: int


def _read_utf8(path: Path) -> str:
    # utf-8-sig 会丢弃开头的 BOM；不可用 read_text，它会归一 \r\n
    return path.read_bytes().decode("utf-8-sig")


def _append_chart_range(
    current: _OpenChart | None,
    body_end: int,
    seen_levels: set[int],
    chart_ranges: list[_ChartRange],
) -> None:
    if current is None or current.level in seen_levels:
        return
    chart_ranges.append(
        _ChartRange(
            level=current.level,
            inote_value=current.inote_value,
            body_start=current.body_start,
            body_end=body_end,
        )
    )
    seen_levels.add(current.level)


def _scan_lines(
    lines: list[str],
) -> tuple[dict[str, list[str]], list[_ChartRange]]:
    parameters: dict[str, list[str]] = {}
    chart_ranges: list[_ChartRange] = []
    seen_levels: set[int] = set()
    current: _OpenChart | None = None

    for index, line in enumerate(lines):
        stripped = line.rstrip("\r\n")
        inote_match = _INOTE_RE.match(stripped)
        if inote_match:
            _append_chart_range(current, index, seen_levels, chart_ranges)
            current = _OpenChart(
                level=int(inote_match.group(1)),
                inote_value=inote_match.group(2),
                body_start=index + 1,
            )
            continue

        if stripped.startswith("&"):
            _append_chart_range(current, index, seen_levels, chart_ranges)
            current = None
            # 参数正则以 ^& 开头，只可能命中 & 行
            parameter_match = _PARAMETER_RE.match(stripped)
            if parameter_match:
                key, value = parameter_match.group(1), parameter_match.group(2)
                parameters.setdefault(key, []).append(value)

    _append_chart_range(current, len(lines), seen_levels, chart_ranges)
    return parameters, chart_ranges


def _build_header_candidates(
    parameters: dict[str, list[str]],
) -> dict[str, tuple[str, ...]]:
    return {
        key: tuple(dict.fromkeys(parameters.get(key, [])))
        for key in HEADER_KEYS
    }


def _build_charts(
    source_path: Path,
    lines: list[str],
    parameters: dict[str, list[str]],
    chart_ranges: list[_ChartRange],
) -> tuple[ChartBlock, ...]:
    charts: list[ChartBlock] = []
    for chart_range in chart_ranges:
        level = chart_range.level
        charts.append(
            ChartBlock(
                level=level,
                inote_value=chart_range.inote_value,
                body_lines=tuple(
                    lines[chart_range.body_start:chart_range.body_end]
                ),
                designer=parameters.get(f"des_{level}", [""])[0],
                level_value=parameters.get(f"lv_{level}", [""])[0],
                source_path=source_path,
            )
        )
    return tuple(charts)


def parse_chart_file(path: str | Path) -> ParsedChartFile:
    source_path = Path(path)
    lines = _read_utf8(source_path).splitlines(keepends=True)
    parameters, chart_ranges = _scan_lines(lines)

    return ParsedChartFile(
        path=source_path,
        header_candidates=_build_header_candidates(parameters),
        charts=_build_charts(source_path, lines, parameters, chart_ranges),
    )
