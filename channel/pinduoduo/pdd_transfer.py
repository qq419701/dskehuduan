# -*- coding: utf-8 -*-
"""
拼多多转人工自动化核心
使用 playwright（异步）操作 https://mms.pinduoduo.com/chat-merchant/index.html
实现自动转移会话到指定客服

支持的分配策略：
  first        — 始终选第一个客服
  random       — 随机选一个客服
  least_busy   — 选当前未回复数最少的客服
  round_robin  — 按 shop_id 轮询（A→B→A→B）
"""
import logging
import random
import re
from typing import Optional

import config as cfg

logger = logging.getLogger(__name__)

# 轮询策略全局索引（按 shop_id 隔离）
_round_robin_index: dict = {}

CHAT_BASE_URL = "https://mms.pinduoduo.com/chat-merchant/index.html"


def get_transfer_config() -> dict:
    """从本地配置文件读取转人工设置（无配置时返回默认值）"""
    return cfg.get_pdd_transfer_settings()


class PddTransferHuman:
    """
    拼多多聊天页面转移会话自动化。
    复用 pdd_login 登录后保存的 cookies，通过 Playwright 操作转移会话弹窗。

    :param shop_id:   店铺唯一标识（用于 round_robin 轮询隔离）
    :param cookies:   pdd_login 登录后的 cookies 字典（{name: value}）
    :param strategy:  分配策略：first / random / least_busy / round_robin
    """

    def __init__(self, shop_id: str, cookies: dict, strategy: str = "first"):
        self.shop_id = shop_id
        self.cookies = cookies or {}
        self.strategy = strategy
        self._browser = None
        self._context = None
        self._page = None

    # ------------------------------------------------------------------
    # 浏览器生命周期
    # ------------------------------------------------------------------

    async def _ensure_browser(self, headless: bool = True):
        """确保浏览器已启动并注入 cookies"""
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
            self._page = await self._context.new_page()

    @staticmethod
    def _get_chrome_path() -> Optional[str]:
        """获取本地Chrome路径"""
        import os
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        candidates = [
            os.path.join(local_app_data, r"Google\Chrome\Application\chrome.exe"),
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            r"C:\Users\Administrator\Desktop\chrome-win64\chrome.exe",
        ]
        for p in candidates:
            if p and os.path.exists(p):
                return p
        return None  # 使用 playwright 内置

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

    # ------------------------------------------------------------------
    # 核心：转移会话
    # ------------------------------------------------------------------

    async def transfer(self, buyer_id: str = "", order_sn: str = "") -> dict:
        """
        自动转移会话到指定客服。

        :param buyer_id:  买家ID（用于定位会话，可选）
        :param order_sn:  拼多多订单号（优先用于定位会话，可选）
        :return: {"success": bool, "agent": str, "message": str}
        """
        try:
            await self._ensure_browser(headless=True)
            page = self._page

            # 1. 打开聊天页面（优先使用 order_sn 定位）
            if order_sn:
                url = f"{CHAT_BASE_URL}?orderSn={order_sn}#/"
            else:
                url = f"{CHAT_BASE_URL}#/"
            logger.info("打开拼多多聊天页面: %s", url)
            await page.goto(url, wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(2000)

            # 2. 如果有 buyer_id 且没有 order_sn，尝试点击对应买家会话
            if buyer_id and not order_sn:
                await self._locate_buyer_session(page, buyer_id)

            # 3. 点击「转移会话」按钮
            clicked = await self._click_transfer_button(page)
            if not clicked:
                return {"success": False, "agent": "", "message": "未找到「转移会话」按钮"}

            # 4. 等待弹窗出现
            await page.wait_for_timeout(1500)

            # 5. 解析客服列表
            agents = await self._parse_agent_list(page)
            if not agents:
                return {"success": False, "agent": "", "message": "未找到客服列表"}

            logger.info("获取到 %d 个客服: %s", len(agents), [a.get("name") for a in agents])

            # 6. 按策略选择客服
            chosen = self._choose_agent(agents)
            if not chosen:
                return {"success": False, "agent": "", "message": "策略未能选出客服"}

            # 7. 点击选中客服的「转移」按钮
            success = await self._click_agent_transfer(page, chosen)
            if success:
                logger.info("转移会话成功，目标客服: %s", chosen.get("name", ""))
                return {
                    "success": True,
                    "agent": chosen.get("name", ""),
                    "message": f"已成功转移给客服 {chosen.get('name', '')}",
                }
            return {"success": False, "agent": "", "message": "点击转移按钮失败"}

        except Exception as e:
            logger.error("转移会话异常: %s", e)
            return {"success": False, "agent": "", "message": str(e)}

    # ------------------------------------------------------------------
    # 辅助：定位买家会话
    # ------------------------------------------------------------------

    async def _locate_buyer_session(self, page, buyer_id: str):
        """在会话列表中点击对应买家"""
        selectors = [
            f'[data-buyer-id="{buyer_id}"]',
            f'[data-uid="{buyer_id}"]',
            f'[class*="session"]:has-text("{buyer_id}")',
            f'[class*="conversation"]:has-text("{buyer_id}")',
        ]
        for sel in selectors:
            try:
                el = await page.query_selector(sel)
                if el:
                    await el.click()
                    await page.wait_for_timeout(1000)
                    logger.info("已定位买家会话: %s", buyer_id)
                    return
            except Exception:
                continue
        logger.warning("未能定位买家会话: %s，使用当前活跃会话", buyer_id)

    # ------------------------------------------------------------------
    # 辅助：点击「转移会话」按钮
    # ------------------------------------------------------------------

    async def _click_transfer_button(self, page) -> bool:
        """点击页面顶部的「转移会话」按钮"""
        selectors = [
            'button:has-text("转移会话")',
            '[class*="transfer"]:has-text("转移")',
            'span:has-text("转移会话")',
            '[title="转移会话"]',
            '[data-action="transfer"]',
        ]
        for sel in selectors:
            try:
                el = await page.query_selector(sel)
                if el:
                    await el.click()
                    logger.info("已点击「转移会话」按钮")
                    return True
            except Exception:
                continue
        logger.warning("未找到「转移会话」按钮，尝试的 selector: %s", selectors)
        return False

    # ------------------------------------------------------------------
    # 辅助：解析客服列表
    # ------------------------------------------------------------------

    async def _parse_agent_list(self, page) -> list:
        """
        解析转移会话弹窗中的客服列表。
        表格列：账号名 | 昵称 | 备注 | 当前未回复 | 操作（转移 / 转移并微信通知）
        返回：[{"name": str, "nickname": str, "unreplied": int, "index": int, "element": el}]
        """
        agents = []

        # 等待弹窗表格行出现
        row_selectors = [
            '[class*="transfer"] tr',
            '[class*="modal"] tr',
            '[class*="dialog"] tr',
            '.transfer-dialog tr',
            'table tr',
        ]

        rows = []
        for sel in row_selectors:
            try:
                rows = await page.query_selector_all(sel)
                if rows and len(rows) > 1:
                    break
            except Exception:
                continue

        if not rows:
            logger.warning("未找到客服列表表格行")
            return agents

        # 解析每一行（跳过表头行）
        for i, row in enumerate(rows):
            try:
                cells = await row.query_selector_all("td")
                if len(cells) < 4:
                    continue  # 跳过表头或无效行

                name = (await cells[0].inner_text()).strip()
                nickname = (await cells[1].inner_text()).strip() if len(cells) > 1 else ""
                unreplied_text = (await cells[3].inner_text()).strip() if len(cells) > 3 else "0"

                # 提取未回复数字
                nums = re.findall(r"\d+", unreplied_text)
                unreplied = int(nums[0]) if nums else 0

                # 找到该行的「转移」按钮
                transfer_btn = None
                btn_selectors = [
                    'button:has-text("转移")',
                    'span:has-text("转移")',
                    'a:has-text("转移")',
                    '[class*="transfer-btn"]',
                ]
                for btn_sel in btn_selectors:
                    try:
                        btn = await row.query_selector(btn_sel)
                        if btn:
                            transfer_btn = btn
                            break
                    except Exception:
                        continue

                if name:
                    agents.append({
                        "name": name,
                        "nickname": nickname,
                        "unreplied": unreplied,
                        "index": len(agents),
                        "button": transfer_btn,
                    })
            except Exception as e:
                logger.debug("解析客服行 %d 异常: %s", i, e)
                continue

        return agents

    # ------------------------------------------------------------------
    # 辅助：按策略选择客服
    # ------------------------------------------------------------------

    def _choose_agent(self, agents: list) -> Optional[dict]:
        """
        按分配策略从客服列表中选出目标客服。

        策略说明：
          first       — 始终选第一个
          random      — 随机选
          least_busy  — 选未回复数最少的
          round_robin — 按 shop_id 轮询
        """
        if not agents:
            return None

        strategy = self.strategy

        if strategy == "first":
            return agents[0]

        if strategy == "random":
            return random.choice(agents)

        if strategy == "least_busy":
            return min(agents, key=lambda a: a["unreplied"])

        if strategy == "round_robin":
            global _round_robin_index
            idx = _round_robin_index.get(self.shop_id, 0)
            chosen = agents[idx % len(agents)]
            _round_robin_index[self.shop_id] = (idx + 1) % len(agents)
            return chosen

        # 默认 first
        logger.warning("未知策略 '%s'，使用 first", strategy)
        return agents[0]

    # ------------------------------------------------------------------
    # 辅助：点击指定客服的「转移」按钮
    # ------------------------------------------------------------------

    async def _click_agent_transfer(self, page, agent: dict) -> bool:
        """点击选中客服行的「转移」按钮"""
        btn = agent.get("button")
        if btn:
            try:
                await btn.click()
                await page.wait_for_timeout(1500)
                logger.info("已点击客服 [%s] 的转移按钮", agent.get("name", ""))
                return True
            except Exception as e:
                logger.error("点击转移按钮异常: %s", e)

        # 备用：通过文字定位（按名称查找行再点击）
        agent_name = agent.get("name", "")
        if agent_name:
            fallback_selectors = [
                f'tr:has-text("{agent_name}") button:has-text("转移")',
                f'tr:has-text("{agent_name}") span:has-text("转移")',
                f'tr:has-text("{agent_name}") a:has-text("转移")',
            ]
            for sel in fallback_selectors:
                try:
                    el = await page.query_selector(sel)
                    if el:
                        await el.click()
                        await page.wait_for_timeout(1500)
                        return True
                except Exception:
                    continue

        return False
