# -*- coding: utf-8 -*-
"""
账号登录弹窗（v2.0）
用 aikefu 后台账号密码登录，登录成功后将 client_token 保存到本地配置。
原来的 MySQL 配置弹窗已被此界面完全替代。
"""
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QMessageBox,
)

import config as cfg
from core.server_api import ServerAPI


class LoginThread(QThread):
    """后台线程执行登录请求，避免 UI 卡顿"""
    result = pyqtSignal(bool, str, str, str)  # success, client_token, username, error_msg

    def __init__(self, server_url: str, username: str, password: str):
        super().__init__()
        self._server_url = server_url
        self._username = username
        self._password = password

    def run(self):
        api = ServerAPI(base_url=self._server_url)
        data = api.client_login(self._username, self._password)
        if data.get("success"):
            self.result.emit(
                True,
                data.get("client_token", ""),
                data.get("username", self._username),
                "",
            )
        else:
            self.result.emit(False, "", "", data.get("error", "登录失败，请检查账号密码"))


class LoginDialog(QDialog):
    """账号密码登录弹窗"""

    login_success = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"🤖 {cfg.APP_NAME} v{cfg.APP_VERSION} - 登录")
        self.setFixedSize(420, 320)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self._login_thread = None
        self._init_ui()
        self._load_saved()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(36, 24, 36, 24)
        layout.setSpacing(14)

        # 标题
        title = QLabel(f"🤖 {cfg.APP_NAME} v{cfg.APP_VERSION}")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 17px; font-weight: bold; margin-bottom: 6px;")
        layout.addWidget(title)

        # 表单
        form = QFormLayout()
        form.setSpacing(10)

        self.server_edit = QLineEdit()
        self.server_edit.setPlaceholderText("http://8.145.43.255:5000")
        form.addRow("服务器地址:", self.server_edit)

        self.user_edit = QLineEdit()
        self.user_edit.setPlaceholderText("用户名")
        form.addRow("用    户:", self.user_edit)

        self.pass_edit = QLineEdit()
        self.pass_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.pass_edit.setPlaceholderText("密码")
        self.pass_edit.returnPressed.connect(self._do_login)
        form.addRow("密    码:", self.pass_edit)

        layout.addLayout(form)

        # 状态提示
        self.status_label = QLabel("")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet("color: #e74c3c; font-size: 12px;")
        layout.addWidget(self.status_label)

        # 登录按钮
        self.login_btn = QPushButton("🔗 登录")
        self.login_btn.setFixedHeight(36)
        self.login_btn.setDefault(True)
        self.login_btn.setStyleSheet(
            "QPushButton{background:#1890ff;color:white;border:none;border-radius:4px;font-size:14px;}"
            "QPushButton:hover{background:#40a9ff;}"
            "QPushButton:pressed{background:#096dd9;}"
            "QPushButton:disabled{background:#b0c4de;}"
        )
        self.login_btn.clicked.connect(self._do_login)
        layout.addWidget(self.login_btn)

        # 说明文字
        hint = QLabel("ℹ️ 使用 aikefu 后台的账号密码登录")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(hint)

    def _load_saved(self):
        """加载上次保存的服务器地址"""
        self.server_edit.setText(cfg.get_server_url())
        self.user_edit.setText(cfg.get_client_username())

    def _do_login(self):
        server_url = self.server_edit.text().strip() or cfg.AIKEFU_SERVER
        username = self.user_edit.text().strip()
        password = self.pass_edit.text()

        if not username:
            self._show_error("请填写用户名")
            return
        if not password:
            self._show_error("请填写密码")
            return

        self.login_btn.setEnabled(False)
        self.status_label.setText("登录中...")
        self.status_label.setStyleSheet("color: #1890ff; font-size: 12px;")

        # 保存服务器地址
        cfg_data = cfg.load_config()
        cfg_data["server_url"] = server_url
        cfg.save_config(cfg_data)

        self._login_thread = LoginThread(server_url, username, password)
        self._login_thread.result.connect(self._on_login_result)
        self._login_thread.start()

    def _on_login_result(self, success: bool, client_token: str, username: str, error_msg: str):
        self.login_btn.setEnabled(True)
        if success:
            cfg.save_client_token(client_token)
            cfg.save_client_username(username)
            self.status_label.setStyleSheet("color: #27ae60; font-size: 12px;")
            self.status_label.setText(f"✅ 登录成功！欢迎 {username}")
            self.login_success.emit()
            self.accept()
        else:
            self._show_error(error_msg or "登录失败，请检查账号密码或服务器地址")

    def _show_error(self, msg: str):
        self.status_label.setStyleSheet("color: #e74c3c; font-size: 12px;")
        self.status_label.setText(f"❌ {msg}")


# 保持向后兼容：原来 app.py 使用 SetupDialog
SetupDialog = LoginDialog

