content = open('channel/pinduoduo/pdd_transfer.py', encoding='utf-8').read()

# 修复：不用 persistent context，改用普通 browser + 注入 cookies，避免和采集线程抢 user_data_dir
old = '''    async def _ensure_browser(self, headless: bool = True):
        \"\"\"确保浏览器已启动并注入 cookies\"\"\"
        if self._browser is None:
            from playwright.async_api import async_playwright
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=headless,
                executable_path=self._get_chrome_path(),
            )
            self._context = await self._browser.new_context()
            if self.cookies:
                cookie_list = [
                    {"name": k, "value": v, "domain": ".pinduoduo.com",
                     "path": "/", "httpOnly": False, "secure": True}
                    for k, v in self.cookies.items()
                ]
                await self._context.add_cookies(cookie_list)
            self._page = await self._context.new_page()'''

new = '''    async def _ensure_browser(self, headless: bool = True):
        \"\"\"确保浏览器已启动并注入 cookies（普通模式，不占用 user_data_dir，避免和采集线程冲突）\"\"\"
        if self._browser is None:
            from playwright.async_api import async_playwright
            self._playwright = await async_playwright().start()
            # 使用普通 launch（非 persistent），避免和 pdd_login 的 persistent context 抢同一目录
            self._browser = await self._playwright.chromium.launch(
                headless=headless,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            self._context = await self._browser.new_context(
                locale="zh-CN",
                timezone_id="Asia/Shanghai",
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            )
            if self.cookies:
                cookie_list = [
                    {"name": k, "value": v, "domain": ".pinduoduo.com",
                     "path": "/", "httpOnly": False, "secure": True}
                    for k, v in self.cookies.items()
                ]
                await self._context.add_cookies(cookie_list)
                logger.info("已注入 %d 个cookies到转人工浏览器", len(self.cookies))
            else:
                logger.warning("转人工浏览器没有cookies，可能未登录！")
            self._page = await self._context.new_page()'''

if old in content:
    content = content.replace(old, new)
    open('channel/pinduoduo/pdd_transfer.py', 'w', encoding='utf-8').write(content)
    print('OK: pdd_transfer.py 修复完成')
else:
    print('NOT FOUND')
