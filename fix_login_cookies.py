content = open('channel/pinduoduo/pdd_login.py', encoding='utf-8').read()

old = '''            raw = await ctx.cookies()
            self.cookies = {c["name"]: c["value"] for c in raw}
            logger.info("店铺 %s cookies: %d个", self.shop_id, len(self.cookies))'''

new = '''            raw = await ctx.cookies()
            self.cookies = {c["name"]: c["value"] for c in raw}
            logger.info("店铺 %s cookies: %d个", self.shop_id, len(self.cookies))
            import json as _json
            _cookies_path = os.path.join(user_data_dir, "aikefu_cookies.json")
            try:
                with open(_cookies_path, "w", encoding="utf-8") as _f:
                    _json.dump(self.cookies, _f, ensure_ascii=False)
                logger.info("店铺 %s cookies已保存: %s", self.shop_id, _cookies_path)
            except Exception as _e:
                logger.warning("保存cookies失败: %s", _e)'''

if old in content:
    content = content.replace(old, new)
    open('channel/pinduoduo/pdd_login.py', 'w', encoding='utf-8').write(content)
    print('OK')
else:
    # 定位实际内容
    idx = content.find('raw = await ctx.cookies()')
    print('NOT FOUND, 附近内容:')
    print(repr(content[idx:idx+200]) if idx >= 0 else '找不到 raw = await ctx.cookies()')
