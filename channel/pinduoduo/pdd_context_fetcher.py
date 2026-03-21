# -*- coding: utf-8 -*-
"""
通过 HTTP 接口主动采集买家订单上下文
无需拼多多开放API，使用客户端 cookies 鉴权
"""
import asyncio
import logging
import time
from typing import Optional
import aiohttp
import config as cfg

logger = logging.getLogger(__name__)

# 买家订单接口（latitude 聊天窗口接口，首选）
PDD_ORDER_LIST_URL = 'https://mms.pinduoduo.com/latitude/order/userAllOrder'
# 备用订单接口（mangkhut 后台接口，兜底）
PDD_ORDER_LIST_FALLBACK_URL = 'https://mms.pinduoduo.com/mangkhut/mms/recentOrderList'
# 买家浏览足迹接口（去掉错误的 /leopard/api 前缀）
PDD_RECOMMEND_GOODS_URL = 'https://mms.pinduoduo.com/latitude/goods/singleRecommendGoods'


class PddContextFetcher:
    """
    主动通过 HTTP API 采集买家订单，补充到上下文管理器
    采集方式：
    1. 通过 latitude/order/userAllOrder 接口，按 uid 过滤最近订单
    2. 通过 latitude/goods/singleRecommendGoods 接口获取浏览足迹
    3. 结果更新到 BuyerContextManager
    """

    def __init__(self, shop_id, cookies: dict, context_manager, shop_token: str = ''):
        self.shop_id = str(shop_id)
        self.cookies = cookies
        self.context_manager = context_manager
        self.shop_token = shop_token
        self._pending_buyers: set = set()   # 待查询的 buyer_id 队列
        self._querying: set = set()         # 正在查询中的 buyer_id
        self._last_query: dict = {}         # buyer_id -> 上次查询时间戳
        self._query_cooldown = 120          # 同一买家120秒内不重复查询
        self._running = False
        self._task = None

    def _build_headers(self) -> dict:
        anti = cfg.get_anti_content(self.shop_id)
        cookie_str = '; '.join(f'{k}={v}' for k, v in self.cookies.items())
        headers = {
            'Cookie': cookie_str,
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': 'https://mms.pinduoduo.com/',
            'Content-Type': 'application/json',
            'Origin': 'https://mms.pinduoduo.com',
        }
        if anti:
            headers['X-Anti-Content'] = anti
        return headers

    @staticmethod
    def _is_redirected(url: str) -> bool:
        return '/other/404' in url or '__from=' in url

    @staticmethod
    def _extract_orders(data: dict) -> list:
        result = data.get('result') or data.get('data') or {}
        if isinstance(result, dict):
            return result.get('orderList') or result.get('list') or result.get('orders') or []
        if isinstance(result, list):
            return result
        return []

    def request_fetch(self, buyer_id: str):
        """
        请求异步采集某买家的订单（非阻塞）
        由 pdd_channel 在收到买家消息时调用
        """
        buyer_id = str(buyer_id)
        now = time.time()
        last = self._last_query.get(buyer_id, 0)
        if now - last < self._query_cooldown:
            return  # 冷却期内不重复查
        if buyer_id not in self._querying:
            self._pending_buyers.add(buyer_id)

    async def fetch_and_update(self, buyer_id: str) -> bool:
        """
        立即并发采集买家订单和浏览足迹，更新上下文（带120秒冷却期）。
        由 pdd_channel 在每条买家消息时直接 await 调用，确保 AI 回复前有上下文数据。
        返回 True 表示采集到了新数据，返回 False 表示处于冷却期或未采集到数据。
        """
        buyer_id = str(buyer_id)
        now = time.time()
        last = self._last_query.get(buyer_id, 0)
        if now - last < self._query_cooldown:
            return False
        if buyer_id in self._querying:
            return False   # 正在采集中，跳过
        self._querying.add(buyer_id)
        self._last_query[buyer_id] = now
        try:
            # 并发采集：订单 + 浏览足迹
            orders_task = asyncio.create_task(self.fetch_buyer_orders(buyer_id))
            footprint_task = asyncio.create_task(self.fetch_buyer_footprint(buyer_id))
            orders, footprint = await asyncio.gather(orders_task, footprint_task, return_exceptions=True)

            updated = False
            if isinstance(orders, list) and orders:
                self.context_manager.update_from_http_orders(self.shop_id, buyer_id, orders)
                logger.info('[fetcher] 买家 %s 实时采集订单成功: %d 条', buyer_id, len(orders))
                updated = True
            elif isinstance(orders, Exception):
                logger.debug('[fetcher] 买家 %s 订单采集异常: %s', buyer_id, orders)
            if isinstance(footprint, dict) and footprint:
                # 只有当上下文中没有 current_goods 时才用接口数据（WS直接数据优先级更高）
                ctx = self.context_manager.get_context(self.shop_id, buyer_id)
                if not ctx.get('current_goods'):
                    self.context_manager.update_footprint(self.shop_id, buyer_id, footprint)
                    logger.info('[fetcher] 买家 %s 浏览足迹采集成功: %s', buyer_id, footprint.get('goods_name', ''))
                    updated = True
            elif isinstance(footprint, Exception):
                logger.debug('[fetcher] 买家 %s 浏览足迹采集异常: %s', buyer_id, footprint)
            return updated
        except Exception as e:
            logger.debug('[fetcher] 买家 %s fetch_and_update 异常: %s', buyer_id, e)
            return False
        finally:
            self._querying.discard(buyer_id)

    async def fetch_buyer_footprint(self, buyer_id: str, conversation_id: str = '') -> Optional[dict]:
        """
        通过 latitude/goods/singleRecommendGoods 接口获取买家浏览足迹
        返回最近浏览的商品信息（goods_id, goods_name, goods_img）
        """
        payload = {
            'type': 2,
            'uid': str(buyer_id),
            'conversationId': conversation_id,
            'pageSize': 5,
            'pageNum': 1,
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    PDD_RECOMMEND_GOODS_URL,
                    json=payload,
                    headers=self._build_headers(),
                    timeout=aiohttp.ClientTimeout(total=8),
                ) as resp:
                    final_url = str(resp.url)
                    if self._is_redirected(final_url):
                        logger.warning('[fetcher] 浏览足迹接口被重定向（session过期）: %s', final_url)
                        return None
                    if resp.status != 200:
                        return None
                    try:
                        data = await resp.json(content_type=None)
                    except Exception as e:
                        logger.debug('[fetcher] 浏览足迹接口响应非JSON: %s', e)
                        return None
            if not data.get('success'):
                return None
            result = data.get('result') or data.get('data') or {}
            # singleRecommendGoods 接口返回的 result 是列表（每个元素含 goodsList/total）
            if isinstance(result, list):
                first = result[0] if result else {}
                result = first if isinstance(first, dict) else {}
            goods_list = result.get('goodsList') or result.get('list') or []
            if not goods_list:
                return None
            # 优先取有"历史浏览"标签的商品
            footprint_goods = None
            for g in goods_list:
                tags = g.get('goodsTag') or {}
                footprint_tags = tags.get('footprintTags') or []
                for t in footprint_tags:
                    if '浏览' in str(t.get('desc', '')):
                        footprint_goods = g
                        break
                if footprint_goods:
                    break
            # 没有足迹标签，取第一个
            target = footprint_goods or goods_list[0]
            goods_id = str(target.get('goodsId') or target.get('goods_id') or '')
            goods_name = str(target.get('goodsName') or target.get('goods_name') or '')
            goods_img = str(target.get('goodsImageUrl') or target.get('thumbUrl') or target.get('goods_img') or '')
            if goods_id or goods_name:
                return {'goods_id': goods_id, 'goods_name': goods_name, 'goods_img': goods_img}
            return None
        except Exception as e:
            logger.debug('[fetcher] 买家 %s 浏览足迹采集异常: %s', buyer_id, e)
            return None

    async def fetch_buyer_orders(self, buyer_id: str) -> list:
        """
        通过 HTTP API 采集指定买家的最近订单
        首先尝试 latitude/order/userAllOrder 接口（聊天窗口实际接口），
        失败时回退到 mangkhut/mms/recentOrderList 接口
        """
        # 方法1：latitude/order/userAllOrder
        payload_latitude = {
            'uid': str(buyer_id),
            'pageSize': 10,
            'pageNum': 1,
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    PDD_ORDER_LIST_URL,
                    json=payload_latitude,
                    headers=self._build_headers(),
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 200:
                        final_url = str(resp.url)
                        if not self._is_redirected(final_url):
                            try:
                                data = await resp.json(content_type=None)
                            except Exception:
                                data = {}
                            if data.get('success'):
                                orders = self._extract_orders(data)
                                if orders:
                                    logger.info('买家 %s 通过latitude接口查到 %d 条订单', buyer_id, len(orders))
                                    return orders
                            else:
                                err = data.get('error_msg') or data.get('errorMsg') or ''
                                logger.debug('买家 %s latitude接口返回失败: %s，尝试兜底接口', buyer_id, err)
        except Exception as e:
            logger.debug('买家 %s latitude接口异常: %s，尝试兜底接口', buyer_id, e)

        # 方法2（兜底）：mangkhut/mms/recentOrderList + buyerUid
        now = int(time.time())
        payload_fallback = {
            'orderType': 0,
            'afterSaleType': 0,
            'remarkStatus': -1,
            'urgeShippingStatus': -1,
            'groupStartTime': now - 7 * 86400,
            'groupEndTime': now,
            'pageNumber': 1,
            'pageSize': 10,
            'hideRegionBlackDelayShipping': False,
            'mobileMarkSearch': False,
            'buyerUid': str(buyer_id),
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    PDD_ORDER_LIST_FALLBACK_URL,
                    json=payload_fallback,
                    headers=self._build_headers(),
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status != 200:
                        logger.debug('买家 %s 兜底订单查询返回 %d', buyer_id, resp.status)
                        return []
                    final_url = str(resp.url)
                    if self._is_redirected(final_url):
                        logger.warning('兜底订单接口被重定向（session过期）: %s', final_url)
                        return []
                    try:
                        data = await resp.json(content_type=None)
                    except Exception as e:
                        logger.debug('买家 %s 兜底接口响应非JSON: %s', buyer_id, e)
                        return []

            if not data.get('success'):
                err = data.get('error_msg') or data.get('errorMsg') or ''
                logger.debug('买家 %s 兜底订单查询失败: %s', buyer_id, err)
                return []

            orders = self._extract_orders(data)

            logger.info('买家 %s 通过兜底接口查到 %d 条近7天订单', buyer_id, len(orders))
            return orders

        except Exception as e:
            logger.debug('买家 %s 订单HTTP采集异常: %s', buyer_id, e)
            return []

    async def _process_pending(self):
        """处理待查询队列"""
        while self._pending_buyers:
            buyer_id = self._pending_buyers.pop()
            if buyer_id in self._querying:
                continue
            self._querying.add(buyer_id)
            try:
                orders = await self.fetch_buyer_orders(buyer_id)
                if orders:
                    self.context_manager.update_from_http_orders(
                        self.shop_id, buyer_id, orders
                    )
                self._last_query[buyer_id] = time.time()
            except Exception as e:
                logger.debug('处理买家 %s 订单采集异常: %s', buyer_id, e)
            finally:
                self._querying.discard(buyer_id)
            await asyncio.sleep(0.5)  # 避免请求过快

    async def run(self):
        """后台运行，定期处理待查询队列"""
        self._running = True
        logger.info('店铺 %s 买家上下文采集器已启动', self.shop_id)
        while self._running:
            try:
                if self._pending_buyers:
                    await self._process_pending()
            except Exception as e:
                logger.error('买家上下文采集器异常: %s', e)
            await asyncio.sleep(2)

    def stop(self):
        self._running = False

    async def fetch_once_if_needed(self, buyer_id: str, current_ctx: dict):
        """
        若该买家从未通过HTTP采集过订单，且当前上下文中无订单信息，
        则立即执行一次采集（最多等3秒），确保AI首条回复能带上订单信息。
        """
        buyer_id = str(buyer_id)
        # 已有订单上下文，不需要重复采集
        if current_ctx.get('order_sn') or current_ctx.get('order_info'):
            return
        # 已在冷却期内，不重复
        now = time.time()
        if now - self._last_query.get(buyer_id, 0) < self._query_cooldown:
            return
        # 正在查询中，等待最多3秒
        if buyer_id in self._querying:
            for _ in range(30):
                await asyncio.sleep(0.1)
                if buyer_id not in self._querying:
                    break
            return
        # 立即执行一次采集
        self._querying.add(buyer_id)
        try:
            orders = await self.fetch_buyer_orders(buyer_id)
            if orders:
                self.context_manager.update_from_http_orders(
                    self.shop_id, buyer_id, orders
                )
            self._last_query[buyer_id] = time.time()
            logger.info('[ctx_fetcher] 买家 %s 首次消息，立即采集订单完成', buyer_id)
        except Exception as e:
            logger.debug('[ctx_fetcher] 买家 %s 立即采集异常: %s', buyer_id, e)
        finally:
            self._querying.discard(buyer_id)

    def update_cookies(self, cookies: dict):
        """更新 cookies（店铺重新登录后调用）"""
        self.cookies = cookies
