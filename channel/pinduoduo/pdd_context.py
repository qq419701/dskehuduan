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

# HTTP采集浏览足迹不覆盖WS数据的保护时间（秒）
FOOTPRINT_CACHE_TTL = 600  # 10分钟


class BuyerContext:
    """单个买家的上下文数据"""
    def __init__(self):
        self.order_sn: str = ''           # 最近订单号
        self.order_info: dict = {}        # 最近订单详细信息
        self.current_goods: dict = {}     # 当前浏览的商品（浏览足迹）
        self.from_goods_detail: bool = False   # 买家是否来自商品详情页
        self.current_goods_url: str = ''       # 当前商品链接
        self.current_goods_updated: float = 0  # 浏览足迹最后更新时间（0表示从未更新）
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
            'from_goods_detail': self.from_goods_detail,
            'current_goods_url': self.current_goods_url,
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

        # 记录"来自商品详情页"标志
        if msg.get('from_goods_detail'):
            ctx.from_goods_detail = True

        # 1. 订单卡片消息 → 更新订单上下文
        if msg_type == 'order':
            order_info = msg.get('order_info') or {}
            order_sn = msg.get('order_id') or str(order_info.get('orderSn') or order_info.get('order_sn') or '')
            if order_sn:
                ctx.order_sn = order_sn
                ctx.order_info = order_info
                logger.info('买家 %s 订单上下文已更新（订单卡片）: %s', buyer_id, order_sn)

        # 2. 商品卡片消息 → 更新浏览足迹（兼容 order_info 和顶层字段两种格式）
        if msg_type == 'goods':
            order_info_data = msg.get('order_info') or {}
            # order_info 中的字段（来自 _parse_content_obj）
            goods_id = str(order_info_data.get('goods_id') or order_info_data.get('goodsId') or '')
            goods_name = str(order_info_data.get('goods_name') or order_info_data.get('goodsName') or '')
            goods_img = str(order_info_data.get('goods_img') or order_info_data.get('goodsImg') or '')
            goods_price = order_info_data.get('price') or 0
            # 若 order_info 里没有，再从 source_goods 补充
            sg = msg.get('source_goods') or {}
            if isinstance(sg, dict):
                goods_id = goods_id or str(sg.get('goods_id') or sg.get('goodsId') or '')
                goods_name = goods_name or str(sg.get('goods_name') or sg.get('goodsName') or '')
                goods_img = goods_img or str(sg.get('goods_img') or sg.get('goodsImg') or '')
                goods_price = goods_price or sg.get('goods_price') or sg.get('goodsPrice') or 0
            goods_url = msg.get('goods_url', '') or (sg.get('goods_url', '') if isinstance(sg, dict) else '')
            if goods_id or goods_name:
                ctx.current_goods = {
                    'goods_id': goods_id,
                    'goods_name': goods_name,
                    'goods_img': goods_img,
                    'goods_price': goods_price,
                }
                if goods_url:
                    ctx.current_goods['goods_url'] = goods_url
                    ctx.current_goods_url = goods_url
                ctx.current_goods_updated = time.time()
                logger.info('买家 %s 浏览足迹已更新（商品卡片）: %s %s', buyer_id, goods_id, goods_name)

        # 3. 兜底：任何消息类型，只要有 source_goods 字段就更新浏览足迹缓存
        source_goods = msg.get('source_goods')
        if source_goods and isinstance(source_goods, dict):
            goods_id = str(source_goods.get('goods_id') or source_goods.get('goodsId') or '')
            goods_name = str(source_goods.get('goods_name') or source_goods.get('goodsName') or '')
            goods_img = str(source_goods.get('goods_img') or source_goods.get('goodsImg') or '')
            goods_url = source_goods.get('goods_url', '') or msg.get('goods_url', '')
            if goods_id or goods_name:
                ctx.current_goods = {
                    'goods_id': goods_id,
                    'goods_name': goods_name,
                    'goods_img': goods_img,
                }
                if goods_url:
                    ctx.current_goods['goods_url'] = goods_url
                    ctx.current_goods_url = goods_url
                ctx.current_goods_updated = time.time()
                logger.debug('买家 %s 浏览足迹已更新（source_goods兜底）: %s', buyer_id, goods_name)

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
        # 同时兼容驼峰和蛇形命名（接口实际返回驼峰字段）
        order_sn = str(
            latest.get('orderSn') or latest.get('order_sn') or
            latest.get('sn') or latest.get('orderNo') or latest.get('id') or ''
        )
        # 总是更新 order_info（保证详情是最新的）
        ctx.order_info = latest
        if order_sn and order_sn != ctx.order_sn:
            ctx.order_sn = order_sn
            logger.info('买家 %s 订单号已更新（HTTP采集）: %s', buyer_id, order_sn)
        elif order_sn:
            logger.debug('买家 %s 订单详情已刷新（HTTP采集）: %s', buyer_id, order_sn)
        else:
            logger.debug('买家 %s 订单详情已刷新（HTTP采集，无订单号）', buyer_id)

        # 从订单商品列表更新浏览足迹（仅在WS缓存无数据时填充）
        if not (ctx.current_goods and (ctx.current_goods.get('goods_id') or ctx.current_goods.get('goods_name'))):
            goods_list = (latest.get('orderGoodsList') or latest.get('goods_list') or
                          latest.get('goodsList') or [])
            if goods_list and isinstance(goods_list[0], dict):
                g = goods_list[0]
                goods_name = g.get('goodsName') or g.get('goods_name') or ''
                goods_id = str(g.get('goodsId') or g.get('goods_id') or '')
                goods_img = str(g.get('goodsImageUrl') or g.get('thumbUrl') or g.get('goods_img') or '')
                if goods_name or goods_id:
                    ctx.current_goods = {
                        'goods_id': goods_id,
                        'goods_name': goods_name,
                        'goods_img': goods_img,
                    }
                    logger.debug('买家 %s 商品信息已从订单提取（HTTP采集）: %s', buyer_id, goods_name)

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

    def update_footprint(self, shop_id: str, buyer_id: str, goods: dict):
        """从HTTP接口采集的浏览足迹更新上下文（WS直接数据优先，但超过10分钟允许覆盖）"""
        ctx = self._get_ctx(shop_id, buyer_id)
        # 已有 current_goods 且10分钟内不覆盖（WS数据优先）
        if ctx.current_goods and (ctx.current_goods.get('goods_id') or ctx.current_goods.get('goods_name')):
            age = time.time() - ctx.current_goods_updated
            if age < FOOTPRINT_CACHE_TTL:
                return
        if goods.get('goods_id') or goods.get('goods_name'):
            ctx.current_goods = {
                'goods_id': str(goods.get('goods_id') or ''),
                'goods_name': str(goods.get('goods_name') or ''),
                'goods_img': str(goods.get('goods_img') or ''),
            }
            ctx.current_goods_updated = time.time()
            logger.info('买家 %s 浏览足迹已更新（HTTP singleRecommendGoods）: %s',
                        buyer_id, goods.get('goods_name', ''))

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
