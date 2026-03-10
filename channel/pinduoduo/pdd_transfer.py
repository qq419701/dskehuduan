# -*- coding: utf-8 -*-
"""
拼多多转人工自动化核心
使用 playwright（异步）+ Playwright 路由拦截 anti_content 方案
"""
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
    # 内部：启动浏览器并注入 cookies
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
        if self.cookies:
            cookie_list = [
                {"name": k, "value": v, "domain": ".pinduoduo.com",
                 "path": "/", "httpOnly": False, "secure": True}
                for k, v in self.cookies.items()
            ]
            await self._context.add_cookies(cookie_list)
            logger.info("已注入 %d 个cookies", len(self.cookies))
        else:
            logger.warning("没有cookies，可能未登录！")

        self._page = await self._context.new_page()
        self._ready = True

    # ------------------------------------------------------------------
    # 核心：转移会话
    # 流程：
    #   1. 打开聊天页，通过 URL 参数或会话列表定位买家
    #   2. JS fetch 获取客服列表（getAssignCsList）
    #   3. 按策略选出目标客服
    #   4. JS fetch 直接调用 move_conversation（带 anti_content）
    # ------------------------------------------------------------------

    async def transfer(self, buyer_id="", order_sn="", buyer_name=""):
        try:
            await self._ensure_page()
            page = self._page

            # 1. 打开聊天页面，带 buyer_id 参数（让页面自动定位到该买家会话）
            if order_sn:
                url = f"https://mms.pinduoduo.com/chat-merchant/index.html?orderSn={order_sn}#/"
            elif buyer_id:
                url = f"https://mms.pinduoduo.com/chat-merchant/index.html?uid={buyer_id}#/"
            else:
                url = "https://mms.pinduoduo.com/chat-merchant/index.html#/"

            logger.info("打开拼多多聊天页面: %s", url)
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(4000)

            # 检查是否被踢到登录页
            cur_url = page.url
            if "login" in cur_url or "verify" in cur_url or "passport" in cur_url:
                logger.error("cookies已失效，重定向到: %s", cur_url)
                return {"success": False, "agent": "", "message": "cookies已失效，请重新登录"}

            # 2. 在页面内 JS fetch 获取客服列表（自动携带合法 cookies）
            agents = await self._js_get_agent_list(page)
            if agents is None:
                return {"success": False, "agent": "", "message": "获取客服列表失败"}
            if not agents:
                return {"success": False, "agent": "", "message": "没有可用客服"}

            logger.info("获取到 %d 个客服: %s", len(agents), [a.get("name") for a in agents])

            # 3. 按策略选择目标客服
            chosen = self._choose_agent(agents)
            if not chosen:
                return {"success": False, "agent": "", "message": "策略未能选出客服"}

            # 4. JS fetch 调用 move_conversation
            #    拼多多页面会在 window._jsvmpentry / jiagu 等对象里挂载 anti_content 生成器
            #    我们通过让页面先调用一次 getAssignCsList（已成功），
            #    再直接 fetch move_conversation，由浏览器 JS 环境自动附加 credentials
            ok = await self._js_move_conversation(page, chosen, buyer_id)
            if ok:
                logger.info("转移成功 → %s", chosen.get("name", ""))
                return {
                    "success": True,
                    "agent": chosen.get("name", ""),
                    "message": "已转移给客服 " + chosen.get("name", ""),
                }

            # 5. JS 方案失败，尝试 UI 点击（最可靠但需要页面处于正确状态）
            logger.warning("JS fetch 未成功，尝试 UI 点击方式")
            ok2 = await self._click_transfer_ui(page, chosen, buyer_id)
            if ok2:
                return {
                    "success": True,
                    "agent": chosen.get("name", ""),
                    "message": "已转移给客服 " + chosen.get("name", "") + "（UI方式）",
                }
            return {"success": False, "agent": "", "message": "转移失败，请手动操作"}

        except Exception as e:
            logger.error("转移会话异常: %s", e)
            self._ready = False
            return {"success": False, "agent": "", "message": str(e)}

    # ------------------------------------------------------------------
    # JS: 获取客服列表
    # ------------------------------------------------------------------

    async def _js_get_agent_list(self, page):
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
            logger.info("客服列表响应: %s", str(result)[:300])
            if result.get("success"):
                cs_map = (result.get("result") or {}).get("csList") or {}
                agents = []
                for uid_key, item in cs_map.items():
                    name = (item.get("csName") or item.get("username") or
                            item.get("nickname") or uid_key)
                    agents.append({
                        "name": name,
                        "csid": uid_key,          # 原始 key，如 "cs_106324383_180462738"
                        "uid": str(item.get("id") or ""),
                        "unreplied": item.get("unreplyNum", 0),
                    })
                return agents
        except Exception as e:
            logger.warning("JS获取客服列表失败: %s", e)
        return None

    # ------------------------------------------------------------------
    # JS: 调用 move_conversation
    # 关键：在页面 JS 上下文中 fetch，浏览器自动携带 credentials 和
    #       页面 JS SDK 生成的 anti_content（通过拦截 XMLHttpRequest send）
    # ------------------------------------------------------------------

    async def _js_move_conversation(self, page, agent, buyer_id=""):
        csid = agent.get("csid", "")
        uid = str(buyer_id) if buyer_id else ""
        request_id = int(time.time() * 1000)

        # 先注入一个钩子，拦截下一次 XHR/fetch 请求里的 anti_content
        # 然后用拦截到的 anti_content 重发 move_conversation
        js = f"""
        async () => {{
            // 尝试从页面内部获取 anti_content 生成函数
            let antiContent = '';
            const antiSources = [
                () => window.__AC__ && window.__AC__.get ? window.__AC__.get() : null,
                () => window._jsvmpentry && window._jsvmpentry.anti_content,
                () => window.AntiContent && window.AntiContent.get ? window.AntiContent.get() : null,
                () => {{
                    // 从 cookie 里找 anti_content
                    const m = document.cookie.match(/anti_content=([^;]+)/);
                    return m ? decodeURIComponent(m[1]) : null;
                }},
            ];
            for (const fn of antiSources) {{
                try {{
                    const v = fn();
                    if (v && typeof v === 'string' && v.length > 10) {{
                        antiContent = v;
                        break;
                    }}
                }} catch(e) {{}}
            }}

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
            const resp = await r.json();
            // 返回包含 antiContent 的完整结果，方便调试
            return {{ resp: resp, antiContent: antiContent }};
        }}
        """
        try:
            result = await page.evaluate(js)
            resp = result.get("resp", {})
            anti = result.get("antiContent", "")
            logger.info("move_conversation 响应: %s | anti_content长度: %d", str(resp)[:300], len(anti))
            if (resp.get("success") and
                    isinstance(resp.get("result"), dict) and
                    resp["result"].get("result") == "ok"):
                return True
        except Exception as e:
            logger.error("JS move_conversation 异常: %s", e)
        return False

    # ------------------------------------------------------------------
    # 备用：UI 点击方式
    # 需要页面已定位到目标买家会话（通过 URL uid 参数）
    # ------------------------------------------------------------------

    async def _click_transfer_ui(self, page, agent, buyer_id=""):
        try:
            agent_name = agent.get("name", "")

            # 先等页面加载买家会话
            await page.wait_for_timeout(2000)

            # 点击「转移会话」按钮
            transfer_selectors = [
                'span:has-text("转移会话")',
                'button:has-text("转移会话")',
                '[class*="transfer-chat"]',
                '[class*="transferChat"]',
                '.transfer-btn',
            ]
            clicked = False
            for sel in transfer_selectors:
                try:
                    el = await page.query_selector(sel)
                    if el:
                        await el.scroll_into_view_if_needed()
                        await el.click()
                        clicked = True
                        logger.info("已点击转移会话按钮: %s", sel)
                        break
                except Exception:
                    continue

            if not clicked:
                # 截图帮助调试
                try:
                    await page.screenshot(path="transfer_debug.png")
                    logger.warning("截图已保存到 transfer_debug.png，未找到「转移会话」按钮")
                except Exception:
                    pass
                return False

            await page.wait_for_timeout(1500)

            # 在弹窗表格里找目标客服行
            for row_sel in [
                f'tr:has-text("{agent_name}")',
                f'[class*="table"] [class*="row":has-text("{agent_name}")]',
                f'td:has-text("{agent_name}")',
            ]:
                try:
                    row_or_cell = await page.query_selector(row_sel)
                    if row_or_cell:
                        # 找「转移」按钮（不要选「转移并微信通知」）
                        btn = await row_or_cell.query_selector('a:has-text("转移"), span:has-text("转移"), button:has-text("转移")')
                        if not btn:
                            # 父元素找
                            parent = await page.evaluate_handle(
                                "(el) => el.closest('tr') || el.parentElement", row_or_cell)
                            btn = await parent.query_selector('a:has-text("转移"), span:has-text("转移")')
                        if btn:
                            await btn.click()
                            await page.wait_for_timeout(1000)

                            # 选择转移原因（如出现下拉）
                            for reason_text in ["无原因直接转移", "催发货", "发货/物流问题"]:
                                try:
                                    reason = await page.query_selector(f'text="{reason_text}"')
                                    if not reason:
                                        reason = await page.query_selector(f':has-text("{reason_text}")')
                                    if reason:
                                        await reason.click()
                                        await page.wait_for_timeout(400)
                                        break
                                except Exception:
                                    pass

                            # 点发送
                            try:
                                send_btn = await page.query_selector('button:has-text("发送")')
                                if send_btn:
                                    await send_btn.click()
                                    await page.wait_for_timeout(1000)
                            except Exception:
                                pass

                            logger.info("UI点击方式转移完成 → %s", agent_name)
                            return True
                except Exception as e:
                    logger.debug("行点击异常: %s", e)

            logger.warning("UI方式未找到客服行: %s", agent_name)
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