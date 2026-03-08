# -*- coding: utf-8 -*-
"""
U号租自动化核心
使用 playwright（异步）操作 https://b.uhaozu.com
"""
import logging
import re

logger = logging.getLogger(__name__)


class UHaozuAutomation:
    BASE_URL = "https://b.uhaozu.com"

    def __init__(self, username: str, password: str, cookies: dict = None):
        self.username = username
        self.password = password
        self.cookies = cookies or {}
        self._browser = None
        self._context = None
        self._page = None

    async def _ensure_browser(self):
        """确保浏览器已启动"""
        if self._browser is None:
            from playwright.async_api import async_playwright
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(headless=True)
            self._context = await self._browser.new_context()
            if self.cookies:
                cookie_list = [
                    {"name": k, "value": v, "url": self.BASE_URL}
                    for k, v in self.cookies.items()
                ]
                await self._context.add_cookies(cookie_list)
            self._page = await self._context.new_page()

    async def close(self):
        """关闭浏览器"""
        try:
            if self._browser:
                await self._browser.close()
            if hasattr(self, "_playwright"):
                await self._playwright.stop()
        except Exception as e:
            logger.warning("关闭浏览器异常: %s", e)
        finally:
            self._browser = None
            self._context = None
            self._page = None

    async def login(self) -> bool:
        """登录U号租，保存cookies"""
        try:
            await self._ensure_browser()
            page = self._page

            await page.goto(f"{self.BASE_URL}/login", wait_until="networkidle", timeout=30000)

            # 填写账号密码
            await page.fill('input[type="text"], input[name="username"], input[placeholder*="账号"]',
                            self.username)
            await page.fill('input[type="password"], input[name="password"], input[placeholder*="密码"]',
                            self.password)

            # 点击登录按钮
            await page.click('button[type="submit"], button:has-text("登录")')
            await page.wait_for_load_state("networkidle", timeout=15000)

            # 检测是否登录成功
            current_url = page.url
            if "/login" not in current_url:
                # 保存cookies
                cookies = await self._context.cookies()
                self.cookies = {c["name"]: c["value"] for c in cookies}
                logger.info("U号租登录成功: %s", self.username)
                return True
            else:
                logger.warning("U号租登录失败: %s", self.username)
                return False
        except Exception as e:
            logger.error("U号租登录异常: %s", e)
            return False

    async def check_login_status(self) -> bool:
        """检测是否在线（访问首页检查是否跳转登录页）"""
        try:
            await self._ensure_browser()
            page = self._page

            await page.goto(self.BASE_URL, wait_until="networkidle", timeout=15000)
            current_url = page.url
            is_logged_in = "/login" not in current_url
            logger.info("U号租登录状态 [%s]: %s", self.username, is_logged_in)
            return is_logged_in
        except Exception as e:
            logger.error("检测U号租登录状态异常: %s", e)
            return False

    async def get_balance(self) -> float:
        """获取账户余额（从页面右上角余额区域）"""
        try:
            await self._ensure_browser()
            page = self._page

            is_logged = await self.check_login_status()
            if not is_logged:
                return 0.0

            # 尝试从页面右上角余额区域获取余额
            selectors = [
                ".balance", ".user-balance", "[class*='balance']",
                ".amount", "[class*='amount']",
            ]
            for sel in selectors:
                try:
                    el = await page.query_selector(sel)
                    if el:
                        text = await el.inner_text()
                        # 提取数字
                        nums = re.findall(r"[\d.]+", text.replace(",", ""))
                        if nums:
                            return float(nums[0])
                except Exception:
                    continue

            logger.warning("未能获取U号租余额")
            return 0.0
        except Exception as e:
            logger.error("获取U号租余额异常: %s", e)
            return 0.0

    async def exchange_number(self, pdd_order_id: str) -> dict:
        """
        自动换号
        访问 https://b.uhaozu.com/key-exchange
        输入拼多多订单号，点击一键换货
        返回 {"success": bool, "message": str, "new_account": str}
        """
        try:
            await self._ensure_browser()
            page = self._page

            await page.goto(f"{self.BASE_URL}/key-exchange", wait_until="networkidle", timeout=15000)

            # 输入拼多多订单号
            input_selectors = [
                'input[placeholder*="订单"]',
                'input[placeholder*="order"]',
                'input[name*="order"]',
                'input[type="text"]',
            ]
            filled = False
            for sel in input_selectors:
                try:
                    el = await page.query_selector(sel)
                    if el:
                        await el.fill(pdd_order_id)
                        filled = True
                        break
                except Exception:
                    continue

            if not filled:
                return {"success": False, "message": "未找到订单号输入框", "new_account": ""}

            # 点击换货按钮
            btn_selectors = [
                'button:has-text("换货")',
                'button:has-text("换号")',
                'button:has-text("一键换")',
                'button[type="submit"]',
            ]
            clicked = False
            for sel in btn_selectors:
                try:
                    btn = await page.query_selector(sel)
                    if btn:
                        await btn.click()
                        clicked = True
                        break
                except Exception:
                    continue

            if not clicked:
                return {"success": False, "message": "未找到换货按钮", "new_account": ""}

            await page.wait_for_load_state("networkidle", timeout=15000)

            # 尝试获取新账号信息
            new_account = ""
            result_selectors = [
                ".result-account", ".new-account", "[class*='account']",
                ".success-info", "[class*='success']",
            ]
            for sel in result_selectors:
                try:
                    el = await page.query_selector(sel)
                    if el:
                        new_account = await el.inner_text()
                        break
                except Exception:
                    continue

            logger.info("U号租换号完成，订单: %s，新账号: %s", pdd_order_id, new_account)
            return {"success": True, "message": "换号成功", "new_account": new_account}
        except Exception as e:
            logger.error("U号租换号异常: %s", e)
            return {"success": False, "message": str(e), "new_account": ""}

    async def search_numbers(self, game: str, filters: dict) -> list:
        """
        自动选号 - 在开单助手搜索符合条件的号
        访问 https://b.uhaozu.com/opening-order
        返回 [{"id": str, "title": str, "price": float, "role": str}]
        """
        try:
            await self._ensure_browser()
            page = self._page

            await page.goto(f"{self.BASE_URL}/opening-order", wait_until="networkidle", timeout=15000)

            # 搜索游戏名
            search_selectors = [
                'input[placeholder*="游戏"]',
                'input[placeholder*="搜索"]',
                'input[type="search"]',
                'input[type="text"]',
            ]
            for sel in search_selectors:
                try:
                    el = await page.query_selector(sel)
                    if el:
                        await el.fill(game)
                        await el.press("Enter")
                        break
                except Exception:
                    continue

            await page.wait_for_load_state("networkidle", timeout=10000)

            # 应用筛选条件
            filter_map = {
                "no_deposit": ["无押金", "不押金"],
                "time_rental_bonus": ["时租满送"],
                "login_tool": ["登号器"],
                "anti_addiction": ["防沉迷"],
                "non_cloud": ["非云"],
                "high_login_rate": ["上号率高", "上号率"],
                "no_friend_add": ["禁言", "不能加好友"],
                "allow_ranked": ["排位赛允许", "排位"],
            }
            for key, labels in filter_map.items():
                if filters.get(key):
                    for label in labels:
                        try:
                            el = await page.query_selector(f':has-text("{label}")')
                            if el:
                                await el.click()
                                break
                        except Exception:
                            continue

            await page.wait_for_load_state("networkidle", timeout=10000)

            # 收集搜索结果
            results = []
            item_selectors = [".product-item", ".game-item", ".number-item", "[class*='item']"]
            for sel in item_selectors:
                items = await page.query_selector_all(sel)
                if items:
                    for item in items[:20]:
                        try:
                            title_el = await item.query_selector(".title, .name, h3, h4")
                            price_el = await item.query_selector(".price, .amount, [class*='price']")
                            id_attr = await item.get_attribute("data-id") or ""

                            title = await title_el.inner_text() if title_el else ""
                            price_text = await price_el.inner_text() if price_el else "0"
                            price_nums = re.findall(r"[\d.]+", price_text.replace(",", ""))
                            price = float(price_nums[0]) if price_nums else 0.0

                            results.append({
                                "id": id_attr,
                                "title": title.strip(),
                                "price": price,
                                "role": "",
                            })
                        except Exception:
                            continue
                    break

            logger.info("U号租搜索 [%s] 找到 %d 个结果", game, len(results))
            return results
        except Exception as e:
            logger.error("U号租搜索号码异常: %s", e)
            return []

    async def place_order(self, product_id: str) -> dict:
        """
        按商品编号下单
        返回 {"success": bool, "account": str, "password": str}
        """
        try:
            await self._ensure_browser()
            page = self._page

            # 访问商品页面
            await page.goto(f"{self.BASE_URL}/product/{product_id}", wait_until="networkidle", timeout=15000)

            # 点击下单/租号按钮
            btn_selectors = [
                'button:has-text("立即租号")',
                'button:has-text("下单")',
                'button:has-text("租用")',
                'button[type="submit"]',
            ]
            clicked = False
            for sel in btn_selectors:
                try:
                    btn = await page.query_selector(sel)
                    if btn:
                        await btn.click()
                        clicked = True
                        break
                except Exception:
                    continue

            if not clicked:
                return {"success": False, "account": "", "password": ""}

            await page.wait_for_load_state("networkidle", timeout=15000)

            # 获取账号密码
            account = ""
            password = ""
            acc_selectors = [".account-info", ".login-account", "[class*='account']"]
            pwd_selectors = [".account-password", ".login-password", "[class*='password']"]

            for sel in acc_selectors:
                try:
                    el = await page.query_selector(sel)
                    if el:
                        account = await el.inner_text()
                        break
                except Exception:
                    continue

            for sel in pwd_selectors:
                try:
                    el = await page.query_selector(sel)
                    if el:
                        password = await el.inner_text()
                        break
                except Exception:
                    continue

            logger.info("U号租下单完成，商品: %s", product_id)
            return {"success": True, "account": account.strip(), "password": password.strip()}
        except Exception as e:
            logger.error("U号租下单异常: %s", e)
            return {"success": False, "account": "", "password": ""}
