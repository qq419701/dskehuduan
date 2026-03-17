# -*- coding: utf-8 -*-
"""
拼多多设置页
包含：转人工客服设置（已上线）、同步订单（预留）、自动退款（预留）
配置保存到 ~/.aikefu-client/config.json 的 pdd_settings 字段
"""
import logging
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QRadioButton, QButtonGroup, QFrame, QScrollArea,
    QSpinBox, QMessageBox,
)
import config as cfg

logger = logging.getLogger(__name__)

# ── 样式常量 ──────────────────────────────────────────
CARD_STYLE = """
QFrame#card {
    background: #2d2d2d;
    border-radius: 10px;
    border: 1px solid #3a3a3a;
}
"""
HEADER_STYLE = "font-size:15px; font-weight:bold; color:#ffffff;"
SUB_STYLE    = "font-size:12px; color:#999999;"
BADGE_ONLINE = "background:#1a6b3c; color:#4ade80; border-radius:4px; padding:2px 8px; font-size:11px;"
BADGE_WIP    = "background:#3d2b00; color:#f59e0b; border-radius:4px; padding:2px 8px; font-size:11px;"
INPUT_STYLE  = """
QLineEdit {
    background:#1e1e1e; color:#ddd; border:1px solid #555;
    border-radius:5px; padding:6px 10px; font-size:13px;
}
QLineEdit:focus { border:1px solid #0078d4; }
"""
RADIO_STYLE  = "color:#cccccc; font-size:13px;"
SAVE_BTN_STYLE = """
QPushButton {
    background:#0078d4; color:white; border:none;
    border-radius:6px; padding:8px 24px; font-size:13px; font-weight:bold;
}
QPushButton:hover { background:#106ebe; }
QPushButton:pressed { background:#005a9e; }
"""


def _make_card(parent=None) -> QFrame:
    card = QFrame(parent)
    card.setObjectName("card")
    card.setStyleSheet(CARD_STYLE)
    return card


class PddSettingsPage(QWidget):
    """拼多多设置页"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("PddSettingsPage")
        self._init_ui()
        self._load_settings()

    # ── UI 构建 ──────────────────────────────────────
    def _init_ui(self):
        # 外层可滚动容器
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea{background:transparent;}")

        container = QWidget()
        container.setStyleSheet("background:transparent;")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(30, 20, 30, 30)
        layout.setSpacing(20)

        # 页面标题
        title = QLabel("🛒 拼多多功能设置")
        title.setStyleSheet("font-size:20px; font-weight:bold; color:#ffffff;")
        layout.addWidget(title)

        subtitle = QLabel("管理拼多多平台自动化操作的相关配置，通过浏览器自动执行")
        subtitle.setStyleSheet("font-size:13px; color:#888888;")
        layout.addWidget(subtitle)

        # 三个卡片
        layout.addWidget(self._build_transfer_card())
        layout.addWidget(self._build_order_card())
        layout.addWidget(self._build_refund_card())
        layout.addStretch()

        scroll.setWidget(container)
        outer.addWidget(scroll)

    def _build_transfer_card(self) -> QFrame:
        """转人工客服设置卡片"""
        card = _make_card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 16, 20, 20)
        layout.setSpacing(14)

        # 标题行
        hdr = QHBoxLayout()
        icon_title = QLabel("🤝  转人工客服设置")
        icon_title.setStyleSheet(HEADER_STYLE)
        badge = QLabel("✅ 功能已上线")
        badge.setStyleSheet(BADGE_ONLINE)
        hdr.addWidget(icon_title)
        hdr.addStretch()
        hdr.addWidget(badge)
        layout.addLayout(hdr)

        desc = QLabel("买家触发转人工意图时，自动在拼多多客服页面执行转移操作")
        desc.setStyleSheet(SUB_STYLE)
        layout.addWidget(desc)

        # 分割线
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("color:#3a3a3a;")
        layout.addWidget(line)

        # 分配策略
        strat_label = QLabel("客服分配策略")
        strat_label.setStyleSheet("font-size:13px; color:#cccccc; font-weight:bold;")
        layout.addWidget(strat_label)

        self._strat_group = QButtonGroup(self)
        strat_layout = QHBoxLayout()
        strat_layout.setSpacing(20)

        strategies = [
            ("first",       "始终第一个"),
            ("least_busy",  "最少未回复 (推荐)"),
            ("round_robin", "轮询分配"),
            ("random",      "随机选择"),
        ]
        self._strat_radios = {}
        for key, label in strategies:
            rb = QRadioButton(label)
            rb.setStyleSheet(RADIO_STYLE)
            rb.setProperty("strategy", key)
            self._strat_group.addButton(rb)
            strat_layout.addWidget(rb)
            self._strat_radios[key] = rb
        strat_layout.addStretch()
        layout.addLayout(strat_layout)

        # 指定转人工客服（按店铺配置）
        agent_section_label = QLabel("指定转人工客服（按店铺配置）")
        agent_section_label.setStyleSheet("font-size:13px; color:#cccccc; font-weight:bold;")
        layout.addWidget(agent_section_label)

        agent_hint = QLabel("为每个拼多多店铺单独指定转人工客服账号，留空则按上方策略自动选择")
        agent_hint.setStyleSheet(SUB_STYLE)
        layout.addWidget(agent_hint)

        active_shops = cfg.get_active_shops()
        pdd_shops = [s for s in active_shops if s.get('platform', 'pdd') == 'pdd']

        shops_widget = QWidget()
        shops_layout = QVBoxLayout(shops_widget)
        shops_layout.setContentsMargins(0, 4, 0, 0)
        shops_layout.setSpacing(8)

        if pdd_shops:
            for shop in pdd_shops:
                shop_id = str(shop.get('id', ''))
                shop_name = shop.get('name', '未知店铺')

                row_widget = QWidget()
                row = QHBoxLayout(row_widget)
                row.setContentsMargins(0, 0, 0, 0)
                row.setSpacing(8)

                name_label = QLabel(shop_name)
                name_label.setStyleSheet("color:#cccccc; font-size:13px;")
                name_label.setFixedWidth(180)
                name_label.setWordWrap(True)

                agent_edit = QLineEdit()
                agent_edit.setPlaceholderText("客服账号名（留空自动分配）")
                agent_edit.setStyleSheet(INPUT_STYLE)
                agent_edit.setText(cfg.get_shop_transfer_agent(shop_id))

                save_btn = QPushButton("💾 保存")
                save_btn.setFixedWidth(72)
                save_btn.setStyleSheet(
                    "QPushButton{background:#0078d4;color:white;border:none;"
                    "border-radius:5px;padding:5px 12px;font-size:12px;}"
                    "QPushButton:hover{background:#106ebe;}"
                    "QPushButton:pressed{background:#005a9e;}"
                )

                status_label = QLabel("")
                status_label.setStyleSheet("font-size:11px; color:#888888;")

                def _make_save_handler(shop_id, agent_edit, status_label):
                    def _handler():
                        name = agent_edit.text().strip()
                        ok = cfg.save_shop_transfer_agent(shop_id, name)
                        if ok:
                            status_label.setText("✅ 已保存" if name else "✅ 已清除")
                            logger.info("店铺 %s 转人工客服已保存: %s", shop_id, name or "(自动分配)")
                        else:
                            status_label.setText("❌ 保存失败")
                    return _handler

                save_btn.clicked.connect(_make_save_handler(shop_id, agent_edit, status_label))

                row.addWidget(name_label)
                row.addWidget(agent_edit)
                row.addWidget(save_btn)
                row.addWidget(status_label)
                row.addStretch()
                shops_layout.addWidget(row_widget)
        else:
            empty_label = QLabel("暂无激活的拼多多店铺，请先在设置页同步并激活店铺")
            empty_label.setStyleSheet("color:#666666; font-size:12px;")
            shops_layout.addWidget(empty_label)

        layout.addWidget(shops_widget)

        # 触发后立即发送的话术
        reply_label = QLabel("转接时立即发送的话术")
        reply_label.setStyleSheet("font-size:13px; color:#cccccc; font-weight:bold;")
        layout.addWidget(reply_label)

        self._transfer_reply_input = QLineEdit()
        self._transfer_reply_input.setPlaceholderText("如：您好，正在为您转接人工客服，请稍候～")
        self._transfer_reply_input.setStyleSheet(INPUT_STYLE)
        layout.addWidget(self._transfer_reply_input)

        # 超时设置
        timeout_layout = QHBoxLayout()
        timeout_label = QLabel("操作超时（秒）")
        timeout_label.setStyleSheet("font-size:13px; color:#cccccc;")
        self._timeout_spin = QSpinBox()
        self._timeout_spin.setRange(10, 120)
        self._timeout_spin.setValue(30)
        self._timeout_spin.setStyleSheet(
            "QSpinBox{background:#1e1e1e;color:#ddd;border:1px solid #555;"
            "border-radius:5px;padding:4px 8px;font-size:13px;}"
        )
        timeout_tip = QLabel("超过此时间未完成转移则记录失败日志")
        timeout_tip.setStyleSheet(SUB_STYLE)
        timeout_layout.addWidget(timeout_label)
        timeout_layout.addWidget(self._timeout_spin)
        timeout_layout.addWidget(timeout_tip)
        timeout_layout.addStretch()
        layout.addLayout(timeout_layout)

        # 保存按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        save_btn = QPushButton("💾  保存转人工设置")
        save_btn.setStyleSheet(SAVE_BTN_STYLE)
        save_btn.clicked.connect(self._save_transfer_settings)
        btn_layout.addWidget(save_btn)
        layout.addLayout(btn_layout)

        return card

    def _build_order_card(self) -> QFrame:
        """同步订单设置卡片（预留/灰显）"""
        card = _make_card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 16, 20, 20)
        layout.setSpacing(12)

        hdr = QHBoxLayout()
        icon_title = QLabel("📦  同步订单设置")
        icon_title.setStyleSheet(HEADER_STYLE)
        badge = QLabel("🔒 开发中")
        badge.setStyleSheet(BADGE_WIP)
        hdr.addWidget(icon_title)
        hdr.addStretch()
        hdr.addWidget(badge)
        layout.addLayout(hdr)

        desc = QLabel("自动同步拼多多订单数据到系统，支持待发货提醒、发货状态跟踪")
        desc.setStyleSheet(SUB_STYLE)
        layout.addWidget(desc)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("color:#3a3a3a;")
        layout.addWidget(line)

        # 灰显内容
        coming_label = QLabel(
            "🚧  此功能正在开发中，即将上线\n\n预计支持：\n"
            "• 实时/定时同步订单数据\n"
            "• 待发货/已发货/已完成状态筛选\n"
            "• 异常订单自动标记提醒"
        )
        coming_label.setStyleSheet("font-size:13px; color:#666666;")
        coming_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(coming_label)

        return card

    def _build_refund_card(self) -> QFrame:
        """自动处理退款设置卡片（预留/灰显）"""
        card = _make_card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 16, 20, 20)
        layout.setSpacing(12)

        hdr = QHBoxLayout()
        icon_title = QLabel("💰  自动处理退款设置")
        icon_title.setStyleSheet(HEADER_STYLE)
        badge = QLabel("🔒 开发中")
        badge.setStyleSheet(BADGE_WIP)
        hdr.addWidget(icon_title)
        hdr.addStretch()
        hdr.addWidget(badge)
        layout.addLayout(hdr)

        desc = QLabel("根据规则自动同意或拒绝退款申请，支持金额阈值和黑名单控制")
        desc.setStyleSheet(SUB_STYLE)
        layout.addWidget(desc)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("color:#3a3a3a;")
        layout.addWidget(line)

        coming_label = QLabel(
            "🚧  此功能正在开发中，即将上线\n\n预计支持：\n"
            "• 小额退款自动同意（金额可配置）\n"
            "• 恶意买家自动拒绝（联动黑名单）\n"
            "• 退款申请实时通知人工复核"
        )
        coming_label.setStyleSheet("font-size:13px; color:#666666;")
        coming_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(coming_label)

        return card

    # ── 配置读写 ─────────────────────────────────────
    def _load_settings(self):
        """从 config.json 读取已保存的设置"""
        transfer = cfg.get_pdd_transfer_settings()

        # 分配策略
        strategy = transfer.get("strategy", "least_busy")
        radio = self._strat_radios.get(strategy, self._strat_radios["least_busy"])
        radio.setChecked(True)

        # 话术
        self._transfer_reply_input.setText(
            transfer.get("reply", cfg.DEFAULT_TRANSFER_REPLY)
        )

        # 超时
        self._timeout_spin.setValue(transfer.get("timeout", 30))

    def _save_transfer_settings(self):
        """保存转人工设置"""
        # 读取当前选中的策略
        checked = self._strat_group.checkedButton()
        strategy = checked.property("strategy") if checked else "least_busy"

        settings = {
            "strategy":       strategy,
            "reply":          self._transfer_reply_input.text().strip()
                              or cfg.DEFAULT_TRANSFER_REPLY,
            "timeout":        self._timeout_spin.value(),
        }
        ok = cfg.save_pdd_transfer_settings(settings)
        if ok:
            QMessageBox.information(
                self, "保存成功",
                "✅ 转人工设置已保存！\n\n下次触发转人工时将使用新配置。"
            )
            logger.info("转人工设置已保存: strategy=%s", strategy)
        else:
            QMessageBox.warning(self, "保存失败", "❌ 配置文件写入失败，请检查权限。")
