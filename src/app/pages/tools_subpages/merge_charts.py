from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..base_output_page import BaseOutputPage, _create_row
from src.core.chart_merge import ChartBlock, ParsedChartFile, collect_input_paths, compose_maidata, parse_chart_file
from src.core.tools import (
    select_windows_files,
    select_windows_folders,
    show_confirm_dialog,
    show_notify_dialog,
    validate_windows_filename,
)
from ...widgets import (
    create_button,
    create_combo_box,
    create_divider,
    create_help_icon,
    create_label,
    create_line_edit,
    create_path_display,
    create_split_drop_line_edit,
    create_stated_button,
)
import i18n


I18N_PREFIX = "app.tools_subpages.merge_charts"
_HEADER_KEYS = ("title", "artist", "first", "des")
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


def _t(key: str, **kwargs) -> str:
    return i18n.t(f"{I18N_PREFIX}.{key}", **kwargs)


class MergeChartsPage(BaseOutputPage):
    def setup_content(self) -> None:
        self.content_layout = QVBoxLayout(self.content_area)
        self.content_layout.setContentsMargins(10, 10, 10, 10)
        self.content_layout.setSpacing(10)

        self._parsed_files: list[ParsedChartFile] = []
        self._level_rows: dict[int, tuple[QComboBox, QWidget, QWidget, list[ChartBlock | None]]] = {}
        self._header_edits = {}

        select_files_button = create_button(_t("ui_select_files_button"), width=85)
        select_dirs_button = create_button(_t("ui_select_dirs_button"), width=103)
        self._input_combo = create_combo_box(show_tooltip=True)
        self._remove_input_button = create_button(_t("ui_remove_current_button"), width=100)
        self._clear_inputs_button = create_button(_t("ui_clear_all_button"), width=75)
        self.content_layout.addWidget(create_divider(_t("ui_select_file_divider")))
        self.content_layout.addWidget(
            _create_row(
                select_files_button,
                select_dirs_button,
                create_help_icon(_t("ui_input_help")),
                self._input_combo,
                self._remove_input_button,
                self._clear_inputs_button,
            )
        )

        select_files_button.clicked.connect(self._select_files)
        select_dirs_button.clicked.connect(self._select_directories)
        self._remove_input_button.clicked.connect(self._remove_current_input)
        self._clear_inputs_button.clicked.connect(self._clear_inputs)

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

        self.content_layout.addWidget(create_divider(_t("ui_header_divider")))
        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(5)
        for key in _HEADER_KEYS:
            label = create_label(_t(f"ui_{key}_label"))
            edit = create_split_drop_line_edit(length=_HEADER_FIXED_WIDTHS.get(key))
            self._header_edits[key] = edit
            header_row.addWidget(label)
            # 仅 title 动态占满，其余保持固定宽度
            header_row.addWidget(edit, 1 if key == "title" else 0)
        self.content_layout.addLayout(header_row)

        self.output_dir_button = create_button(_t("ui_output_dir_button"), width=125)
        self.output_dir_display = create_path_display()
        self.output_filename_edit = create_line_edit(default_text="maidata", length=140)
        self.output_suffix_label = create_label(".txt   ") # 与输出按钮保持间距
        self.export_button = create_stated_button(_t("ui_export_button"), isbig=True)
        self.content_layout.addWidget(
            _create_row(
            self.output_dir_button,
            self.output_dir_display,
                create_label(_t("ui_filename_label")),
                self.output_filename_edit,
                self.output_suffix_label,
                self.export_button,
            )
        )

        self.output_dir_button.clicked.connect(self._select_output_directory)
        self.output_filename_edit.editingFinished.connect(self._normalize_filename)
        self.export_button.clicked.connect(self._export)
        self._create_level_rows(set())
        self._sync_input_combo()

    def _select_files(self) -> None:
        try:
            paths = select_windows_files(
                int(self.window().winId()),
                _t("dialog_select_files_title"),
                filter_name=_t("dialog_txt_filter"),
            )
        except OSError as exc:
            show_notify_dialog(_t("dialog_error_title"), _t("warning_dialog_failed", error=str(exc)))
            return
        self._add_inputs(paths)

    def _select_directories(self) -> None:
        try:
            paths = select_windows_folders(
                int(self.window().winId()),
                _t("dialog_select_dir_title"),
            )
        except OSError as exc:
            show_notify_dialog(_t("dialog_error_title"), _t("warning_dialog_failed", error=str(exc)))
            return
        self._add_inputs(paths)

    def _select_output_directory(self) -> None:
        try:
            paths = select_windows_folders(
                int(self.window().winId()),
                _t("ui_output_dir_button"),
                multiple=False,
            )
        except OSError as exc:
            show_notify_dialog(_t("dialog_error_title"), _t("warning_dialog_failed", error=str(exc)))
            return
        if paths:
            self.output_dir_display.setText(str(Path(paths[0]).resolve()))

    @staticmethod
    def _path_key(path: Path) -> str:
        return str(path.resolve()).casefold()

    @staticmethod
    def _path_label(path: Path) -> str:
        return f"{path.parent.name}\\{path.name}"

    def _capture_level_state(self) -> dict[int, tuple[str | None, bool, str, str]]:
        state: dict[int, tuple[str | None, bool, str, str]] = {}
        for level, (combo, designer_edit, level_edit, candidates) in self._level_rows.items():
            index = combo.currentIndex()
            chart = candidates[index] if 0 <= index < len(candidates) else None
            state[level] = (
                self._path_key(chart.source_path) if chart is not None else None,
                len(candidates) > 1,
                designer_edit.text(),
                level_edit.text(),
            )
        return state

    def _current_input_key(self) -> str | None:
        index = self._input_combo.currentIndex()
        if 0 <= index < len(self._parsed_files):
            return self._path_key(self._parsed_files[index].path)
        return None

    def _add_inputs(self, paths: list[str]) -> None:
        if not paths:
            return
        previous_level_state = self._capture_level_state()
        current_input_key = self._current_input_key()
        had_files = bool(self._parsed_files)
        existing = {self._path_key(parsed.path) for parsed in self._parsed_files}
        collection = collect_input_paths(paths)
        ignored = list(collection.ignored)

        for path in collection.files:
            key = self._path_key(path)
            if key in existing:
                continue
            try:
                parsed = parse_chart_file(path)
            except UnicodeDecodeError:
                ignored.append((path, _t("ignore_invalid_encoding")))
                continue
            except OSError as exc:
                ignored.append((path, _t("ignore_read_failed", error=str(exc))))
                continue
            self._parsed_files.append(parsed)
            existing.add(key)

        self._write_ignored(ignored)
        self._sync_input_combo(current_input_key)
        self._refresh_candidates(
            preserve_headers=had_files,
            previous_level_state=previous_level_state,
        )

    def _clear_inputs(self) -> None:
        self._parsed_files.clear()
        self._sync_input_combo()
        self._set_header_candidates({key: [] for key in _HEADER_KEYS})
        self._create_level_rows(set())

    def _remove_current_input(self) -> None:
        index = self._input_combo.currentIndex()
        if not 0 <= index < len(self._parsed_files):
            return
        previous_level_state = self._capture_level_state()
        self._parsed_files.pop(index)
        self._sync_input_combo(selected_index=min(index, len(self._parsed_files) - 1))
        self._refresh_candidates(
            preserve_headers=True,
            previous_level_state=previous_level_state,
        )

    def _write_ignored(self, ignored: list[tuple[Path, str]]) -> None:
        for path, reason in ignored:
            if reason in {"unresolved", "not_txt", "maidata_missing", "invalid_path"}:
                reason = _t(f"ignore_{reason}")
            self.output_widget.append_text(_t("notice_ignored", path=str(path), reason=reason))

    def _sync_input_combo(
        self,
        selected_key: str | None = None,
        selected_index: int | None = None,
    ) -> None:
        self._input_combo.clear()
        if self._parsed_files:
            self._input_combo.addItems([self._path_label(parsed.path) for parsed in self._parsed_files])
            self._input_combo.set_item_tooltips([str(parsed.path) for parsed in self._parsed_files])
            if selected_key is not None:
                for index, parsed in enumerate(self._parsed_files):
                    if self._path_key(parsed.path) == selected_key:
                        self._input_combo.setCurrentIndex(index)
                        break
            elif selected_index is not None and selected_index >= 0:
                self._input_combo.setCurrentIndex(selected_index)
            self._input_combo.setEnabled(True)
        else:
            self._input_combo.addItem(_t("ui_no_input_option"))
            self._input_combo.set_item_tooltips([None])
            self._input_combo.setEnabled(False)
        enabled = bool(self._parsed_files)
        self._remove_input_button.setEnabled(enabled)
        self._clear_inputs_button.setEnabled(enabled)

    def _refresh_candidates(
        self,
        *,
        preserve_headers: bool,
        previous_level_state: dict[int, tuple[str | None, bool, str, str]],
    ) -> None:
        header_candidates = {key: [] for key in _HEADER_KEYS}
        charts_by_level: dict[int, list[ChartBlock]] = {}
        for parsed in self._parsed_files:
            for key in _HEADER_KEYS:
                for value in parsed.header_candidates[key]:
                    if value not in header_candidates[key]:
                        header_candidates[key].append(value)
            for chart in parsed.charts:
                charts_by_level.setdefault(chart.level, []).append(chart)

        self._set_header_candidates(header_candidates, preserve_text=preserve_headers)
        self._create_level_rows(set(charts_by_level))
        self._populate_level_rows(charts_by_level, previous_level_state)

    def _set_header_candidates(
        self,
        candidates: dict[str, list[str]],
        *,
        preserve_text: bool = False,
    ) -> None:
        for key, edit in self._header_edits.items():
            values = candidates.get(key, [])
            edit.set_items(values)
            if not preserve_text:
                edit.setText(values[0] if values else "")

    def _create_level_rows(self, extra_levels: set[int]) -> None:
        while self._chart_rows_layout.count():
            item = self._chart_rows_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()

        self._level_rows.clear()
        levels = sorted(set(range(2, 8)) | {level for level in extra_levels if level not in range(2, 8)})

        for row, level in enumerate(levels):
            level_text = _LEVEL_NAMES.get(level, f"Level {level}")
            level_label = create_label(level_text)
            level_label.setFixedWidth(_LEVEL_LABEL_WIDTH)
            combo = create_combo_box(show_tooltip=True)
            combo.addItem(_t("ui_empty_option"))
            designer_edit = create_line_edit(length=_DESIGNER_EDIT_WIDTH)
            level_edit = create_line_edit(length=_LEVEL_EDIT_WIDTH)
            candidates: list[ChartBlock | None] = [None]
            self._level_rows[level] = (combo, designer_edit, level_edit, candidates)
            combo.currentIndexChanged.connect(lambda index, lv=level: self._on_chart_selected(lv, index))
            self._chart_rows_layout.addWidget(level_label, row, 0)
            self._chart_rows_layout.addWidget(combo, row, 1)
            self._chart_rows_layout.addWidget(create_label(_t("ui_designer_label", level=level)), row, 2)
            self._chart_rows_layout.addWidget(designer_edit, row, 3)
            self._chart_rows_layout.addWidget(create_label(_t("ui_level_label", level=level)), row, 4)
            self._chart_rows_layout.addWidget(level_edit, row, 5)
        self._chart_rows_layout.setColumnStretch(1, 1)
        self._chart_rows_layout.setRowStretch(len(levels), 1)

    def _populate_level_rows(
        self,
        charts_by_level: dict[int, list[ChartBlock]],
        previous_level_state: dict[int, tuple[str | None, bool, str, str]],
    ) -> None:
        for level, (combo, designer_edit, level_edit, candidates) in self._level_rows.items():
            charts = charts_by_level.get(level, [])
            candidates[:] = [None, *charts]
            combo.clear()
            combo.addItem(_t("ui_empty_option"))
            combo.addItems([self._path_label(chart.source_path) for chart in charts])
            combo.set_item_tooltips([None, *[str(chart.source_path) for chart in charts]])

            previous_path, previously_had_candidates, previous_designer, previous_level = previous_level_state.get(
                level, (None, False, "", "")
            )
            selected_index = 0
            if previous_path is not None:
                for index, chart in enumerate(charts, start=1):
                    if self._path_key(chart.source_path) == previous_path:
                        selected_index = index
                        break
            elif not previously_had_candidates and len(charts) == 1:
                selected_index = 1
            combo.setCurrentIndex(selected_index)
            self._on_chart_selected(level, combo.currentIndex())
            if selected_index > 0 and previous_path is not None:
                designer_edit.setText(previous_designer)
                level_edit.setText(previous_level)

    def _on_chart_selected(self, level: int, index: int) -> None:
        row = self._level_rows.get(level)
        if row is None:
            return
        _combo, designer_edit, level_edit, candidates = row
        chart = candidates[index] if 0 <= index < len(candidates) else None
        if chart is None:
            designer_edit.clear()
            level_edit.clear()
            return
        designer_edit.setText(chart.designer)
        level_edit.setText(chart.level_value)

    def _filename_base(self) -> str:
        filename = self.output_filename_edit.text().strip()
        return filename[:-4] if filename.casefold().endswith(".txt") else filename

    def _normalize_filename(self) -> None:
        filename = self._filename_base()
        if filename != self.output_filename_edit.text():
            self.output_filename_edit.setText(filename)

    def _selected_charts(self) -> dict[int, ChartBlock | None]:
        selected: dict[int, ChartBlock | None] = {}
        for level, (combo, designer_edit, level_edit, candidates) in self._level_rows.items():
            index = combo.currentIndex()
            chart = candidates[index] if 0 <= index < len(candidates) else None
            selected[level] = replace(
                chart,
                designer=designer_edit.text(),
                level_value=level_edit.text(),
            ) if chart is not None else None
        return selected

    def _export(self) -> None:
        directory = self.output_dir_display.text().strip()
        filename = self._filename_base()
        if not directory:
            show_notify_dialog(_t("dialog_error_title"), _t("warning_output_dir_required"))
            return
        if not Path(directory).is_dir():
            show_notify_dialog(_t("dialog_error_title"), _t("warning_output_dir_invalid"))
            return
        validation = validate_windows_filename(filename)
        if not validation.is_ok:
            show_notify_dialog(_t("dialog_error_title"), _t("warning_filename_invalid", error=validation.error_msg))
            return
        if not self._parsed_files:
            show_notify_dialog(_t("dialog_error_title"), _t("warning_no_input"))
            return

        output_path = Path(directory) / f"{filename}.txt"
        if output_path.exists() and not show_confirm_dialog(
            _t("dialog_overwrite_title"), _t("warning_overwrite", path=str(output_path))
        ):
            return

        headers = {key: edit.text() for key, edit in self._header_edits.items()}
        try:
            compose_maidata(output_path, headers, self._selected_charts())
        except OSError as exc:
            show_notify_dialog(_t("dialog_error_title"), _t("warning_export_failed", error=str(exc)))
            return
        self.output_widget.append_text(_t("notice_export_success", path=str(output_path)))
