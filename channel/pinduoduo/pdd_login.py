# -*- coding: utf-8 -*-
"""
拼多多登录模块
使用 Playwright 登录拼多多商家后台，获取 Cookie 和 IM Token
"""
import asyncio
import logging
import os
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

PDD_LOGIN_URL = "https://mms.pinduoduo.com/login"
PDD_HOME_URL = "https://mms.pinduoduo.com/"
PDD_IM_TOKEN_API = "https://mms.pinduoduo.com/mms/api/auth/getImToken"

# 浏览器数据目录（持久化登录状态）
BROWSER_DATA_DIR = os.path.join(os.path.expanduser("~"), ".aikefu-client", "browser_data")


class PddLogin:
    """拼多多登录处理器"""

    def __init__(self, shop_id: int, db_client=None):
        self.shop_id = shop_id
        self.db_client = db_client
        self.browser_context = None
        self.page = None
        self.cookies: dict = {}
        self.im_token: str = ""

    def get_user_data_dir(self) -> str:
        """获取当前店铺的浏览器数据目录"""
        shop_dir = os.path.join(BROWSER_DATA_DIR, f"shop_{self.shop_id}")
        os.makedirs(shop_dir, exist_ok=True)
        return shop_dir

    async def login(self, username: str = "", password: str = "") -> bool:
        """
        使用 Playwright 打开浏览器登录拼多多商家后台。
        支持扫码登录（不传账号密码）和账号密码登录。
        返回是否登录成功。
        """
        from playwright.async_api import async_playwright

        user_data_dir = self.get_user_data_dir()

        async with async_playwright() as p:
            self.browser_context = await p.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                headless=False,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
                locale="zh-CN",
                timezone_id="Asia/Shanghai",
            )

            if self.browser_context.pages:
                self.page = self.browser_context.pages[0]
            else:
                self.page = await self.browser_context.new_page()

            try:
                await self.page.goto(PDD_LOGIN_URL, wait_until="networkidle", timeout=30000)

                # 检查是否已经登录（已在商家后台）
                if await self._is_logged_in():
                    logger.info("店铺%d 已有有效登录状态", self.shop_id)
                    await self._after_login()
                    return True

                # 如果提供了账号密码，尝试账号密码登录
                if username and password:
                    success = await self._login_with_password(username, password)
                    if success:
                        await self._after_login()
                        return True
                    return False

                # 等待用户手动扫码或登录（最多等待5分钟）
                logger.info("等待用户手动登录拼多多商家后台...")
                try:
                    await self.page.wait_for_function(
                        "document.title.includes('拼多多') && !document.title.includes('登录')",
                        timeout=300000,  # 5分钟
                    )
                    await self._after_login()
                    return True
                except Exception:
                    logger.error("登录超时")
                    return False

            except Exception as e:
                logger.error("登录过程出错: %s", e)
                return False

    async def _is_logged_in(self) -> bool:
        """检查是否已登录"""
        try:
            title = await self.page.title()
            return "登录" not in title and "拼多多" in title
        except Exception:
            return False

    async def _login_with_password(self, username: str, password: str) -> bool:
        """账号密码登录"""
        try:
            # 点击账号登录标签
            try:
                await self.page.click('text=账号登录', timeout=5000)
                await asyncio.sleep(0.5)
            except Exception:
                pass

            # 填写账号
            username_input = await self.page.wait_for_selector(
                'input[name="username"], input[placeholder*="账号"], input[type="text"]',
                timeout=10000,
            )
            await username_input.fill(username)

            # 填写密码
            password_input = await self.page.wait_for_selector(
                'input[name="password"], input[placeholder*="密码"], input[type="password"]',
                timeout=10000,
            )
            await password_input.fill(password)

            # 点击登录按钮
            login_btn = await self.page.wait_for_selector(
                'button[type="submit"], button:has-text("登录")',
                timeout=10000,
            )
            await login_btn.click()

            # 等待登录完成
            await self.page.wait_for_function(
                "document.title.includes('拼多多') && !document.title.includes('登录')",
                timeout=30000,
            )
            return True

        except Exception as e:
            logger.error("账号密码登录失败: %s", e)
            return False

    async def _after_login(self):
        """登录成功后获取Cookie和IM Token"""
        await self._fetch_cookies()
        await self._fetch_im_token()

        # 更新数据库中的token
        if self.db_client and self.im_token:
            expires_at = datetime.now() + timedelta(hours=24)
            self.db_client.update_shop_token(self.shop_id, self.im_token, expires_at)

    async def _fetch_cookies(self):
        """从浏览器上下文获取Cookies"""
        try:
            cookies_list = await self.browser_context.cookies()
            self.cookies = {c["name"]: c["value"] for c in cookies_list}
            logger.info("获取到%d个Cookie", len(self.cookies))
        except Exception as e:
            logger.error("获取Cookie失败: %s", e)

    async def _fetch_im_token(self):
        """调用接口获取IM Token"""
        try:
            response = await self.page.evaluate(
                """
                async () => {
                    const resp = await fetch('/mms/api/auth/getImToken', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        credentials: 'include',
                    });
                    return await resp.json();
                }
                """
            )
            if response and response.get("success"):
                self.im_token = (
                    response.get("result", {}).get("imToken")
                    or response.get("imToken")
                    or ""
                )
                logger.info("获取IM Token成功")
            else:
                logger.warning("获取IM Token失败: %s", response)
        except Exception as e:
            logger.error("获取IM Token异常: %s", e)

    def get_page(self):
        """返回当前Playwright Page对象（用于PddSender）"""
        return self.page

    async def close(self):
        """关闭浏览器"""
        try:
            if self.browser_context:
                await self.browser_context.close()
        except Exception:
            pass
