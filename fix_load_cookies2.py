content = open('ui/main_window.py', encoding='utf-8').read()

old = '''    def _load_shop_cookies(self, shops: list) -> dict:
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
        return result'''

new = '''    def _load_shop_cookies(self, shops: list) -> dict:
        \"\"\"从持久化目录的 aikefu_cookies.json 读取已保存的 cookies（不启动浏览器，无冲突）\"\"\"
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
        return result'''

if old in content:
    content = content.replace(old, new)
    open('ui/main_window.py', 'w', encoding='utf-8').write(content)
    print('OK: _load_shop_cookies 修复完成')
else:
    # 找到实际的旧函数边界
    start = content.find('def _load_shop_cookies')
    end = content.find('\n    def ', start + 1)
    print('NOT FOUND，实际内容:')
    print(repr(content[start:end]))
