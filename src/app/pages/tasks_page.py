from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Iterable, Optional, Tuple

import i18n
from PyQt6.QtCore import Qt, QTimer, qInstallMessageHandler, QtMsgType
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from src.services import TaskInfo, TaskStatus, task_scheduler_api

from .base_output_page import BaseOutputPage
from ..ui_style import UI_Style
from ..widgets import *



class TasksPage(BaseOutputPage):
    def __init__(self, parent: Optional[QWidget] = None):
        self._auto_rechart_scroll: Optional[QScrollArea] = None
        self._media_scroll: Optional[QScrollArea] = None
        self._auto_rechart_list_layout: Optional[QVBoxLayout] = None
        self._media_list_layout: Optional[QVBoxLayout] = None
        self._last_by_id: Dict[str, Tuple[Any, ...]] = {}

        # 安装消息处理器以过滤 QFont::setPointSize 警告
        self._old_message_handler = qInstallMessageHandler(self._qt_message_filter)

        super().__init__(parent)

        task_scheduler_api.get_signals().task_list_changed.connect(self._on_task_list_changed)



    def setup_content(self) -> None:

        # 总体是水平布局，左右两栏
        self.content_layout = QHBoxLayout(self.content_area)
        self.content_layout.setContentsMargins(0, 10, 0, 10)
        self.content_layout.setSpacing(UI_Style.widget_spacing)

        # 需要用到的公共变量
        self._auto_rechart_scroll = None
        self._auto_rechart_list_layout = None
        self._media_scroll = None
        self._media_list_layout = None

        auto_rechart_panel, self._auto_rechart_scroll, self._auto_rechart_list_layout = self._create_queue_panel("Auto Rechart")
        media_panel, self._media_scroll, self._media_list_layout = self._create_queue_panel("Media")

        self.content_layout.addWidget(auto_rechart_panel)
        self.content_layout.addWidget(media_panel)





    # -------------------
    # UI builders
    # -------------------

    def _create_queue_panel(self, title: str) -> tuple[QWidget, QScrollArea, QVBoxLayout]:
        
        panel = QWidget()
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(UI_Style.widget_spacing)

        header = create_label(title, font_size = UI_Style.default_text_size + 3, bold = True)
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        panel_layout.addWidget(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        #scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        scroll.setStyleSheet(
            f"""
            QScrollBar:vertical {{
                background-color: {UI_Style.COLORS['bg']};
                width: 12px;
                border: none;
            }}
            QScrollBar::handle:vertical {{
                background-color: {UI_Style.COLORS['text_secondary']};
                border-radius: 6px;
                min-height: 20px;
            }}
            QScrollBar::handle:vertical:hover {{
                background-color: {UI_Style.COLORS['accent']};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: none;
            }}

            QScrollBar:horizontal {{
                background-color: {UI_Style.COLORS['bg']};
                height: 12px;
                border: none;
            }}
            QScrollBar::handle:horizontal {{
                background-color: {UI_Style.COLORS['text_secondary']};
                border-radius: 6px;
                min-width: 20px;
            }}
            QScrollBar::handle:horizontal:hover {{
                background-color: {UI_Style.COLORS['accent']};
            }}
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
                width: 0px;
            }}
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
                background: none;
            }}
            """
        )

        # 一个列的内部的纵向卡片堆叠
        inner = QWidget()
        inner_layout = QVBoxLayout(inner)
        inner_layout.setContentsMargins(4, 4, 4, 4)
        inner_layout.setSpacing(4)

        scroll.setWidget(inner)
        panel_layout.addWidget(scroll)

        return panel, scroll, inner_layout



    def _create_task_card(self, task: TaskInfo) -> QWidget:

        task_bg = self._get_task_bg_color(task.status)

        card = QFrame()
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        card.setStyleSheet(
            f"""
            QFrame {{
                background-color: {task_bg};
                color: {UI_Style.COLORS['text_primary']};
                border-radius: 16px;
            }}
            """
        )

        # 设置 tooltip 显示任务状态
        status_text = self._get_status_display_text(task.status)
        tooltip_text = i18n.t("task_scheduler.ui_task_status_tooltip", status=status_text)
        card.setToolTip(tooltip_text)

        # 左右布局：左边显示task信息，右边显示取消按钮
        row = QHBoxLayout(card)
        row.setContentsMargins(20, 8, 10, 8)
        row.setSpacing(0)

        # 左边信息区：垂直布局分三行
        left = QWidget()
        left.setStyleSheet(f"background: {task_bg};")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)

        uuid_label = create_path_display(
            default_text = f"ID: {task.runner_id}",
            length = 160,
            font_color = UI_Style.COLORS['text_primary'],
            font_bold = True)

        name_label = create_path_display(
            default_text = task.task_name or " ",
            length = 200,
            font_color = UI_Style.COLORS['text_primary'])

        accepted_label = create_path_display(
            default_text = self._format_accepted(task.accepted_at),
            length = 160)

        left_layout.addWidget(uuid_label)
        left_layout.addWidget(name_label)
        left_layout.addWidget(accepted_label)

        cancel_btn = QToolButton()
        cancel_btn.setText("✕")
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)  # type: ignore[name-defined]
        cancel_btn.setStyleSheet(
            f"""
            QToolButton {{
                background: transparent;
                color: {UI_Style.COLORS['text_primary']};
                font-size: 20px;
                border: none;
            }}
            QToolButton:hover {{
                color: {UI_Style.COLORS['stop_hover']};
            }}
            """
        )
        cancel_btn.clicked.connect(lambda _=False, rid=task.runner_id: self._on_cancel_task(rid))

        row.addWidget(left, 1)
        row.addWidget(cancel_btn, 0)

        return card




    # -------------------
    # Data -> UI
    # -------------------

    def _on_task_list_changed(self, snapshot: object) -> None:
        if not isinstance(snapshot, dict):
            return

        auto_rechart_tasks = snapshot.get("auto_rechart") or []
        media_tasks = snapshot.get("media") or []

        if not isinstance(auto_rechart_tasks, list):
            auto_rechart_tasks = []
        if not isinstance(media_tasks, list):
            media_tasks = []

        self._log_task_list_diff(auto_rechart_tasks, media_tasks)
        self._render_columns(auto_rechart_tasks, media_tasks)



    def _render_columns(self, auto_rechart_tasks: list[TaskInfo], media_tasks: list[TaskInfo]) -> None:
        if self._auto_rechart_scroll is None or self._media_scroll is None:
            return
        if self._auto_rechart_list_layout is None or self._media_list_layout is None:
            return

        auto_rechart_scroll_value = self._auto_rechart_scroll.verticalScrollBar().value()
        media_scroll_value = self._media_scroll.verticalScrollBar().value()

        self._rebuild_list(self._auto_rechart_list_layout, auto_rechart_tasks)
        self._rebuild_list(self._media_list_layout, media_tasks)

        self._auto_rechart_scroll.verticalScrollBar().setValue(auto_rechart_scroll_value)
        self._media_scroll.verticalScrollBar().setValue(media_scroll_value)



    def _rebuild_list(self, layout: QVBoxLayout, tasks: list[TaskInfo]) -> None:
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        for task in self._sort_tasks_for_display(tasks):
            if task.status == TaskStatus.CANCELLED:
                continue
            layout.addWidget(self._create_task_card(task))
        
        layout.addStretch()



    def _sort_tasks_for_display(self, tasks: Iterable[TaskInfo]) -> list[TaskInfo]:
        visible = [t for t in tasks if t.status != TaskStatus.CANCELLED]

        running = [t for t in visible if t.status == TaskStatus.RUNNING]
        pending = [t for t in visible if t.status == TaskStatus.PENDING]
        ended = [t for t in visible if t.status == TaskStatus.ENDED]

        def key(t: TaskInfo) -> datetime:
            return t.accepted_at or datetime.min

        running.sort(key=key)             # 越早接受的任务在上面
        pending.sort(key=key)             # 越早接受的任务在上面
        ended.sort(key=key, reverse=True) # 越晚结束的任务在上面

        return running + pending + ended





    # -------------------
    # Diff logging
    # -------------------

    def _task_fingerprint(self, task: TaskInfo) -> Tuple[Any, ...]:
        accepted = task.accepted_at.isoformat(sep=" ", timespec="seconds") if task.accepted_at else None
        return (
            task.runner_id,
            getattr(task.task_type, "value", task.task_type),
            getattr(task.status, "value", task.status),
            task.task_name or "",
            accepted,
            task.error_msg or "",
        )



    def _log_task_list_diff(self, auto_rechart_tasks: list[TaskInfo], media_tasks: list[TaskInfo]) -> None:
        new_by_id: Dict[str, Tuple[Any, ...]] = {}
        for task in list(auto_rechart_tasks) + list(media_tasks):
            try:
                new_by_id[str(task.runner_id)] = self._task_fingerprint(task)
            except Exception:
                continue

        old_ids = set(self._last_by_id.keys())
        new_ids = set(new_by_id.keys())

        added = sorted(new_ids - old_ids)
        removed = sorted(old_ids - new_ids)

        for rid in added:
            fp = new_by_id[rid]
            self.output_widget.append_text(f"[+] {rid} type={fp[1]} status={fp[2]} name=\"{fp[3]}\" accepted_at={fp[4]}")

        for rid in removed:
            fp = self._last_by_id.get(rid)
            last_status = fp[2] if fp else "?"
            self.output_widget.append_text(f"[-] {rid} last_status={last_status}")

        for rid in sorted(new_ids & old_ids):
            old_fp = self._last_by_id.get(rid)
            new_fp = new_by_id.get(rid)
            if old_fp is None or new_fp is None or old_fp == new_fp:
                continue

            changes = []
            if old_fp[2] != new_fp[2]:
                changes.append(f"status {old_fp[2]} -> {new_fp[2]}")
            if old_fp[3] != new_fp[3]:
                changes.append(f"name \"{old_fp[3]}\" -> \"{new_fp[3]}\"")
            if old_fp[4] != new_fp[4]:
                changes.append(f"accepted_at {old_fp[4]} -> {new_fp[4]}")
            if old_fp[1] != new_fp[1]:
                changes.append(f"type {old_fp[1]} -> {new_fp[1]}")
            if old_fp[5] != new_fp[5] and new_fp[5]:
                changes.append(f"error {new_fp[5]}")

            if changes:
                self.output_widget.append_text(f"[*] {rid} " + "; ".join(changes))

        self._last_by_id = new_by_id




    # -------------------
    # Formatting / colors
    # -------------------

    def _format_accepted(self, accepted_at: Optional[datetime]) -> str:
        if accepted_at is None:
            return ""
        return accepted_at.isoformat(sep=" ", timespec="seconds")


    def _on_cancel_task(self, runner_id: str) -> None:
        """处理取消任务操作，并在失败时显示错误信息"""
        result = task_scheduler_api.cancel(runner_id)
        if not result.is_ok:
            self.output_widget.append_text(f"[Cancel Failed] {runner_id}: {result.error_msg}")


    def _get_task_bg_color(self, status: TaskStatus) -> str:
        if status == TaskStatus.PENDING:
            return UI_Style.COLORS["task_pending"]
        if status == TaskStatus.RUNNING:
            return UI_Style.COLORS["task_running"]
        return UI_Style.COLORS["task_ended"]


    def _get_status_display_text(self, status: TaskStatus) -> str:
        """获取任务状态的显示文本"""
        status_map = {
            TaskStatus.PENDING: i18n.t("task_scheduler.status_pending"),
            TaskStatus.RUNNING: i18n.t("task_scheduler.status_running"),
            TaskStatus.ENDED: i18n.t("task_scheduler.status_ended"),
        }
        return status_map.get(status, str(status))


    def _qt_message_filter(self, msg_type: QtMsgType, msg_log_context: object, msg: str) -> None:
        """Qt 消息过滤器，屏蔽 QFont::setPointSize 警告"""
        # 过滤掉 QFont::setPointSize 的警告
        # 不知道怎么回事，总是有这个警告出现，直接眼不见为净
        if "QFont::setPointSize" in msg:
            return

        # 其他消息正常处理
        if self._old_message_handler:
            self._old_message_handler(msg_type, msg_log_context, msg)
