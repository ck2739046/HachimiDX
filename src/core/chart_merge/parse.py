from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


_INOTE_RE = re.compile(r"^&inote_(\d+)=(.*)$")
_PARAMETER_RE = re.compile(r"^&([a-zA-Z]+(?:_\d+)?)=(.*)$")


@dataclass(frozen=True)
class ChartBlock:
    level: int
    inote_value: str
    body_lines: tuple[str, ...]
    designer: str
    level_value: str
    source_path: Path

    @property
    def source_label(self) -> str:
        return str(self.source_path)


@dataclass(frozen=True)
class ParsedChartFile:
    path: Path
    headers: dict[str, str]
    header_candidates: dict[str, tuple[str, ...]]
    charts: tuple[ChartBlock, ...]


def _read_utf8(path: Path) -> str:
    data = path.read_bytes()
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    return data.decode("utf-8")


def _split_parameter(line: str) -> tuple[str, str] | None:
    match = _PARAMETER_RE.match(line.rstrip("\r\n"))
    if not match:
        return None
    return match.group(1), match.group(2)


def parse_chart_file(path: str | Path) -> ParsedChartFile:
    source_path = Path(path)
    lines = _read_utf8(source_path).splitlines(keepends=True)
    parameters: dict[str, list[str]] = {}
    chart_ranges: list[tuple[int, str, int, int]] = []

    current_level: int | None = None
    current_inote: str | None = None
    current_start = 0

    def finish_chart(end: int) -> None:
        nonlocal current_level, current_inote, current_start
        if current_level is not None and current_inote is not None:
            chart_ranges.append((current_level, current_inote, current_start, end))
        current_level = None
        current_inote = None

    for index, line in enumerate(lines):
        stripped = line.rstrip("\r\n")
        inote_match = _INOTE_RE.match(stripped)
        if inote_match:
            finish_chart(index)
            current_level = int(inote_match.group(1))
            current_inote = inote_match.group(2)
            current_start = index + 1
            continue

        parameter = _split_parameter(stripped)
        if parameter is not None:
            finish_chart(index)
            key, value = parameter
            parameters.setdefault(key, []).append(value)

    finish_chart(len(lines))

    headers = {
        key: values[0]
        for key, values in parameters.items()
        if key in {"title", "artist", "first", "des"} and values
    }
    header_candidates = {
        key: tuple(dict.fromkeys(parameters.get(key, [])))
        for key in ("title", "artist", "first", "des")
    }

    charts: list[ChartBlock] = []
    for level, inote_value, start, end in chart_ranges:
        level_value = parameters.get(f"lv_{level}", [""])[0]
        designer = parameters.get(f"des_{level}", [""])[0]
        charts.append(
            ChartBlock(
                level=level,
                inote_value=inote_value,
                body_lines=tuple(lines[start:end]),
                designer=designer,
                level_value=level_value,
                source_path=source_path,
            )
        )

    return ParsedChartFile(
        path=source_path,
        headers=headers,
        header_candidates=header_candidates,
        charts=tuple(charts),
    )
