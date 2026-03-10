# -*- coding: utf-8 -*-
"""
拼多多店铺管理界面（v2.0）
数据来源从 MySQL 改为 config.get_active_shops()（已激活的店铺）。
"""
import logging

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QGridLayout, QMessageBox, QSizePolicy,
)

import config as cfg

logger = logging.getLogger(__name__)


class ShopCard(QFrame):
    """单个店铺卡片组件"""

    start_requested = pyqtSignal(dict)
    stop_requested = pyqtSignal(dict)

    def __init__(self, shop_info: dict, parent=None):
        super().__init__(parent)
        self.shop_info = shop_info
        self.is_running = False
        self.setFrameShape(QFrame.Shape.Box)
        self.setLineWidth(1)
        self.setMinimumWidth(260)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        # 店铺名称
        name_label = QLabel(f"🏪 {self.shop_info.get('name', '未命名店铺')}")
        name_label.setStyleSheet("font-size: 15px; font-weight: bold;")
        layout.addWidget(name_label)

        # 平台标签
        platform = self.shop_info.get("platform", "pdd")
        platform_text = {"pdd": "拼多多", "taobao": "淘宝", "jd": "京东"}.get(platform, platform)
        platform_label = QLabel(f"平台：{platform_text}")
        platform_label.setStyleSheet("color: #666; font-size: 12px;")
        layout.addWidget(platform_label)

        # 状态指示
        status_layout = QHBoxLayout()
        self.status_dot = QLabel("🔴")
        self.status_text = QLabel("已停止")
        self.status_text.setStyleSheet("color: #666; font-size: 12px;")
        status_layout.addWidget(self.status_dot)
        status_layout.addWidget(self.status_text)
        status_layout.addStretch()
        layout.addLayout(status_layout)

        # 统计信息
        self.stats_label = QLabel("今日消息：-")
        self.stats_label.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(self.stats_label)

        # 控制按钮
        btn_layout = QHBoxLayout()
        self.start_btn = QPushButton("▶ 启动采集")
        self.stop_btn = QPushButton("⏹ 停止")
        self.stop_btn.setEnabled(False)

        self.start_btn.clicked.connect(lambda: self.start_requested.emit(self.shop_info))
        self.stop_btn.clicked.connect(lambda: self.stop_requested.emit(self.shop_info))

        btn_layout.addWidget(self.start_btn)
        btn_layout.addWidget(self.stop_btn)
        layout.addLayout(btn_layout)

    def set_running(self, running: bool):
        self.is_running = running
        if running:
            self.status_dot.setText("🟢")
            self.status_text.setText("运行中")
            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
        else:
            self.status_dot.setText("🔴")
            self.status_text.setText("已停止")
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)

    def set_today_count(self, count: int):
        self.stats_label.setText(f"今日消息：{count} 条")


class ShopPage(QWidget):
    """拼多多店铺管理页面"""

    channel_start_requested = pyqtSignal(dict)
    channel_stop_requested = pyqtSignal(dict)

    def __init__(self, db_client=None, parent=None):
        super().__init__(parent)
        # db_client 保留以兼容旧调用，v2.0 中不使用
        self._cards: dict = {}  # shop_id -> ShopCard
        self._init_ui()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        # 顶部工具栏
        top_layout = QHBoxLayout()
        title = QLabel("🏪 拼多多店铺管理")
        title.setStyleSheet("font-size: 20px; font-weight: bold;")
        top_layout.addWidget(title)
        top_layout.addStretch()

        refresh_btn = QPushButton("🔄 刷新店铺列表")
        refresh_btn.clicked.connect(self.load_shops)
        top_layout.addWidget(refresh_btn)

        main_layout.addLayout(top_layout)

        hint = QLabel(
            "💡 提示：在「设置」中同步并勾选店铺后，店铺将出现在此处。"
        )
        hint.setStyleSheet("color: #888; font-size: 12px;")
        main_layout.addWidget(hint)

        # 店铺卡片滚动区域
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.cards_container = QWidget()
        self.cards_layout = QGridLayout(self.cards_container)
        self.cards_layout.setSpacing(12)
        self.cards_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        scroll.setWidget(self.cards_container)
        main_layout.addWidget(scroll)

        # 初始加载
        self.load_shops()

    def set_db_client(self, db_client):
        """兼容旧接口，v2.0 中不使用 db_client"""
        self.load_shops()

    def load_shops(self):
        """从 config.get_active_shops() 加载已激活的店铺列表"""
        # 清空现有卡片
        while self.cards_layout.count():
            item = self.cards_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._cards.clear()

        shops = cfg.get_active_shops()

        if not shops:
            no_shop = QLabel(
                f"暂无已激活的拼多多店铺。\n"
                f"请在「设置」→「拼多多店铺管理」中同步并勾选店铺后保存。\n"
                f"（服务器：{cfg.get_server_url()}）"
            )
            no_shop.setAlignment(Qt.AlignmentFlag.AlignCenter)
            no_shop.setStyleSheet("color: #999; font-size: 13px; margin: 40px;")
            self.cards_layout.addWidget(no_shop, 0, 0)
            return

        for i, shop in enumerate(shops):
            card = ShopCard(shop)
            card.start_requested.connect(self.channel_start_requested)
            card.stop_requested.connect(self.channel_stop_requested)
            row, col = divmod(i, 3)
            self.cards_layout.addWidget(card, row, col)
            shop_id = str(shop.get("id", shop.get("shop_id", i)))
            self._cards[shop_id] = card

    def set_shop_running(self, shop_id, running: bool):
        """更新店铺运行状态"""
        card = self._cards.get(str(shop_id))
        if card:
            card.set_running(running)
