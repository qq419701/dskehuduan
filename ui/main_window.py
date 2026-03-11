# -*- coding: utf-8 -*-
"""
主窗口（v2.0）
启动流程：检查 client_token → 无则弹出登录弹窗 → 登录成功后进入主界面。
导航栏：首页 | 拼多多店铺 | 消息监控 | 🔌 插件状态 | U号租专区 | 📖 帮助文档 | ⚙️ 设置
"""
import asyncio
import logging
import time

from PyQt6.QtCore import Qt, pyqtSignal, QThread
from PyQt6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon, QMenu

try:
    from qfluentwidgets import (
        FluentWindow, NavigationItemPosition, FluentIcon,
        setTheme, Theme,
    )
    HAS_FLUENT = True
except ImportError:
    from PyQt6.QtWidgets import QMainWindow as FluentWindow
    HAS_FLUENT = False

from ui.dashboard_ui import DashboardPage
from ui.shop_ui import ShopPage
from ui.message_ui import MessagePage
from ui.setting_ui import SettingPage
from ui.uhaozu_ui import UHaozuPage
from ui.plugin_status_ui import PluginStatusPage
from ui.help_ui import HelpPage
from ui.pdd_settings_ui import PddSettingsPage
from core.server_api import ServerAPI
import config as cfg

logger = logging.getLogger(__name__)


class ChannelWorker(QThread):
    """在独立线程中运行采集渠道的 asyncio 事件循环"""

    message_received = pyqtSignal(int, dict)  # shop_id, msg
    status_changed = pyqtSignal(int, bool)    # shop_id, is_running
    cookies_ready = pyqtSignal(str, dict)     # shop_id, cookies

    def __init__(self, shop_info: dict, server_api: ServerAPI, parent=None):
        super().__init__(parent)
        self.shop_info = shop_info
        self.server_api = server_api
        self._channel = None
        self._loop = None
        self._running = True

    def run(self):
        MAX_RETRIES = 5
        retry_count = 0
        while self._running and retry_count < MAX_RETRIES:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            try:
                self._loop.run_until_complete(self._start_channel())
                break  # 正常退出，不重启
            except Exception as e:
                retry_count += 1
                err_str = str(e)
                # 浏览器被关闭是可恢复的异常，自动重启
                if "Target page, context or browser has been closed" in err_str or \
                   "Browser has been closed" in err_str:
                    logger.warning(
                        "采集线程异常（浏览器关闭），%d秒后自动重启（第%d次）: %s",
                        5 * retry_count, retry_count, err_str[:100],
                    )
                    time.sleep(5 * retry_count)  # 指数退避
                    continue
                else:
                    logger.error("采集线程异常: %s", e)
                    break
            finally:
                try:
                    self._loop.close()
                except Exception:
                    pass

    async def _start_channel(self):
        from channel.pinduoduo.pdd_login import PddLogin
        from channel.pinduoduo.pdd_channel import PddChannel
        from channel.pinduoduo.pdd_sender import PddSender

        shop_token = self.shop_info.get("shop_token", "")
        shop_id = self.shop_info.get("id", self.shop_info.get("shop_id"))

        # 登录（使用 shop_token，不依赖 MySQL）
        self._pdd_login = PddLogin(
            shop_id=shop_id,
            db_client=None,
            shop_token=shop_token,
            shop_name=self.shop_info.get("name", ""),
        )
        success = await self._pdd_login.login()
        if not success:
            logger.error("店铺 %s 登录失败", shop_id)
            self.status_changed.emit(shop_id, False)
            return

        sender = PddSender(cookies=self._pdd_login.cookies, shop_id=shop_id)

        self._channel = PddChannel(
            shop_id=shop_id,
            shop_info=self.shop_info,
            im_token=self._pdd_login.im_token,
            cookies=self._pdd_login.cookies,
            db_client=None,
            server_api=self.server_api,
            sender=sender,
        )

        def on_message(sid, msg):
            self.message_received.emit(sid, msg)

        self._channel.set_message_callback(on_message)
        self._channel.is_running = True
        self.status_changed.emit(shop_id, True)
        # 登录成功后把 cookies 同步给 task_runner
        self.cookies_ready.emit(str(shop_id), self._pdd_login.cookies)

        await self._channel.run_with_reconnect()
        self.status_changed.emit(shop_id, False)

    def stop_channel(self):
        self._running = False
        if self._channel and self._loop:
            self._loop.call_soon_threadsafe(
                lambda: self._loop.create_task(self._channel.stop())
            )


class MainWindow(FluentWindow):
    """爱客服采集客户端主窗口（v2.0）"""

    def __init__(self):
        super().__init__()
        self.server_api: ServerAPI = None
        self._workers: dict = {}        # shop_id -> ChannelWorker
        self._multi_runner = None       # MultiShopTaskRunner 实例

        self._check_login()
        self._init_ui()
        self._setup_tray()
        self._start_task_runners()

    def _check_login(self):
        """检查登录状态，未登录则弹出登录弹窗"""
        if not cfg.is_logged_in():
            from ui.login_ui import LoginDialog
            dialog = LoginDialog()
            result = dialog.exec()
            if result != LoginDialog.DialogCode.Accepted:
                import sys
                logger.info("用户取消登录，退出")
                sys.exit(0)

        server_url = cfg.get_server_url()
        self.server_api = ServerAPI(base_url=server_url)

    def _init_ui(self):
        self.setWindowTitle(f"{cfg.APP_NAME} v{cfg.APP_VERSION}")
        self.resize(1280, 800)

        # 创建页面
        self.dashboard_page = DashboardPage()
        self.shop_page = ShopPage()
        self.pdd_settings_page = PddSettingsPage()
        self.message_page = MessagePage()
        self.plugin_status_page = PluginStatusPage()
        self.uhaozu_page = UHaozuPage()
        self.help_page = HelpPage()
        self.setting_page = SettingPage()

        # 连接信号
        self.shop_page.channel_start_requested.connect(self._start_shop)
        self.shop_page.channel_stop_requested.connect(self._stop_shop)
        self.setting_page.settings_saved.connect(self._on_settings_saved)
        self.plugin_status_page.shop_start_requested.connect(self._start_shop_by_id)
        self.plugin_status_page.shop_stop_requested.connect(self._stop_shop_by_id)

        if HAS_FLUENT:
            self._add_fluent_pages()
        else:
            self._add_basic_pages()

    def _add_fluent_pages(self):
        from qfluentwidgets import FluentIcon

        self.dashboard_page.setObjectName("dashboardPage")
        self.shop_page.setObjectName("shopPage")
        self.pdd_settings_page.setObjectName("pddSettingsPage")
        self.message_page.setObjectName("messagePage")
        self.plugin_status_page.setObjectName("pluginStatusPage")
        self.uhaozu_page.setObjectName("uhaozuPage")
        self.help_page.setObjectName("helpPage")
        self.setting_page.setObjectName("settingPage")

        self.addSubInterface(self.dashboard_page, FluentIcon.HOME, "首页")
        self.addSubInterface(self.shop_page, FluentIcon.SHOPPING_CART, "拼多多店铺")
        self.addSubInterface(self.pdd_settings_page, FluentIcon.SETTING, "拼多多设置")
        self.addSubInterface(self.message_page, FluentIcon.CHAT, "消息监控")

        # 插件状态图标
        plugin_icon = getattr(FluentIcon, "DEVELOPER_TOOLS",
                     getattr(FluentIcon, "CODE", FluentIcon.SETTING))
        self.addSubInterface(self.plugin_status_page, plugin_icon, "🔌 插件状态")

        uhaozu_icon = getattr(FluentIcon, "SPEED",
                     getattr(FluentIcon, "GAME", FluentIcon.SETTING))
        self.addSubInterface(self.uhaozu_page, uhaozu_icon, "U号租专区")

        help_icon = getattr(FluentIcon, "HELP",
                   getattr(FluentIcon, "QUESTION", FluentIcon.SETTING))
        self.addSubInterface(self.help_page, help_icon, "📖 帮助文档")

        self.addSubInterface(
            self.setting_page,
            FluentIcon.SETTING,
            "设置",
            NavigationItemPosition.BOTTOM,
        )

    def _add_basic_pages(self):
        from PyQt6.QtWidgets import QTabWidget
        tabs = QTabWidget()
        tabs.addTab(self.dashboard_page, "首页")
        tabs.addTab(self.shop_page, "拼多多店铺")
        tabs.addTab(self.pdd_settings_page, "拼多多设置")
        tabs.addTab(self.message_page, "消息监控")
        tabs.addTab(self.plugin_status_page, "🔌 插件状态")
        tabs.addTab(self.uhaozu_page, "U号租专区")
        tabs.addTab(self.help_page, "📖 帮助文档")
        tabs.addTab(self.setting_page, "设置")
        self.setCentralWidget(tabs)

    def _setup_tray(self):
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setToolTip(cfg.APP_NAME)
        tray_menu = QMenu()
        show_action = tray_menu.addAction("显示主界面")
        show_action.triggered.connect(self.show)
        quit_action = tray_menu.addAction("退出")
        quit_action.triggered.connect(QApplication.quit)
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self._on_tray_activated)
        self.tray_icon.show()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show()
            self.activateWindow()

    def _start_task_runners(self):
        """根据配置启动多店铺任务执行器"""
        active_shops = cfg.get_active_shops()
        if not active_shops:
            logger.info("没有已激活的店铺，跳过任务执行器启动")
            return

        runner_cfg = cfg.get_task_runner_config()
        server_url = cfg.get_server_url()  # 读取用户设置的服务器地址

        from core.task_runner import MultiShopTaskRunner
        # 从浏览器持久化目录读取各店铺已保存的 cookies
        shop_cookies_map = self._load_shop_cookies(active_shops)
        self._multi_runner = MultiShopTaskRunner(
            server_url=server_url,
            shops=active_shops,
            poll_interval=runner_cfg.get("poll_interval", cfg.TASK_RUNNER_POLL_INTERVAL),
            heartbeat_interval=runner_cfg.get("heartbeat_interval", cfg.TASK_RUNNER_HEARTBEAT_INTERVAL),
            shop_cookies_map=shop_cookies_map,
        )
        # 注入 runner 到插件状态页
        self.plugin_status_page.set_runner(self._multi_runner)

        # 用独立线程运行 asyncio event loop，不影响 Qt 主线程
        import threading
        runner = self._multi_runner  # 捕获引用，防止 lambda 闭包问题
        try:
            t = threading.Thread(
                target=lambda: asyncio.run(runner.start_all()),
                daemon=True,
            )
            t.start()
            logger.info("MultiShopTaskRunner 已在后台线程启动，server=%s，店铺数=%d",
                        server_url, len(active_shops))
        except Exception as e:
            logger.warning("MultiShopTaskRunner 启动失败: %s", e)

    def _start_shop(self, shop_info: dict):
        """启动某个店铺的消息采集"""
        shop_id = str(shop_info.get("id", shop_info.get("shop_id", "")))
        if not shop_id:
            return
        if shop_id in self._workers:
            logger.warning("店铺 %s 已在运行", shop_id)
            return
        if not self.server_api:
            QMessageBox.warning(self, "提示", "请先完成登录配置")
            return

        worker = ChannelWorker(shop_info=shop_info, server_api=self.server_api, parent=self)
        worker.message_received.connect(self.message_page.add_message)
        worker.status_changed.connect(self._on_status_changed)
        worker.cookies_ready.connect(self._on_shop_cookies_ready)
        self._workers[shop_id] = worker
        worker.start()
        logger.info("已启动店铺 %s 的采集线程", shop_id)

    def _stop_shop(self, shop_info: dict):
        """停止店铺采集"""
        shop_id = str(shop_info.get("id", shop_info.get("shop_id", "")))
        self._stop_shop_by_id(shop_id)

    def _start_shop_by_id(self, shop_id: str):
        """插件状态页触发：启动店铺执行器"""
        active_shops = cfg.get_active_shops()
        for shop in active_shops:
            if str(shop.get("id", "")) == shop_id:
                self._start_shop(shop)
                return

    def _stop_shop_by_id(self, shop_id: str):
        """插件状态页触发：停止店铺执行器"""
        worker = self._workers.pop(shop_id, None)
        if worker:
            worker.stop_channel()
            worker.quit()
            worker.wait(5000)

    def _on_status_changed(self, shop_id, is_running: bool):
        self.shop_page.set_shop_running(shop_id, is_running)
        if not is_running:
            self._workers.pop(str(shop_id), None)
        self.plugin_status_page._refresh_status()

    def _on_settings_saved(self):
        """设置保存后刷新相关页面"""
        server_url = cfg.get_server_url()
        self.server_api = ServerAPI(base_url=server_url)
        self.shop_page.load_shops()
        self.plugin_status_page.refresh()
        # 重启任务执行器（使用新的服务器地址和店铺列表）
        old_runner = self._multi_runner
        self._multi_runner = None
        if old_runner:
            import threading
            threading.Thread(
                target=lambda: asyncio.run(old_runner.stop_all()),
                daemon=True,
            ).start()
        self._start_task_runners()

    def _load_shop_cookies(self, shops: list) -> dict:
        """从持久化目录的 aikefu_cookies.json 读取已保存的 cookies（不启动浏览器，无冲突）"""
        import os, json as _json
        result = {}
        browser_base = os.path.join(os.path.expanduser("~"), ".aikefu-client", "browser_data")
        for shop in shops:
            shop_id = str(shop.get("id", ""))
            cookies_json = os.path.join(browser_base, f"shop_{shop_id}", "aikefu_cookies.json")
            if os.path.exists(cookies_json):
                try:
                    with open(cookies_json, encoding="utf-8") as f:
                        cookies = _json.load(f)
                    if cookies:
                        result[shop_id] = cookies
                        logger.info("已读取店铺 %s 缓存cookies: %d个", shop_id, len(cookies))
                except Exception as e:
                    logger.warning("读取店铺 %s cookies失败: %s", shop_id, e)
            else:
                logger.warning("店铺 %s 无缓存cookies，请先启动采集登录", shop_id)
        return result

    def _on_shop_cookies_ready(self, shop_id: str, cookies: dict):
        """店铺登录成功后更新 task_runner 的 cookies"""
        if self._multi_runner and cookies:
            self._multi_runner.update_shop_cookies(shop_id, cookies)
            logger.info("已更新店铺 %s 的 cookies 到 task_runner", shop_id)

    def closeEvent(self, event):
        event.ignore()
        self.hide()
        self.tray_icon.showMessage(
            cfg.APP_NAME,
            "程序已最小化到系统托盘，双击图标可重新显示",
            QSystemTrayIcon.MessageIcon.Information,
            3000,
        )


