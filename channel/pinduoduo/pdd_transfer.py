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
        """确保浏览器已启动并注入 cookies（普通模式，不占用 user_data_dir，避免和采集线程冲突）"""
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

    async def transfer(self, buyer_id: str = "", order_sn: str = "",
                       buyer_name: str = "") -> dict:
        """
        自动转移会话到指定客服。

        定位优先级：order_sn URL参数 > 搜索框(buyer_name取前2字) > data属性(buyer_id)

        :param buyer_id:    买家ID（兜底定位，用于 data 属性匹配）
        :param order_sn:    拼多多订单号（优先，URL参数定位）
        :param buyer_name:  买家昵称（优先于buyer_id用于搜索框定位）
        :return: {"success": bool, "agent": str, "message": str}
        """
        try:
            await self._ensure_browser(headless=True)
            page = self._page

            # 1. 打开聊天页面（优先使用 order_sn URL参数定位）
            if order_sn:
                url = f"{CHAT_BASE_URL}?orderSn={order_sn}#/"
            else:
                url = f"{CHAT_BASE_URL}#/"
            logger.info("打开拼多多聊天页面: %s", url)
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
                    continue

            # 2. 无 order_sn 时，通过搜索框或 data 属性定位买家会话
            if not order_sn:
                located = False
                # 2a. 优先：用 buyer_name 搜索（取前2字：兼容拼多多昵称在搜索结果中被截断的情况）
                if buyer_name:
                    search_kw = buyer_name[:2]
                    located = await self._search_and_click_session(page, search_kw, buyer_name)
                # 2b. 次选：buyer_id data属性/文本兜底
                if not located and buyer_id:
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
    # 新增：搜索框定位买家会话（核心优化）
    # ------------------------------------------------------------------

    async def _search_and_click_session(self, page, keyword: str,
                                        full_name: str = "") -> bool:
        """
        在拼多多聊天页顶部搜索框输入关键词，从结果列表中点击匹配的买家会话。

        :param keyword:   搜索关键词（buyer_name 前2字）
        :param full_name: 完整昵称（用于结果列表二次精确匹配，可为空）
        :return: 是否成功定位并点击
        """
        search_selectors = [
            'input[placeholder*="搜索"]',
            'input[placeholder*="Search"]',
            '[class*="search"] input',
            '[class*="Search"] input',
            'input[type="search"]',
            '[class*="searchInput"]',
            '[class*="search-input"]',
        ]

        search_input = None
        for sel in search_selectors:
            try:
                el = await page.query_selector(sel)
                if el:
                    search_input = el
                    break
            except Exception:
                continue

        if not search_input:
            logger.warning("未找到搜索框，keyword=%s", keyword)
            return False

        try:
            await search_input.click()
            await search_input.fill("")
            await search_input.type(keyword, delay=80)
            await page.wait_for_timeout(1200)  # 等待搜索结果渲染
        except Exception as e:
            logger.warning("搜索框输入失败: %s", e)
            return False

        result_selectors = [
            '[class*="searchResult"] [class*="item"]',
            '[class*="search-result"] [class*="item"]',
            '[class*="sessionItem"]',
            '[class*="session-item"]',
            '[class*="conversationItem"]',
            '[class*="conversation-item"]',
            '[class*="chatItem"]',
        ]

        for sel in result_selectors:
            try:
                items = await page.query_selector_all(sel)
                if not items:
                    continue
                # 优先精确匹配（strip + 大小写规范化）
                for item in items:
                    text = (await item.inner_text()).strip()
                    text_norm = text.lower()
                    match = (full_name and full_name.strip().lower() in text_norm) or (keyword.lower() in text_norm)
                    if match:
                        await item.click()
                        await page.wait_for_timeout(800)
                        logger.info("搜索定位买家成功: keyword=%s text=%s", keyword, text[:30])
                        return True
                # 精确匹配失败则点击第一条
                if items:
                    text = (await items[0].inner_text()).strip()
                    await items[0].click()
                    await page.wait_for_timeout(800)
                    logger.info("搜索定位：点击第一条结果 text=%s", text[:30])
                    return True
            except Exception:
                continue

        logger.warning("搜索后未找到匹配会话: keyword=%s", keyword)
        return False

    # ------------------------------------------------------------------
    # 辅助：data属性/文本定位买家会话（兜底）
    # ------------------------------------------------------------------

    async def _locate_buyer_session(self, page, buyer_id: str):
        """在会话列表中通过 data 属性或文本定位买家（buyer_id 兜底方案）"""
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
