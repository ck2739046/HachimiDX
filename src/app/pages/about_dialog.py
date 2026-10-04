from functools import partial

import i18n
from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices, QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
)

from src.services import PathManage

from ..ui_style import UI_Style
from ..widgets import create_clickable_label, create_label, create_stated_button

I18N_Prefix = "app.about"

_ICON_SIZE = 72
_DIALOG_WIDTH = 470


def app_display_name() -> str:
    """
    应用显示名：Lite 版为 HachimiDX-Lite，否则为 HachimiDX。
    """
    from src.main import REPO_NAME  # 避免循环依赖

    return f"{REPO_NAME}-Lite" if PathManage.is_lite() else REPO_NAME


class AboutDialog(QDialog):
    """
    「关于」弹窗：app icon、版本号、作者、仓库地址、QQ 群号。

    除仓库地址（点击打开浏览器）外，文本均可划选。
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        from src.main import AUTHOR, QQ_GROUP, REPO, VERSION  # 避免循环依赖

        self._version = str(VERSION)

        self.setWindowTitle(i18n.t(f"{I18N_Prefix}.window_title"))
        self.setModal(True)
        # 用 minimumWidth 而不是 fixedWidth: 不同语言/字体/DPI 下文本更宽时让窗口自然撑开,
        # 避免仓库地址那一行被裁切。
        self.setMinimumWidth(_DIALOG_WIDTH)
        self.setStyleSheet(f"QDialog {{ background-color: {UI_Style.COLORS['bg']}; }}")

        self._apply_window_icon()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(UI_Style.widget_spacing)

        layout.addLayout(self._build_header())
        layout.addSpacing(6)
        layout.addLayout(self._build_info_grid(AUTHOR, REPO, QQ_GROUP))
        layout.addSpacing(4)
        layout.addLayout(self._build_buttons())

        self._center_on_parent(parent)

    def _apply_window_icon(self) -> None:
        try:
            if PathManage.APP_ICON_PATH.is_file():
                self.setWindowIcon(QIcon(str(PathManage.APP_ICON_PATH)))
        except Exception:
            pass

    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(14)

        # 左侧 app icon
        # 注意: 必须用 QIcon 取帧。QPixmap 直读多尺寸 .ico 只会拿到最小的 16x16 帧,
        # 拉到 72px 会明显发虚; QIcon.pixmap() 会按目标尺寸挑选最合适的一帧。
        icon_label = QLabel()
        icon_label.setFixedSize(_ICON_SIZE, _ICON_SIZE)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        try:
            pixmap = QIcon(str(PathManage.APP_ICON_PATH)).pixmap(_ICON_SIZE, _ICON_SIZE)
            if not pixmap.isNull():
                icon_label.setPixmap(pixmap)
        except Exception:
            pass
        row.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignVCenter)

        # 右侧名称 + 版本号
        text_column = QVBoxLayout()
        text_column.setSpacing(2)
        text_column.addWidget(
            create_label(app_display_name(), font_size=20, bold=True, selectable=True)
        )
        text_column.addWidget(
            create_label(
                f"v{self._version}",
                color=UI_Style.COLORS["text_secondary"],
                selectable=True,
            )
        )
        text_column.addStretch()

        row.addLayout(text_column, 1)
        return row

    def _build_info_grid(self, author: str, repo: str, qq_group: str) -> QGridLayout:
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(8)
        grid.setColumnStretch(1, 1)

        key_color = UI_Style.COLORS["text_secondary"]

        def _key(key_text: str) -> QLabel:
            return create_label(key_text, color=key_color)

        rows = (
            (
                _key(i18n.t(f"{I18N_Prefix}.label_author")),
                create_label(str(author), selectable=True),
            ),
            (
                _key(i18n.t(f"{I18N_Prefix}.label_repo")),
                # 仓库地址：由本界面自己实现"点击用浏览器打开"
                # （因此不开启划选，见 clickable_label 的说明）
                create_clickable_label(
                    label_text=str(repo),
                    tooltip_text=i18n.t(f"{I18N_Prefix}.tooltip_repo"),
                    label_color=UI_Style.COLORS["accent"],
                    on_click=partial(QDesktopServices.openUrl, QUrl(str(repo))),
                ),
            ),
            (
                _key(i18n.t(f"{I18N_Prefix}.label_qq_group")),
                create_label(str(qq_group), selectable=True),
            ),
        )

        alignment = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        for row_index, (key_label, value_label) in enumerate(rows):
            grid.addWidget(key_label, row_index, 0, alignment)
            grid.addWidget(value_label, row_index, 1, alignment)

        return grid

    def _build_buttons(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addStretch(1)

        self.close_button = create_stated_button(
            i18n.t(f"{I18N_Prefix}.ui_close_button")
        )
        self.close_button.clicked.connect(self.accept)
        row.addWidget(self.close_button)

        return row

    def _center_on_parent(self, parent) -> None:
        try:
            self.adjustSize()
            if parent is not None:
                geometry = parent.frameGeometry()
            else:
                screen = QApplication.primaryScreen()
                if screen is None:
                    return
                geometry = screen.availableGeometry()
            self.move(geometry.center() - self.rect().center())
        except Exception:
            return


def show_about_dialog(parent=None) -> None:
    """
    模态显示「关于」弹窗，Esc / 关闭按钮结束。

    Args:
        parent: 父窗口，用于居中；None 时居中于主屏幕
    """

    # 已有模态窗口时忽略，避免连点叠出多个
    if QApplication.activeModalWidget() is not None:
        return

    AboutDialog(parent).exec()
