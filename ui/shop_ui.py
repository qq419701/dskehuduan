# -*- coding: utf-8 -*-
import logging, os, shutil
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QGridLayout, QMessageBox, QSizePolicy,
)
import config as cfg

logger = logging.getLogger(__name__)

BROWSER_DATA_DIR = os.path.join(os.path.expanduser("~"), ".aikefu-client", "browser_data")


class ShopCard(QFrame):
    start_requested = pyqtSignal(dict)
    stop_requested = pyqtSignal(dict)
    relogin_requested = pyqtSignal(dict)

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

        name_label = QLabel(f"🏪 {self.shop_info.get('name', '未命名店铺')}")
        name_label.setStyleSheet("font-size: 15px; font-weight: bold;")
        layout.addWidget(name_label)

        platform = self.shop_info.get("platform", "pdd")
        platform_text = {"pdd": "拼多多", "taobao": "淘宝", "jd": "京东"}.get(platform, platform)
        platform_label = QLabel(f"平台：{platform_text}")
        platform_label.setStyleSheet("color: #666; font-size: 12px;")
        layout.addWidget(platform_label)

        status_layout = QHBoxLayout()
        self.status_dot = QLabel("🔴")
        self.status_text = QLabel("已停止")
        self.status_text.setStyleSheet("color: #666; font-size: 12px;")
        status_layout.addWidget(self.status_dot)
        status_layout.addWidget(self.status_text)
        status_layout.addStretch()
        layout.addLayout(status_layout)

        self.stats_label = QLabel("今日消息：-")
        self.stats_label.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(self.stats_label)

        # 启动/停止按钮行
        btn_layout = QHBoxLayout()
        self.start_btn = QPushButton("▶ 启动采集")
        self.stop_btn = QPushButton("⏹ 停止")
        self.stop_btn.setEnabled(False)
        self.start_btn.clicked.connect(lambda: self.start_requested.emit(self.shop_info))
        self.stop_btn.clicked.connect(lambda: self.stop_requested.emit(self.shop_info))
        btn_layout.addWidget(self.start_btn)
        btn_layout.addWidget(self.stop_btn)
        layout.addLayout(btn_layout)

        # 重新登录按钮行
        relogin_btn = QPushButton("🔄 清空缓存重新登录")
        relogin_btn.setStyleSheet(
            "QPushButton{background:#e67e22;color:white;border:none;border-radius:4px;padding:5px 10px;font-size:12px;}"
            "QPushButton:hover{background:#d35400;}"
        )
        relogin_btn.clicked.connect(self._on_relogin)
        layout.addWidget(relogin_btn)

    def _on_relogin(self):
        shop_id = str(self.shop_info.get("id", ""))
        name = self.shop_info.get("name", "该店铺")
        reply = QMessageBox.question(
            self, "重新登录",
            f"确定要清空【{name}】的登录缓存并重新登录吗？\n（会先停止采集，然后打开浏览器重新扫码）",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        # 清空浏览器缓存
        d = os.path.join(BROWSER_DATA_DIR, f"shop_{shop_id}")
        if os.path.exists(d):
            shutil.rmtree(d)
            logger.info("已清空店铺 %s 浏览器缓存", shop_id)
        os.makedirs(d, exist_ok=True)
        QMessageBox.information(self, "已清空", f"【{name}】缓存已清空！\n请点击「▶ 启动采集」重新登录。")
        self.relogin_requested.emit(self.shop_info)

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
    channel_start_requested = pyqtSignal(dict)
    channel_stop_requested = pyqtSignal(dict)

    def __init__(self, db_client=None, parent=None):
        super().__init__(parent)
        self._cards: dict = {}
        self._init_ui()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        top_layout = QHBoxLayout()
        title = QLabel("🏪 拼多多店铺管理")
        title.setStyleSheet("font-size: 20px; font-weight: bold;")
        top_layout.addWidget(title)
        top_layout.addStretch()

        refresh_btn = QPushButton("🔄 刷新店铺列表")
        refresh_btn.clicked.connect(self.load_shops)
        top_layout.addWidget(refresh_btn)
        main_layout.addLayout(top_layout)

        hint = QLabel("💡 提示：在「设置」中同步并勾选店铺后，店铺将出现在此处。")
        hint.setStyleSheet("color: #888; font-size: 12px;")
        main_layout.addWidget(hint)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.cards_container = QWidget()
        self.cards_layout = QGridLayout(self.cards_container)
        self.cards_layout.setSpacing(12)
        self.cards_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        scroll.setWidget(self.cards_container)
        main_layout.addWidget(scroll)
        self.load_shops()

    def set_db_client(self, db_client):
        self.load_shops()

    def load_shops(self):
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
            card.relogin_requested.connect(self._on_relogin)
            row, col = divmod(i, 3)
            self.cards_layout.addWidget(card, row, col)
            shop_id = str(shop.get("id", shop.get("shop_id", i)))
            self._cards[shop_id] = card

    def _on_relogin(self, shop_info: dict):
        # 先停止采集，再触发重新启动（重新登录）
        self.channel_stop_requested.emit(shop_info)
        self.channel_start_requested.emit(shop_info)

    def set_shop_running(self, shop_id, running: bool):
        card = self._cards.get(str(shop_id))
        if card:
            card.set_running(running)
