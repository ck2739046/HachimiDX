from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable, Sequence

from .parse import HEADER_KEYS

if TYPE_CHECKING:
    from .parse import ChartBlock, ParsedChartFile


STANDARD_LEVELS = tuple(range(2, 8))


@dataclass(frozen=True, slots=True)
class CandidateCollection:
    header_candidates: dict[str, tuple[str, ...]]
    charts_by_level: dict[int, tuple[ChartBlock, ...]]


def aggregate_candidates(
    parsed_files: Sequence[ParsedChartFile],
) -> CandidateCollection:
    """按输入顺序聚合共有参数和各等级谱面候选。"""
    header_candidates: dict[str, list[str]] = {
        key: [] for key in HEADER_KEYS
    }
    charts_by_level: dict[int, list[ChartBlock]] = {}

    for parsed in parsed_files:
        for key in HEADER_KEYS:
            for value in parsed.header_candidates[key]:
                if value not in header_candidates[key]:
                    header_candidates[key].append(value)
        for chart in parsed.charts:
            charts_by_level.setdefault(chart.level, []).append(chart)

    return CandidateCollection(
        header_candidates={
            key: tuple(values) for key, values in header_candidates.items()
        },
        charts_by_level={
            level: tuple(charts) for level, charts in charts_by_level.items()
        },
    )


def ordered_chart_levels(extra_levels: Iterable[int] = ()) -> tuple[int, ...]:
    return tuple(sorted(set(STANDARD_LEVELS).union(extra_levels)))
