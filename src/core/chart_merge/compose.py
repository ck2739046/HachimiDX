from __future__ import annotations

from pathlib import Path
from typing import Mapping

from .candidates import HEADER_KEYS
from .parse import ChartBlock

def _collect_selected_charts(
    selected_charts: Mapping[int, ChartBlock | None],
) -> list[ChartBlock]:
    return [
        chart
        for level, chart in sorted(selected_charts.items())
        if chart is not None and chart.level == level
    ]


def _render_maidata(
    headers: Mapping[str, str],
    selected_charts: Mapping[int, ChartBlock | None],
) -> str:
    output = [f"&{key}={headers.get(key, '')}\n" for key in HEADER_KEYS]
    output.append("\n")

    charts = _collect_selected_charts(selected_charts)
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
) -> Path:
    path = Path(output_path)
    path.write_text(
        _render_maidata(headers, selected_charts),
        encoding="utf-8",
        newline="",
    )
    return path
