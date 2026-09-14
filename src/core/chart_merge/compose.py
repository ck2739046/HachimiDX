from __future__ import annotations

from pathlib import Path
from typing import Mapping

from .parse import ChartBlock


def compose_maidata(
    output_path: str | Path,
    headers: Mapping[str, str],
    selected_charts: Mapping[int, ChartBlock | None],
) -> Path:
    path = Path(output_path)

    output: list[str] = []
    for key in ("title", "artist", "first", "des"):
        output.append(f"&{key}={headers.get(key, '')}\n")
    output.append("\n")

    charts = [
        chart for level, chart in sorted(selected_charts.items())
        if chart is not None and chart.level == level
    ]
    for chart in charts:
        if chart.designer != "":
            output.append(f"&des_{chart.level}={chart.designer}\n")
        if chart.level_value != "":
            output.append(f"&lv_{chart.level}={chart.level_value}\n")
    output.append("\n")

    for index, chart in enumerate(charts):
        output.append(f"&inote_{chart.level}={chart.inote_value}\n")
        output.extend(chart.body_lines)
        if index != len(charts) - 1 and chart.body_lines and not chart.body_lines[-1].endswith(("\n", "\r")):
            output.append("\n")

    path.write_text("".join(output), encoding="utf-8", newline="")
    return path
