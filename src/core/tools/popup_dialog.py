from __future__ import annotations

import ctypes
import os
import threading

import i18n
from PyQt6.QtCore import QEventLoop, QTimer, Qt
from PyQt6.QtGui import QCloseEvent, QGuiApplication, QTextOption
from PyQt6.QtWidgets import QApplication, QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QSizePolicy


class _PopupConfirmDialog(QDialog):
    def __init__(
        self,
        title: str,
        prompt_text: str,
        *,
        timeout_seconds: int = 30,
        mode: str = "confirm",
    ):
        super().__init__()

        self._prompt_text = prompt_text
        self._seconds_left = int(timeout_seconds)
        self._result_value = False
        self._completed = False
        self._mode = str(mode or "confirm").lower().strip()
        if self._mode not in ("confirm", "notify"):
            self._mode = "confirm"

        # 插入零宽空格，让 QLabel 自动换行
        self._display_text = "\u200B".join(list(self._prompt_text)).strip()

        self.setWindowTitle(title)
        self.setModal(False)
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        
        # --- Size Logic (User Req 3 & 4) ---
        W_SMALL = 330
        W_MEDIUM = 500
        W_LARGE = 700
        
        lines = self._prompt_text.splitlines()
        max_line_len = max(len(line) for line in lines) if lines else 0
            
        if max_line_len <= 50:
            target_width = W_SMALL
        elif max_line_len <= 100:
            target_width = W_MEDIUM
        else:
            target_width = W_LARGE

        # Constraints (User Req 3)
        try:
            screen = QGuiApplication.primaryScreen()
            if screen:
                geo = screen.availableGeometry()
                max_w = int(geo.width() * 0.9)
                max_h = int(geo.height() * 0.8)
                final_width = min(target_width, max_w)
                self.setFixedWidth(final_width)
                self.setMaximumHeight(max_h)
            else:
                self.setFixedWidth(target_width)
        except Exception:
            self.setFixedWidth(target_width)

        # Text area: QLabel (User Req 1, 2, 5)
        self._text_label = QLabel(self._display_text)
        self._text_label.setWordWrap(True)
        self._text_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._text_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
            | Qt.TextInteractionFlag.LinksAccessibleByMouse
        )

        # Countdown hint
        self._hint_label = QLabel()
        self._hint_label.setWordWrap(True)
        self._hint_label.setTextFormat(Qt.TextFormat.PlainText)
        self._hint_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)

        self._confirm_button: QPushButton | None = None
        self._cancel_button: QPushButton | None = None
        self._ok_button: QPushButton | None = None

        if self._mode == "confirm":
            self._confirm_button = QPushButton(i18n.t("popup_dialog.ui_confirm"))
            self._cancel_button = QPushButton(i18n.t("popup_dialog.ui_cancel"))
            btn_row.addWidget(self._confirm_button)
            btn_row.addSpacing(20)
            btn_row.addWidget(self._cancel_button)
        else:
            self._ok_button = QPushButton(i18n.t("popup_dialog.ui_ok"))
            btn_row.addWidget(self._ok_button)

        btn_row.addStretch(1)

        layout = QVBoxLayout()
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(0)
        layout.addWidget(self._text_label, 0)
        layout.addWidget(self._hint_label, 0)
        layout.addSpacing(15)
        layout.addLayout(btn_row)
        self.setLayout(layout)

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)

        if self._confirm_button is not None:
            self._confirm_button.clicked.connect(self._on_confirm)
        if self._cancel_button is not None:
            self._cancel_button.clicked.connect(self._on_cancel)
        if self._ok_button is not None:
            self._ok_button.clicked.connect(self._on_ok)
        self.rejected.connect(self._on_reject)

        self._refresh_text()
        self._timer.start()

        try:
            self.adjustSize()
        except Exception:
            pass

        self._center_on_primary_screen()

    def _center_on_primary_screen(self) -> None:
        try:
            screen = QGuiApplication.primaryScreen()
            if screen is None:
                return
            geo = screen.availableGeometry()
            self.move(
                int(geo.x() + (geo.width() - self.width()) / 2),
                int(geo.y() + (geo.height() - self.height()) / 2),
            )
        except Exception:
            return

    def _refresh_text(self) -> None:
        if self._mode == "notify":
            hint_key = "popup_dialog.ui_timeout_hint_close"
        else:
            hint_key = "popup_dialog.ui_timeout_hint"
        hint = i18n.t(hint_key, seconds=self._seconds_left)
        self._hint_label.setText(hint)

    def _finish(self, value: bool) -> None:
        if self._completed:
            return
        self._completed = True
        self._result_value = bool(value)

        try:
            self._timer.stop()
        except Exception:
            pass

        # IMPORTANT:
        # Use accept()/reject() instead of close().
        # close() may trigger rejected() and overwrite result_value.
        if self._result_value:
            try:
                self.accept()
            except Exception:
                try:
                    self.done(int(QDialog.DialogCode.Accepted))
                except Exception:
                    pass
        else:
            try:
                self.reject()
            except Exception:
                try:
                    self.done(int(QDialog.DialogCode.Rejected))
                except Exception:
                    pass

    def _on_confirm(self) -> None:
        self._finish(True)

    def _on_ok(self) -> None:
        self._finish(True)

    def _on_cancel(self) -> None:
        self._finish(False)

    def _on_reject(self) -> None:
        self._finish(False)

    def closeEvent(self, event: QCloseEvent) -> None:
        # User clicked the window close button.
        self._finish(False)
        try:
            event.accept()
        except Exception:
            pass

    def _tick(self) -> None:
        self._seconds_left -= 1
        if self._seconds_left < 0:
            self._on_reject()
            return
        self._refresh_text()

    def result_value(self) -> bool:
        return bool(self._result_value)


def show_confirm_dialog(title: str, prompt_text: str) -> bool:
    """A tiny blocking confirm dialog.

    Public API contract (keep it simple):
    - Accepts only (title: str, prompt_text: str)
    - Blocks until user decides or 30s timeout
    - Returns bool (Confirm=True, Cancel/timeout/error=False)

    Note: Windows-only behavior is acceptable for this tool.
    """

    # One giant try/except: anything goes wrong -> default cancel.
    try:
        if os.name == "nt":
            try:
                # Provide an independent taskbar icon group for this process.
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                    "hachimidx.tools.popup_dialog"
                )
            except Exception:
                pass

        # If caller calls this from a non-main thread, Qt will warn and behavior is undefined.
        # This tool keeps it simple: non-main-thread calls fail closed (return False).
        if threading.current_thread() is not threading.main_thread():
            return False

        app = QApplication.instance()
        created_app = False
        if app is None:
            created_app = True
            app = QApplication([])
            app.setQuitOnLastWindowClosed(True)

        dialog = _PopupConfirmDialog(title, prompt_text, timeout_seconds=30)
        event_loop = QEventLoop()
        dialog.finished.connect(lambda _code: event_loop.quit())
        dialog.show()
        event_loop.exec()

        if created_app:
            try:
                app.processEvents()
            except Exception:
                pass

        return dialog.result_value()

    except Exception:
        return False


def show_notify_dialog(title: str, prompt_text: str) -> bool:
    """A tiny blocking notify dialog.

    Public API contract (keep it simple):
    - Accepts only (title: str, prompt_text: str)
    - Blocks until user clicks OK or 30s timeout
    - Returns bool (OK=True, timeout/close/error=False)

    Note: Windows-only behavior is acceptable for this tool.
    """

    try:
        if os.name == "nt":
            try:
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                    "hachimidx.tools.popup_dialog"
                )
            except Exception:
                pass

        if threading.current_thread() is not threading.main_thread():
            return False

        app = QApplication.instance()
        created_app = False
        if app is None:
            created_app = True
            app = QApplication([])
            app.setQuitOnLastWindowClosed(True)

        dialog = _PopupConfirmDialog(
            title,
            prompt_text,
            timeout_seconds=30,
            mode="notify",
        )
        event_loop = QEventLoop()
        dialog.finished.connect(lambda _code: event_loop.quit())
        dialog.show()
        event_loop.exec()

        if created_app:
            try:
                app.processEvents()
            except Exception:
                pass

        return dialog.result_value()

    except Exception:
        return False



if __name__ == "__main__":

    # init i18n
    tool_dir = os.path.dirname(os.path.abspath(__file__))
    locales_dir = os.path.normpath(os.path.join(tool_dir, "../../resources/locales"))
    i18n.load_path.append(locales_dir)
    i18n.set("filename_format", "{locale}.yaml")
    # i18n.set("locale", "zh_CN")
    i18n.set("locale", "en_US")
    i18n.set("fallback", "en_US")

    # Multi-dialog manual test
    # Create 4 windows (2 confirm, 2 notify) with 1s interval.
    app = QApplication.instance() or QApplication([])

    test_configs = [
        ("Confirm 1", f"这是第一个 Confirm 弹窗\n2\n3\n4\n5{"5" * 1000}", "confirm"),
        ("Confirm 2", "这是第二个 Confirm 弹窗", "confirm"),
        ("Notify 1", "这是第一个 Notify 弹窗", "notify"),
        ("Notify 2", "这是第二个 Notify 弹窗", "notify"),
    ]

    results: dict[str, bool] = {}
    active_dialogs = []

    def spawn_next(index: int) -> None:
        if index >= len(test_configs):
            print("All test windows spawned.")
            return

        title, text, mode = test_configs[index]
        print(f"Spawning window {index+1}/{len(test_configs)}: {title} ({mode})")
        
        d = _PopupConfirmDialog(title, text, mode=mode)
        key = f"win_{index}_{mode}"
        d.finished.connect(
            lambda _code, d=d, key=key: results.__setitem__(key, d.result_value())
        )
        
        d.show()
        active_dialogs.append(d)

        # Schedule next spawn in 1 second
        QTimer.singleShot(1000, lambda: spawn_next(index + 1))

    # Start spawning
    spawn_next(0)

    app.exec()
    print("\nFinal Results Summary:")
    for k, v in results.items():
        print(f"  {k}: {v}")
