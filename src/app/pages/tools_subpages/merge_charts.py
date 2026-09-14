from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QLabel,
    QListWidget,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..base_output_page import BaseOutputPage, _create_row
from src.core.chart_merge import ChartBlock, ParsedChartFile, collect_input_paths, compose_maidata, parse_chart_file
from src.core.tools import show_confirm_dialog, show_notify_dialog, validate_windows_filename
from ...widgets import (
    create_button,
    create_combo_box,
    create_directory_selection_row,
    create_label,
    create_line_edit,
    create_path_display,
    create_split_drop_line_edit,
    create_stated_button,
)
import i18n


I18N_PREFIX = "app.tools_subpages.merge_charts"
_HEADER_KEYS = ("title", "artist", "first", "des")
_LEVEL_NAMES = {
    2: "basic",
    3: "advanced",
    4: "expert",
    5: "master",
    6: "remaster",
    7: "utage",
}


def _t(key: str, **kwargs) -> str:
    return i18n.t(f"{I18N_PREFIX}.{key}", **kwargs)


class MergeChartsPage(BaseOutputPage):
    def setup_content(self) -> None:
        self.content_layout = QVBoxLayout(self.content_area)
        self.content_layout.setContentsMargins(10, 10, 10, 10)

        self._parsed_files: list[ParsedChartFile] = []
        self._selected_paths: list[Path] = []
        self._level_rows: dict[int, tuple[QComboBox, QLabel, QLabel, list[ChartBlock | None]]] = {}
        self._header_edits = {}

        self.content_layout.addWidget(create_label(_t("ui_input_divider"), bold=True))
        select_files_button = create_button(_t("ui_select_files_button"), width=150)
        select_dirs_button = create_button(_t("ui_select_dirs_button"), width=150)
        self._selection_summary = create_label(_t("ui_selection_empty"))
        self._selection_summary.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        self._selected_files_list = QListWidget()
        self._selected_files_list.setFixedHeight(70)
        self._selected_files_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.content_layout.addWidget(
            _create_row(select_files_button, select_dirs_button, self._selection_summary, add_stretch=True)
        )
        self.content_layout.addWidget(self._selected_files_list)

        select_files_button.clicked.connect(self._select_files)
        select_dirs_button.clicked.connect(self._select_directory)

        self.content_layout.addWidget(create_label(_t("ui_header_divider"), bold=True))
        for key in _HEADER_KEYS:
            label = create_label(_t(f"ui_{key}_label"))
            edit = create_split_drop_line_edit(length=360)
            edit.setPlaceholderText(_t("ui_value_placeholder"))
            self._header_edits[key] = edit
            self.content_layout.addWidget(_create_row(label, edit, add_stretch=True))

        self.content_layout.addWidget(create_label(_t("ui_chart_divider"), bold=True))
        self._chart_rows_widget = QWidget()
        self._chart_rows_layout = QVBoxLayout(self._chart_rows_widget)
        self._chart_rows_layout.setContentsMargins(0, 0, 0, 0)
        self._chart_scroll = QScrollArea()
        self._chart_scroll.setWidgetResizable(True)
        self._chart_scroll.setWidget(self._chart_rows_widget)
        self._chart_scroll.setMinimumHeight(150)
        self.content_layout.addWidget(self._chart_scroll, 1)
        self._create_level_rows(set())

        self.content_layout.addWidget(create_label(_t("ui_output_divider"), bold=True))
        self.output_dir_button, self.output_dir_display, _ = create_directory_selection_row(
            _t("ui_output_dir_button"), button_length=130
        )
        self.output_filename_edit = create_line_edit(default_text="maidata", length=180)
        self.output_suffix_label = create_label(".txt")
        self.output_path_display = create_path_display()
        self.export_button = create_stated_button(_t("ui_export_button"), isbig=True)
        self.content_layout.addWidget(
            _create_row(
                self.output_dir_button,
                self.output_dir_display,
                create_label(_t("ui_filename_label")),
                self.output_filename_edit,
                self.output_suffix_label,
                add_stretch=True,
            )
        )
        self.content_layout.addWidget(_create_row(create_label(_t("ui_full_path_label")), self.output_path_display, add_stretch=True))
        self.content_layout.addWidget(_create_row(self.export_button, add_stretch=True))

        self.output_dir_display.textChanged.connect(self._update_output_path)
        self.output_filename_edit.textChanged.connect(self._update_output_path)
        self.output_filename_edit.editingFinished.connect(self._normalize_filename)
        self.export_button.clicked.connect(self._export)
        self.content_layout.addStretch()

    def _select_files(self) -> None:
        self._clear_inputs()
        parent = self.window()
        paths, _ = QFileDialog.getOpenFileNames(
            parent,
            _t("dialog_select_files_title"),
            str(Path.cwd()),
            _t("dialog_txt_filter"),
        )
        if paths:
            self._load_inputs(paths)

    def _select_directory(self) -> None:
        self._clear_inputs()
        parent = self.window()
        dialog = QFileDialog(
            parent,
            _t("dialog_select_dir_title"),
            self.output_dir_display.text().strip() or str(Path.cwd()),
        )
        dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
        dialog.setFileMode(QFileDialog.FileMode.Directory)
        dialog.setOption(QFileDialog.Option.ShowDirsOnly, True)
        dialog.setViewMode(QFileDialog.ViewMode.Detail)
        for view in dialog.findChildren(QAbstractItemView):
            view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        if dialog.exec():
            paths = dialog.selectedFiles()
            if paths:
                self._load_inputs(paths)

    def _clear_inputs(self) -> None:
        self._selected_paths.clear()
        self._parsed_files.clear()
        self._selected_files_list.clear()
        self._create_level_rows(set())
        self._set_header_candidates({key: [] for key in _HEADER_KEYS})
        self._selection_summary.setText(_t("ui_selection_empty"))

    def _load_inputs(self, paths: list[str]) -> None:
        self._clear_inputs()
        collection = collect_input_paths(paths)
        ignored = list(collection.ignored)

        for path in collection.files:
            try:
                parsed = parse_chart_file(path)
            except UnicodeDecodeError:
                ignored.append((path, _t("ignore_invalid_encoding")))
                continue
            except OSError as exc:
                ignored.append((path, _t("ignore_read_failed", error=str(exc))))
                continue
            self._parsed_files.append(parsed)
            self._selected_paths.append(path)

        for path in self._selected_paths:
            self._selected_files_list.addItem(str(path))
        for path, reason in ignored:
            if reason in {"unresolved", "not_txt", "maidata_missing", "invalid_path"}:
                reason = _t(f"ignore_{reason}")
            self.output_widget.append_text(_t("notice_ignored", path=str(path), reason=reason))

        header_candidates = {key: [] for key in _HEADER_KEYS}
        charts_by_level: dict[int, list[ChartBlock]] = {}
        for parsed in self._parsed_files:
            for key in _HEADER_KEYS:
                for value in parsed.header_candidates[key]:
                    if value not in header_candidates[key]:
                        header_candidates[key].append(value)
            for chart in parsed.charts:
                charts_by_level.setdefault(chart.level, []).append(chart)

        self._set_header_candidates(header_candidates)
        self._create_level_rows(set(charts_by_level))
        self._populate_level_rows(charts_by_level)
        self._selection_summary.setText(
            _t("ui_selection_summary", selected=len(self._selected_paths), ignored=len(ignored))
        )

    def _set_header_candidates(self, candidates: dict[str, list[str]]) -> None:
        for key, edit in self._header_edits.items():
            values = candidates.get(key, [])
            edit.set_items(values)
            edit.setText(values[0] if values else "")

    def _create_level_rows(self, extra_levels: set[int]) -> None:
        while self._chart_rows_layout.count():
            item = self._chart_rows_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()

        self._level_rows.clear()
        levels = sorted(set(range(2, 8)) | {level for level in extra_levels if level not in range(2, 8)})
        for level in levels:
            level_text = f"{level} {_LEVEL_NAMES[level]}" if level in _LEVEL_NAMES else _t("level_unknown", level=level)
            level_label = create_label(level_text)
            level_label.setFixedWidth(95)
            combo = create_combo_box(length=300)
            combo.addItem(_t("ui_empty_option"))
            metadata = create_label(_t("ui_no_chart"))
            metadata.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            source_label = create_label("")
            source_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            candidates: list[ChartBlock | None] = [None]
            self._level_rows[level] = (combo, metadata, source_label, candidates)
            combo.currentIndexChanged.connect(lambda index, lv=level: self._on_chart_selected(lv, index))
            self._chart_rows_layout.addWidget(
                _create_row(level_label, combo, metadata, source_label, add_stretch=True)
            )

    def _populate_level_rows(self, charts_by_level: dict[int, list[ChartBlock]]) -> None:
        for level, (combo, _metadata, _source_label, candidates) in self._level_rows.items():
            charts = charts_by_level.get(level, [])
            candidates[:] = [None, *charts]
            combo.clear()
            combo.addItem(_t("ui_empty_option"))
            combo.addItems([str(chart.source_path) for chart in charts])
            combo.setCurrentIndex(1 if len(charts) == 1 else 0)
            self._on_chart_selected(level, combo.currentIndex())

    def _on_chart_selected(self, level: int, index: int) -> None:
        row = self._level_rows.get(level)
        if row is None:
            return
        _combo, metadata, source_label, candidates = row
        chart = candidates[index] if 0 <= index < len(candidates) else None
        if chart is None:
            metadata.setText(_t("ui_no_chart"))
            source_label.setText("")
            return
        metadata.setText(_t("ui_chart_metadata", level=chart.level_value or "-", designer=chart.designer or "-"))
        source_label.setText(str(chart.source_path))
        source_label.setToolTip(str(chart.source_path))

    def _update_output_path(self) -> None:
        directory = self.output_dir_display.text().strip()
        filename = self._filename_base()
        self.output_path_display.setText(str(Path(directory) / f"{filename}.txt") if directory and filename else "")

    def _filename_base(self) -> str:
        filename = self.output_filename_edit.text().strip()
        return filename[:-4] if filename.casefold().endswith(".txt") else filename

    def _normalize_filename(self) -> None:
        filename = self._filename_base()
        if filename != self.output_filename_edit.text():
            self.output_filename_edit.setText(filename)

    def _selected_charts(self) -> dict[int, ChartBlock | None]:
        return {
            level: candidates[combo.currentIndex()] if 0 <= combo.currentIndex() < len(candidates) else None
            for level, (combo, _metadata, _source_label, candidates) in self._level_rows.items()
        }

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
