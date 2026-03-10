import os

# =============================================
# 修复1: pdd_transfer.py - 登录弹窗处理 + goto
# =============================================
t = open('channel/pinduoduo/pdd_transfer.py', encoding='utf-8').read()

# 在 goto 之后加上：关闭登录弹窗、检查是否被重定向到登录页
old_goto = '''            logger.info("打开拼多多聊天页面: %s", url)
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(2000)'''

new_goto = '''            logger.info("打开拼多多聊天页面: %s", url)
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(3000)

            # 检查是否被重定向到登录页（cookies失效）
            cur_url = page.url
            if "login" in cur_url or "verify" in cur_url or "passport" in cur_url:
                logger.error("cookies已失效，被重定向到登录页: %s", cur_url)
                return {"success": False, "agent": "", "message": "cookies已失效，请重新登录"}

            # 关闭可能出现的登录/验证弹窗
            for close_sel in ['[class*="dialog"] [class*="close"]', '[class*="modal"] [class*="close"]',
                               'button:has-text("关闭")', 'button:has-text("取消")',
                               '[class*="fullscreen-dialog"] button']:
                try:
                    el = await page.query_selector(close_sel)
                    if el:
                        await el.click()
                        await page.wait_for_timeout(500)
                        logger.info("已关闭弹窗: %s", close_sel)
                        break
                except Exception:
                    continue'''

if old_goto in t:
    t = t.replace(old_goto, new_goto)
    open('channel/pinduoduo/pdd_transfer.py', 'w', encoding='utf-8').write(t)
    print('OK: pdd_transfer.py goto+弹窗处理 修复完成')
else:
    print('SKIP/NOT FOUND: pdd_transfer.py goto已是新版或格式不匹配')
    idx = t.find('打开拼多多聊天页面')
    print('附近内容:', repr(t[idx:idx+200]))

# =============================================
# 修复2: pdd_login.py - 保存 aikefu_cookies.json
# =============================================
l = open('channel/pinduoduo/pdd_login.py', encoding='utf-8').read()

if 'aikefu_cookies.json' in l:
    print('SKIP: pdd_login.py 已有json保存逻辑')
else:
    old_login = '''            raw = await ctx.cookies()
            self.cookies = {c["name"]: c["value"] for c in raw}
            logger.info("店铺 %s cookies: %d个", self.shop_id, len(self.cookies))'''

    new_login = '''            raw = await ctx.cookies()
            self.cookies = {c["name"]: c["value"] for c in raw}
            logger.info("店铺 %s cookies: %d个", self.shop_id, len(self.cookies))
            # 保存cookies到json文件，供transfer使用（不启动浏览器，无冲突）
            import json as _json
            _cookies_path = os.path.join(user_data_dir, "aikefu_cookies.json")
            try:
                with open(_cookies_path, "w", encoding="utf-8") as _f:
                    _json.dump(self.cookies, _f, ensure_ascii=False)
                logger.info("店铺 %s cookies已保存: %s", self.shop_id, _cookies_path)
            except Exception as _e:
                logger.warning("保存cookies失败: %s", _e)'''

    if old_login in l:
        l = l.replace(old_login, new_login)
        open('channel/pinduoduo/pdd_login.py', 'w', encoding='utf-8').write(l)
        print('OK: pdd_login.py json保存 修复完成')
    else:
        idx = l.find('ctx.cookies()')
        print('NOT FOUND pdd_login.py，附近:', repr(l[idx:idx+200]))
