"""悬浮通知「锚点跟随」（事件快速路径 + 50ms 兜底轮询）的离屏回归测试。

覆盖：
- 锚点归一化（传子控件也统一成顶层窗口，定位与轮询用同一身份）
- 锚点移动 / 缩放时通知跟随（完全依赖轮询，不依赖 Qt 事件）
- 只靠几何变化就能跟随（换成非 QWidget 的几何源，模拟收不到事件的窗口）
- 锚点事件快速路径：停掉轮询后，移动锚点仍立刻跟随
- 事件过滤器的生命周期：首个通知挂上、最后一个通知摘掉、非 QWidget 锚点不挂
- 锚点最小化时收起通知，从最小化恢复时重新显示（含最小化期间新建的通知）
- 锚点被 hide()（非最小化）时同样收起，重新显示时恢复
- 最小化期间自动关闭倒计时暂停，恢复后继续计完
- 多条通知从右下角向上堆叠、关闭一条后收拢
- 多锚点独立跟随
- 轮询定时器只在有通知时运行，清空后停止并清缓存
- 锚点销毁后记录被清理、定时器停止

运行::

    python test/test_floating_notification_follow.py
    # 或
    python -m pytest test/test_floating_notification_follow.py -v
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

# 离屏运行，避免测试时弹窗
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from PyQt6.QtCore import QEvent, QRect  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication, QFrame, QMainWindow, QWidget  # noqa: E402

# 部分 widget 在 import 期就会构造 QPixmap，必须先有 QApplication
_app = QApplication.instance() or QApplication(sys.argv[:1])

from src.app.widgets.floating_notification import (  # noqa: E402
    FloatingNotificationManager,
)

W = FloatingNotificationManager.FIXED_WIDTH
H = FloatingNotificationManager.FIXED_HEIGHT
MARGIN = FloatingNotificationManager.MARGIN
SPACING = FloatingNotificationManager.SPACING
POLL = FloatingNotificationManager.FOLLOW_POLL_MS

TOLERANCE = 2  # offscreen 平台下的像素容差
FOLLOW_WAIT = POLL * 3 + 30  # 等待若干轮轮询


def expected_pos(anchor, index: int) -> tuple[int, int]:
    """通知在锚点右下角的期望位置（index=0 是最下面那条）"""
    geo = anchor.frameGeometry()
    x = geo.right() - W - MARGIN
    y = geo.bottom() - H - MARGIN - index * (H + SPACING)
    return x, y


class _FakeAnchor:
    """只有 frameGeometry() 的几何源：模拟收不到 Qt 移动事件的窗口"""

    def __init__(self, rect: QRect) -> None:
        self._rect = rect

    def frameGeometry(self) -> QRect:
        return self._rect


class FloatingNotificationFollowTest(unittest.TestCase):

    def setUp(self) -> None:
        self.manager = FloatingNotificationManager.get_instance()
        self._reset_manager()

        self.window = QMainWindow()
        self.window.resize(900, 700)
        self.window.move(120, 90)
        self.window.show()
        QTest.qWait(60)

    def tearDown(self) -> None:
        for notification in list(self.manager._active_notifications):
            try:
                notification.close()
            except RuntimeError:
                # 父窗口已销毁时通知会一起被 C++ 删除，等下一轮轮询清理即可
                pass
        self._reset_manager()
        self.window.close()
        self.window.deleteLater()
        QTest.qWait(30)

    def _reset_manager(self) -> None:
        self.manager._release_all_hooks()
        self.manager._active_notifications.clear()
        self.manager._anchor_geos.clear()
        self.manager._collapsed_anchors.clear()
        self.manager._follow_timer.stop()

    def _assert_at(self, notification, anchor, index: int) -> None:
        exp_x, exp_y = expected_pos(anchor, index)
        self.assertLessEqual(abs(notification.x() - exp_x), TOLERANCE,
                             f"x: 实际 {notification.x()}，期望 {exp_x}")
        self.assertLessEqual(abs(notification.y() - exp_y), TOLERANCE,
                             f"y: 实际 {notification.y()}，期望 {exp_y}")

    # ---------------------------------------------------------------- 锚点归一化

    def test_anchor_normalized_to_top_level_window(self) -> None:
        """传子控件时，锚点应归一化为顶层窗口（修复创建/关闭身份不一致）"""
        child = QWidget(self.window)
        notification = self.manager.create_notification("hello", child)

        self.assertIs(notification._anchor, self.window)
        self._assert_at(notification, self.window, 0)

    # ---------------------------------------------------------------- 轮询跟随

    def test_follows_anchor_move(self) -> None:
        notification = self.manager.create_notification("move", self.window)
        self._assert_at(notification, self.window, 0)

        self.window.move(400, 300)
        QTest.qWait(FOLLOW_WAIT)
        self._assert_at(notification, self.window, 0)

    def test_follows_anchor_resize(self) -> None:
        notification = self.manager.create_notification("resize", self.window)
        self._assert_at(notification, self.window, 0)

        self.window.resize(1040, 780)
        QTest.qWait(FOLLOW_WAIT)
        self._assert_at(notification, self.window, 0)

    def test_follows_geometry_source_without_events(self) -> None:
        """换成非 QWidget 的几何源：轮询照样能发现变化并跟随"""
        notification = self.manager.create_notification("fake", self.window)

        fake = _FakeAnchor(QRect(600, 500, 900, 700))
        notification._anchor = fake
        QTest.qWait(FOLLOW_WAIT)
        self._assert_at(notification, fake, 0)

        notification._anchor._rect = QRect(200, 150, 900, 700)
        QTest.qWait(FOLLOW_WAIT)
        self._assert_at(notification, fake, 0)

    def test_stack_and_reflow_on_close(self) -> None:
        first = self.manager.create_notification("1/2", self.window)
        second = self.manager.create_notification("2/2", self.window)

        self._assert_at(first, self.window, 0)
        self._assert_at(second, self.window, 1)

        self.manager._close_notification(first)
        QTest.qWait(FOLLOW_WAIT)

        self.assertFalse(any(n is first for n in self.manager._active_notifications))
        self._assert_at(second, self.window, 0)  # 剩下那条向上收拢

    def test_follows_multi_anchor_independently(self) -> None:
        other = QMainWindow()
        other.resize(600, 500)
        other.move(1000, 200)
        other.show()
        QTest.qWait(60)

        try:
            main_note = self.manager.create_notification("main", self.window)
            other_note = self.manager.create_notification("other", other)
            self._assert_at(main_note, self.window, 0)
            self._assert_at(other_note, other, 0)

            other.move(1100, 260)
            QTest.qWait(FOLLOW_WAIT)
            self._assert_at(other_note, other, 0)
            self._assert_at(main_note, self.window, 0)  # 另一个锚点不受影响
        finally:
            other.close()
            other.deleteLater()
            QTest.qWait(FOLLOW_WAIT)  # 让轮询清理掉随窗口销毁的通知

    # ---------------------------------------------------------------- 事件快速路径

    def test_fast_path_repositions_without_polling(self) -> None:
        """锚点是 QWidget 时会挂钩：停掉轮询后，移动锚点仍然立刻跟随"""
        notification = self.manager.create_notification("fast", self.window)
        self.assertIn(id(self.window), self.manager._hooked_anchors)

        self.manager._follow_timer.stop()          # 只留事件快速路径

        self.window.move(500, 380)
        QTest.qWait(80)

        self.assertFalse(self.manager._follow_timer.isActive())
        self._assert_at(notification, self.window, 0)

    def test_fast_path_handles_synthetic_move(self) -> None:
        """确定性版本：直接投递 Move 事件，验证过滤器接线（不依赖平台是否发事件）"""
        notification = self.manager.create_notification("synthetic", self.window)
        self.manager._follow_timer.stop()

        self.window.move(360, 260)
        QApplication.sendEvent(self.window, QEvent(QEvent.Type.Move))
        QTest.qWait(20)

        self._assert_at(notification, self.window, 0)

    def test_hook_lifecycle(self) -> None:
        """首个通知挂上事件过滤器；同锚点第二条不重复挂；最后一条关闭后摘掉"""
        first = self.manager.create_notification("1/2", self.window)
        second = self.manager.create_notification("2/2", self.window)
        self.assertEqual(list(self.manager._hooked_anchors), [id(self.window)])

        self.manager._close_notification(first)
        self.assertIn(id(self.window), self.manager._hooked_anchors)  # 还有第二条

        self.manager._close_notification(second)
        self.assertEqual(self.manager._hooked_anchors, {})            # 全关了 → 摘钩
        self.assertFalse(self.manager._follow_timer.isActive())

    def test_non_widget_anchor_is_not_hooked(self) -> None:
        """非 QWidget 锚点（外部句柄那类）挂不上过滤器，但不能抛异常，轮询兜底"""
        fake = _FakeAnchor(QRect(300, 200, 800, 600))
        self.manager._ensure_anchor_hooked(fake)
        self.assertNotIn(id(fake), self.manager._hooked_anchors)
        self.manager._release_anchor_hook(fake)  # 幂等，不应抛异常

    def test_auto_close_timer_is_single_shot(self) -> None:
        """自动关闭是"到点关一次"，不需要重复触发"""
        notification = self.manager.create_notification("once", self.window)
        self.assertTrue(notification._auto_close_timer.isSingleShot())
        self.assertTrue(notification._auto_close_timer.isActive())

    def test_invalid_color_shows_obvious_anomaly(self) -> None:
        """配色配置非法时不能崩，且要用显眼的异常色（纯黑），不能悄悄回退成正常配色"""
        from src.app.ui_style import UI_Style  # noqa: PLC0415

        original = UI_Style.COLORS['task_running']
        UI_Style.COLORS['task_running'] = "not-a-color"
        try:
            notification = self.manager.create_notification("bad-color", self.window)
            frame = notification.findChild(QFrame)
            self.assertIn("rgba(0,0,0,204)", frame.styleSheet())         # 异常色：黑
            self.assertNotIn("rgba(31,111,61,", frame.styleSheet())      # 不是正常配色
        finally:
            UI_Style.COLORS['task_running'] = original

    # ---------------------------------------------------------------- 最小化 / 恢复

    def test_hides_when_anchor_minimized_and_restores(self) -> None:
        first = self.manager.create_notification("1/2", self.window)
        second = self.manager.create_notification("2/2", self.window)
        self._assert_at(first, self.window, 0)
        self._assert_at(second, self.window, 1)

        self.window.showMinimized()
        QTest.qWait(FOLLOW_WAIT)
        self.assertFalse(first.isVisible())  # 最小化 → 全部收起
        self.assertFalse(second.isVisible())

        self.window.showNormal()
        QTest.qWait(FOLLOW_WAIT)
        self.assertTrue(first.isVisible())  # 恢复 → 全部回来
        self.assertTrue(second.isVisible())
        self._assert_at(first, self.window, 0)  # 堆叠顺序不变
        self._assert_at(second, self.window, 1)

    def test_notification_created_while_minimized_stays_hidden(self) -> None:
        self.window.showMinimized()
        QTest.qWait(FOLLOW_WAIT)

        notification = self.manager.create_notification("late", self.window)
        self.assertFalse(notification.isVisible())  # 最小化期间不弹出
        QTest.qWait(FOLLOW_WAIT)
        self.assertFalse(notification.isVisible())

        self.window.showNormal()
        QTest.qWait(FOLLOW_WAIT)
        self.assertTrue(notification.isVisible())
        self._assert_at(notification, self.window, 0)

    def test_hides_when_anchor_hidden_and_restores(self) -> None:
        """锚点被 hide()（不是最小化）时也要收起，重新显示时回来"""
        notification = self.manager.create_notification("hide", self.window)
        self.assertTrue(notification.isVisible())

        self.window.hide()
        QTest.qWait(FOLLOW_WAIT)
        self.assertFalse(notification.isVisible())  # 隐藏 → 收起

        self.window.show()
        QTest.qWait(FOLLOW_WAIT)
        self.assertTrue(notification.isVisible())  # 恢复显示 → 回来
        self._assert_at(notification, self.window, 0)

    def test_minimize_state_survives_restore_without_drift(self) -> None:
        """收起/恢复多次后位置仍然正确（缓存不因最小化而错位）"""
        notification = self.manager.create_notification("toggle", self.window)

        for _ in range(2):
            self.window.showMinimized()
            QTest.qWait(FOLLOW_WAIT)
            self.assertFalse(notification.isVisible())
            self.window.showNormal()
            QTest.qWait(FOLLOW_WAIT)
            self.assertTrue(notification.isVisible())
        self._assert_at(notification, self.window, 0)

    def test_auto_close_countdown_paused_while_minimized(self) -> None:
        """最小化期间自动关闭倒计时暂停；恢复后仍能看到，之后照常超时关闭"""
        notification = self.manager.create_notification("timer", self.window)
        notification._auto_close_timer.start(400)  # 缩短倒计时便于测试

        self.window.showMinimized()
        QTest.qWait(FOLLOW_WAIT)
        self.assertFalse(notification.isVisible())

        QTest.qWait(500)  # 已超过原剩余倒计时，但不该被关掉（倒计时已暂停）
        self.assertTrue(any(n is notification for n in self.manager._active_notifications))

        self.window.showNormal()
        QTest.qWait(FOLLOW_WAIT)
        self.assertTrue(notification.isVisible())  # 恢复后通知还在

        QTest.qWait(500)  # 剩余倒计时走完 → 自动关闭
        self.assertFalse(any(n is notification for n in self.manager._active_notifications))

    # ---------------------------------------------------------------- 定时器生命周期

    def test_follow_timer_only_runs_with_notifications(self) -> None:
        self.assertFalse(self.manager._follow_timer.isActive())

        first = self.manager.create_notification("a", self.window)
        self.assertTrue(self.manager._follow_timer.isActive())

        second = self.manager.create_notification("b", self.window)
        self.assertTrue(self.manager._follow_timer.isActive())

        self.manager._close_notification(first)
        self.assertTrue(self.manager._follow_timer.isActive())  # 还有一条，继续轮询

        self.manager._close_notification(second)
        self.assertFalse(self.manager._follow_timer.isActive())
        self.assertEqual(self.manager._anchor_geos, {})

    def test_dead_anchor_is_pruned_and_timer_stops(self) -> None:
        other = QMainWindow()
        other.resize(500, 400)
        other.show()
        QTest.qWait(60)

        self.manager.create_notification("dead", other)
        self.assertTrue(self.manager._follow_timer.isActive())

        other.close()
        other.deleteLater()
        QTest.qWait(FOLLOW_WAIT * 2)

        self.assertEqual(self.manager._active_notifications, [])
        self.assertEqual(self.manager._hooked_anchors, {})  # 钩子也要跟着摘掉
        self.assertFalse(self.manager._follow_timer.isActive())


if __name__ == "__main__":
    unittest.main(verbosity=2)
