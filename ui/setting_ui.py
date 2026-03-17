# -*- coding: utf-8 -*-
"""
设置界面（v2.0）
去掉 MySQL 配置，新增店铺同步管理区块。
"""
import sys
import logging

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFormLayout, QGroupBox, QMessageBox,
    QCheckBox, QScrollArea, QListWidget, QListWidgetItem,
)

import config as cfg
from core.server_api import ServerAPI

logger = logging.getLogger(__name__)

BASE_STYLE = '''
QWidget { background-color: #ffffff; color: #222222; }
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
QPushButton:disabled { background: #b0c4de; }
QCheckBox { color: #222; }
QLabel { color: #222; }
QListWidget { background: #fff; border: 1px solid #e0e0e0; border-radius: 4px; }
'''


class SyncShopsThread(QThread):
    """后台线程同步店铺列表"""
    result = pyqtSignal(bool, list, str)  # success, shops, error_msg

    def __init__(self, server_url: str, client_token: str):
        super().__init__()
        self._server_url = server_url
        self._client_token = client_token

    def run(self):
        api = ServerAPI(base_url=self._server_url)
        shops = api.client_get_shops(self._client_token)
        if shops is not None:
            self.result.emit(True, shops, "")
        else:
            self.result.emit(False, [], "获取店铺列表失败")


class SettingPage(QWidget):
    settings_saved = pyqtSignal()

    def __init__(self, db_client=None, parent=None):
        super().__init__(parent)
        # db_client 参数保留以兼容旧调用方，v2.0 中不使用
        self._sync_thread = None
        self._all_shops: list = []
        self.setStyleSheet(BASE_STYLE)
        self._init_ui()
        self._load_settings()

    def _init_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet('QScrollArea{border:none;background:#ffffff;}')

        content = QWidget()
        content.setStyleSheet('background:#ffffff;')
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        title = QLabel('⚙️ 设置')
        title.setStyleSheet('font-size:20px;font-weight:bold;color:#222;')
        layout.addWidget(title)

        # ── 服务器配置 ──────────────────────────────────────────────────────
        server_group = QGroupBox('aikefu 服务器配置')
        server_form = QFormLayout(server_group)
        self.server_url_edit = QLineEdit()
        self.server_url_edit.setPlaceholderText('http://8.145.43.255:5000')
        server_form.addRow('服务器地址:', self.server_url_edit)
        layout.addWidget(server_group)

        # ── 账号信息 ────────────────────────────────────────────────────────
        account_group = QGroupBox('账号信息')
        account_layout = QHBoxLayout(account_group)
        self.account_label = QLabel('未登录')
        self.account_label.setStyleSheet('color:#555;font-size:13px;')
        self.logout_btn = QPushButton('退出登录')
        self.logout_btn.setFixedWidth(90)
        self.logout_btn.setStyleSheet(
            'QPushButton{background:#e74c3c;color:white;border:none;border-radius:4px;padding:4px 10px;}'
            'QPushButton:hover{background:#c0392b;}'
        )
        self.logout_btn.clicked.connect(self._logout)
        account_layout.addWidget(self.account_label)
        account_layout.addStretch()
        account_layout.addWidget(self.logout_btn)
        layout.addWidget(account_group)

        # ── 拼多多店铺管理 ──────────────────────────────────────────────────
        shop_group = QGroupBox('拼多多店铺管理')
        shop_v = QVBoxLayout(shop_group)

        sync_row = QHBoxLayout()
        self.sync_btn = QPushButton('🔄 同步店铺列表')
        self.sync_btn.clicked.connect(self._sync_shops)
        self.sync_status = QLabel('')
        self.sync_status.setStyleSheet('color:#555;font-size:12px;')
        sync_row.addWidget(self.sync_btn)
        sync_row.addWidget(self.sync_status)
        sync_row.addStretch()
        shop_v.addLayout(sync_row)

        self.shop_list = QListWidget()
        self.shop_list.setMinimumHeight(120)
        self.shop_list.setMaximumHeight(200)
        shop_v.addWidget(self.shop_list)

        hint = QLabel('勾选后该店铺将自动注册插件并轮询任务')
        hint.setStyleSheet('color:#888;font-size:11px;')
        shop_v.addWidget(hint)

        layout.addWidget(shop_group)

        # ── 任务执行器全局设置 ──────────────────────────────────────────────
        runner_group = QGroupBox('任务执行器全局设置')
        runner_form = QFormLayout(runner_group)
        self.runner_enabled = QCheckBox('启用任务自动轮询')
        runner_form.addRow('', self.runner_enabled)
        self.runner_poll_edit = QLineEdit()
        self.runner_poll_edit.setPlaceholderText('2')
        self.runner_poll_edit.setFixedWidth(60)
        runner_form.addRow('轮询间隔（秒）:', self.runner_poll_edit)
        layout.addWidget(runner_group)

        # ── 系统设置 ────────────────────────────────────────────────────────
        sys_group = QGroupBox('系统设置')
        sys_form = QFormLayout(sys_group)
        self.notify_enabled = QCheckBox('启用桌面通知')
        self.startup_enabled = QCheckBox('开机自动启动')
        sys_form.addRow('', self.notify_enabled)
        sys_form.addRow('', self.startup_enabled)
        layout.addWidget(sys_group)

        # ── 保存按钮 ────────────────────────────────────────────────────────
        save_btn = QPushButton('💾  保存设置')
        save_btn.setFixedHeight(38)
        save_btn.clicked.connect(self._save_settings)
        layout.addWidget(save_btn)
        layout.addStretch()

        scroll.setWidget(content)
        outer.addWidget(scroll)

    def _load_settings(self):
        """从配置文件加载并填充 UI"""
        current = cfg.load_config()
        self.server_url_edit.setText(current.get('server_url', cfg.AIKEFU_SERVER))

        username = cfg.get_client_username()
        if username:
            self.account_label.setText(f'当前登录：{username}')
        else:
            self.account_label.setText('未登录')

        runner = current.get('task_runner', {})
        self.runner_enabled.setChecked(runner.get('enabled', False))
        self.runner_poll_edit.setText(str(runner.get('poll_interval', cfg.TASK_RUNNER_POLL_INTERVAL)))
        self.notify_enabled.setChecked(current.get('notify_enabled', True))
        self.startup_enabled.setChecked(current.get('startup_enabled', False))

        # 渲染已激活店铺
        self._render_shop_list(cfg.get_active_shops())

    def _render_shop_list(self, active_shops: list):
        """将店铺列表渲染到 QListWidget，使用复选框标记激活状态"""
        active_ids = {str(s.get('id', '')) for s in active_shops}
        self.shop_list.clear()

        if not self._all_shops:
            # 没有同步过，仅显示已激活店铺
            self._all_shops = list(active_shops)

        for shop in self._all_shops:
            shop_id = str(shop.get('id', ''))
            name = shop.get('name', '未知店铺')
            platform = shop.get('platform', 'pdd')
            platform_text = {'pdd': '拼多多', 'taobao': '淘宝', 'jd': '京东'}.get(platform, platform)

            item = QListWidgetItem(f"{name}（{platform_text}）")
            item.setData(Qt.ItemDataRole.UserRole, shop)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if shop_id in active_ids else Qt.CheckState.Unchecked
            )
            self.shop_list.addItem(item)

        if not self._all_shops:
            placeholder = QListWidgetItem('暂无店铺，请先点击「同步店铺列表」')
            placeholder.setForeground(Qt.GlobalColor.gray)
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self.shop_list.addItem(placeholder)

    def _sync_shops(self):
        """从服务端同步店铺列表"""
        client_token = cfg.get_client_token()
        if not client_token:
            self.sync_status.setText('❌ 请先登录账号')
            return

        server_url = self.server_url_edit.text().strip() or cfg.AIKEFU_SERVER
        self.sync_btn.setEnabled(False)
        self.sync_status.setText('同步中...')

        self._sync_thread = SyncShopsThread(server_url, client_token)
        self._sync_thread.result.connect(self._on_sync_result)
        self._sync_thread.start()

    def _on_sync_result(self, success: bool, shops: list, error_msg: str):
        self.sync_btn.setEnabled(True)
        if success:
            self._all_shops = shops
            self.sync_status.setText(f'✅ 同步成功，共 {len(shops)} 家店铺')
            self._render_shop_list(cfg.get_active_shops())
        else:
            self.sync_status.setText(f'❌ {error_msg}')

    def _get_checked_shops(self) -> list:
        """获取列表中被勾选的店铺"""
        result = []
        for i in range(self.shop_list.count()):
            item = self.shop_list.item(i)
            if item and item.checkState() == Qt.CheckState.Checked:
                shop = item.data(Qt.ItemDataRole.UserRole)
                if shop:
                    result.append(shop)
        return result

    def _logout(self):
        """退出登录：清除 client_token"""
        reply = QMessageBox.question(
            self, '退出登录', '确定要退出当前账号吗？',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        # 通知服务端登出（忽略失败）
        token = cfg.get_client_token()
        if token:
            try:
                server_url = self.server_url_edit.text().strip() or cfg.AIKEFU_SERVER
                ServerAPI(base_url=server_url).client_logout(token)
            except Exception:
                pass

        cfg.save_client_token('')
        cfg.save_client_username('')
        cfg.save_active_shops([])
        self.account_label.setText('未登录')
        self.shop_list.clear()
        QMessageBox.information(self, '已退出', '已退出登录，请重启客户端重新登录。')

    def _save_settings(self):
        """保存所有设置"""
        current = cfg.load_config()
        current['server_url'] = self.server_url_edit.text().strip() or cfg.AIKEFU_SERVER
        current['notify_enabled'] = self.notify_enabled.isChecked()
        current['startup_enabled'] = self.startup_enabled.isChecked()

        try:
            poll_interval = int(self.runner_poll_edit.text().strip() or str(cfg.TASK_RUNNER_POLL_INTERVAL))
        except ValueError:
            poll_interval = cfg.TASK_RUNNER_POLL_INTERVAL

        current['task_runner'] = {
            'enabled': self.runner_enabled.isChecked(),
            'poll_interval': poll_interval,
            'heartbeat_interval': cfg.TASK_RUNNER_HEARTBEAT_INTERVAL,
        }

        # 保存勾选的激活店铺
        checked = self._get_checked_shops()
        current['active_shops'] = checked

        if cfg.save_config(current):
            if self.startup_enabled.isChecked():
                self._setup_autostart()
            else:
                self._remove_autostart()
            QMessageBox.information(self, '成功', '设置已保存')
            self.settings_saved.emit()
        else:
            QMessageBox.critical(self, '错误', '保存失败')

    def _setup_autostart(self):
        if sys.platform != 'win32':
            return
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r'Software\Microsoft\Windows\CurrentVersion\Run', 0, winreg.KEY_SET_VALUE
            )
            winreg.SetValueEx(key, 'AiKeFuClient', 0, winreg.REG_SZ, sys.executable)
            winreg.CloseKey(key)
        except Exception as e:
            logger.warning('设置开机自启失败: %s', e)

    def _remove_autostart(self):
        if sys.platform != 'win32':
            return
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r'Software\Microsoft\Windows\CurrentVersion\Run', 0, winreg.KEY_SET_VALUE
            )
            try:
                winreg.DeleteValue(key, 'AiKeFuClient')
            except FileNotFoundError:
                pass
            winreg.CloseKey(key)
        except Exception as e:
            logger.warning('取消开机自启失败: %s', e)

    # 兼容旧 main_window 调用
    def set_db_client(self, db_client):
        pass

