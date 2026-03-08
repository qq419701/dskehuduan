# -*- coding: utf-8 -*-
"""
U号租专区 - 主页面
包含账号管理、自动换号、自动选号、编号自动下单（预留）四个子Tab
"""
import asyncio
import logging
import uuid
from datetime import datetime

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTabWidget, QTableWidget, QTableWidgetItem,
    QGroupBox, QFormLayout, QCheckBox, QSpinBox, QDoubleSpinBox,
    QDialog, QDialogButtonBox, QMessageBox, QHeaderView, QScrollArea,
    QFrame, QSizePolicy,
)

import config as cfg

logger = logging.getLogger(__name__)

BASE_STYLE = '''
QWidget { background-color: #ffffff; color: #222222; }
QTabWidget::pane { border: 1px solid #e0e0e0; border-radius: 4px; }
QTabBar::tab { padding: 6px 16px; color: #555; }
QTabBar::tab:selected { color: #1890ff; border-bottom: 2px solid #1890ff; }
QGroupBox {
    background-color: #f8f9fa;
    border: 1px solid #e0e0e0;
    border-radius: 6px;
    margin-top: 8px;
    color: #222;
    font-weight: bold;
}
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #222; }
QLineEdit {
    background: #fff;
    border: 1px solid #d0d0d0;
    border-radius: 4px;
    padding: 4px 8px;
    color: #222;
}
QLineEdit:focus { border: 1px solid #1890ff; }
QPushButton {
    background: #1890ff;
    color: white;
    border: none;
    border-radius: 4px;
    padding: 6px 16px;
}
QPushButton:hover { background: #40a9ff; }
QPushButton:pressed { background: #096dd9; }
QPushButton:disabled { background: #b0b0b0; }
QCheckBox { color: #222; }
QLabel { color: #222; }
QTableWidget { border: 1px solid #e0e0e0; border-radius: 4px; gridline-color: #f0f0f0; }
QTableWidget::item { padding: 4px; }
QTableWidget::item:selected { background: #e6f7ff; color: #1890ff; }
QHeaderView::section { background: #f5f5f5; border: none; padding: 6px; font-weight: bold; }
QSpinBox, QDoubleSpinBox {
    background: #fff;
    border: 1px solid #d0d0d0;
    border-radius: 4px;
    padding: 4px 8px;
    color: #222;
}
'''


# ── Worker threads ─────────────────────────────────────────────────────────────

class _AsyncWorker(QThread):
    """通用异步任务 Worker"""

    finished = pyqtSignal(object)   # result
    error = pyqtSignal(str)         # error message

    def __init__(self, coro_factory, parent=None):
        super().__init__(parent)
        self._coro_factory = coro_factory

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(self._coro_factory())
            self.finished.emit(result)
        except Exception as e:
            logger.error("异步任务异常: %s", e)
            self.error.emit(str(e))
        finally:
            loop.close()


# ── Add Account Dialog ─────────────────────────────────────────────────────────

class AddAccountDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("添加U号租账号")
        self.resize(360, 200)

        layout = QFormLayout(self)

        self._phone = QLineEdit()
        self._phone.setPlaceholderText("请输入手机号")

        self._employee = QLineEdit()
        self._employee.setPlaceholderText("请输入员工账号")

        self._password = QLineEdit()
        self._password.setPlaceholderText("请输入密码")
        self._password.setEchoMode(QLineEdit.EchoMode.Password)

        layout.addRow("手机号：", self._phone)
        layout.addRow("员工账号：", self._employee)
        layout.addRow("密码：", self._password)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def get_data(self):
        phone = self._phone.text().strip()
        employee = self._employee.text().strip()
        username = f"{phone}:{employee}" if phone and employee else ""
        return username, self._password.text()


# ── Tab1: 账号管理 ──────────────────────────────────────────────────────────────

class AccountTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._workers = []
        self._build_ui()
        self._load_accounts()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # 工具栏
        toolbar = QHBoxLayout()
        self._btn_add = QPushButton("➕ 添加账号")
        self._btn_delete = QPushButton("🗑️ 删除账号")
        self._btn_default = QPushButton("⭐ 设为默认")
        self._btn_check = QPushButton("🔍 检测登录")
        self._btn_balance = QPushButton("💰 查询余额")
        self._status_label = QLabel("")
        self._status_label.setStyleSheet("color: #888;")

        for btn in [self._btn_add, self._btn_delete, self._btn_default,
                    self._btn_check, self._btn_balance]:
            toolbar.addWidget(btn)
        toolbar.addWidget(self._status_label)
        toolbar.addStretch()

        layout.addLayout(toolbar)

        # 账号列表表格
        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(["账号名", "状态", "余额", "默认", "操作"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self._table)

        # 连接信号
        self._btn_add.clicked.connect(self._on_add)
        self._btn_delete.clicked.connect(self._on_delete)
        self._btn_default.clicked.connect(self._on_set_default)
        self._btn_check.clicked.connect(self._on_check_login)
        self._btn_balance.clicked.connect(self._on_query_balance)

    def _load_accounts(self):
        accounts = cfg.get_uhaozu_accounts()
        self._refresh_table(accounts)

    def _refresh_table(self, accounts):
        self._table.setRowCount(0)
        for acc in accounts:
            row = self._table.rowCount()
            self._table.insertRow(row)
            self._table.setItem(row, 0, QTableWidgetItem(acc.get("username", "")))
            status = "🟢 在线" if acc.get("online") else "🔴 离线"
            self._table.setItem(row, 1, QTableWidgetItem(status))
            balance = str(acc.get("balance", "--"))
            self._table.setItem(row, 2, QTableWidgetItem(balance))
            is_default = "✅" if acc.get("is_default") else ""
            self._table.setItem(row, 3, QTableWidgetItem(is_default))
            self._table.setItem(row, 4, QTableWidgetItem(acc.get("id", "")))

    def _selected_row(self):
        rows = self._table.selectionModel().selectedRows()
        return rows[0].row() if rows else -1

    def _on_add(self):
        dlg = AddAccountDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            username, password = dlg.get_data()
            if not username or ':' not in username or username.startswith(':') or username.endswith(':'):
                QMessageBox.warning(self, "提示", "手机号和员工账号不能为空")
                return
            accounts = cfg.get_uhaozu_accounts()
            accounts.append({
                "id": str(uuid.uuid4()),
                "username": username,
                "password": password,
                "is_default": len(accounts) == 0,
                "cookies": {},
            })
            cfg.save_uhaozu_accounts(accounts)
            self._load_accounts()

    def _on_delete(self):
        row = self._selected_row()
        if row < 0:
            QMessageBox.information(self, "提示", "请先选择要删除的账号")
            return
        accounts = cfg.get_uhaozu_accounts()
        if row < len(accounts):
            name = accounts[row].get("username", "")
            reply = QMessageBox.question(
                self, "确认删除", f"确认删除账号 {name}？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                accounts.pop(row)
                cfg.save_uhaozu_accounts(accounts)
                self._load_accounts()

    def _on_set_default(self):
        row = self._selected_row()
        if row < 0:
            QMessageBox.information(self, "提示", "请先选择要设为默认的账号")
            return
        accounts = cfg.get_uhaozu_accounts()
        if row < len(accounts):
            for i, acc in enumerate(accounts):
                acc["is_default"] = (i == row)
            cfg.save_uhaozu_accounts(accounts)
            self._load_accounts()

    def _on_check_login(self):
        row = self._selected_row()
        if row < 0:
            QMessageBox.information(self, "提示", "请先选择账号")
            return
        accounts = cfg.get_uhaozu_accounts()
        if row >= len(accounts):
            return
        acc = accounts[row]
        self._set_busy(True, "检测中...")

        from automation.uhaozu import UHaozuAutomation
        automation = UHaozuAutomation(
            username=acc.get("username", ""),
            password=acc.get("password", ""),
            cookies=acc.get("cookies", {}),
        )

        async def _check():
            try:
                result = await automation.check_login_status()
                return result
            finally:
                await automation.close()

        worker = _AsyncWorker(_check, self)
        worker.finished.connect(lambda ok: self._on_check_done(row, ok))
        worker.error.connect(lambda e: self._on_worker_error(e))
        worker.finished.connect(lambda _: self._set_busy(False, ""))
        worker.error.connect(lambda _: self._set_busy(False, ""))
        self._workers.append(worker)
        worker.start()

    def _on_check_done(self, row, is_online: bool):
        accounts = cfg.get_uhaozu_accounts()
        if row < len(accounts):
            accounts[row]["online"] = is_online
            cfg.save_uhaozu_accounts(accounts)
            self._refresh_table(accounts)

    def _on_query_balance(self):
        row = self._selected_row()
        if row < 0:
            QMessageBox.information(self, "提示", "请先选择账号")
            return
        accounts = cfg.get_uhaozu_accounts()
        if row >= len(accounts):
            return
        acc = accounts[row]
        self._set_busy(True, "查询中...")

        from automation.uhaozu import UHaozuAutomation
        automation = UHaozuAutomation(
            username=acc.get("username", ""),
            password=acc.get("password", ""),
            cookies=acc.get("cookies", {}),
        )

        async def _get():
            try:
                return await automation.get_balance()
            finally:
                await automation.close()

        worker = _AsyncWorker(_get, self)
        worker.finished.connect(lambda bal: self._on_balance_done(row, bal))
        worker.error.connect(lambda e: self._on_worker_error(e))
        worker.finished.connect(lambda _: self._set_busy(False, ""))
        worker.error.connect(lambda _: self._set_busy(False, ""))
        self._workers.append(worker)
        worker.start()

    def _on_balance_done(self, row, balance: float):
        accounts = cfg.get_uhaozu_accounts()
        if row < len(accounts):
            accounts[row]["balance"] = balance
            cfg.save_uhaozu_accounts(accounts)
            self._refresh_table(accounts)

    def _on_worker_error(self, err: str):
        QMessageBox.warning(self, "操作失败", err)

    def _set_busy(self, busy: bool, text: str):
        for btn in [self._btn_add, self._btn_delete, self._btn_default,
                    self._btn_check, self._btn_balance]:
            btn.setEnabled(not busy)
        self._status_label.setText(text)


# ── Tab2: 自动换号 ──────────────────────────────────────────────────────────────

class ExchangeTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._workers = []
        self._build_ui()
        self._load_settings()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # 设置区域
        settings_group = QGroupBox("换号设置")
        settings_layout = QFormLayout(settings_group)
        self._max_exchange = QSpinBox()
        self._max_exchange.setRange(1, 99)
        self._max_exchange.setValue(5)
        settings_layout.addRow("每订单最大换号次数：", self._max_exchange)

        btn_save = QPushButton("保存设置")
        btn_save.clicked.connect(self._on_save_settings)
        settings_layout.addRow("", btn_save)
        layout.addWidget(settings_group)

        # 手动换号区域
        manual_group = QGroupBox("手动换号")
        manual_layout = QHBoxLayout(manual_group)
        self._order_input = QLineEdit()
        self._order_input.setPlaceholderText("输入拼多多订单号")
        self._btn_exchange = QPushButton("立即换号")
        self._btn_exchange.clicked.connect(self._on_manual_exchange)
        self._exchange_status = QLabel("")
        self._exchange_status.setStyleSheet("color: #888;")
        manual_layout.addWidget(QLabel("订单号："))
        manual_layout.addWidget(self._order_input, 1)
        manual_layout.addWidget(self._btn_exchange)
        manual_layout.addWidget(self._exchange_status)
        layout.addWidget(manual_group)

        # 说明文字
        info = QLabel(
            "💡 AI识别到买家换号请求后，自动获取买家订单号，到U号租一键换货页面完成换号"
        )
        info.setStyleSheet("color: #888; font-size: 12px;")
        info.setWordWrap(True)
        layout.addWidget(info)

        # 换号记录
        records_group = QGroupBox("换号记录")
        records_layout = QVBoxLayout(records_group)
        self._records_table = QTableWidget(0, 4)
        self._records_table.setHorizontalHeaderLabels(["订单号", "已换次数", "最后换号时间", "状态"])
        self._records_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._records_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._records_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._records_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self._records_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        records_layout.addWidget(self._records_table)
        layout.addWidget(records_group, 1)

    def _load_settings(self):
        settings = cfg.get_uhaozu_settings()
        self._max_exchange.setValue(settings.get("max_exchange_per_order", 5))

    def _on_save_settings(self):
        settings = cfg.get_uhaozu_settings()
        settings["max_exchange_per_order"] = self._max_exchange.value()
        if cfg.save_uhaozu_settings(settings):
            QMessageBox.information(self, "提示", "设置已保存")
        else:
            QMessageBox.warning(self, "错误", "保存失败")

    def _on_manual_exchange(self):
        order_id = self._order_input.text().strip()
        if not order_id:
            QMessageBox.warning(self, "提示", "请输入拼多多订单号")
            return

        acc = cfg.get_default_uhaozu_account()
        if not acc:
            QMessageBox.warning(self, "提示", "请先在账号管理中添加并设置默认账号")
            return

        self._btn_exchange.setEnabled(False)
        self._exchange_status.setText("换号中...")

        from automation.uhaozu import UHaozuAutomation
        automation = UHaozuAutomation(
            username=acc.get("username", ""),
            password=acc.get("password", ""),
            cookies=acc.get("cookies", {}),
        )

        async def _exchange():
            try:
                return await automation.exchange_number(order_id)
            finally:
                await automation.close()

        worker = _AsyncWorker(_exchange, self)
        worker.finished.connect(lambda r: self._on_exchange_done(order_id, r))
        worker.error.connect(self._on_exchange_error)
        self._workers.append(worker)
        worker.start()

    def _on_exchange_done(self, order_id: str, result: dict):
        self._btn_exchange.setEnabled(True)
        if result.get("success"):
            self._exchange_status.setText("✅ 换号成功")
            new_acc = result.get("new_account", "")
            QMessageBox.information(self, "换号成功", f"换号成功！新账号：{new_acc}")
            # 添加到记录表
            row = self._records_table.rowCount()
            self._records_table.insertRow(row)
            self._records_table.setItem(row, 0, QTableWidgetItem(order_id))
            self._records_table.setItem(row, 1, QTableWidgetItem("1"))
            self._records_table.setItem(
                row, 2, QTableWidgetItem(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            )
            self._records_table.setItem(row, 3, QTableWidgetItem("成功"))
        else:
            self._exchange_status.setText("❌ 换号失败")
            QMessageBox.warning(self, "换号失败", result.get("message", "未知错误"))

    def _on_exchange_error(self, err: str):
        self._btn_exchange.setEnabled(True)
        self._exchange_status.setText("❌ 出错")
        QMessageBox.warning(self, "换号失败", err)


# ── Tab3: 自动选号 ──────────────────────────────────────────────────────────────

class _PriceRuleRow(QWidget):
    """加价规则单行"""

    remove_requested = pyqtSignal(object)

    def __init__(self, min_val=0.0, max_val=0.0, markup=0.0, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self._min = QDoubleSpinBox()
        self._min.setRange(0, 9999)
        self._min.setDecimals(2)
        self._min.setValue(min_val)
        self._max = QDoubleSpinBox()
        self._max.setRange(0, 9999)
        self._max.setDecimals(2)
        self._max.setValue(max_val)
        self._markup = QDoubleSpinBox()
        self._markup.setRange(0, 9999)
        self._markup.setDecimals(2)
        self._markup.setValue(markup)

        btn_del = QPushButton("删除")
        btn_del.setFixedWidth(50)
        btn_del.setStyleSheet("background:#ff4d4f;")
        btn_del.clicked.connect(lambda: self.remove_requested.emit(self))

        layout.addWidget(QLabel("¥"))
        layout.addWidget(self._min)
        layout.addWidget(QLabel("~"))
        layout.addWidget(self._max)
        layout.addWidget(QLabel("加价¥"))
        layout.addWidget(self._markup)
        layout.addWidget(btn_del)
        layout.addStretch()

    def get_data(self):
        return {
            "min": self._min.value(),
            "max": self._max.value(),
            "markup": self._markup.value(),
        }


class _GameConfigWidget(QFrame):
    """单个游戏配置折叠面板"""

    FILTER_LABELS = {
        "no_deposit": "无押金",
        "time_rental_bonus": "时租满送",
        "login_tool": "登号器",
        "anti_addiction": "防沉迷",
        "non_cloud": "非云",
        "high_login_rate": "上号率高",
        "no_friend_add": "禁言/不能加好友",
        "allow_ranked": "排位赛允许",
    }

    def __init__(self, game_name: str, config: dict, parent=None):
        super().__init__(parent)
        self.game_name = game_name
        self._config = config
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._build_ui()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # 标题行（点击展开/折叠）
        header = QPushButton(f"▶ {self.game_name}")
        header.setStyleSheet(
            "text-align:left; background:#f0f5ff; color:#1890ff; "
            "border:none; padding:6px 10px; font-weight:bold;"
        )
        header.setCheckable(True)
        header.setChecked(False)
        outer.addWidget(header)

        # 内容区
        self._content = QWidget()
        self._content.setVisible(False)
        content_layout = QVBoxLayout(self._content)
        content_layout.setContentsMargins(16, 8, 8, 8)
        content_layout.setSpacing(6)

        # 平台
        plat_layout = QHBoxLayout()
        plat_layout.addWidget(QLabel("平台："))
        self._cb_android = QCheckBox("安卓")
        self._cb_android.setChecked("安卓" in self._config.get("platforms", []))
        self._cb_ios = QCheckBox("苹果")
        self._cb_ios.setChecked("苹果" in self._config.get("platforms", []))
        plat_layout.addWidget(self._cb_android)
        plat_layout.addWidget(self._cb_ios)
        plat_layout.addStretch()
        content_layout.addLayout(plat_layout)

        # 登录方式
        login_layout = QHBoxLayout()
        login_layout.addWidget(QLabel("登录方式："))
        self._cb_wechat = QCheckBox("微信")
        self._cb_wechat.setChecked("微信" in self._config.get("login_methods", []))
        self._cb_qq = QCheckBox("QQ")
        self._cb_qq.setChecked("QQ" in self._config.get("login_methods", []))
        login_layout.addWidget(self._cb_wechat)
        login_layout.addWidget(self._cb_qq)
        login_layout.addStretch()
        content_layout.addLayout(login_layout)

        # 筛选项
        filters = self._config.get("filters", {})
        self._filter_cbs = {}
        filter_layout = QHBoxLayout()
        filter_layout.setSpacing(12)
        for key, label in self.FILTER_LABELS.items():
            cb = QCheckBox(label)
            cb.setChecked(filters.get(key, False))
            self._filter_cbs[key] = cb
            filter_layout.addWidget(cb)
        filter_layout.addStretch()
        content_layout.addLayout(filter_layout)

        outer.addWidget(self._content)

        def _toggle(checked):
            self._content.setVisible(checked)
            header.setText(f"{'▼' if checked else '▶'} {self.game_name}")

        header.toggled.connect(_toggle)

    def get_data(self) -> dict:
        platforms = []
        if self._cb_android.isChecked():
            platforms.append("安卓")
        if self._cb_ios.isChecked():
            platforms.append("苹果")
        login_methods = []
        if self._cb_wechat.isChecked():
            login_methods.append("微信")
        if self._cb_qq.isChecked():
            login_methods.append("QQ")
        filters = {k: cb.isChecked() for k, cb in self._filter_cbs.items()}
        return {
            "platforms": platforms,
            "login_methods": login_methods,
            "filters": filters,
        }


class SelectTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._price_rows = []
        self._game_widgets = []
        self._build_ui()
        self._load_settings()

    def _build_ui(self):
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        # ── 加价规则 ──
        price_group = QGroupBox("加价规则")
        self._price_layout = QVBoxLayout(price_group)
        self._price_layout.setSpacing(4)

        add_rule_btn = QPushButton("➕ 新增区间")
        add_rule_btn.setFixedWidth(100)
        add_rule_btn.clicked.connect(lambda: self._add_price_row())
        self._price_layout.addWidget(add_rule_btn)

        save_price_btn = QPushButton("保存加价规则")
        save_price_btn.clicked.connect(self._on_save_price_rules)
        self._price_layout.addWidget(save_price_btn)

        layout.addWidget(price_group)

        # ── 游戏筛选配置 ──
        self._game_group = QGroupBox("游戏筛选配置")
        self._game_layout = QVBoxLayout(self._game_group)
        self._game_layout.setSpacing(4)

        save_game_btn = QPushButton("保存游戏配置")
        save_game_btn.clicked.connect(self._on_save_game_configs)
        self._game_layout.addWidget(save_game_btn)

        layout.addWidget(self._game_group)
        layout.addStretch()

        scroll.setWidget(container)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        # 保存按钮引用以便排序
        self._add_rule_btn = add_rule_btn
        self._save_price_btn = save_price_btn
        self._save_game_btn = save_game_btn

    def _add_price_row(self, min_val=0.0, max_val=0.0, markup=0.0):
        row = _PriceRuleRow(min_val, max_val, markup)
        row.remove_requested.connect(self._remove_price_row)
        # 插入到「新增区间」按钮之前
        idx = self._price_layout.indexOf(self._add_rule_btn)
        self._price_layout.insertWidget(idx, row)
        self._price_rows.append(row)

    def _remove_price_row(self, row):
        self._price_layout.removeWidget(row)
        row.deleteLater()
        if row in self._price_rows:
            self._price_rows.remove(row)

    def _load_settings(self):
        settings = cfg.get_uhaozu_settings()

        # 加价规则
        for rule in settings.get("price_markup_rules", []):
            self._add_price_row(rule.get("min", 0), rule.get("max", 0), rule.get("markup", 0))

        # 游戏配置
        game_configs = settings.get("game_configs", {})
        for game_name, game_cfg in game_configs.items():
            self._add_game_widget(game_name, game_cfg)

    def _add_game_widget(self, game_name: str, game_cfg: dict):
        w = _GameConfigWidget(game_name, game_cfg)
        idx = self._game_layout.indexOf(self._save_game_btn)
        self._game_layout.insertWidget(idx, w)
        self._game_widgets.append(w)

    def _on_save_price_rules(self):
        rules = [row.get_data() for row in self._price_rows]
        settings = cfg.get_uhaozu_settings()
        settings["price_markup_rules"] = rules
        if cfg.save_uhaozu_settings(settings):
            QMessageBox.information(self, "提示", "加价规则已保存")
        else:
            QMessageBox.warning(self, "错误", "保存失败")

    def _on_save_game_configs(self):
        game_configs = {}
        for w in self._game_widgets:
            game_configs[w.game_name] = w.get_data()
        settings = cfg.get_uhaozu_settings()
        settings["game_configs"] = game_configs
        if cfg.save_uhaozu_settings(settings):
            QMessageBox.information(self, "提示", "游戏配置已保存")
        else:
            QMessageBox.warning(self, "错误", "保存失败")


# ── Tab4: 编号自动下单（预留）──────────────────────────────────────────────────

class OrderTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label = QLabel("🚧 功能开发中，敬请期待...")
        label.setStyleSheet("font-size: 18px; color: #aaa;")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)


# ── 主页面 ─────────────────────────────────────────────────────────────────────

class UHaozuPage(QWidget):
    """U号租专区主页面"""

    def __init__(self, db_client=None, parent=None):
        super().__init__(parent)
        self.db_client = db_client
        self.setStyleSheet(BASE_STYLE)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # 页面标题
        title = QLabel("U号租专区")
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #222; padding: 12px 16px 4px 16px;")
        layout.addWidget(title)

        # Tab 容器
        tabs = QTabWidget()
        tabs.addTab(AccountTab(), "账号管理")
        tabs.addTab(ExchangeTab(), "自动换号")
        tabs.addTab(SelectTab(), "自动选号")
        tabs.addTab(OrderTab(), "编号自动下单")
        layout.addWidget(tabs)
