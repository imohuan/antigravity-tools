"""仪表盘页面"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QFrame
)
from PySide6.QtCore import Qt

from ...i18n import t
from ...utils.store import load_accounts
from ...models import AccountStatus


class StatCard(QFrame):
    """统计卡片"""

    def __init__(self, title: str, value: str, icon: str = "", color: str = "#2B6CB0"):
        super().__init__()
        self.setObjectName("card")
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(16, 12, 16, 12)

        header = QHBoxLayout()
        if icon:
            icon_label = QLabel(icon)
            icon_label.setStyleSheet("font-size: 20px;")
            header.addWidget(icon_label)
        title_label = QLabel(title)
        title_label.setObjectName("card_label")
        title_label.setStyleSheet("font-size: 12px; color: #9BA4B0;")
        header.addWidget(title_label)
        header.addStretch()
        layout.addLayout(header)

        self._value_label = QLabel(value)
        self._value_label.setObjectName("card_value")
        self._value_label.setStyleSheet(f"color: {color}; font-size: 24px; font-weight: 700;")
        layout.addWidget(self._value_label)

    def set_value(self, text: str):
        self._value_label.setText(text)


class DashboardPage(QWidget):
    """仪表盘页面 — 纯本地数据概览，不自动发网络请求"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("content_area")
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 标题
        title = QLabel(t("nav.dashboard"))
        title.setObjectName("page_title")
        layout.addWidget(title)

        subtitle = QLabel("全局概览（本地数据，需查询请前往对应页面）")
        subtitle.setObjectName("page_subtitle")
        layout.addWidget(subtitle)

        # 内容区域
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(32, 0, 32, 32)
        content_layout.setSpacing(20)

        # 统计卡片网格
        grid = QGridLayout()
        grid.setSpacing(16)

        self._card_total = StatCard("总账号数", "--", "👥", "#2B6CB0")
        self._card_active = StatCard("活跃账号", "--", "✅", "#38A169")
        self._card_checked = StatCard("今日已签到", "--", "🎯", "#D69E2E")
        self._card_quota = StatCard("总剩余积分", "--", "💎", "#805AD5")

        grid.addWidget(self._card_total, 0, 0)
        grid.addWidget(self._card_active, 0, 1)
        grid.addWidget(self._card_checked, 0, 2)
        grid.addWidget(self._card_quota, 0, 3)

        content_layout.addLayout(grid)

        # 签到状态分布
        checkin_label = QLabel("🎯 签到状态")
        checkin_label.setStyleSheet("font-size: 16px; font-weight: 600; margin-top: 8px;")
        content_layout.addWidget(checkin_label)

        self._checkin_container = QWidget()
        self._checkin_layout = QHBoxLayout(self._checkin_container)
        self._checkin_layout.setSpacing(12)
        content_layout.addWidget(self._checkin_container)

        content_layout.addStretch()
        layout.addWidget(content)

    def _refresh_data(self):
        """刷新仪表盘数据（纯本地，不联网）"""
        accounts = load_accounts()

        # 统计卡片
        total = len(accounts)
        active = len([a for a in accounts if a.status == AccountStatus.ACTIVE])
        checked = len([a for a in accounts if a.checkin.checked_today])

        # 计算总积分（仅统计已查询过的）
        has_queried = [a for a in accounts if a.quota.credits_total > 0]
        total_credits = sum(a.quota.credits_remaining for a in has_queried)

        self._card_total.set_value(str(total))
        self._card_active.set_value(str(active))
        self._card_checked.set_value(str(checked))
        if has_queried:
            self._card_quota.set_value(f"{total_credits:.0f}")
        else:
            self._card_quota.set_value("--")

        # 签到状态分布
        while self._checkin_layout.count():
            item = self._checkin_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        unchecked_count = total - checked
        self._checkin_layout.addWidget(StatCard("已签到", str(checked), "✅", "#38A169"))
        self._checkin_layout.addWidget(StatCard("未签到", str(unchecked_count), "⏳", "#D69E2E"))
        self._checkin_layout.addStretch()

    def showEvent(self, event):
        """页面显示时刷新数据"""
        super().showEvent(event)
        self._refresh_data()
