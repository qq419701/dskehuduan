# -*- coding: utf-8 -*-
"""
U号租专区（v2.0 全新重写）
分为五个子Tab：账号管理、自动换号、自动选号、自动下单、任务记录
大部分功能为骨架预留，接口已留出，后续逐步实现。
U号租账号列表从 aikefu 服务端 API 获取（而非本地 MySQL）。
"""
import logging
import os
from datetime import datetime

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QTabWidget, QTableWidget, QTableWidgetItem, QHeaderView,
    QGroupBox, QFormLayout, QTextEdit, QMessageBox, QScrollArea,
    QSizePolicy,
)

import config as cfg
from core.server_api import ServerAPI

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
QTableWidget { border: 1px solid #e0e0e0; border-radius: 4px; gridline-color: #f0f0f0; }
QTableWidget::item { padding: 4px; }
QTableWidget::item:selected { background: #e6f7ff; color: #1890ff; }
QLabel { color: #222; }
'''

# ---------------------------------------------------------------------------
# 辅助：骨架占位页
# ---------------------------------------------------------------------------

def _make_coming_soon(title: str, desc: str = "") -> QWidget:
    """创建'即将上线'占位页"""
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lbl = QLabel(f"🚧 {title}")
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lbl.setStyleSheet("font-size:22px;font-weight:bold;color:#bbb;")
    lay.addWidget(lbl)
    sub = QLabel(desc or "该功能正在开发中，敬请期待")
    sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
    sub.setStyleSheet("font-size:13px;color:#ccc;margin-top:8px;")
    lay.addWidget(sub)
    return w


# ---------------------------------------------------------------------------
# Tab 1：账号管理
# ---------------------------------------------------------------------------

class FetchAccountsThread(QThread):
    """后台拉取 U号租账号列表"""
    result = pyqtSignal(bool, list, str)

    def __init__(self, server_url: str, client_token: str):
        super().__init__()
        self._server_url = server_url
        self._client_token = client_token

    def run(self):
        # 预留接口：GET /api/uhaozu/accounts
        try:
            api = ServerAPI(base_url=self._server_url)
            resp = api.session.get(
                f"{api.base_url}/api/uhaozu/accounts",
                headers={"X-Client-Token": self._client_token},
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                accounts = data if isinstance(data, list) else data.get("accounts", [])
                self.result.emit(True, accounts, "")
            elif resp.status_code == 404:
                # 接口尚未实现
                self.result.emit(True, [], "（接口开发中，暂无数据）")
            else:
                self.result.emit(False, [], f"服务器返回 {resp.status_code}")
        except Exception as e:
            self.result.emit(False, [], str(e))


class AccountTab(QWidget):
    """Tab 1：账号管理"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._fetch_thread = None
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # 工具栏
        top = QHBoxLayout()
        title = QLabel("U号租账号管理")
        title.setStyleSheet("font-size:15px;font-weight:bold;")
        top.addWidget(title)
        top.addStretch()
        self.refresh_btn = QPushButton("🔄 从服务端获取")
        self.refresh_btn.clicked.connect(self._fetch_accounts)
        top.addWidget(self.refresh_btn)
        layout.addLayout(top)

        self.status_label = QLabel("点击「从服务端获取」拉取账号列表")
        self.status_label.setStyleSheet("color:#888;font-size:12px;")
        layout.addWidget(self.status_label)

        # 表格
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["账号ID", "用户名", "平台", "备注"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self.table)

        hint = QLabel("ℹ️ 账号管理功能（添加/删除/设默认）持续开发中")
        hint.setStyleSheet("color:#aaa;font-size:11px;")
        layout.addWidget(hint)

    def _fetch_accounts(self):
        token = cfg.get_client_token()
        if not token:
            self.status_label.setText("❌ 请先登录账号")
            return
        server_url = cfg.get_server_url()
        self.refresh_btn.setEnabled(False)
        self.status_label.setText("获取中...")
        self._fetch_thread = FetchAccountsThread(server_url, token)
        self._fetch_thread.result.connect(self._on_result)
        self._fetch_thread.start()

    def _on_result(self, success: bool, accounts: list, msg: str):
        self.refresh_btn.setEnabled(True)
        if success:
            self.table.setRowCount(0)
            for acc in accounts:
                row = self.table.rowCount()
                self.table.insertRow(row)
                self.table.setItem(row, 0, QTableWidgetItem(str(acc.get("id", ""))))
                self.table.setItem(row, 1, QTableWidgetItem(acc.get("username", "")))
                self.table.setItem(row, 2, QTableWidgetItem(acc.get("platform", "U号租")))
                self.table.setItem(row, 3, QTableWidgetItem(acc.get("remark", "")))
            info = msg or f"共 {len(accounts)} 个账号"
            self.status_label.setText(f"✅ {info}")
        else:
            self.status_label.setText(f"❌ 获取失败：{msg}")


# ---------------------------------------------------------------------------
# Tab 2：自动换号
# ---------------------------------------------------------------------------

class ExchangeTab(QWidget):
    """Tab 2：自动换号"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel("自动换号")
        title.setStyleSheet("font-size:15px;font-weight:bold;")
        layout.addWidget(title)

        desc = QLabel(
            "买家触发换号请求后，aikefu 服务端会下发 <code>auto_exchange</code> 任务，"
            "客户端的任务执行器会自动调用 U号租换号接口完成操作。"
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color:#555;font-size:12px;")
        layout.addWidget(desc)

        # 手动触发测试
        test_group = QGroupBox("手动测试换号")
        test_layout = QFormLayout(test_group)
        self.order_id_edit = QLineEdit()
        self.order_id_edit.setPlaceholderText("输入拼多多订单号")
        test_layout.addRow("订单号:", self.order_id_edit)
        self.test_btn = QPushButton("▶ 触发换号测试")
        self.test_btn.clicked.connect(self._trigger_test)
        test_layout.addRow("", self.test_btn)
        self.test_result = QLabel("")
        self.test_result.setStyleSheet("color:#555;font-size:12px;")
        test_layout.addRow("结果:", self.test_result)
        layout.addWidget(test_group)

        # 任务队列（来自插件任务系统）
        queue_group = QGroupBox("换号任务队列（最近10条）")
        queue_layout = QVBoxLayout(queue_group)
        self.queue_table = QTableWidget(0, 4)
        self.queue_table.setHorizontalHeaderLabels(["任务ID", "订单号", "状态", "时间"])
        self.queue_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.queue_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        queue_layout.addWidget(self.queue_table)
        layout.addWidget(queue_group)
        layout.addStretch()

    def _trigger_test(self):
        order_id = self.order_id_edit.text().strip()
        if not order_id:
            self.test_result.setText("❌ 请填写订单号")
            return
        self.test_result.setText(f"⏳ 已提交换号请求，订单号: {order_id}（功能开发中）")

    def add_task_record(self, task_id: str, order_id: str, status: str):
        """从外部添加任务记录到队列表格"""
        row = 0
        self.queue_table.insertRow(row)
        self.queue_table.setItem(row, 0, QTableWidgetItem(task_id))
        self.queue_table.setItem(row, 1, QTableWidgetItem(order_id))
        self.queue_table.setItem(row, 2, QTableWidgetItem(status))
        self.queue_table.setItem(row, 3, QTableWidgetItem(datetime.now().strftime("%H:%M:%S")))
        # 只保留最近10条
        while self.queue_table.rowCount() > 10:
            self.queue_table.removeRow(self.queue_table.rowCount() - 1)


# ---------------------------------------------------------------------------
# Tab 5：任务记录
# ---------------------------------------------------------------------------

class TaskRecordTab(QWidget):
    """Tab 5：任务记录（从本地日志读取最近记录）"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()
        self._load_logs()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        top = QHBoxLayout()
        title = QLabel("任务记录")
        title.setStyleSheet("font-size:15px;font-weight:bold;")
        top.addWidget(title)
        top.addStretch()
        refresh_btn = QPushButton("🔄 刷新")
        refresh_btn.clicked.connect(self._load_logs)
        top.addWidget(refresh_btn)
        layout.addLayout(top)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setStyleSheet(
            "font-family:Consolas,monospace;font-size:11px;"
            "background:#1e1e1e;color:#d4d4d4;border:none;"
        )
        layout.addWidget(self.log_view)

    def _load_logs(self):
        """从本地日志文件读取最近200行"""
        log_dir = os.path.join(os.path.expanduser("~"), ".aikefu-client", "logs")
        log_file = os.path.join(log_dir, "aikefu-client.log")
        if not os.path.exists(log_file):
            self.log_view.setPlainText("（暂无日志文件）")
            return
        try:
            with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            last_200 = "".join(lines[-200:])
            self.log_view.setPlainText(last_200)
            # 滚动到末尾
            cursor = self.log_view.textCursor()
            from PyQt6.QtGui import QTextCursor
            cursor.movePosition(QTextCursor.MoveOperation.End)
            self.log_view.setTextCursor(cursor)
        except Exception as e:
            self.log_view.setPlainText(f"读取日志失败: {e}")


# ---------------------------------------------------------------------------
# 主页面：UHaozuPage
# ---------------------------------------------------------------------------

class UHaozuPage(QWidget):
    """U号租专区主页面（v2.0）"""

    def __init__(self, db_client=None, parent=None):
        super().__init__(parent)
        # db_client 保留以兼容旧调用，v2.0 不使用
        self.setStyleSheet(BASE_STYLE)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel("🎮 U号租专区")
        title.setStyleSheet("font-size:20px;font-weight:bold;")
        layout.addWidget(title)

        tabs = QTabWidget()
        tabs.setStyleSheet(BASE_STYLE)

        # Tab 1：账号管理
        self.account_tab = AccountTab()
        tabs.addTab(self.account_tab, "账号管理")

        # Tab 2：自动换号
        self.exchange_tab = ExchangeTab()
        tabs.addTab(self.exchange_tab, "自动换号")

        # Tab 3：自动选号（骨架）
        tabs.addTab(
            _make_coming_soon("自动选号", "根据买家需求自动匹配并选取合适账号"),
            "自动选号"
        )

        # Tab 4：自动下单（骨架）
        tabs.addTab(
            _make_coming_soon("自动下单", "自动完成拼多多下单流程"),
            "自动下单"
        )

        # Tab 5：任务记录
        self.record_tab = TaskRecordTab()
        tabs.addTab(self.record_tab, "任务记录")

        layout.addWidget(tabs)

    def set_db_client(self, db_client):
        """兼容旧接口"""
        pass
