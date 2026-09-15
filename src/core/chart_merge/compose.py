from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Mapping

from .parse import HEADER_KEYS, ChartBlock


@dataclass(frozen=True, slots=True)
class LevelSelection:
    """某个等级最终写入的谱面，以及覆盖 des_x / lv_x 的文本."""

    chart: ChartBlock
    designer: str
    level_value: str


def _collect_selected_charts(
    selections: Mapping[int, LevelSelection],
) -> list[ChartBlock]:
    charts: list[ChartBlock] = []
    for level in sorted(selections):
        selection = selections[level]
        charts.append(
            replace(
                selection.chart,
                designer=selection.designer,
                level_value=selection.level_value,
            )
        )
    return charts


def _render_maidata(
    headers: Mapping[str, str],
    selections: Mapping[int, LevelSelection],
) -> str:
    output = [f"&{key}={headers.get(key, '')}\n" for key in HEADER_KEYS]
    output.append("\n")

    charts = _collect_selected_charts(selections)
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
    selections: Mapping[int, LevelSelection],
) -> Path:
    path = Path(output_path)
    path.write_text(
        _render_maidata(headers, selections),
        encoding="utf-8",
        newline="",
    )
    return path
