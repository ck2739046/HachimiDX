"""Check for updates from GitHub daily — async, non-blocking via QNetworkAccessManager."""

import json
import re
from datetime import datetime
from typing import NamedTuple

import i18n
from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from src.core.schemas.op_result import OpResult, err, ok
from src.core.schemas.settings_config import SettingsConfig_Definitions as S_Defs
from src.core.tools import show_confirm_dialog, show_notify_dialog

from .settings_manage import SettingsManage

# Transfer timeout: abort if no data for 10 seconds.
REQUEST_TIMEOUT_MS = 10_000


# ---------------------------------------------------------------------------
# version model
# ---------------------------------------------------------------------------
# 版本号 "x.x.x" 后面可选追加 dev / beta / rc 三种预发布后缀
# 优先级为 dev < beta < rc < 正式版（无后缀）

# 版本号的数值段必须严格为 3 位 (x.x.x)，不足或超出都判为无法解析。

# 预发布后缀的语法: <连接符><种类><自然数?><数字之后的任何字符一律忽略>
#   "1.6.6.dev"    -> dev0     （没跟数字时视为 0）
#   "1.6.6.beta1"  -> beta1
#   "1.6.6.beta2a" -> beta2    （数字之后的内容被忽略）
#   "1.6.6.rc-1"   -> rc0      （"-1" 不是自然数，忽略）
#   "1.6.6.foo"    -> 无法解析 （只允许 dev / beta / rc）

# 版本号与预发布后缀之间的连接符有 4 个可选项 . - _ +
# 连接符必须存在，且只能有一个
#   "1.6.6.beta1" == "1.6.6-beta1" == "1.6.6_beta1" == "1.6.6+beta1"
#   "1.6.6beta1"   -> 无法解析 （缺连接符）
#   "1.6.6..beta1" -> 无法解析 （多个连接符）


_SUFFIX_RANK = {"dev": 0, "beta": 1, "rc": 2}
_RELEASE_RANK = 3  # 无后缀的正式版比同数值段的所有预发布版都新

# 连接符
_SEPARATORS = "._-+"

# 数值段固定 3 位（x.x.x）
_NUMERIC_FIELDS = 3

_VERSION_RE = re.compile(r"\s*v?([0-9]+(?:\.[0-9]+)*)(.*)", re.IGNORECASE)
_SUFFIX_RE = re.compile(r"(dev|beta|rc)([0-9]*)", re.IGNORECASE)


class _VersionKey(NamedTuple):
    """可比较的版本键: (数值段, 后缀种类优先级, 后缀数字)。"""

    numbers: tuple[int, ...]
    rank: int
    suffix_number: int


def _parse_version(raw: str) -> _VersionKey | None:
    """Parse a version string into a comparable key.
    Returns None when the version cannot be parsed.
    """
    match = _VERSION_RE.match(raw.strip())
    if match is None:
        return None

    parts = match.group(1).split(".")
    if len(parts) != _NUMERIC_FIELDS:
        return None  # 数值段只能是 x.x.x
    numbers = tuple(int(part) for part in parts)

    rest = match.group(2)
    if not rest:
        return _VersionKey(numbers, _RELEASE_RANK, 0)  # 无后缀: 正式版
    if rest[0] not in _SEPARATORS:
        return None  # 缺连接符: "1.6.6beta1" 不合法

    suffix = rest[1:]
    if not suffix or suffix[0] in _SEPARATORS:
        return None  # 一个连接符后必须有内容, 且不能再有连接符

    suffix_match = _SUFFIX_RE.match(suffix)
    if suffix_match is None:
        return None  # 只允许 dev / beta / rc 三种后缀

    kind = suffix_match.group(1).lower()
    digits_str = suffix_match.group(2)
    digits = int(digits_str) if digits_str else 0

    return _VersionKey(numbers, _SUFFIX_RANK[kind], digits)


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
                print(
                    i18n.t("check_update.notice_check_failed", error=result.error_msg)
                )
                return
            if not result.value:
                print(i18n.t("check_update.notice_skipped"))
                return

            # 检查今天是否已经检查过更新
            today_str = datetime.now().astimezone().date().isoformat()
            last_result = SettingsManage.get(S_Defs.last_check_update_time.key)
            if (
                last_result.is_ok
                and last_result.value
                and str(last_result.value) >= today_str
            ):
                print(i18n.t("check_update.notice_already_checked_today"))
                return
        else:
            today_str = datetime.now().astimezone().date().isoformat()

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
                status = reply.attribute(
                    QNetworkRequest.Attribute.HttpStatusCodeAttribute
                )
                if status != 200:
                    msg = i18n.t(
                        "check_update.notice_fetch_failed",
                        status=status or 0,
                        error=reply.reasonPhrase() or "unknown",
                    )
                    print(msg)
                    if force:
                        show_notify_dialog(dialog_title, msg)
                    return

                # 3. Parse JSON body
                tag_result = _extract_tag_name(reply)
                if not tag_result.is_ok:
                    msg = i18n.t(
                        "check_update.notice_fetch_failed",
                        status=200,
                        error=tag_result.error_msg,
                    )
                    print(msg)
                    if force:
                        show_notify_dialog(dialog_title, msg)
                    return
                latest_tag = tag_result.value

                # 4. Compare versions
                latest_ver = _parse_version(latest_tag)
                current_ver = _parse_version(VERSION)

                if latest_ver is None or current_ver is None:
                    msg = i18n.t(
                        "check_update.notice_parse_failed",
                        current=VERSION,
                        latest=latest_tag,
                    )
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
                print(
                    i18n.t(
                        "check_update.notice_new_version",
                        latest=latest_tag,
                        current=VERSION,
                    )
                )
                SettingsManage.set(S_Defs.last_check_update_time.key, today_str)
                if show_confirm_dialog(
                    i18n.t("check_update.dialog_title"),
                    i18n.t(
                        "check_update.dialog_prompt",
                        latest_version=latest_tag,
                        current_version=f"v{VERSION}",
                    ),
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
