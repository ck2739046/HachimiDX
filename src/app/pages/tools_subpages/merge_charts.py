from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Callable

import i18n
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.core.chart_merge import (
    ChartBlock,
    CollectedInput,
    HEADER_KEYS,
    LevelSelection,
    ParsedChartFile,
    aggregate_candidates,
    compose_maidata,
    import_chart_inputs,
    ordered_chart_levels,
    path_key,
)
from src.core.tools import (
    select_windows_files,
    select_windows_folders,
    show_confirm_dialog,
    show_notify_dialog,
    validate_windows_filename,
)
from ...widgets import (
    SplitDropLineEdit,
    create_button,
    create_combo_box,
    create_divider,
    create_help_icon,
    create_label,
    create_line_edit,
    create_path_display,
    create_split_drop_line_edit,
    create_stated_button,
    widget_utils,
)
from ...widgets.combo_box import ToolTipComboBox
from ..base_output_page import BaseOutputPage


I18N_PREFIX = "app.tools_subpages.merge_charts"

# 与 auto rechart 页 chart_lv 的英文标签保持一致
_LEVEL_NAMES = {
    2: "Basic",
    3: "Advanced",
    4: "Expert",
    5: "Master",
    6: "Re:Master",
    7: "Utage",
}
_DESIGNER_EDIT_WIDTH = 130
_LEVEL_EDIT_WIDTH = 50
_LEVEL_LABEL_WIDTH = 65
_HEADER_FIXED_WIDTHS = {"artist": 130, "first": 78, "des": 130}

_MARKER_ADDED = "[+]"
_MARKER_IGNORED = "[*]"
_MARKER_REMOVED = "[-]"
_TIMESTAMP_FORMAT = "%y.%m.%d %H:%M:%S"


def _t(key: str, **kwargs) -> str:
    return i18n.t(f"{I18N_PREFIX}.{key}", **kwargs)


@dataclass(slots=True)
class _LevelRow:
    combo_box: ToolTipComboBox
    designer_line_edit: QLineEdit
    level_line_edit: QLineEdit
    candidates: list[ChartBlock | None] = field(default_factory=lambda: [None])


@dataclass(frozen=True, slots=True)
class _RowState:
    source_key: str | None
    had_candidates: bool
    designer: str
    level_value: str


_EMPTY_ROW_STATE = _RowState(None, False, "", "")


def _chart_at(row: _LevelRow) -> ChartBlock | None:
    index = row.combo_box.currentIndex()
    return row.candidates[index] if 0 <= index < len(row.candidates) else None


def _row_state(row: _LevelRow) -> _RowState:
    chart = _chart_at(row)
    return _RowState(
        source_key=path_key(chart.source_path) if chart is not None else None,
        had_candidates=len(row.candidates) > 1,
        designer=row.designer_line_edit.text(),
        level_value=row.level_line_edit.text(),
    )


def _apply_chart_text(row: _LevelRow) -> None:
    chart = _chart_at(row)
    if chart is None:
        row.designer_line_edit.clear()
        row.level_line_edit.clear()
        return
    row.designer_line_edit.setText(chart.designer)
    row.level_line_edit.setText(chart.level_value)


class MergeChartsPage(BaseOutputPage):
    def setup_content(self) -> None:
        self.content_layout = QVBoxLayout(self.content_area)
        self.content_layout.setContentsMargins(10, 10, 10, 10)
        self.content_layout.setSpacing(10)

        self._parsed_files: list[ParsedChartFile] = []
        self._level_rows: dict[int, _LevelRow] = {}
        self._header_edits: dict[str, SplitDropLineEdit] = {}

        self._build_input_section()
        self._build_chart_section()
        self._build_header_section()
        self._build_output_section()

        self._sync_input_combo()
        self._refresh_candidates(preserve_headers=False)

    def _build_input_section(self) -> None:
        self.content_layout.addWidget(create_divider(_t("ui_select_file_divider")))

        select_files_button = create_button(_t("ui_select_files_button"), width=85)
        select_dirs_button = create_button(_t("ui_select_dirs_button"), width=103)
        input_help = create_help_icon(_t("ui_input_help"))
        self._input_combo = create_combo_box(show_tooltip=True)
        self._remove_input_button = create_button(_t("ui_remove_current_button"), width=100)
        self._clear_inputs_button = create_button(_t("ui_clear_all_button"), width=75)
        self.create_row(
            select_files_button,
            select_dirs_button,
            input_help,
            self._input_combo,
            self._remove_input_button,
            self._clear_inputs_button,
        )

        select_files_button.clicked.connect(self._select_files)
        select_dirs_button.clicked.connect(self._select_directories)
        self._remove_input_button.clicked.connect(self._remove_current_input)
        self._clear_inputs_button.clicked.connect(self._clear_inputs)

    def _build_chart_section(self) -> None:
        self.content_layout.addWidget(create_divider(_t("ui_chart_divider")))
        self._chart_rows_widget = QWidget()
        self._chart_rows_layout = QGridLayout(self._chart_rows_widget)
        self._chart_rows_layout.setContentsMargins(0, 0, 0, 0)
        self._chart_rows_layout.setHorizontalSpacing(4)
        self._chart_rows_layout.setVerticalSpacing(5)
        self._chart_scroll = QScrollArea()
        self._chart_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._chart_scroll.setWidgetResizable(True)
        self._chart_scroll.setWidget(self._chart_rows_widget)
        self.content_layout.addWidget(self._chart_scroll, 1)

    def _build_header_section(self) -> None:
        self.content_layout.addWidget(create_divider(_t("ui_header_divider")))
        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(5)

        for key in HEADER_KEYS:
            label = create_label(_t(f"ui_{key}_label"))
            edit = create_split_drop_line_edit(length=_HEADER_FIXED_WIDTHS.get(key))
            self._header_edits[key] = edit
            header_row.addWidget(label)
            header_row.addWidget(edit, 1 if key == "title" else 0)

        self.content_layout.addLayout(header_row)

    def _build_output_section(self) -> None:
        self.output_dir_button = create_button(_t("ui_output_dir_button"), width=125)
        self.output_dir_display = create_path_display()
        self.output_filename_edit = create_line_edit(default_text="maidata", length=140)
        self.output_suffix_label = create_label(".txt   ")
        self.export_button = create_stated_button(_t("ui_export_button"), isbig=True)

        self.create_row(
            self.output_dir_button,
            self.output_dir_display,
            create_label(_t("ui_filename_label")),
            self.output_filename_edit,
            self.output_suffix_label,
            self.export_button,
        )

        self.output_dir_button.clicked.connect(self._select_output_directory)
        self.output_filename_edit.editingFinished.connect(self._normalize_filename)
        self.export_button.clicked.connect(self._export)

    def _pick_paths(
        self,
        picker: Callable[..., list[str]],
        title: str,
        **kwargs,
    ) -> list[str]:
        try:
            return picker(int(self.window().winId()), title, **kwargs)
        except OSError as exc:
            show_notify_dialog(
                _t("dialog_error_title"),
                _t("warning_dialog_failed", error=str(exc)),
            )
            return []

    def _select_files(self) -> None:
        self._add_inputs(
            self._pick_paths(
                select_windows_files,
                _t("dialog_select_files_title"),
                filter_name=_t("dialog_txt_filter"),
            )
        )

    def _select_directories(self) -> None:
        self._add_inputs(
            self._pick_paths(
                select_windows_folders,
                _t("dialog_select_dir_title"),
            )
        )

    def _select_output_directory(self) -> None:
        paths = self._pick_paths(
            select_windows_folders,
            _t("ui_output_dir_button"),
            multiple=False,
        )
        if paths:
            self.output_dir_display.setText(str(Path(paths[0]).resolve()))

    @staticmethod
    def _path_label(path: Path) -> str:
        return f"{path.parent.name}\\{path.name}"

    @staticmethod
    def _timestamp() -> str:
        return datetime.now().strftime(_TIMESTAMP_FORMAT)

    def _log(self, marker: str | None, key: str, **kwargs) -> None:
        prefix = f"[{self._timestamp()}]"
        if marker is not None:
            prefix = f"{prefix} {marker}"
        self.output_widget.append_text(f"{prefix} {_t(key, **kwargs)}")

    def _log_input_results(self, results: list[CollectedInput]) -> None:
        for entry in results:
            if entry.reason is None:
                self._log(
                    _MARKER_ADDED,
                    "log_added",
                    path=str(entry.resolved_path),
                )
                continue
            self._log(
                _MARKER_IGNORED,
                "log_ignored",
                path=str(entry.resolved_path),
                reason=_t(f"ignore_{entry.reason}", error=entry.detail),
            )

    def _current_input_key(self) -> str | None:
        index = self._input_combo.currentIndex()
        if 0 <= index < len(self._parsed_files):
            return path_key(self._parsed_files[index].path)
        return None

    def _add_inputs(self, paths: list[str]) -> None:
        if not paths:
            return

        current_input_key = self._current_input_key()
        had_files = bool(self._parsed_files)
        existing_keys = frozenset(
            path_key(parsed.path) for parsed in self._parsed_files
        )

        loaded, results = import_chart_inputs(paths, existing_keys)
        self._parsed_files.extend(loaded)
        self._log_input_results(results)
        self._sync_input_combo(current_input_key)
        self._refresh_candidates(preserve_headers=had_files)

    def _clear_inputs(self) -> None:
        had_files = bool(self._parsed_files)
        self._parsed_files.clear()
        self._sync_input_combo()
        self._refresh_candidates(preserve_headers=False)
        if had_files:
            self._log(_MARKER_REMOVED, "log_cleared")

    def _remove_current_input(self) -> None:
        index = self._input_combo.currentIndex()
        if not 0 <= index < len(self._parsed_files):
            return

        removed = self._parsed_files.pop(index)
        self._log(_MARKER_REMOVED, "log_removed", path=str(removed.path))
        self._sync_input_combo(selected_index=min(index, len(self._parsed_files) - 1))
        self._refresh_candidates(preserve_headers=True)

    def _sync_input_combo(
        self,
        selected_key: str | None = None,
        selected_index: int | None = None,
    ) -> None:
        self._input_combo.clear()
        has_files = bool(self._parsed_files)
        if has_files:
            self._input_combo.addItems(
                [self._path_label(parsed.path) for parsed in self._parsed_files]
            )
            self._input_combo.set_item_tooltips(
                [str(parsed.path) for parsed in self._parsed_files]
            )
            if selected_key is not None:
                for index, parsed in enumerate(self._parsed_files):
                    if path_key(parsed.path) == selected_key:
                        self._input_combo.setCurrentIndex(index)
                        break
            elif selected_index is not None and selected_index >= 0:
                self._input_combo.setCurrentIndex(selected_index)
            self._input_combo.setEnabled(True)
        else:
            self._input_combo.addItem(_t("ui_no_input_option"))
            self._input_combo.set_item_tooltips([None])
            self._input_combo.setEnabled(False)
        self._remove_input_button.setEnabled(has_files)
        self._clear_inputs_button.setEnabled(has_files)

    def _refresh_candidates(self, *, preserve_headers: bool) -> None:
        candidates = aggregate_candidates(self._parsed_files)
        self._set_header_candidates(
            candidates.header_candidates,
            preserve_text=preserve_headers,
        )
        self._sync_level_rows(candidates.charts_by_level)

    def _set_header_candidates(
        self,
        candidates: dict[str, tuple[str, ...]],
        *,
        preserve_text: bool = False,
    ) -> None:
        for key, edit in self._header_edits.items():
            values = candidates.get(key, [])
            edit.set_items(values)
            if not preserve_text:
                edit.setText(values[0] if values else "")

    def _sync_level_rows(self, charts_by_level: dict[int, tuple[ChartBlock, ...]]) -> None:
        previous = {
            level: _row_state(row) for level, row in self._level_rows.items()
        }
        levels = ordered_chart_levels(charts_by_level)
        if tuple(self._level_rows) != levels:
            self._rebuild_level_rows(levels)

        for level, row in self._level_rows.items():
            self._populate_level_row(
                row,
                charts_by_level.get(level, ()),
                previous.get(level, _EMPTY_ROW_STATE),
            )

    def _rebuild_level_rows(self, levels: tuple[int, ...]) -> None:
        widget_utils.clear_layout(self._chart_rows_layout)
        self._level_rows.clear()

        for row, level in enumerate(levels):
            level_text = _LEVEL_NAMES.get(level, _t("level_unknown", level=level))
            level_label = create_label(level_text)
            level_label.setFixedWidth(_LEVEL_LABEL_WIDTH)
            combo = create_combo_box(show_tooltip=True)
            designer_edit = create_line_edit(length=_DESIGNER_EDIT_WIDTH)
            level_edit = create_line_edit(length=_LEVEL_EDIT_WIDTH)
            level_row = _LevelRow(
                combo_box=combo,
                designer_line_edit=designer_edit,
                level_line_edit=level_edit,
            )
            self._level_rows[level] = level_row
            combo.currentIndexChanged.connect(partial(self._on_chart_selected, level))

            self._chart_rows_layout.addWidget(level_label, row, 0)
            self._chart_rows_layout.addWidget(combo, row, 1)
            self._chart_rows_layout.addWidget(
                create_label(" " + _t("ui_designer_label", level=level)),
                row,
                2,
            )
            self._chart_rows_layout.addWidget(designer_edit, row, 3)
            self._chart_rows_layout.addWidget(
                create_label(" " + _t("ui_level_label", level=level)),
                row,
                4,
            )
            self._chart_rows_layout.addWidget(level_edit, row, 5)
        self._chart_rows_layout.setColumnStretch(1, 1)
        self._chart_rows_layout.setRowStretch(len(levels), 1)

    def _sync_level_combo(
        self,
        row: _LevelRow,
        charts: tuple[ChartBlock, ...],
        selected_index: int,
    ) -> None:
        """刷新候选项并设置选中下标；下标 0 固定为空选项."""
        row.candidates[:] = [None, *charts]
        row.combo_box.blockSignals(True)
        try:
            row.combo_box.clear()
            row.combo_box.addItem(_t("ui_empty_option"))
            row.combo_box.addItems(
                [self._path_label(chart.source_path) for chart in charts]
            )
            row.combo_box.set_item_tooltips(
                [None, *(str(chart.source_path) for chart in charts)]
            )
            row.combo_box.setCurrentIndex(selected_index)
        finally:
            row.combo_box.blockSignals(False)

    def _populate_level_row(
        self,
        row: _LevelRow,
        charts: tuple[ChartBlock, ...],
        previous: _RowState,
    ) -> None:
        selected_index = 0
        if previous.source_key is not None:
            for index, chart in enumerate(charts, start=1):
                if path_key(chart.source_path) == previous.source_key:
                    selected_index = index
                    break
        elif not previous.had_candidates and len(charts) == 1:
            selected_index = 1

        self._sync_level_combo(row, charts, selected_index)
        _apply_chart_text(row)
        if selected_index > 0 and previous.source_key is not None:
            row.designer_line_edit.setText(previous.designer)
            row.level_line_edit.setText(previous.level_value)

    def _on_chart_selected(self, level: int, _index: int) -> None:
        row = self._level_rows.get(level)
        if row is not None:
            _apply_chart_text(row)

    def _filename_base(self) -> str:
        filename = self.output_filename_edit.text().strip()
        return filename[:-4] if filename.casefold().endswith(".txt") else filename

    def _normalize_filename(self) -> None:
        filename = self._filename_base()
        if filename != self.output_filename_edit.text():
            self.output_filename_edit.setText(filename)

    def _selections(self) -> dict[int, LevelSelection]:
        selections: dict[int, LevelSelection] = {}
        for level, row in self._level_rows.items():
            chart = _chart_at(row)
            if chart is None:
                continue
            selections[level] = LevelSelection(
                chart=chart,
                designer=row.designer_line_edit.text(),
                level_value=row.level_line_edit.text(),
            )
        return selections

    def _export(self) -> None:
        directory = self.output_dir_display.text().strip()
        filename = self._filename_base()
        if not directory:
            show_notify_dialog(
                _t("dialog_error_title"),
                _t("warning_output_dir_required"),
            )
            return
        if not Path(directory).is_dir():
            show_notify_dialog(
                _t("dialog_error_title"),
                _t("warning_output_dir_invalid"),
            )
            return
        validation = validate_windows_filename(filename)
        if not validation.is_ok:
            show_notify_dialog(
                _t("dialog_error_title"),
                _t("warning_filename_invalid", error=validation.error_msg),
            )
            return
        if not self._parsed_files:
            show_notify_dialog(_t("dialog_error_title"), _t("warning_no_input"))
            return

        output_path = Path(directory) / f"{filename}.txt"
        if output_path.exists() and not show_confirm_dialog(
            _t("dialog_overwrite_title"),
            _t("warning_overwrite", path=str(output_path)),
        ):
            return

        headers = {key: edit.text() for key, edit in self._header_edits.items()}
        try:
            compose_maidata(
                output_path,
                headers,
                self._selections(),
            )
        except OSError as exc:
            show_notify_dialog(
                _t("dialog_error_title"),
                _t("warning_export_failed", error=str(exc)),
            )
            return
        self._log(None, "notice_export_success", path=str(output_path))
