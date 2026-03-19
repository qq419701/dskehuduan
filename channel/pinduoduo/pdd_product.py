# -*- coding: utf-8 -*-
"""
拼多多商品信息采集模块
采集店铺商品数据，用于同步到 aikefu 知识库
"""
import asyncio
import json
import logging

import aiohttp

logger = logging.getLogger(__name__)

PDD_GOODS_LIST_URL = "https://mms.pinduoduo.com/mms/api/goods/list"


def _safe_float(val, default=0.0) -> float:
    """安全转换为浮点数，转换失败时返回默认值"""
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _safe_int(val, default=0) -> int:
    """安全转换为整数，转换失败时返回默认值"""
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


class PddProductCollector:
    """拼多多商品采集器"""

    def __init__(self, shop_id: int, db_client=None, server_api=None, shop_token: str = ''):
        self.shop_id = shop_id
        self.db_client = db_client
        self.server_api = server_api
        # 店铺Token（同步到服务端时使用）
        self.shop_token = shop_token

    async def fetch_products(self, cookies: dict, page: int = 1, page_size: int = 20) -> list:
        """
        获取商品列表
        GET https://mms.pinduoduo.com/mms/api/goods/list
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
        params = {"page": page, "pageSize": page_size}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    PDD_GOODS_LIST_URL,
                    headers=headers,
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=15),
                    ssl=False,
                ) as resp:
                    if resp.status != 200:
                        return []
                    # 检测拼多多未登录/session过期时的重定向（HTTP 200但跳到404页）
                    final_url = str(resp.url)
                    if '/other/404' in final_url or '__from=' in final_url:
                        logger.warning('商品接口被重定向（可能未登录/session过期）: %s', final_url)
                        return []
                    try:
                        data = await resp.json(content_type=None)
                    except (json.JSONDecodeError, aiohttp.ContentTypeError) as e:
                        logger.error('商品接口响应解析失败: %s', e)
                        return []

            if not data.get("success"):
                return []

            result = data.get("result") or data.get("data") or {}
            goods = result.get("list") or result.get("goods") or []
            return goods

        except Exception as e:
            logger.error("获取商品列表异常: %s", e)
            return []

    async def sync_products(self, cookies: dict):
        """
        同步商品信息
        1. 分页拉取所有商品
        2. 如果配置了 server_api，批量上报到aikefu服务端
        """
        logger.info("开始同步店铺 %s 的商品信息...", self.shop_id)
        page = 1
        total = 0
        all_goods = []  # 收集所有商品，用于批量上报

        while True:
            products = await self.fetch_products(cookies, page=page)
            if not products:
                break
            # 规范化商品字段格式，便于服务端统一处理
            for item in products:
                normalized = {
                    'goods_id': str(item.get('goodsId') or item.get('goods_id') or ''),
                    'goods_name': str(item.get('goodsName') or item.get('goods_name') or ''),
                    'goods_img': str(item.get('goodsImageUrl') or item.get('goods_img') or ''),
                    'price': _safe_float(item.get('minGroupPrice') or item.get('price') or 0) / 100,
                    'stock': _safe_int(item.get('stockQuantity') or item.get('stock') or 0),
                    'status': '在售' if item.get('isOnSale') or item.get('status') == 1 else '下架',
                    'category': str(item.get('catName') or item.get('category') or ''),
                }
                all_goods.append(normalized)
            total += len(products)
            if len(products) < 20:
                break
            page += 1
            await asyncio.sleep(1)

        logger.info("店铺 %s 商品同步完成，共 %d 件", self.shop_id, total)

        # 批量上报到aikefu服务端（如已配置server_api）
        if self.server_api and all_goods and self.shop_token:
            try:
                result = self.server_api.sync_goods_to_server(self.shop_token, all_goods)
                logger.info("店铺 %s 商品已上报到服务端，结果: %s", self.shop_id, result)
            except Exception as e:
                logger.error("上报商品到服务端失败: %s", e)
