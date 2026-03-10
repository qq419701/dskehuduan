# -*- coding: utf-8 -*-
# pdd_transfer.py
# 通过 Playwright 注入 cookies 打开拼多多聊天页面，
# 再用 JS evaluate 触发页面内部的 move_conversation 接口（带合法 anti_content）
import asyncio
import logging
import random
import time

logger = logging.getLogger(__name__)
_round_robin_index = {}


class PddTransferHuman:
    def __init__(self, shop_id: str, cookies: dict, strategy: str = "first"):
        self.shop_id = shop_id
        self.cookies = cookies or {}
        self.strategy = strategy
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None
        self._ready = False

    # ------------------------------------------------------------------
    # 内部：启动无头浏览器并注入 cookies
    # ------------------------------------------------------------------

    async def _ensure_page(self):
        if self._ready:
            return
        from playwright.async_api import async_playwright
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage",
                  "--disable-blink-features=AutomationControlled"],
        )
        self._context = await self._browser.new_context(
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        # 注入 cookies
        if self.cookies:
            cookie_list = [
                {"name": k, "value": v, "domain": ".pinduoduo.com",
                 "path": "/", "httpOnly": False, "secure": True}
                for k, v in self.cookies.items()
            ]
            await self._context.add_cookies(cookie_list)
            logger.info("已注入 %d 个cookies", len(self.cookies))

        self._page = await self._context.new_page()
        # 打开聊天页面（让页面完成初始化，生成 anti_content 环境）
        await self._page.goto(
            "https://mms.pinduoduo.com/chat-merchant/index.html#/",
            wait_until="domcontentloaded",
            timeout=60000,
        )
        await self._page.wait_for_timeout(4000)
        self._ready = True
        logger.info("拼多多聊天页面已就绪")

    # ------------------------------------------------------------------
    # 核心：转移会话
    # ------------------------------------------------------------------

    async def transfer(self, buyer_id="", order_sn="", buyer_name=""):
        try:
            await self._ensure_page()
            page = self._page

            # 1. 先获取客服列表（直接用页面 fetch，带合法 cookies 和 anti_content）
            agents = await self._js_get_agent_list(page, buyer_id)
            if agents is None:
                return {"success": False, "agent": "", "message": "获取客服列表失败"}
            if not agents:
                return {"success": False, "agent": "", "message": "没有可用客服"}

            logger.info("获取到 %d 个客服: %s", len(agents), [a.get("name") for a in agents])

            # 2. 按策略选择目标客服
            chosen = self._choose_agent(agents)
            if not chosen:
                return {"success": False, "agent": "", "message": "策略未能选出客服"}

            # 3. 通过页面 JS 调用 move_conversation
            ok = await self._js_move_conversation(page, chosen, buyer_id)
            if ok:
                logger.info("转移会话成功 → %s", chosen.get("name", ""))
                return {
                    "success": True,
                    "agent": chosen.get("name", ""),
                    "message": "已转移给客服 " + chosen.get("name", ""),
                }
            return {"success": False, "agent": "", "message": "move_conversation 调用失败"}

        except Exception as e:
            logger.error("转移会话异常: %s", e)
            # 重置页面，下次重新初始化
            self._ready = False
            return {"success": False, "agent": "", "message": str(e)}

    # ------------------------------------------------------------------
    # JS: 获取客服列表
    # ------------------------------------------------------------------

    async def _js_get_agent_list(self, page, buyer_id=""):
        """在页面上下文中用 fetch 调用 getAssignCsList，自动带上合法 cookies"""
        try:
            result = await page.evaluate("""
                async () => {
                    const r = await fetch(
                        'https://mms.pinduoduo.com/latitude/assign/getAssignCsList',
                        {
                            method: 'POST',
                            headers: {'Content-Type': 'application/json'},
                            body: JSON.stringify({wechatCheck: true}),
                            credentials: 'include',
                        }
                    );
                    return await r.json();
                }
            """)
            logger.info("客服列表JS响应: %s", str(result)[:300])
            if result.get("success"):
                cs_map = (result.get("result") or {}).get("csList") or {}
                agents = []
                for uid_key, item in cs_map.items():
                    name = (item.get("csName") or item.get("username") or
                            item.get("nickname") or uid_key)
                    agents.append({
                        "name": name,
                        "csid": uid_key,
                        "uid": str(item.get("id") or ""),
                        "unreplied": item.get("unreplyNum", 0),
                        "raw": item,
                    })
                return agents
        except Exception as e:
            logger.warning("JS获取客服列表失败: %s", e)
        return None

    # ------------------------------------------------------------------
    # JS: 调用 move_conversation（通过页面 fetch，自动携带合法 anti_content）
    # ------------------------------------------------------------------

    async def _js_move_conversation(self, page, agent, buyer_id=""):
        csid = agent.get("csid", "")
        uid = str(buyer_id) if buyer_id else ""
        request_id = int(time.time() * 1000)

        js = f"""
        async () => {{
            let antiContent = '';
            try {{
                if (window.__pdd_anti_content__) antiContent = window.__pdd_anti_content__;
            }} catch(e) {{}}

            const body = {{
                data: {{
                    cmd: 'move_conversation',
                    request_id: {request_id},
                    conversation: {{
                        csid: '{csid}',
                        uid: '{uid}',
                        need_wx: false,
                        remark: '无原因直接转移',
                    }},
                    anti_content: antiContent,
                }},
                client: 'WEB',
                anti_content: antiContent,
            }};

            const r = await fetch(
                'https://mms.pinduoduo.com/plateau/chat/move_conversation',
                {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify(body),
                    credentials: 'include',
                }}
            );
            return await r.json();
        }}
        """
        try:
            result = await page.evaluate(js)
            logger.info("move_conversation JS响应: %s", str(result)[:300])
            if (result.get("success") and
                    isinstance(result.get("result"), dict) and
                    result["result"].get("result") == "ok"):
                return True
            logger.warning("JS move_conversation 未成功，尝试UI点击方式")
            return await self._click_transfer_ui(page, agent, uid)
        except Exception as e:
            logger.error("JS move_conversation 异常: %s", e)
            return await self._click_transfer_ui(page, agent, uid)

    # ------------------------------------------------------------------
    # 备用：UI点击方式（最可靠，自动生成完整 anti_content）
    # ------------------------------------------------------------------

    async def _click_transfer_ui(self, page, agent, buyer_uid=""):
        try:
            agent_name = agent.get("name", "")

            # 点击「转移会话」按钮
            transfer_selectors = [
                'span.transfer-chat',
                '[class*="transfer-chat"]',
                'button:has-text("转移会话")',
                'span:has-text("转移会话")',
            ]
            clicked = False
            for sel in transfer_selectors:
                try:
                    el = await page.query_selector(sel)
                    if el:
                        await el.click()
                        clicked = True
                        logger.info("已点击转移会话按钮: %s", sel)
                        break
                except Exception:
                    continue

            if not clicked:
                logger.warning("未找到「转移会话」按钮")
                return False

            await page.wait_for_timeout(1500)

            # 在弹窗中找目标客服行并点「转移」
            for row_sel in [
                f'tr:has-text("{agent_name}")',
                f'[class*="row"]:has-text("{agent_name}")',
            ]:
                try:
                    row = await page.query_selector(row_sel)
                    if row:
                        btn = await row.query_selector('text=转移')
                        if btn:
                            await btn.click()
                            await page.wait_for_timeout(1000)
                            # 选转移原因
                            try:
                                reason = await page.query_selector('text=无原因直接转移')
                                if reason:
                                    await reason.click()
                                    await page.wait_for_timeout(300)
                            except Exception:
                                pass
                            # 点发送
                            try:
                                send_btn = await page.query_selector('button:has-text("发送")')
                                if send_btn:
                                    await send_btn.click()
                                    await page.wait_for_timeout(800)
                            except Exception:
                                pass
                            logger.info("UI点击方式转移完成")
                            return True
                except Exception as e:
                    logger.debug("行点击异常: %s", e)

            logger.warning("UI方式未找到目标客服行: %s", agent_name)
            return False
        except Exception as e:
            logger.error("UI点击转移异常: %s", e)
            return False

    # ------------------------------------------------------------------
    # 策略选择
    # ------------------------------------------------------------------

    def _choose_agent(self, agents):
        if not agents:
            return None
        if self.strategy == "random":
            return random.choice(agents)
        if self.strategy == "least_busy":
            return min(agents, key=lambda a: a.get("unreplied", 0))
        if self.strategy == "round_robin":
            global _round_robin_index
            idx = _round_robin_index.get(self.shop_id, 0)
            chosen = agents[idx % len(agents)]
            _round_robin_index[self.shop_id] = (idx + 1) % len(agents)
            return chosen
        return agents[0]

    # ------------------------------------------------------------------
    # 关闭
    # ------------------------------------------------------------------

    async def close(self):
        try:
            if self._browser:
                await self._browser.close()
            if self._pw:
                await self._pw.stop()
        except Exception as e:
            logger.warning("关闭浏览器异常: %s", e)
        finally:
            self._pw = None
            self._browser = None
            self._context = None
            self._page = None
            self._ready = False