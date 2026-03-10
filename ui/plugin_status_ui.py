# -*- coding: utf-8 -*-
"""
插件状态页（v2.0）
显示所有已注册插件（每个激活店铺对应一个插件）的实时运行状态。
每 30 秒自动刷新，也可手动刷新。支持单独启动/停止某个店铺的任务执行器。
"""
import logging
from datetime import datetime

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QGridLayout, QSizePolicy,
)

import config as cfg

logger = logging.getLogger(__name__)

AUTO_REFRESH_INTERVAL_MS = 30_000  # 30 秒自动刷新


class PluginCard(QFrame):
    """单个插件/店铺状态卡片"""

    start_requested = pyqtSignal(str)  # shop_id
    stop_requested = pyqtSignal(str)   # shop_id

    def __init__(self, shop: dict, parent=None):
        super().__init__(parent)
        self.shop = shop
        self.setFrameShape(QFrame.Shape.Box)
        self.setLineWidth(1)
        self.setMinimumWidth(280)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(6)

        shop_id = str(self.shop.get("id", ""))
        name = self.shop.get("name", "未知店铺")
        platform = self.shop.get("platform", "pdd")
        platform_text = {"pdd": "拼多多", "taobao": "淘宝", "jd": "京东"}.get(platform, platform)
        plugin_id = f"pdd_shop_{shop_id}"

        # 店铺名
        name_label = QLabel(f"🏪 {name}")
        name_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        layout.addWidget(name_label)

        # 插件 ID
        plugin_label = QLabel(f"插件ID: {plugin_id}")
        plugin_label.setStyleSheet("color: #666; font-size: 11px;")
        layout.addWidget(plugin_label)

        # 平台
        platform_label = QLabel(f"平台: {platform_text}")
        platform_label.setStyleSheet("color: #666; font-size: 11px;")
        layout.addWidget(platform_label)

        # 状态指示
        status_row = QHBoxLayout()
        self.status_dot = QLabel("🔴")
        self.status_text = QLabel("离线")
        self.status_text.setStyleSheet("color: #e74c3c; font-size: 12px;")
        status_row.addWidget(self.status_dot)
        status_row.addWidget(self.status_text)
        status_row.addStretch()
        layout.addLayout(status_row)

        # 操作按钮
        btn_row = QHBoxLayout()
        self.start_btn = QPushButton("▶ 启动")
        self.stop_btn = QPushButton("⏹ 停止")
        self.stop_btn.setEnabled(False)
        self.start_btn.setStyleSheet(
            "QPushButton{background:#27ae60;color:white;border:none;border-radius:3px;padding:3px 10px;}"
            "QPushButton:hover{background:#2ecc71;}"
        )
        self.stop_btn.setStyleSheet(
            "QPushButton{background:#e74c3c;color:white;border:none;border-radius:3px;padding:3px 10px;}"
            "QPushButton:hover{background:#c0392b;}"
            "QPushButton:disabled{background:#ccc;}"
        )
        self.start_btn.clicked.connect(lambda: self.start_requested.emit(shop_id))
        self.stop_btn.clicked.connect(lambda: self.stop_requested.emit(shop_id))
        btn_row.addWidget(self.start_btn)
        btn_row.addWidget(self.stop_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

    def set_running(self, running: bool):
        if running:
            self.status_dot.setText("🟢")
            self.status_text.setText("在线")
            self.status_text.setStyleSheet("color: #27ae60; font-size: 12px;")
            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
        else:
            self.status_dot.setText("🔴")
            self.status_text.setText("离线")
            self.status_text.setStyleSheet("color: #e74c3c; font-size: 12px;")
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)


class PluginStatusPage(QWidget):
    """插件状态总览页面"""

    # 当用户手动启动/停止某个店铺时，发出信号供 MainWindow 处理
    shop_start_requested = pyqtSignal(str)  # shop_id
    shop_stop_requested = pyqtSignal(str)   # shop_id

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cards: dict = {}  # shop_id -> PluginCard
        # 外部注入 MultiShopTaskRunner 引用（可为 None）
        self._multi_runner = None
        self._init_ui()
        self._refresh_cards()

        # 30 秒自动刷新
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh_status)
        self._timer.start(AUTO_REFRESH_INTERVAL_MS)

    def set_runner(self, runner):
        """注入 MultiShopTaskRunner 实例，用于读取运行状态"""
        self._multi_runner = runner

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        # 标题行
        top_row = QHBoxLayout()
        title = QLabel("🔌 插件状态")
        title.setStyleSheet("font-size: 20px; font-weight: bold;")
        top_row.addWidget(title)
        top_row.addStretch()

        refresh_btn = QPushButton("🔄 刷新状态")
        refresh_btn.clicked.connect(self._refresh_status)
        top_row.addWidget(refresh_btn)
        main_layout.addLayout(top_row)

        self.last_update_label = QLabel("最后更新：-")
        self.last_update_label.setStyleSheet("color: #888; font-size: 11px;")
        main_layout.addWidget(self.last_update_label)

        hint = QLabel("💡 下方展示所有已激活店铺的插件运行状态，每 30 秒自动刷新一次")
        hint.setStyleSheet("color: #888; font-size: 12px;")
        main_layout.addWidget(hint)

        # 卡片滚动区域
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.cards_container = QWidget()
        self.cards_layout = QGridLayout(self.cards_container)
        self.cards_layout.setSpacing(12)
        self.cards_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        scroll.setWidget(self.cards_container)
        main_layout.addWidget(scroll)

    def _refresh_cards(self):
        """根据 active_shops 配置重新渲染卡片"""
        # 清空
        while self.cards_layout.count():
            item = self.cards_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._cards.clear()

        shops = cfg.get_active_shops()
        if not shops:
            empty = QLabel("暂无已激活的店铺。\n请在「设置」中同步并勾选店铺后保存。")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet("color: #999; font-size: 13px; margin: 40px;")
            self.cards_layout.addWidget(empty, 0, 0)
            return

        for i, shop in enumerate(shops):
            shop_id = str(shop.get("id", ""))
            card = PluginCard(shop)
            card.start_requested.connect(self._on_start_requested)
            card.stop_requested.connect(self._on_stop_requested)
            row, col = divmod(i, 3)
            self.cards_layout.addWidget(card, row, col)
            self._cards[shop_id] = card

        # 立即刷新运行状态
        self._refresh_status()

    def _refresh_status(self):
        """刷新每张卡片的运行状态"""
        self.last_update_label.setText(f"最后更新：{datetime.now().strftime('%H:%M:%S')}")

        if self._multi_runner is None:
            # 没有注入 runner，所有卡片显示离线
            for card in self._cards.values():
                card.set_running(False)
            return

        status_list = self._multi_runner.get_status()
        running_ids = {s["id"] for s in status_list if s.get("running")}

        for shop_id, card in self._cards.items():
            card.set_running(shop_id in running_ids)

    def _on_start_requested(self, shop_id: str):
        self.shop_start_requested.emit(shop_id)

    def _on_stop_requested(self, shop_id: str):
        self.shop_stop_requested.emit(shop_id)

    def refresh(self):
        """外部调用刷新入口（重新读取 active_shops 并重绘卡片）"""
        self._refresh_cards()
