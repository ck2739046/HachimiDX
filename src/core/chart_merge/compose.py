from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Mapping

from .parse import HEADER_KEYS, ChartBlock


# level -> (designer, level_value)
LevelOverride = tuple[str, str]


def _collect_selected_charts(
    selected_charts: Mapping[int, ChartBlock | None],
    overrides: Mapping[int, LevelOverride],
) -> list[ChartBlock]:
    charts: list[ChartBlock] = []
    for level, chart in sorted(selected_charts.items()):
        if chart is None or chart.level != level:
            continue
        designer, level_value = overrides.get(
            level, (chart.designer, chart.level_value)
        )
        charts.append(
            replace(chart, designer=designer, level_value=level_value)
        )
    return charts


def _render_maidata(
    headers: Mapping[str, str],
    selected_charts: Mapping[int, ChartBlock | None],
    overrides: Mapping[int, LevelOverride],
) -> str:
    output = [f"&{key}={headers.get(key, '')}\n" for key in HEADER_KEYS]
    output.append("\n")

    charts = _collect_selected_charts(selected_charts, overrides)
    for chart in charts:
        if chart.designer != "":
            output.append(f"&des_{chart.level}={chart.designer}\n")
        if chart.level_value != "":
            output.append(f"&lv_{chart.level}={chart.level_value}\n")
    output.append("\n")

    for index, chart in enumerate(charts):
        output.append(f"&inote_{chart.level}={chart.inote_value}\n")
        output.extend(chart.body_lines)
        if (
            index != len(charts) - 1
            and chart.body_lines
            and not chart.body_lines[-1].endswith(("\n", "\r"))
        ):
            output.append("\n")

    return "".join(output)


def compose_maidata(
    output_path: str | Path,
    headers: Mapping[str, str],
    selected_charts: Mapping[int, ChartBlock | None],
    overrides: Mapping[int, LevelOverride],
) -> Path:
    path = Path(output_path)
    path.write_text(
        _render_maidata(headers, selected_charts, overrides),
        encoding="utf-8",
        newline="",
    )
    return path
