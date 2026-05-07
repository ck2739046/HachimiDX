from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

try:
    import win32gui
except ImportError:
    from win32 import win32gui

from PyQt6.QtCore import QUrl, pyqtSlot
from PyQt6.QtGui import QWindow
from PyQt6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from src.services import PathManage, stop_majdata
from ..ui_style import UI_Style
from ..widgets import *
import i18n
from src.core.tools import show_notify_dialog


_MAJDATA_PAGE_INSTANCE: Optional["MajdataPage"] = None



class MajdataPage(QWidget):

    def __init__(self, media_player=None, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        global _MAJDATA_PAGE_INSTANCE
        _MAJDATA_PAGE_INSTANCE = self

        self._media_player = media_player # QMediaPlayer 实例，用于控制视频播放
        self._majdataedit_placeholder: Optional[QWidget] = None

        self._control_txt: Path = None

        self._select_song_button = None
        self._selected_song_path: Optional[Path] = None
        self._maidata_combo = None
        self._track_combo = None
        self._video_combo = None
        self._play_video_checkbox = None

        # 存储 MajdataEdit 窗口句柄引用
        self._edit_hwnd: Optional[int] = None

        self._setup_ui()




    def _setup_ui(self) -> None:
    
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Top control bar
        top_control_bar = self._setup_control_bar()
        layout.addWidget(top_control_bar)

        # MajdataEdit Embed area
        self._majdataedit_placeholder = QWidget()
        self._majdataedit_placeholder.setStyleSheet(f"background-color: {UI_Style.COLORS['grey']};")
        embed_layout = QVBoxLayout(self._majdataedit_placeholder)
        embed_layout.setContentsMargins(0, 0, 0, 0)
        embed_layout.setSpacing(0)
        layout.addWidget(self._majdataedit_placeholder, 1)



    def set_edit_hwnd(self, hwnd: int) -> None:
        """Embed MajdataEdit by hwnd."""

        # while self._embed_layout.count():
        #     item = self._embed_layout.takeAt(0)
        #     w = item.widget()
        #     if w is not None:
        #         w.setParent(None)
        #         w.deleteLater()

        self._edit_hwnd = hwnd
        win = QWindow.fromWinId(hwnd)
        container = QWidget.createWindowContainer(win, self) # parent = self
        self._majdataedit_placeholder.layout().addWidget(container, 1)



    def _setup_control_bar(self) -> QWidget:

        self._control_txt = PathManage.MajdataEdit_CONTROL_TXT_PATH

        bar = QWidget()
        bar.setFixedHeight(50)
        bar.setStyleSheet(f"background-color: {UI_Style.COLORS['grey_hover']};")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Directory selection button (only button, no path display)
        self._select_song_button, _, _song_button_help = create_directory_selection_row(
            button_text = i18n.t("app.majdata_page.ui_select_song_button"),
            help_text=i18n.t("app.majdata_page.ui_song_help"),
            button_length=100,
            on_button_clicked_handler=self._on_song_directory_selected
        )
        layout.addWidget(self._select_song_button)
        layout.addWidget(_song_button_help)
        # Maidata choose
        self._maidata_combo = create_combo_box(120, show_tooltip = True)
        layout.addWidget(self._maidata_combo)
        # Track choose
        self._track_combo = create_combo_box(200, show_tooltip = True)
        layout.addWidget(self._track_combo)
        # Video choose
        self._video_combo = create_combo_box(230, show_tooltip = True)
        layout.addWidget(self._video_combo)
        # CheckBox: play video in MajdataView
        self._play_video_checkbox = create_check_box(True)
        layout.addWidget(self._play_video_checkbox)
        play_video_help = create_help_icon(i18n.t("app.majdata_page.ui_play_video_help"))
        layout.addWidget(play_video_help)
        # Load button
        load_btn = create_button("Load", 60)
        load_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {UI_Style.COLORS['grey']};
            }}
            QPushButton:hover {{
                background-color: {UI_Style.COLORS['grey_hover']};
            }}
        """)
        layout.addWidget(load_btn)

        # connect
        load_btn.clicked.connect(self.on_load_clicked)

        return bar


    def showEvent(self, event) -> None:
        """页面显示时启用 MajdataEdit 窗口输入."""
        super().showEvent(event)
        if self._edit_hwnd:
            win32gui.EnableWindow(self._edit_hwnd, True)


    def hideEvent(self, event) -> None:
        """页面隐藏时禁用 MajdataEdit 窗口输入，防止拦截其他页面的键盘输入."""
        super().hideEvent(event)
        if self._edit_hwnd:
            win32gui.EnableWindow(self._edit_hwnd, False)







    def _on_song_directory_selected(self, song_dir_path: str) -> None:
        """Scan and update maidata, track, video comboboxes when song directory is selected."""

        song_path = Path(song_dir_path)
        if not song_path.exists() or not song_path.is_dir():
            return

        # Update selected song path
        self._selected_song_path = song_path

        # Clear combobox
        self._maidata_combo.clear()
        self._track_combo.clear()
        self._video_combo.clear()

        # scan txt and add to maidata_combo
        txt_files = [f for f in os.listdir(song_path)
                     if f.lower().endswith(".txt")
                     and f.lower() not in ("track_result.txt", "detect_result.txt", "note_preprocess_result.txt")]
        if txt_files:
            txt_files = sorted(txt_files)
            self._maidata_combo.addItems(txt_files)
            # 如果有 maidata.txt，优先选择它
            if "maidata.txt" in txt_files:
                index = txt_files.index("maidata.txt")
                self._maidata_combo.setCurrentIndex(index)
            # 否则默认选择第一个
            else:
                self._maidata_combo.setCurrentIndex(0)

        # scan mp3/ogg and add to track_combo
        audio_files = [f for f in os.listdir(song_path)
                       if f.lower().endswith((".mp3", ".ogg"))]
        if audio_files:
            self._track_combo.addItems(sorted(audio_files))
            self._track_combo.setCurrentIndex(0)

        # scan mp4 and add to video_combo
        video_files = [f for f in os.listdir(song_path)
                       if f.lower().endswith(".mp4")]
        if video_files:
            video_files = sorted(video_files)
            self._video_combo.addItems(video_files)
            # 如果有 sync.mp4，优先选择它
            if "sync.mp4" in video_files:
                index = video_files.index("sync.mp4")
                self._video_combo.setCurrentIndex(index)
            # 否则默认选择第一个
            else:
                self._video_combo.setCurrentIndex(0)



    @pyqtSlot()
    def on_load_clicked(self) -> None:

        # Check if song directory is selected
        if self._selected_song_path is None:
            self.reset_majdataview()
            return
        
        selected_maidata = self._maidata_combo.currentText()
        selected_track = self._track_combo.currentText()
        selected_video = self._video_combo.currentText()
        is_play_video = self._play_video_checkbox.isChecked()

        if not selected_maidata or not selected_track:
            self.reset_majdataview()
            return

        majdataview_has_video = bool(selected_video and is_play_video)

        # Reset video player
        self.unload_video()

        # Create a control txt for MajdataEdit
        control_text = f"folder: {self._selected_song_path}\nmaidata: {selected_maidata}\ntrack: {selected_track}"
        if majdataview_has_video:
            control_text += f"\nmovie: {selected_video}"

        try:
            self._control_txt.write_text(control_text, encoding="utf-8")
        except Exception as e:
            print(f"Error writing to MajdataEdit control file: {e}")
        
        # Load video to media player (if applicable)
        # 在 control_file 创建完成后才检查 video 是否存在
        if not selected_video:
            return

        video_path = self._selected_song_path / selected_video
        if self._media_player is not None:
            self._media_player.setSource(QUrl.fromLocalFile(str(video_path)))
            self._media_player.pause()



    def reset_majdataview(self) -> None:

        # 1. Reset video player
        self.unload_video()

        # 2. Stop majdata
        stop_majdata()

        # 3. Clear comboboxes
        self._maidata_combo.clear()
        self._track_combo.clear()
        self._video_combo.clear()

        # 4. Reset selected song path
        self._selected_song_path = None

        return


    def unload_video(self) -> None:
        if self._media_player is not None:
            self._media_player.stop()
            self._media_player.setSource(QUrl())



    @classmethod
    def try_unload_video_if_matches(cls, target_path: Path) -> None:
        """当传入路径与当前已加载视频相同，让播放器卸载视频"""

        try:
            majdata_page = _MAJDATA_PAGE_INSTANCE
            if majdata_page is None: return
            if majdata_page._media_player is None: return
            # 获取当前已加载的视频路径
            source = majdata_page._media_player.source()
            if source.isEmpty(): return
            loaded_file = source.toLocalFile()
            if not loaded_file: return
            # 如果与传入的视频相同，则卸载视频
            norm_loaded = os.path.normpath(os.path.abspath(loaded_file)).lower()
            norm_target = os.path.normpath(os.path.abspath(str(target_path))).lower()
            if norm_loaded == norm_target:
                majdata_page.unload_video()
        except Exception:
            return
