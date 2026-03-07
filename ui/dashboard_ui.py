# -*- coding: utf-8 -*-
"""
数据统计面板
直接查询MySQL数据库，显示今日消息统计
"""
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QGridLayout, QFrame, QSizePolicy,
)


class StatCard(QFrame):
    """统计数字卡片"""

    def __init__(self, title: str, value: str = "0", color: str = "#1890ff", parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.Box)
        self.setLineWidth(1)
        self.setMinimumSize(160, 100)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setContentsMargins(16, 12, 16, 12)

        self.value_label = QLabel(value)
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.value_label.setStyleSheet(
            f"font-size: 36px; font-weight: bold; color: {color};"
        )
        layout.addWidget(self.value_label)

        title_label = QLabel(title)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setStyleSheet("font-size: 13px; color: #666;")
        layout.addWidget(title_label)

    def set_value(self, value):
        self.value_label.setText(str(value))


class DashboardPage(QWidget):
    """数据统计面板页面"""

    def __init__(self, db_client=None, parent=None):
        super().__init__(parent)
        self.db_client = db_client
        self._init_ui()
        self._setup_refresh_timer()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(20)

        # 标题
        title = QLabel("📊 今日数据统计")
        title.setStyleSheet("font-size: 20px; font-weight: bold;")
        layout.addWidget(title)

        # 统计卡片网格
        grid = QGridLayout()
        grid.setSpacing(16)

        self.card_total = StatCard("今日总消息数", "0", "#1890ff")
        self.card_ai = StatCard("AI处理数", "0", "#52c41a")
        self.card_human = StatCard("转人工数", "0", "#fa8c16")
        self.card_shops = StatCard("运行店铺数", "0", "#722ed1")

        grid.addWidget(self.card_total, 0, 0)
        grid.addWidget(self.card_ai, 0, 1)
        grid.addWidget(self.card_human, 0, 2)
        grid.addWidget(self.card_shops, 0, 3)

        layout.addLayout(grid)

        # 刷新状态标签
        self.refresh_label = QLabel("数据每30秒自动刷新")
        self.refresh_label.setStyleSheet("color: #999; font-size: 11px;")
        layout.addWidget(self.refresh_label)

        layout.addStretch()

        # 初始加载
        self.refresh_stats()

    def _setup_refresh_timer(self):
        """每30秒刷新一次统计数据"""
        self._timer = QTimer(self)
        self._timer.setInterval(30000)
        self._timer.timeout.connect(self.refresh_stats)
        self._timer.start()

    def set_db_client(self, db_client):
        self.db_client = db_client
        self.refresh_stats()

    def set_running_shops_count(self, count: int):
        self.card_shops.set_value(count)

    def refresh_stats(self):
        """刷新统计数据"""
        if not self.db_client:
            return
        try:
            stats = self.db_client.get_today_stats()
            self.card_total.set_value(stats.get("total", 0))
            self.card_ai.set_value(stats.get("ai_handled", 0))
            self.card_human.set_value(stats.get("human_handled", 0))
        except Exception:
            pass
