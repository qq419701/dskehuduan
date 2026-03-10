# -*- coding: utf-8 -*-
"""
aikefu 任务轮询执行器

功能：定期轮询 aikefu 服务端的任务队列（GET /api/plugin/tasks），
      自动执行客户端支持的插件动作，执行完成后回报结果。

支持的动作码：
  auto_exchange   — 自动换号（调用 UHaozuAutomation）
  handle_refund   — 退款处理（记录模式，目前为人工确认）
  auto_order      — 自动下单选号（预留，开发中）

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
    "auto_exchange": "_handle_auto_exchange",
    "handle_refund": "_handle_refund",
    "auto_order": "_handle_auto_order",
}

# 插件注册名称
PLUGIN_NAME = "自动换号客户端"

# 已执行任务 ID 最大缓存数量（防止无限增长）
MAX_EXECUTED_IDS = 2000


class AikefuTaskRunner:
    """
    aikefu 任务轮询执行器。
    启动后并发运行轮询协程和心跳协程，不阻塞 UI / PDD 消息监听。
    """

    def __init__(self, server_url: str, shop_token: str, plugin_id: str,
                 poll_interval: int = 2, heartbeat_interval: int = 30):
        """
        :param server_url:          aikefu 服务地址，如 http://8.145.43.255:6000
        :param shop_token:          店铺 Token（X-Shop-Token 请求头）
        :param plugin_id:           本客户端的插件唯一 ID（用于注册和心跳）
        :param poll_interval:       轮询间隔（秒），默认 2
        :param heartbeat_interval:  心跳间隔（秒），默认 30
        """
        self.server_url = server_url
        self.shop_token = shop_token
        self.plugin_id = plugin_id
        self.poll_interval = poll_interval
        self.heartbeat_interval = heartbeat_interval

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
                version="2.0.0",
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
