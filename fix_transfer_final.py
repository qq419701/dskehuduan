content = open('channel/pinduoduo/pdd_transfer.py', encoding='utf-8').read()

# 修复1：goto 超时和 wait_until
old1 = "await page.goto(url, wait_until=\"networkidle\", timeout=30000)"
new1 = "await page.goto(url, wait_until=\"domcontentloaded\", timeout=60000)"

# 修复2：_ensure_browser 改用普通 launch 不用 executable_path（避免找不到chrome报错）
old2 = '''    async def _ensure_browser(self, headless: bool = True):
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

new2 = '''    async def _ensure_browser(self, headless: bool = True):
        \"\"\"确保浏览器已启动并注入 cookies（普通模式，不抢 user_data_dir）\"\"\"
        if self._browser is None:
            from playwright.async_api import async_playwright
            self._playwright = await async_playwright().start()
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

ok = True
for old, new, name in [(old1, new1, 'goto timeout'), (old2, new2, '_ensure_browser')]:
    if old in content:
        content = content.replace(old, new)
        print(f'OK: {name}')
    else:
        print(f'NOT FOUND: {name}')
        ok = False

if ok:
    open('channel/pinduoduo/pdd_transfer.py', 'w', encoding='utf-8').write(content)
    print('=== 修复完成 ===')
else:
    print('=== 部分失败 ===')
