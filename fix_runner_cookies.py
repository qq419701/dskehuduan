content = open('ui/main_window.py', encoding='utf-8').read()

# 修复1：_start_task_runners 改为从浏览器缓存读取 cookies 传入 runner
old1 = '''        from core.task_runner import MultiShopTaskRunner
        self._multi_runner = MultiShopTaskRunner(
            server_url=server_url,
            shops=active_shops,
            poll_interval=runner_cfg.get(\"poll_interval\", cfg.TASK_RUNNER_POLL_INTERVAL),
            heartbeat_interval=runner_cfg.get(\"heartbeat_interval\", cfg.TASK_RUNNER_HEARTBEAT_INTERVAL),
        )'''

new1 = '''        from core.task_runner import MultiShopTaskRunner
        # 从浏览器持久化目录读取各店铺已保存的 cookies
        shop_cookies_map = self._load_shop_cookies(active_shops)
        self._multi_runner = MultiShopTaskRunner(
            server_url=server_url,
            shops=active_shops,
            poll_interval=runner_cfg.get(\"poll_interval\", cfg.TASK_RUNNER_POLL_INTERVAL),
            heartbeat_interval=runner_cfg.get(\"heartbeat_interval\", cfg.TASK_RUNNER_HEARTBEAT_INTERVAL),
            shop_cookies_map=shop_cookies_map,
        )'''

# 修复2：ChannelWorker 登录成功后回传 cookies 给 runner
old2 = '''        self._channel.set_message_callback(on_message)
        self._channel.is_running = True
        self.status_changed.emit(shop_id, True)'''

new2 = '''        self._channel.set_message_callback(on_message)
        self._channel.is_running = True
        self.status_changed.emit(shop_id, True)
        # 登录成功后把 cookies 同步给 task_runner
        self.cookies_ready.emit(str(shop_id), self._pdd_login.cookies)'''

# 修复3：ChannelWorker 增加 cookies_ready 信号
old3 = '''    message_received = pyqtSignal(int, dict)  # shop_id, msg
    status_changed = pyqtSignal(int, bool)    # shop_id, is_running'''

new3 = '''    message_received = pyqtSignal(int, dict)  # shop_id, msg
    status_changed = pyqtSignal(int, bool)    # shop_id, is_running
    cookies_ready = pyqtSignal(str, dict)     # shop_id, cookies'''

# 修复4：MainWindow 连接 cookies_ready 信号
old4 = '''        worker.message_received.connect(self.message_page.add_message)
        worker.status_changed.connect(self._on_status_changed)'''

new4 = '''        worker.message_received.connect(self.message_page.add_message)
        worker.status_changed.connect(self._on_status_changed)
        worker.cookies_ready.connect(self._on_shop_cookies_ready)'''

# 修复5：增加辅助方法（在 closeEvent 前插入）
old5 = '''    def closeEvent(self, event):'''

new5 = '''    def _load_shop_cookies(self, shops: list) -> dict:
        \"\"\"从 Playwright 浏览器持久化目录读取已保存的 cookies\"\"\"
        import os, json as _json
        from playwright.sync_api import sync_playwright
        result = {}
        browser_base = os.path.join(os.path.expanduser("~"), ".aikefu-client", "browser_data")
        for shop in shops:
            shop_id = str(shop.get("id", ""))
            user_data_dir = os.path.join(browser_base, f"shop_{shop_id}")
            cookies_file = os.path.join(user_data_dir, "Default", "Cookies")
            if not os.path.exists(user_data_dir):
                continue
            try:
                with sync_playwright() as pw:
                    ctx = pw.chromium.launch_persistent_context(
                        user_data_dir, headless=True,
                        args=["--no-sandbox"],
                    )
                    raw = ctx.cookies(["https://mms.pinduoduo.com"])
                    ctx.close()
                cookies = {c["name"]: c["value"] for c in raw if c.get("value")}
                if cookies:
                    result[shop_id] = cookies
                    logger.info("已从缓存读取店铺 %s cookies: %d个", shop_id, len(cookies))
            except Exception as e:
                logger.warning("读取店铺 %s cookies失败: %s", shop_id, e)
        return result

    def _on_shop_cookies_ready(self, shop_id: str, cookies: dict):
        \"\"\"店铺登录成功后更新 task_runner 的 cookies\"\"\"
        if self._multi_runner and cookies:
            self._multi_runner.update_shop_cookies(shop_id, cookies)
            logger.info("已更新店铺 %s 的 cookies 到 task_runner", shop_id)

    def closeEvent(self, event):'''

ok = True
for old, new, name in [(old1,new1,'runner cookies_map'), (old2,new2,'cookies_ready emit'),
                        (old3,new3,'signal def'), (old4,new4,'signal connect'), (old5,new5,'helper methods')]:
    if old in content:
        content = content.replace(old, new)
        print(f'OK: {name}')
    else:
        print(f'NOT FOUND: {name}')
        ok = False

if ok:
    open('ui/main_window.py', 'w', encoding='utf-8').write(content)
    print('=== 全部修复完成，请重启客户端 ===')
else:
    print('=== 部分修复失败，请查看上方报错 ===')
