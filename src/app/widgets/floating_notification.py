from __future__ import annotations

from typing import Any, Optional

from PyQt6.QtCore import QEvent, QObject, QRect, QTimer, Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QToolButton, QWidget

from ..ui_style import UI_Style

# 锚点"可能变了"的事件：拖动 / 缩放 / 最小化恢复 / 隐藏恢复 / 重新显示。
# 其余变化（换屏、DPI、以及事件覆盖不到的几何源/外部句柄）交给 50ms 兜底轮询，
_ANCHOR_CHANGE_EVENTS = frozenset({
    QEvent.Type.Move,              # 拖动 / 被外部程序移动
    QEvent.Type.Resize,            # 缩放 / 吸附
    QEvent.Type.WindowStateChange, # 最小化 / 最大化 / 恢复
    QEvent.Type.Hide,              # 隐藏（例如最小化到托盘）
    QEvent.Type.Show,              # 从隐藏恢复
})


class FloatingNotificationManager(QObject):
    """
    悬浮通知管理器（全局单例）
    负责创建、管理和定位所有悬浮通知。

    锚点跟随（事件快速路径 + 轮询兜底）：
    - 快速路径：通知存在期间给锚点装事件过滤器，Move / Resize / 最小化 / 隐藏 / 重新显示
      时立刻重排或收起，拖动窗口不会有半帧延迟；
    - 兜底轮询：仍然保留 50ms 的定时器，负责发现"事件覆盖不到"的变化
      （换屏 / DPI、非 QWidget 的几何源、外部句柄、事件丢失），
      全部通知关闭后停止轮询、清空缓存并释放事件过滤器。
    """
    
    # 单例实例引用
    _instance: Optional["FloatingNotificationManager"] = None
    
    # 配置常量
    FIXED_WIDTH: int = 300
    FIXED_HEIGHT: int = 35
    SPACING: int = 7
    MARGIN: int = 15
    AUTO_CLOSE_MS: int = 5000 # 5秒后自动关闭
    FOLLOW_POLL_MS: int = 50 # 兜底轮询周期；几何变化优先由事件过滤器即时处理


    @classmethod
    def get_instance(cls) -> "FloatingNotificationManager":
        """获取全局单例实例"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance


    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._active_notifications: list[QWidget] = [] # 通知列表
        self._anchor_geos: dict[int, QRect] = {} # 锚点最后一次几何，key = id(anchor)
        self._collapsed_anchors: set[int] = set() # 已收起通知的锚点（最小化或隐藏），key = id(anchor)
        self._hooked_anchors: dict[int, QWidget] = {} # 已装事件过滤器的锚点，key = id(anchor)

        # 锚点跟随轮询：仅在存在通知时运行
        self._follow_timer = QTimer(self)
        self._follow_timer.setInterval(self.FOLLOW_POLL_MS)
        self._follow_timer.timeout.connect(self._poll_anchor_geometries)


    def create_notification(self, message: str, parent: QWidget) -> QWidget:

        # 锚点必须是 QWidget（通知窗口以它为父对象）：统一取顶层窗口，
        # 保证创建、定位、跟随、关闭用的是同一个对象
        anchor = parent.window()
        # 创建组件
        notification = self._create_notification_widget(message, anchor)
        # 添加到列表
        self._active_notifications.append(notification)
        # 超时自动关闭（先起表：锚点收起时 _sync_collapsed_state 会把剩余时间暂存起来）
        notification._auto_close_timer.start(self.AUTO_CLOSE_MS)
        # 触发重新定位
        self._reposition_all_notifications(anchor)
        # 开始跟随（轮询兜底 + 锚点事件快速路径）
        self._sync_follow_state()
        self._ensure_anchor_hooked(anchor)
        # 锚点已收起（最小化 / 隐藏）时不要弹出（也不要先 show 再 hide，免得闪一下）
        if not self._sync_collapsed_state(anchor):
            notification.show()
        
        return notification


    def _create_notification_widget(self, message: str, anchor: QWidget) -> QWidget:

        widget = QWidget(anchor)
        
        # 公共属性
        widget._auto_close_timer = QTimer(widget)
        widget._auto_close_timer.setSingleShot(True) # 到点关一次就够
        widget._auto_close_remaining_ms = -1 # 被收起时暂存的剩余自动关闭时间
        widget._anchor = anchor
        
        # 窗口属性
        widget.setWindowFlags(Qt.WindowType.FramelessWindowHint
                              | Qt.WindowType.Tool
                              | Qt.WindowType.WindowStaysOnTopHint)
        widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True) # 半透明
        widget.setFixedSize(self.FIXED_WIDTH, self.FIXED_HEIGHT)

        # 布局
        outer_layout = QHBoxLayout(widget)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)
        
        # 底色：配置值非法时，fallback 到纯黑，让异常一眼可见
        # （文字是浅色 text_primary，黑底仍然可读）
        color = QColor(UI_Style.COLORS['task_running'])
        if not color.isValid():
            color = QColor(Qt.GlobalColor.black)  # fallback
        r, g, b, _ = color.getRgb()
        a = int(255 * 0.8)  # 80% 不透明度
        frame = QFrame()
        frame.setFrameShape(QFrame.Shape.NoFrame)
        frame.setStyleSheet(f"background-color: rgba({r},{g},{b},{a});"
                            "border-radius: 10px;")

        content_layout = QHBoxLayout(frame)
        content_layout.setContentsMargins(8, 6, 8, 6)
        content_layout.setSpacing(0)
        
        message_label = QLabel(message)
        message_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse
                                            | Qt.TextInteractionFlag.TextSelectableByKeyboard)
        message_label.setCursor(Qt.CursorShape.IBeamCursor)
        message_label.setStyleSheet(f"color: {UI_Style.COLORS['text_primary']}; \
                                      font-size: {UI_Style.default_text_size}px; \
                                      font-weight: bold; \
                                      background: transparent; \
                                      padding-left: 2px;")
        
        close_button = QToolButton(frame)
        close_button.setText("✕")
        close_button.setFixedSize(20, 20)
        close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        close_button.setStyleSheet(f"""
            QToolButton {{
                background: transparent;
                color: {UI_Style.COLORS['text_primary']};
                font-size: 15px;
                font-weight: bold;
            }}
            QToolButton:hover {{
                color: {UI_Style.COLORS['stop_hover']};
            }}""")
        
        content_layout.addWidget(message_label, 1)
        content_layout.addWidget(close_button, 0)
        outer_layout.addWidget(frame)

        # 手动关闭
        close_button.clicked.connect(lambda: self._close_notification(widget))
        # 超时自动关闭
        widget._auto_close_timer.timeout.connect(lambda: self._close_notification(widget))
        
        return widget


    def _close_notification(self, widget: QWidget) -> None:
        # 先取锚点：即使通知的 C++ 对象已销毁（父窗口先没了），Python 侧属性仍在
        anchor = getattr(widget, "_anchor", None)
        try:
            # 停止定时器
            widget._auto_close_timer.stop()
            # 关闭窗口
            widget.close()
        except RuntimeError:
            pass  # 通知的 C++ 对象已销毁，没有东西可关了
        # 从活动列表移除
        if widget in self._active_notifications:
            self._active_notifications.remove(widget)
        if anchor is not None:
            # 触发重新定位
            self._reposition_all_notifications(anchor)
            # 该锚点已经没有通知了：摘掉事件过滤器
            self._release_anchor_hook_if_unused(anchor)
        # 全部关闭后停止跟随（轮询 / 缓存 / 事件过滤器）
        self._sync_follow_state()


    def _reposition_all_notifications(self, anchor: Any) -> None:
        """重新定位所有通知"""
        try:
            if hasattr(anchor, 'frameGeometry'):
                anchor_geo = anchor.frameGeometry()
            else:
                anchor_geo = anchor.geometry()
        except Exception:
            return
        
        # 过滤出属于同一个锚点的通知
        same_anchor_notifications = self._notifications_of(anchor)
        
        # 重新定位
        for idx, notification in enumerate(same_anchor_notifications):
            try:
                x = anchor_geo.right() - notification.width() - self.MARGIN
                y = (
                    anchor_geo.bottom()
                    - notification.height()
                    - self.MARGIN
                    - idx * (notification.height() + self.SPACING)
                )
                notification.move(x, y)
            except Exception:
                # 定位失败，尝试从活动列表中移除
                if notification in self._active_notifications:
                    self._active_notifications.remove(notification)


    def _sync_follow_state(self) -> None:
        """有通知时开启兜底轮询；全部关闭后停止、清空锚点缓存并摘掉所有事件过滤器"""
        if self._active_notifications:
            if not self._follow_timer.isActive():
                self._follow_timer.start()
            return
        self._follow_timer.stop()
        self._anchor_geos.clear()
        self._collapsed_anchors.clear()
        self._release_all_hooks()
    


    # ----------------------------------------------------------------
    # 事件快速路径
    # 轮询是兜底（50ms、覆盖所有几何源）；只要锚点是 QWidget，就再挂一个事件过滤器，
    # 让拖动 / 缩放 / 最小化恢复立刻生效，不用等下一轮。


    def _ensure_anchor_hooked(self, anchor: Any) -> None:
        """给锚点装事件过滤器；装不上（外部句柄 / 已销毁）就算了，轮询仍然兜底"""
        key = id(anchor)
        if key in self._hooked_anchors:
            return
        try:
            anchor.installEventFilter(self)
        except (AttributeError, RuntimeError, TypeError):
            return
        # 同时持强引用：既标识"已挂钩"，也保证持有期间 id() 不会被复用
        self._hooked_anchors[key] = anchor


    def _release_anchor_hook(self, anchor: Any) -> None:
        """摘掉某个锚点的事件过滤器（幂等）"""
        hooked = self._hooked_anchors.pop(id(anchor), None)
        if hooked is None:
            return
        try:
            hooked.removeEventFilter(self)
        except (AttributeError, RuntimeError, TypeError):
            pass


    def _release_anchor_hook_if_unused(self, anchor: Any) -> None:
        """该锚点名下的通知都没了才摘钩"""
        if not self._notifications_of(anchor):
            self._release_anchor_hook(anchor)


    def _release_all_hooks(self) -> None:
        for anchor in list(self._hooked_anchors.values()):
            self._release_anchor_hook(anchor)


    def eventFilter(self, obj, event) -> bool:
        """锚点事件快速路径：只顺手重排/收起，不改变事件本身"""
        try:
            if event.type() in _ANCHOR_CHANGE_EVENTS:
                self._on_anchor_changed(obj)
        except (AttributeError, RuntimeError, TypeError):
            pass  # 锚点已销毁 / 内部换成了非 QWidget 的几何源；轮询与后续事件仍会兜底
        return False


    def _on_anchor_changed(self, anchor: Any) -> None:
        """锚点几何或状态变化：立刻处理（轮询仍会兜底）"""
        if not self._sync_collapsed_state(anchor):
            self._apply_anchor_geometry(anchor, only_if_changed=False)


    def _apply_anchor_geometry(self, anchor: Any, *, only_if_changed: bool) -> None:
        """取锚点几何 → 更新缓存 → 重排；取不到几何说明锚点已销毁，丢弃其通知记录"""
        try:
            if hasattr(anchor, "frameGeometry"):
                geo = anchor.frameGeometry()
            else:
                geo = anchor.geometry()
        except (AttributeError, RuntimeError):
            self._drop_notifications_of(anchor)
            return
        if only_if_changed and self._anchor_geos.get(id(anchor)) == geo:
            return
        self._anchor_geos[id(anchor)] = geo
        self._reposition_all_notifications(anchor)


    def _poll_anchor_geometries(self) -> None:
        """兜底轮询：事件覆盖不到的变化（非 QWidget 几何源 / 外部句柄 / 漏事件）靠它发现"""
        for anchor in self._distinct_anchors():
            # 收起（最小化 / 隐藏）时通知已隐藏，无需定位
            if not self._sync_collapsed_state(anchor):
                self._apply_anchor_geometry(anchor, only_if_changed=True)
        # 轮询中可能丢弃了通知，确保没有通知时定时器停止
        self._sync_follow_state()


    def _sync_collapsed_state(self, anchor: Any) -> bool:
        """锚点最小化或隐藏时收起通知，恢复后重新显示。

        Returns:
            bool: 锚点当前是否处于收起状态（调用方据此跳过定位）
        """
        try:
            # 最小化与隐藏都算"收起"；最小化时 isVisible() 仍为 True，所以要单独判断
            collapsed = (not anchor.isVisible()) or anchor.isMinimized()
        except (AttributeError, RuntimeError):
            return False  # 不是窗口（例如外部句柄 / 几何源），无法判断
        tracked = id(anchor) in self._collapsed_anchors
        if collapsed == tracked:
            return collapsed  # 状态没变，不做任何事
        if collapsed:
            self._collapsed_anchors.add(id(anchor))
        else:
            self._collapsed_anchors.discard(id(anchor))
        for notification in self._notifications_of(anchor):
            try:
                if collapsed:
                    self._suspend_notification(notification)
                else:
                    self._resume_notification(notification)
            except RuntimeError:
                pass
        return collapsed


    def _suspend_notification(self, notification: QWidget) -> None:
        """收起通知（最小化 / 隐藏），同时暂停自动关闭倒计时（否则收起久了回来就什么都没有了）"""
        timer = notification._auto_close_timer
        if timer.isActive():
            notification._auto_close_remaining_ms = timer.remainingTime()
            timer.stop()
        notification.hide()


    def _resume_notification(self, notification: QWidget) -> None:
        """重新显示通知，并接着之前的剩余时间继续自动关闭倒计时"""
        remaining = notification._auto_close_remaining_ms
        if remaining >= 0:
            notification._auto_close_remaining_ms = -1
            if remaining == 0:
                # 收起前就已经到期，直接关闭
                self._close_notification(notification)
                return
            notification._auto_close_timer.start(remaining)
        notification.show()


    def _notifications_of(self, anchor: Any) -> list[QWidget]:
        """属于该锚点的通知（按对象身份比较）"""
        return [n for n in self._active_notifications if n._anchor is anchor]


    def _distinct_anchors(self) -> list[QWidget]:
        """当前通知涉及的锚点（按对象身份去重）"""
        anchors: list[QWidget] = []
        for notification in self._active_notifications:
            anchor = notification._anchor
            if not any(a is anchor for a in anchors):
                anchors.append(anchor)
        return anchors


    def _drop_notifications_of(self, anchor: Any) -> None:
        """丢弃某个锚点名下的所有通知记录"""
        self._active_notifications = [
            n for n in self._active_notifications if n._anchor is not anchor
        ]
        self._anchor_geos.pop(id(anchor), None)
        self._collapsed_anchors.discard(id(anchor))
        self._release_anchor_hook(anchor)




# static
def create_floating_notification(message: str, parent: QWidget) -> QWidget:
    """
    创建悬浮通知
    
    Args:
        message: 通知消息
        parent: 锚点窗口，必须是 QWidget（会归一化为它所属的顶层窗口）
        
    Returns:
        QWidget: 创建的通知窗口
    """
    manager = FloatingNotificationManager.get_instance()
    return manager.create_notification(message, parent)
