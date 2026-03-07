# -*- coding: utf-8 -*-
"""
拼多多订单采集模块
使用登录后的Cookie调用拼多多商家API获取订单数据
"""
import asyncio
import logging
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)

PDD_ORDER_LIST_URL = "https://mms.pinduoduo.com/mms/api/order/list"
ORDER_SYNC_INTERVAL = 300  # 同步间隔（秒），5分钟


class PddOrderCollector:
    """拼多多订单采集器"""

    def __init__(self, shop_id: int, db_client=None):
        self.shop_id = shop_id
        self.db_client = db_client
        self._running = False

    async def fetch_orders(self, cookies: dict, page: int = 1, page_size: int = 20) -> list:
        """
        获取订单列表
        GET https://mms.pinduoduo.com/mms/api/order/list
        """
        cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
        headers = {
            "Cookie": cookie_str,
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Referer": "https://mms.pinduoduo.com/",
        }
        params = {
            "page": page,
            "pageSize": page_size,
            "orderStatus": "",  # 空=全部状态
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    PDD_ORDER_LIST_URL,
                    headers=headers,
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=15),
                    ssl=False,
                ) as resp:
                    if resp.status != 200:
                        logger.warning("订单接口返回 %d", resp.status)
                        return []
                    data = await resp.json()

            if not data.get("success"):
                logger.warning("获取订单失败: %s", data.get("errorMsg"))
                return []

            result = data.get("result") or data.get("data") or {}
            orders = result.get("list") or result.get("orders") or []
            return self._normalize_orders(orders)

        except Exception as e:
            logger.error("获取订单列表异常: %s", e)
            return []

    def _normalize_orders(self, raw_orders: list) -> list:
        """将原始订单数据标准化"""
        normalized = []
        for order in raw_orders:
            try:
                normalized.append({
                    "order_sn": str(order.get("orderSn") or order.get("order_sn") or ""),
                    "order_status": int(order.get("orderStatus") or order.get("order_status") or 0),
                    "goods_name": str(order.get("goodsName") or order.get("goods_name") or ""),
                    "goods_count": int(order.get("goodsCount") or order.get("goods_count") or 1),
                    "goods_price": int(order.get("goodsPrice") or order.get("goods_price") or 0),
                    "pay_amount": int(order.get("payAmount") or order.get("pay_amount") or 0),
                    "buyer_id": str(order.get("buyerId") or order.get("buyer_id") or ""),
                    "buyer_name": str(order.get("buyerNick") or order.get("buyer_name") or ""),
                    "receiver_name": str(order.get("receiverName") or order.get("receiver_name") or ""),
                    "receiver_phone": str(order.get("receiverPhone") or order.get("receiver_phone") or ""),
                    "receiver_address": str(
                        order.get("receiverAddress") or order.get("receiver_address") or ""
                    ),
                    "created_time": order.get("createdTime") or order.get("created_time"),
                    "pay_time": order.get("payTime") or order.get("pay_time"),
                    "remark": str(order.get("remark") or ""),
                })
            except Exception as e:
                logger.debug("订单标准化失败: %s", e)
        return normalized

    async def sync_orders(self, cookies: dict):
        """全量同步订单到MySQL pdd_orders表"""
        logger.info("开始同步店铺 %s 的订单...", self.shop_id)
        page = 1
        total_synced = 0

        while True:
            orders = await self.fetch_orders(cookies, page=page)
            if not orders:
                break

            for order in orders:
                if self.db_client:
                    self.db_client.insert_order(self.shop_id, order)
                    total_synced += 1

            if len(orders) < 20:  # 最后一页
                break
            page += 1
            await asyncio.sleep(1)  # 避免请求过于频繁

        logger.info("店铺 %s 订单同步完成，共同步 %d 条", self.shop_id, total_synced)

    async def watch_new_orders(self, cookies: dict):
        """定时监控新订单（每5分钟）"""
        self._running = True
        logger.info("店铺 %s 开始监控新订单", self.shop_id)

        while self._running:
            try:
                orders = await self.fetch_orders(cookies, page=1, page_size=10)
                for order in orders:
                    if self.db_client:
                        self.db_client.insert_order(self.shop_id, order)
            except Exception as e:
                logger.error("监控新订单异常: %s", e)

            await asyncio.sleep(ORDER_SYNC_INTERVAL)

    def stop(self):
        """停止监控"""
        self._running = False
