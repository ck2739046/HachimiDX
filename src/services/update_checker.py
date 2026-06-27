"""Check for updates from GitHub daily — async, non-blocking via QNetworkAccessManager."""

import json
import re
from datetime import date
from typing import Optional

import i18n

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from src.core.schemas.settings_config import SettingsConfig_Definitions as S_Defs
from src.core.schemas.op_result import OpResult, ok, err
from .settings_manage import SettingsManage
from src.core.tools.popup_dialog import show_confirm_dialog, show_notify_dialog

# Transfer timeout: abort if no data for 10 seconds.
REQUEST_TIMEOUT_MS = 10_000


def _parse_semver(raw: str) -> Optional[tuple[int, ...]]:
    """Parse a version string into a comparable tuple of ints.

    Handles: "1.2.1", "v1.2.1", "v1.2.1-beta", etc.
    Returns None when the version cannot be parsed.
    """
    m = re.search(r"(\d+(?:\.\d+)*)", raw)
    if not m:
        return None
    parts = m.group(1).split(".")
    try:
        return tuple(int(p) for p in parts)
    except ValueError:
        return None


def _extract_tag_name(reply: QNetworkReply) -> OpResult[str]:
    """Safely extract tag_name from a GitHub release JSON reply."""
    try:
        data = json.loads(bytes(reply.readAll()).decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        return err(f"JSON parse: {e}")
    tag = data.get("tag_name", "")
    if not tag:
        return err("tag_name is empty")
    return ok(tag)


# ---------------------------------------------------------------------------
# public entry point
# ---------------------------------------------------------------------------

def check_update(force: bool = False) -> None:
    """
    Main Entry point

    Reads the 'check_update' and 'last_check_update_time' settings internally.
    If force=True (manual trigger), skips the enabled-setting and daily-already-checked guards.
    Otherwise only runs when enabled and not yet checked today.
    Only on a successful check (network OK + valid response) will it persist
    today's date to last_check_update_time, preventing retries on failure.
    """
    try:
        if not force:
            # 先查看设置项，决定是否检查更新
            result = SettingsManage.get(S_Defs.check_update.key)
            if not result.is_ok:
                print(i18n.t("check_update.notice_check_failed", error=result.error_msg))
                return
            if not result.value:
                print(i18n.t("check_update.notice_skipped"))
                return

            # 检查今天是否已经检查过更新
            today_str = date.today().isoformat()
            last_result = SettingsManage.get(S_Defs.last_check_update_time.key)
            if last_result.is_ok and last_result.value:
                if str(last_result.value) >= today_str:
                    print(i18n.t("check_update.notice_already_checked_today"))
                    return
        else:
            today_str = date.today().isoformat()

        from src.main import API_RELEASE_LATEST  # 避免循环依赖

        # create NAM
        nam = QNetworkAccessManager()
        nam.setTransferTimeout(REQUEST_TIMEOUT_MS)
        nam.setAutoDeleteReplies(True)



        def _on_reply_finished(reply: QNetworkReply) -> None:
            """Handle the completed network reply — compare versions, optionally show dialog."""
            from src.main import REPO, VERSION  # 避免循环依赖
            dialog_title = i18n.t("check_update.dialog_title")
            try:
                # 1. Network-level error (DNS, timeout, connection refused, etc.)
                error = reply.error()
                if error != QNetworkReply.NetworkError.NoError:
                    msg = i18n.t("check_update.notice_network_error")
                    print(msg)
                    if force:
                        show_notify_dialog(dialog_title, msg)
                    return

                # 2. HTTP status
                status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
                if status != 200:
                    msg = i18n.t("check_update.notice_fetch_failed",
                                 status=status or 0,
                                 error=reply.reasonPhrase() or "unknown")
                    print(msg)
                    if force:
                        show_notify_dialog(dialog_title, msg)
                    return

                # 3. Parse JSON body
                tag_result = _extract_tag_name(reply)
                if not tag_result.is_ok:
                    msg = i18n.t("check_update.notice_fetch_failed",
                                 status=200, error=tag_result.error_msg)
                    print(msg)
                    if force:
                        show_notify_dialog(dialog_title, msg)
                    return
                latest_tag = tag_result.value

                # 4. Compare versions
                latest_ver = _parse_semver(latest_tag)
                current_ver = _parse_semver(VERSION)

                if latest_ver is None or current_ver is None:
                    msg = i18n.t("check_update.notice_parse_failed",
                                 current=VERSION, latest=latest_tag)
                    print(msg)
                    if force:
                        show_notify_dialog(dialog_title, msg)
                    return

                if latest_ver <= current_ver:
                    msg = i18n.t("check_update.notice_is_latest", version=VERSION)
                    print(msg)
                    if force:
                        show_notify_dialog(dialog_title, msg)
                    SettingsManage.set(S_Defs.last_check_update_time.key, today_str)
                    return

                # 5. New version available — confirm
                print(i18n.t("check_update.notice_new_version",
                             latest=latest_tag, current=VERSION))
                SettingsManage.set(S_Defs.last_check_update_time.key, today_str)
                if show_confirm_dialog(
                    i18n.t("check_update.dialog_title"),
                    i18n.t("check_update.dialog_prompt",
                           latest_version=latest_tag,
                           current_version=f"v{VERSION}")
                ):
                    QDesktopServices.openUrl(QUrl(f"{REPO}/releases/latest"))
            finally:
                # cleanup
                nam.finished.disconnect(_on_reply_finished)
                nam.deleteLater()



        nam.finished.connect(_on_reply_finished)

        # Build request — GitHub requires User-Agent
        req = QNetworkRequest(QUrl(API_RELEASE_LATEST))
        req.setRawHeader(b"Accept", b"application/vnd.github+json")
        req.setRawHeader(b"User-Agent", b"HachimiDX")
        nam.get(req)

        print(i18n.t("check_update.notice_checking"))

    except Exception as e:
        # 此处静默捕获并打印错误，不影响上级调用方
        msg = i18n.t("check_update.notice_check_failed", error=str(e))
        print(msg)
        if force:
            show_notify_dialog(i18n.t("check_update.dialog_title"), msg)
