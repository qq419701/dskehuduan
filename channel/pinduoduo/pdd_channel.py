# -*- coding: utf-8 -*-
"""
拼多多 WebSocket 消息采集渠道
直连 wss://m-ws.pinduoduo.com/，实时接收买家消息
"""
import asyncio
import json
import logging
import time
from typing import Optional, Callable

import websockets
from websockets.exceptions import ConnectionClosed

from channel.base_channel import BaseChannel
from channel.pinduoduo.pdd_message import parse_message

logger = logging.getLogger(__name__)

PDD_WS_URL = "wss://m-ws.pinduoduo.com/"
HEARTBEAT_INTERVAL = 30  # 心跳间隔（秒）


class PddChannel(BaseChannel):
    """拼多多 WebSocket 采集渠道"""

    def __init__(
        self,
        shop_id: int,
        shop_info: dict,
        im_token: str,
        cookies: dict,
        db_client=None,
        server_api=None,
        sender=None,
    ):
        super().__init__(shop_id, shop_info)
        self.im_token = im_token
        self.cookies = cookies
        self.db_client = db_client
        self.server_api = server_api
        self.sender = sender  # PddSender 实例

        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._seen_msg_ids: set = set()  # 消息去重

    # ------------------------------------------------------------------
    # BaseChannel 接口实现
    # ------------------------------------------------------------------

    async def connect(self) -> bool:
        """建立 WebSocket 连接"""
        try:
            headers = self._build_headers()
            self._ws = await websockets.connect(
                PDD_WS_URL,
                extra_headers=headers,
                ping_interval=None,  # 手动管理心跳
                open_timeout=15,
                close_timeout=10,
            )
            logger.info("店铺 %s WebSocket 连接成功", self.shop_id)

            # 发送认证消息
            await self._authenticate()

            # 启动心跳
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

            return True
        except Exception as e:
            logger.error("店铺 %s WebSocket 连接失败: %s", self.shop_id, e)
            return False

    async def disconnect(self):
        """断开 WebSocket 连接"""
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass

        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

    async def run(self):
        """消息接收主循环"""
        if not self._ws:
            raise RuntimeError("WebSocket 未连接")

        try:
            async for raw_msg in self._ws:
                if not self.is_running:
                    break
                await self._handle_raw_message(raw_msg)
        except ConnectionClosed as e:
            logger.warning("店铺 %s WebSocket 连接断开: %s", self.shop_id, e)
        except Exception as e:
            logger.error("店铺 %s 消息接收异常: %s", self.shop_id, e)

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _build_headers(self) -> dict:
        """构建 WebSocket 连接头"""
        cookie_str = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
        return {
            "Cookie": cookie_str,
            "Origin": "https://mms.pinduoduo.com",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        }

    async def _authenticate(self):
        """发送认证消息"""
        auth_msg = {
            "cmd": "auth",
            "token": self.im_token,
            "timestamp": int(time.time() * 1000),
        }
        await self._ws.send(json.dumps(auth_msg, ensure_ascii=False))
        logger.debug("店铺 %s 已发送认证消息", self.shop_id)

    async def _heartbeat_loop(self):
        """心跳循环，每30秒发送一次"""
        try:
            while self.is_running and self._ws:
                await asyncio.sleep(HEARTBEAT_INTERVAL)
                if self._ws and self.is_running:
                    heartbeat = {"cmd": "ping", "timestamp": int(time.time() * 1000)}
                    try:
                        await self._ws.send(json.dumps(heartbeat))
                        logger.debug("店铺 %s 心跳已发送", self.shop_id)
                    except Exception as e:
                        logger.warning("店铺 %s 心跳发送失败: %s", self.shop_id, e)
                        break
        except asyncio.CancelledError:
            pass

    async def _handle_raw_message(self, raw_msg: str):
        """处理原始 WebSocket 消息"""
        try:
            if isinstance(raw_msg, bytes):
                raw_msg = raw_msg.decode("utf-8")
            data = json.loads(raw_msg)
        except Exception:
            return

        # 过滤掉心跳响应和系统消息
        cmd = data.get("cmd") or data.get("type") or ""
        if cmd in ("pong", "ack", "ping"):
            return

        # 尝试解析买家消息
        parsed = parse_message(data)
        if not parsed:
            return

        # 消息去重
        msg_id = parsed.get("msg_id", "")
        if msg_id and msg_id in self._seen_msg_ids:
            return
        if msg_id:
            self._seen_msg_ids.add(msg_id)
            # 限制集合大小，防止内存泄漏
            if len(self._seen_msg_ids) > 10000:
                self._seen_msg_ids.clear()

        await self._process_message(parsed)

    async def _process_message(self, msg: dict):
        """
        处理解析后的消息：
        1. 写入 MySQL messages 表
        2. 调用 aikefu API 获取 AI 回复
        3. 如果有回复且不需要人工 → 发送AI回复
        4. 更新 messages 表回复信息
        """
        buyer_id = msg.get("buyer_id", "")
        buyer_name = msg.get("buyer_name", "")
        content = msg.get("content", "")
        msg_type = msg.get("msg_type", "text")
        image_url = msg.get("image_url", "")
        order_id = msg.get("order_id", "")

        logger.info(
            "店铺 %s 收到消息 [%s] 买家:%s 内容:%s",
            self.shop_id, msg_type, buyer_name or buyer_id,
            content[:50] if content else "",
        )

        # 触发UI回调
        if self._message_callback:
            try:
                self._message_callback(self.shop_id, msg)
            except Exception:
                pass

        # 写入买家消息到数据库
        message_id = 0
        if self.db_client:
            message_id = self.db_client.insert_message(
                shop_id=self.shop_id,
                buyer_id=buyer_id,
                buyer_name=buyer_name,
                order_id=order_id,
                direction="in",
                content=content,
                msg_type=msg_type,
                image_url=image_url,
                status="pending",
            )

        # 只对文字/图片/商品/订单类消息请求AI回复
        if msg_type not in ("text", "image", "goods", "order") or not content:
            return

        if not self.server_api:
            return

        # 调用 aikefu API 获取 AI 回复
        try:
            api_result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self.server_api.send_message(
                    shop_id=self.shop_id,
                    buyer_id=buyer_id,
                    buyer_name=buyer_name,
                    content=content,
                    order_id=order_id,
                    msg_type=msg_type,
                    image_url=image_url,
                ),
            )
        except Exception as e:
            logger.error("调用服务器API异常: %s", e)
            return

        if not api_result.get("success"):
            return

        reply = api_result.get("reply", "")
        needs_human = api_result.get("needs_human", False)
        process_by = api_result.get("process_by", "ai")
        token_used = api_result.get("token_used", 0)

        # 更新消息状态
        if self.db_client and message_id:
            self.db_client.update_message_reply(
                message_id=message_id,
                reply_content=reply,
                process_by=process_by,
                needs_human=needs_human,
                token_used=token_used or 0,
            )

        # 如果有回复且不需要人工介入 → 发送AI回复
        if reply and not needs_human and self.sender:
            try:
                await self.sender.send_text(buyer_id, reply)

                # 记录发出的消息
                if self.db_client:
                    self.db_client.insert_message(
                        shop_id=self.shop_id,
                        buyer_id=buyer_id,
                        buyer_name=buyer_name,
                        order_id=order_id,
                        direction="out",
                        content=reply,
                        msg_type="text",
                        status="processed",
                    )
            except Exception as e:
                logger.error("发送AI回复失败: %s", e)
