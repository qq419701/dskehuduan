# -*- coding: utf-8 -*-
"""
aikefu 任务轮询执行器

功能：定期轮询 aikefu 服务端的任务队列（GET /api/plugin/tasks），
      自动执行客户端支持的插件动作，执行完成后回报结果。

支持的动作码：
  auto_exchange   — 自动换号（调用 UHaozuAutomation）
  handle_refund   — 退款处理（记录模式，目前为人工确认）
  auto_order      — 自动下单选号（预留，开发中）
  transfer_human  — 转人工（调用 PddTransferHuman，自动转移拼多多会话给客服）
  reply_sent      — AI回复已发送（v2.1新增，记录模式）

轮询间隔：2秒（可配置）
心跳间隔：30秒（保持插件在线状态）
"""
import asyncio
import logging
from collections import deque

import config
from core.server_api import ServerAPI

logger = logging.getLogger(__name__)

# 动作码 → 处理方法名映射表
ACTION_HANDLERS = {
    "auto_exchange": "_handle_auto_exchange",    # 自动换号
    "handle_refund": "_handle_refund",           # 退款处理（人工确认）
    "auto_order": "_handle_auto_order",          # 自动下单选号（预留）
    "transfer_human": "_handle_transfer_human",  # 转人工（自动转移拼多多会话）
    "reply_sent":    "_handle_reply_sent",       # AI回复已发送（v2.1新增）
}

# 插件注册名称
PLUGIN_NAME = "爱客服自动化客户端"

# 已执行任务 ID 最大缓存数量（防止无限增长）
MAX_EXECUTED_IDS = 2000


class AikefuTaskRunner:
    """
    aikefu 任务轮询执行器。
    启动后并发运行轮询协程和心跳协程，不阻塞 UI / PDD 消息监听。
    """

    def __init__(self, server_url: str, shop_token: str, plugin_id: str,
                 poll_interval: int = 2, heartbeat_interval: int = 30,
                 shop_cookies: dict = None, shop_id: str = ""):
        """
        :param server_url:          aikefu 服务地址，如 http://8.145.43.255:6000
        :param shop_token:          店铺 Token（X-Shop-Token 请求头）
        :param plugin_id:           本客户端的插件唯一 ID（用于注册和心跳）
        :param poll_interval:       轮询间隔（秒），默认 2
        :param heartbeat_interval:  心跳间隔（秒），默认 30
        :param shop_cookies:        拼多多登录后的 cookies 字典（用于 transfer_human）
        :param shop_id:             店铺 ID（用于 round_robin 轮询隔离）
        """
        self.server_url = server_url
        self.shop_token = shop_token
        self.plugin_id = plugin_id
        self.poll_interval = poll_interval
        self.heartbeat_interval = heartbeat_interval
        self.shop_cookies = shop_cookies or {}
        self.shop_id = shop_id

        self._api = ServerAPI(base_url=server_url)
        self._running = False
        # 任务去重：用有界双端队列跟踪已执行的 task_id，防止无限增长
        self._executed_task_ids: set = set()
        self._executed_task_order: deque = deque(maxlen=MAX_EXECUTED_IDS)

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    async def start(self):
        """启动轮询和心跳（并发运行两个协程）"""
        self._running = True
        logger.info("任务执行器启动，plugin_id=%s，server=%s", self.plugin_id, self.server_url)

        # 先注册插件能力
        await self._register()

        # 并发运行轮询和心跳
        await asyncio.gather(
            self._poll_loop(),
            self._heartbeat_loop(),
            return_exceptions=True,
        )

    async def stop(self):
        """停止所有协程"""
        self._running = False
        logger.info("任务执行器停止")

    # ------------------------------------------------------------------
    # 注册与心跳
    # ------------------------------------------------------------------

    async def _register(self):
        """
        向 aikefu 注册插件能力
        POST /api/plugin/register
        """
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: self._api.plugin_register(
                shop_token=self.shop_token,
                plugin_id=self.plugin_id,
                name=PLUGIN_NAME,
                action_codes=list(ACTION_HANDLERS.keys()),
                version="2.1.0",
            ),
        )
        if result.get("success") is not False:
            logger.info("插件注册成功: %s", result)
        else:
            logger.warning("插件注册返回异常（可能服务端尚未实现该接口）: %s", result)

    async def _heartbeat_loop(self):
        """每隔 heartbeat_interval 秒发一次心跳，保持在线"""
        while self._running:
            await asyncio.sleep(self.heartbeat_interval)
            if not self._running:
                break
            try:
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    None,
                    lambda: self._api.plugin_heartbeat(
                        shop_token=self.shop_token,
                        plugin_id=self.plugin_id,
                    ),
                )
                logger.debug("心跳: %s", result)
            except Exception as e:
                logger.warning("心跳异常: %s", e)

    # ------------------------------------------------------------------
    # 轮询
    # ------------------------------------------------------------------

    async def _poll_loop(self):
        """每隔 poll_interval 秒轮询一次任务队列"""
        while self._running:
            try:
                tasks = await self._fetch_tasks()
                for task in tasks:
                    task_id = str(task.get("task_id") or task.get("id", ""))
                    if not task_id:
                        continue
                    if task_id in self._executed_task_ids:
                        logger.debug("任务 %s 已执行，跳过", task_id)
                        continue
                    # 标记后在独立协程中执行，不阻塞轮询
                    self._executed_task_ids.add(task_id)
                    self._executed_task_order.append(task_id)
                    # 如果超出上限，淘汰最早的记录
                    if len(self._executed_task_ids) > MAX_EXECUTED_IDS:
                        oldest = self._executed_task_order.popleft()
                        self._executed_task_ids.discard(oldest)
                    asyncio.create_task(self._execute_task(task))
            except Exception as e:
                logger.error("轮询任务异常: %s", e)
            await asyncio.sleep(self.poll_interval)

    async def _fetch_tasks(self) -> list:
        """GET /api/plugin/tasks，返回任务列表"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self._api.plugin_get_tasks(shop_token=self.shop_token),
        )

    # ------------------------------------------------------------------
    # 任务执行
    # ------------------------------------------------------------------

    async def _execute_task(self, task: dict):
        """
        执行单个任务（在独立协程中运行，不阻塞轮询）
        流程：claim → execute → report done/fail
        """
        task_id = str(task.get("task_id") or task.get("id", ""))
        action_code = task.get("action_code", "")
        payload = task.get("payload") or {}

        logger.info("开始执行任务 task_id=%s action_code=%s", task_id, action_code)

        # 尝试领取任务（防并发）
        claimed = await self._claim_task(task_id)
        if not claimed:
            logger.warning("任务 %s 领取失败，跳过", task_id)
            return

        # 路由到对应处理器
        handler_name = ACTION_HANDLERS.get(action_code)
        if not handler_name:
            err = f"未知动作码: {action_code}"
            logger.error("任务 %s 失败: %s", task_id, err)
            await self._report_fail(task_id, err)
            return

        handler = getattr(self, handler_name)
        try:
            result = await handler(payload)
            # 如果 handler 返回了明确的 success=False，上报失败而不是成功
            if isinstance(result, dict) and result.get("success") is False:
                err = result.get("message", "任务执行失败")
                logger.warning("任务 %s 执行返回失败: %s", task_id, err)
                await self._report_fail(task_id, err)
            else:
                logger.info("任务 %s 执行成功: %s", task_id, result)
                await self._report_done(task_id, result)
        except Exception as e:
            err = str(e)
            logger.error("任务 %s 执行异常: %s", task_id, err)
            await self._report_fail(task_id, err)

    async def _claim_task(self, task_id: str) -> bool:
        """
        领取任务（防止多个客户端重复执行）。
        如果 aikefu 没有 claim 接口，直接返回 True 继续执行。
        """
        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: self._api.session.post(
                    f"{self._api.base_url}/api/plugin/tasks/{task_id}/claim",
                    json={},
                    headers={"X-Shop-Token": self.shop_token},
                    timeout=10,
                ),
            )
            # 404 说明接口不存在，视为允许执行
            if result.status_code == 404:
                return True
            return result.status_code < 400
        except Exception as e:
            logger.debug("claim 接口调用异常（可能不存在），直接执行: %s", e)
            return True

    async def _report_done(self, task_id: str, result: dict):
        """上报任务成功"""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: self._api.plugin_task_done(
                shop_token=self.shop_token,
                task_id=task_id,
                result=result,
            ),
        )
        logger.info("已上报任务完成 task_id=%s", task_id)

    async def _report_fail(self, task_id: str, error: str):
        """上报任务失败"""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: self._api.plugin_task_fail(
                shop_token=self.shop_token,
                task_id=task_id,
                error=error,
            ),
        )
        logger.info("已上报任务失败 task_id=%s error=%s", task_id, error)

    # ------------------------------------------------------------------
    # 具体动作处理器
    # ------------------------------------------------------------------

    async def _handle_auto_exchange(self, payload: dict) -> dict:
        """
        处理换号任务
        payload: {buyer_id, order_id, message, intent}
        流程：
          1. 从 config 读取默认 U号租账号
          2. 复用 ExchangeHandler._do_exchange() 执行换号
          3. 返回 {success, new_account, message}
        """
        from core.exchange_number import ExchangeHandler

        order_id = str(payload.get("order_id", ""))
        if not order_id:
            return {"success": False, "message": "缺少 order_id，无法换号"}

        account = config.get_default_uhaozu_account()
        if not account:
            return {"success": False, "message": "未配置默认 U号租账号"}

        handler = ExchangeHandler()
        result = await handler._do_exchange(account, order_id)

        if result.get("success"):
            return {
                "success": True,
                "new_account": result.get("new_account", ""),
                "message": "换号成功",
            }
        return {
            "success": False,
            "message": result.get("message", "换号失败"),
        }

    async def _handle_refund(self, payload: dict) -> dict:
        """
        处理退款任务（目前为记录模式，不做自动操作）
        payload: {buyer_id, order_id, message, intent}
        """
        order_id = payload.get("order_id", "未知订单")
        buyer_id = payload.get("buyer_id", "未知买家")
        logger.info("收到退款任务，请人工处理 order_id=%s buyer_id=%s", order_id, buyer_id)
        return {"success": True, "message": "退款任务已记录，请人工处理"}

    async def _handle_auto_order(self, payload: dict) -> dict:
        """预留：自动下单选号（开发中）"""
        return {"success": False, "message": "auto_order 功能开发中"}

    async def _handle_transfer_human(self, payload: dict) -> dict:
        """
        处理转人工任务，自动操作拼多多聊天页面将会话转移给客服。

        payload 字段：
          buyer_id   — 买家 ID（可选，兜底定位）
          buyer_name — 买家昵称（优先用于搜索框定位，取前2字搜索）
          order_sn   — 拼多多订单号（可选，URL参数优先定位）
          order_id   — 内部订单 ID（可选，备用）
          strategy   — 分配策略（first / random / least_busy / round_robin），
                       不传则读取 config.get_transfer_strategy() 默认值

        返回：{"success": bool, "agent": str, "message": str}
        """
        from channel.pinduoduo.pdd_transfer import PddTransferHuman

        buyer_id = str(payload.get("buyer_id", ""))
        buyer_name = str(payload.get("buyer_name", ""))
        order_sn = str(payload.get("order_sn", ""))
        # 优先级：任务payload指定 > 店铺专属配置 > 全局配置兜底
        target_agent = (
            str(payload.get("target_agent", "")).strip()
            or config.get_shop_transfer_agent(self.shop_id)
            or ""
        )
        # strategy 仅在 target_agent 为空时才真正生效（target_agent 优先）
        strategy = payload.get("strategy") or config.get_transfer_strategy()
        logger.info(
            "转人工参数: shop_id=%s target_agent=%r strategy=%s buyer_id=%s",
            self.shop_id, target_agent, strategy, buyer_id,
        )

        if not self.shop_cookies:
            return {
                "success": False,
                "agent": "",
                "message": "未配置店铺 cookies，请先登录拼多多",
            }

        transfer = PddTransferHuman(
            shop_id=self.shop_id,
            cookies=self.shop_cookies,
            strategy=strategy,
        )
        try:
            result = await transfer.transfer(
                buyer_id=buyer_id,
                order_sn=order_sn,
                buyer_name=buyer_name,
                target_agent=target_agent,
            )
        finally:
            await transfer.close()

        return result

    async def _handle_reply_sent(self, payload: dict) -> dict:
        """
        处理 AI 回复已发送通知任务（v2.1 新增）。
        服务端在 AI 回复发送成功后下发此任务，客户端记录日志并可做本地统计。

        payload 字段：
          buyer_id  — 买家 ID
          reply     — 已发送的回复内容
          task_id   — 关联的原始任务 ID（可选）
          shop_id   — 店铺 ID（可选）

        返回：{"success": True, "message": "已记录"}
        """
        buyer_id = payload.get("buyer_id", "未知买家")
        reply = payload.get("reply", "")
        task_id = payload.get("task_id", "")
        logger.info(
            "AI回复已发送记录 buyer_id=%s task_id=%s reply=%s",
            buyer_id, task_id, reply[:50] if reply else "",
        )
        return {"success": True, "message": "已记录"}


# ===========================================================================
# 多店铺任务执行器管理器（v2.0 新增）
# ===========================================================================

class MultiShopTaskRunner:
    """
    多店铺任务执行器管理器。
    为每个激活的店铺创建独立的 AikefuTaskRunner 实例，并发运行。
    """

    def __init__(self, server_url: str, shops: list, poll_interval: int = 2,
                 heartbeat_interval: int = 30, shop_cookies_map: dict = None):
        """
        :param server_url:          aikefu 服务地址
        :param shops:               激活的店铺列表，每项格式：
                                    {"id": 1, "name": "店铺名", "shop_token": "xxx"}
        :param poll_interval:       轮询间隔（秒），默认 2
        :param heartbeat_interval:  心跳间隔（秒），默认 30
        :param shop_cookies_map:    各店铺登录 cookies，格式：{shop_id: cookies_dict}，
                                    可为 None（向后兼容）
        """
        self.server_url = server_url
        self.shops = shops
        self.poll_interval = poll_interval
        self.heartbeat_interval = heartbeat_interval
        self._shop_cookies_map: dict = shop_cookies_map or {}

        self._runners: dict = {}  # shop_id -> AikefuTaskRunner
        self._running = False

        for shop in shops:
            shop_id = str(shop.get("id", ""))
            shop_token = shop.get("shop_token", "")
            if not shop_token:
                logger.warning("店铺 %s 没有 shop_token，跳过", shop.get("name", shop_id))
                continue
            plugin_id = f"pdd_shop_{shop_id}"
            cookies = self._shop_cookies_map.get(shop_id, {})
            runner = AikefuTaskRunner(
                server_url=server_url,
                shop_token=shop_token,
                plugin_id=plugin_id,
                poll_interval=poll_interval,
                heartbeat_interval=heartbeat_interval,
                shop_cookies=cookies,
                shop_id=shop_id,
            )
            # 给 runner 附加店铺元信息，方便状态查询
            runner._shop_info = shop
            self._runners[shop_id] = runner

    async def start_all(self):
        """并发启动所有店铺的任务执行器"""
        if not self._runners:
            logger.info("MultiShopTaskRunner: 没有配置任何店铺")
            return
        self._running = True
        logger.info("MultiShopTaskRunner: 并发启动 %d 个店铺执行器", len(self._runners))
        await asyncio.gather(
            *(runner.start() for runner in self._runners.values()),
            return_exceptions=True,
        )

    async def stop_all(self):
        """停止所有执行器"""
        self._running = False
        await asyncio.gather(
            *(runner.stop() for runner in self._runners.values()),
            return_exceptions=True,
        )
        logger.info("MultiShopTaskRunner: 所有执行器已停止")

    async def start_shop(self, shop_id: str):
        """单独启动某个店铺的执行器"""
        runner = self._runners.get(str(shop_id))
        if runner:
            asyncio.create_task(runner.start())

    async def stop_shop(self, shop_id: str):
        """单独停止某个店铺的执行器"""
        runner = self._runners.get(str(shop_id))
        if runner:
            await runner.stop()

    def update_shop_cookies(self, shop_id: str, cookies: dict):
        """
        更新指定店铺的登录 cookies（店铺重新登录后调用）。
        同步更新内部 cookies 映射和对应 runner 的 shop_cookies。

        :param shop_id:  店铺 ID（字符串）
        :param cookies:  新的 cookies 字典 {name: value}
        """
        shop_id = str(shop_id)
        self._shop_cookies_map[shop_id] = cookies
        runner = self._runners.get(shop_id)
        if runner:
            runner.shop_cookies = cookies
            logger.info("已更新店铺 %s 的 cookies", shop_id)
        else:
            logger.warning("店铺 %s 的执行器不存在，无法更新 cookies", shop_id)

    def get_status(self) -> list:
        """
        返回每个店铺执行器的状态列表。
        格式：[{"id": "1", "name": "店铺名", "plugin_id": "pdd_shop_1",
                "running": True, "shop_token": "xxx", "has_cookies": True}]
        """
        result = []
        for shop_id, runner in self._runners.items():
            shop_info = getattr(runner, "_shop_info", {})
            result.append({
                "id": shop_id,
                "name": shop_info.get("name", shop_id),
                "plugin_id": runner.plugin_id,
                "running": runner._running,
                "shop_token": runner.shop_token,
                "platform": shop_info.get("platform", "pdd"),
                "has_cookies": bool(runner.shop_cookies),
            })
        return result
