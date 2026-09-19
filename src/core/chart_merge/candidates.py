from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Sequence

from .parse import HEADER_KEYS, ChartBlock, ParsedChartFile


@dataclass(frozen=True, slots=True)
class CandidateCollection:
    header_candidates: dict[str, tuple[str, ...]]
    charts_by_level: dict[int, tuple[ChartBlock, ...]]


def aggregate_candidates(
    parsed_files: Sequence[ParsedChartFile],
) -> CandidateCollection:
    """按输入顺序聚合共有参数和各等级谱面候选.

    各等级的 ChartBlock 直接复用 ParsedChartFile 中的原实例，不做拷贝或重建；
    同一等级内同一来源至多出现一次，调用方可用实例身份或相等性定位候选.
    """
    # dict 兼作有序去重集合，保留首次出现顺序
    header_values: dict[str, dict[str, None]] = {key: {} for key in HEADER_KEYS}
    charts_by_level: dict[int, list[ChartBlock]] = {}

    for parsed in parsed_files:
        for key in HEADER_KEYS:
            header_values[key].update(dict.fromkeys(parsed.header_candidates[key]))
        for chart in parsed.charts:
            charts_by_level.setdefault(chart.level, []).append(chart)

    return CandidateCollection(
        header_candidates={
            key: tuple(values) for key, values in header_values.items()
        },
        charts_by_level={
            level: tuple(charts) for level, charts in charts_by_level.items()
        },
    )


def ordered_chart_levels(extra_levels: Iterable[int] = ()) -> tuple[int, ...]:
    return tuple(sorted(set(range(2, 8)).union(extra_levels)))


def _first_matching(
    values: tuple[str, ...],
    predicate: Callable[[str], bool],
) -> str:
    """返回首个满足条件候选项，全部不满足时回落到首个候选项."""
    for value in values:
        if predicate(value):
            return value
    return values[0] if values else ""


# 标题来源常含"谱面确认"，这类值一般不是真正的曲名
_TITLE_CONFIRM_MARKER = "谱面确认"
# artist 的 "default" 多为占位值
_ARTIST_PLACEHOLDER = "default"

_DEFAULT_PICKERS: dict[str, Callable[[tuple[str, ...]], str]] = {
    "title": lambda values: _first_matching(
        values, lambda value: _TITLE_CONFIRM_MARKER not in value
    ),
    "artist": lambda values: _first_matching(
        values, lambda value: value.strip().casefold() != _ARTIST_PLACEHOLDER
    ),
}


def select_header_default(key: str, values: tuple[str, ...]) -> str:
    picker = _DEFAULT_PICKERS.get(key)
    return (
        picker(values)
        if picker is not None
        else (values[0] if values else "")
    )
