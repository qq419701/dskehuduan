# -*- coding: utf-8 -*-
import asyncio, json, logging, os, shutil, requests
from playwright.async_api import async_playwright

logger = logging.getLogger(__name__)
PDD_LOGIN_URL = "https://mms.pinduoduo.com/"
BROWSER_DATA_DIR = os.path.join(os.path.expanduser("~"), ".aikefu-client", "browser_data")
_LOGIN_COUNTDOWN_SECONDS = 30  # 登录成功后的倒计时秒数


class PddLogin:
    def __init__(self, shop_id, db_client=None, shop_token=None, shop_name=None):
        self.shop_id = shop_id
        self.db_client = db_client
        self.shop_token = shop_token
        self.shop_name = shop_name or f"店铺{shop_id}"
        self.cookies = {}
        self.im_token = ""

    def get_user_data_dir(self):
        d = os.path.join(BROWSER_DATA_DIR, f"shop_{self.shop_id}")
        os.makedirs(d, exist_ok=True)
        return d

    def clear_browser_data(self):
        d = os.path.join(BROWSER_DATA_DIR, f"shop_{self.shop_id}")
        if os.path.exists(d):
            shutil.rmtree(d)
            logger.info("已清空店铺 %s 浏览器缓存", self.shop_id)
        os.makedirs(d, exist_ok=True)

    async def login(self, username="", password=""):
        user_data_dir = self.get_user_data_dir()
        logger.info("店铺 %s(%s) 开始登录流程", self.shop_id, self.shop_name)
        async with async_playwright() as pw:
            ctx = await pw.chromium.launch_persistent_context(
                user_data_dir,
                headless=False,
                args=["--no-sandbox"],
                locale="zh-CN",
                timezone_id="Asia/Shanghai",
            )
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()
            await page.goto(PDD_LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2)
            logger.info("店铺 %s 当前URL: %s", self.shop_id, page.url)
            logger.info("请在弹出的浏览器中登录【%s】的拼多多账号（最多等5分钟）", self.shop_name)

            try:
                # 等待通过登录页（URL 不再含 login/verify/captcha）
                await page.wait_for_function(
                    """() => {
                        const url = window.location.href;
                        return !url.includes('login') && !url.includes('verify') &&
                               !url.includes('captcha') && !url.includes('slide') &&
                               url.includes('mms.pinduoduo.com');
                    }""",
                    timeout=300000
                )
                logger.info("店铺 %s 已通过登录页，当前URL: %s", self.shop_id, page.url)

                # 注入30秒倒计时提示 + "立即保存并关闭"按钮
                await page.evaluate("""() => {
                    const div = document.createElement('div');
                    div.id = '__aikefu_countdown__';
                    div.style.cssText = 'position:fixed;top:20px;left:50%;transform:translateX(-50%);'
                        + 'background:rgba(0,0,0,0.82);color:#fff;padding:18px 40px;'
                        + 'border-radius:10px;font-size:18px;z-index:999999;text-align:center;'
                        + 'box-shadow:0 4px 16px rgba(0,0,0,0.4);min-width:340px;';
                    div.innerHTML = `
                        <div id="__aikefu_msg__">✅ 登录成功！30 秒后自动保存退出</div>
                        <button id="__aikefu_save_btn__" style="
                            margin-top:14px;padding:8px 28px;background:#27ae60;color:#fff;
                            border:none;border-radius:6px;font-size:16px;cursor:pointer;
                            box-shadow:0 2px 8px rgba(0,0,0,0.3);">
                            💾 立即保存并关闭
                        </button>`;
                    document.body.appendChild(div);
                    window.__aikefu_save_now__ = false;
                    document.getElementById('__aikefu_save_btn__').onclick = function() {
                        window.__aikefu_save_now__ = true;
                        document.getElementById('__aikefu_msg__').innerHTML = '💾 正在保存，请稍候...';
                        document.getElementById('__aikefu_save_btn__').disabled = true;
                    };
                    let s = 30;
                    const t = setInterval(() => {
                        s--;
                        if (!window.__aikefu_save_now__) {
                            document.getElementById('__aikefu_msg__').innerHTML = '✅ 登录成功！' + s + ' 秒后自动保存退出';
                        }
                        if (s <= 0) {
                            clearInterval(t);
                            window.__aikefu_save_now__ = true;
                            document.getElementById('__aikefu_msg__').innerHTML = '💾 正在保存，请稍候...';
                        }
                    }, 1000);
                }""")

                # 轮询等待：用户手动点击"立即保存"或倒计时结束
                elapsed = 0
                while elapsed < _LOGIN_COUNTDOWN_SECONDS:
                    await asyncio.sleep(0.5)
                    elapsed += 0.5
                    try:
                        save_now = await page.evaluate("() => !!window.__aikefu_save_now__")
                        if save_now:
                            logger.info("店铺 %s 用户手动点击保存，提前结束等待", self.shop_id)
                            break
                    except Exception:
                        break
                logger.info("店铺 %s 登录信息已采集，立即保存", self.shop_id)

            except Exception as e:
                logger.error("店铺 %s 等待超时: %s", self.shop_id, e)
                await ctx.close()
                return False

            raw = await ctx.cookies()
            self.cookies = {c["name"]: c["value"] for c in raw}
            has_token = "PDDAccessToken" in self.cookies
            logger.info(
                "店铺 %s cookies已收集: 共%d个，PDDAccessToken=%s",
                self.shop_id, len(self.cookies), "✓ 已获取" if has_token else "✗ 缺失！"
            )
            _cookies_path = os.path.join(user_data_dir, "aikefu_cookies.json")
            try:
                with open(_cookies_path, "w", encoding="utf-8") as _f:
                    json.dump(self.cookies, _f, ensure_ascii=False)
                logger.info("店铺 %s cookies已保存: %s", self.shop_id, _cookies_path)
            except Exception as _e:
                logger.warning("保存cookies失败: %s", _e)
            await self._fetch_im_token(page)
            logger.info("店铺 %s im_token: [%s]", self.shop_id,
                       self.im_token[:30] if self.im_token else "未获取到!")
            await ctx.close()

        if not self.im_token:
            logger.warning("店铺 %s 尝试用requests获取token", self.shop_id)
            await self._fetch_im_token_by_requests()

        logger.info("店铺 %s 登录完成 PDDAccessToken=%s im_token=%s",
                    self.shop_id,
                    "✓" if "PDDAccessToken" in self.cookies else "✗ 缺失",
                    "成功" if self.im_token else "失败")
        return True

    async def _fetch_im_token(self, page):
        # 方法1：通过浏览器内 fetch（带 credentials，最可靠）
        for fetch_url, body, content_type in [
            (
                "https://mms.pinduoduo.com/chats/getToken",
                "version=3",
                "application/x-www-form-urlencoded",
            ),
            (
                "https://mms.pinduoduo.com/chatbot/im/getImToken",
                "{}",
                "application/json",
            ),
        ]:
            try:
                resp = await page.evaluate(
                    f"""async () => {{
                        const r = await fetch("{fetch_url}",
                            {{method:"POST",
                             headers:{{"Content-Type":"{content_type}"}},
                             body:{json.dumps(body)},
                             credentials:"include"}});
                        return await r.text();
                    }}"""
                )
                logger.info("token响应(%s): %s", fetch_url, str(resp)[:300])
                data = json.loads(resp)
                token = (
                    data.get("token")
                    or (data.get("result") or {}).get("token")
                    or (data.get("result") or {}).get("imToken")
                    or (data.get("data") or {}).get("token")
                    or ""
                )
                if token:
                    self.im_token = token
                    logger.info("店铺 %s im_token获取成功(%s): %s...", self.shop_id, fetch_url, token[:20])
                    return
            except Exception as e:
                logger.warning("通过浏览器fetch获取token失败(%s): %s", fetch_url, e)

    async def _fetch_im_token_by_requests(self):
        if not self.cookies:
            return
        try:
            cookie_str = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
            r = requests.post(
                "https://mms.pinduoduo.com/chats/getToken",
                data={"version": "3"},
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Referer": "https://mms.pinduoduo.com/",
                    "Origin": "https://mms.pinduoduo.com",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Cookie": cookie_str,
                },
                timeout=10,
            )
            logger.info("requests token响应: %s", r.text[:300])
            data = r.json()
            token = (
                data.get("token")
                or (data.get("result") or {}).get("token")
                or (data.get("result") or {}).get("imToken")
                or ""
            )
            if token:
                self.im_token = token
                logger.info("店铺 %s im_token获取成功(requests): %s...", self.shop_id, token[:20])
        except Exception as e:
            logger.warning("requests获取token失败: %s", e)

    def get_page(self):
        return None

    async def close(self):
        pass
