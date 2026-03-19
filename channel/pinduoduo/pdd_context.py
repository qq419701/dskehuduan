# -*- coding: utf-8 -*-
"""
买家上下文管理器
负责维护每个买家的订单、浏览商品等上下文信息
全部通过客户端HTTP采集（无需拼多多开放API）
"""
import logging
import time

logger = logging.getLogger(__name__)

# 上下文过期时间（秒），超过此时间的缓存会被清理
CONTEXT_TTL = 2 * 3600  # 2小时


class BuyerContext:
    """单个买家的上下文数据"""
    def __init__(self):
        self.order_sn: str = ''           # 最近订单号
        self.order_info: dict = {}        # 最近订单详细信息
        self.current_goods: dict = {}     # 当前浏览的商品（浏览足迹）
        self.last_updated: float = time.time()

    def is_expired(self) -> bool:
        return time.time() - self.last_updated > CONTEXT_TTL

    def touch(self):
        self.last_updated = time.time()

    def to_dict(self) -> dict:
        return {
            'order_sn': self.order_sn,
            'order_info': self.order_info,
            'current_goods': self.current_goods if self.current_goods else None,
        }


class BuyerContextManager:
    """
    买家上下文管理器（单例，每个shop_id独立管理）

    上下文来源（优先级由高到低）：
    1. WS消息中的订单卡片/商品卡片（msg_type=order/goods）
    2. WS消息的 push_biz_context 中的 goods_id/goods_name（浏览足迹）
    3. HTTP API 主动拉取买家对本店铺的最近订单
    """

    def __init__(self):
        # _store: {shop_id: {buyer_id: BuyerContext}}
        self._store: dict = {}

    def _get_ctx(self, shop_id: str, buyer_id: str) -> BuyerContext:
        shop_id = str(shop_id)
        buyer_id = str(buyer_id)
        if shop_id not in self._store:
            self._store[shop_id] = {}
        if buyer_id not in self._store[shop_id]:
            self._store[shop_id][buyer_id] = BuyerContext()
        ctx = self._store[shop_id][buyer_id]
        ctx.touch()
        return ctx

    def update_from_message(self, shop_id: str, buyer_id: str, msg: dict):
        """
        从已解析的WS消息中更新买家上下文
        包括：订单卡片、商品卡片、浏览足迹(source_goods/biz_goods)
        """
        ctx = self._get_ctx(shop_id, buyer_id)
        msg_type = msg.get('msg_type', '')

        # 1. 订单卡片消息 → 更新订单上下文
        if msg_type == 'order':
            order_info = msg.get('order_info') or {}
            order_sn = msg.get('order_id') or str(order_info.get('orderSn') or order_info.get('order_sn') or '')
            if order_sn:
                ctx.order_sn = order_sn
                ctx.order_info = order_info
                logger.info('买家 %s 订单上下文已更新（订单卡片）: %s', buyer_id, order_sn)

        # 2. 商品卡片消息 → 更新浏览足迹
        if msg_type == 'goods':
            order_info = msg.get('order_info') or {}
            goods_id = str(order_info.get('goods_id') or order_info.get('goodsId') or '')
            goods_name = str(order_info.get('goods_name') or order_info.get('goodsName') or '')
            goods_img = str(order_info.get('goods_img') or order_info.get('goodsImg') or '')
            if goods_id or goods_name:
                ctx.current_goods = {
                    'goods_id': goods_id,
                    'goods_name': goods_name,
                    'goods_img': goods_img,
                }
                logger.info('买家 %s 浏览足迹已更新（商品卡片）: %s', buyer_id, goods_name)

        # 3. 消息中携带 source_goods（WS biz 上下文中的浏览商品）
        source_goods = msg.get('source_goods')
        if source_goods and isinstance(source_goods, dict):
            goods_id = str(source_goods.get('goods_id') or source_goods.get('goodsId') or '')
            goods_name = str(source_goods.get('goods_name') or source_goods.get('goodsName') or '')
            goods_img = str(source_goods.get('goods_img') or source_goods.get('goodsImg') or '')
            if goods_id or goods_name:
                ctx.current_goods = {
                    'goods_id': goods_id,
                    'goods_name': goods_name,
                    'goods_img': goods_img,
                }
                logger.info('买家 %s 浏览足迹已更新（source_goods）: %s %s', buyer_id, goods_id, goods_name)

    def update_from_http_orders(self, shop_id: str, buyer_id: str, orders: list):
        """
        从HTTP API拉取的订单列表更新上下文（取最近一条）
        由 PddContextFetcher 调用
        """
        if not orders:
            return
        ctx = self._get_ctx(shop_id, buyer_id)
        # 取第一条（最近的）
        latest = orders[0]
        order_sn = str(
            latest.get('orderSn') or latest.get('order_sn') or
            latest.get('sn') or ''
        )
        if order_sn and order_sn != ctx.order_sn:
            ctx.order_sn = order_sn
            ctx.order_info = latest
            logger.info('买家 %s 订单上下文已更新（HTTP采集）: %s', buyer_id, order_sn)

    def get_context(self, shop_id: str, buyer_id: str) -> dict:
        """
        获取买家当前上下文，返回字典：
        {order_sn, order_info, current_goods}
        没有上下文时返回空字典
        """
        shop_id = str(shop_id)
        buyer_id = str(buyer_id)
        shop_store = self._store.get(shop_id, {})
        ctx = shop_store.get(buyer_id)
        if ctx and not ctx.is_expired():
            return ctx.to_dict()
        return {}

    def cleanup_expired(self):
        """清理过期的上下文缓存，防止内存泄漏"""
        for shop_id in list(self._store.keys()):
            for buyer_id in list(self._store[shop_id].keys()):
                if self._store[shop_id][buyer_id].is_expired():
                    del self._store[shop_id][buyer_id]


# 全局单例
_manager = BuyerContextManager()


def get_manager() -> BuyerContextManager:
    return _manager
