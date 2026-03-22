# -*- coding: utf-8 -*-
"""
拼多多 WebSocket 消息解析
支持：文字、图片、撤回、商品卡片、订单卡片
"""
import json
import logging
import re
from typing import Optional
from urllib.parse import urlparse, parse_qs

logger = logging.getLogger(__name__)

def _extract_goods_from_url(text: str) -> Optional[dict]:
    """从拼多多商品URL提取goods_id"""
    goods_id = None
    # 匹配 yangkeduo.com 或 mobile.pinduoduo.com 的商品链接
    pattern = (
        r'https?://(?:mobile\.yangkeduo\.com|mobile\.pinduoduo\.com|yangkeduo\.com)\n        r'/goods(?:\.html|/detail)[^\s]*goods_id=(\d+)[^\s]*'
    )
    m = re.search(pattern, text)
    if m:
        goods_id = m.group(1)
    elif 'yangkeduo' in text or 'pinduoduo' in text:
        m2 = re.search(r'goods_id=(\d+)', text)
        if m2:
            goods_id = m2.group(1)

    if goods_id:
        return {
            'goods_id': goods_id,
            'goods_name': '',
            'goods_img': '',
        }
    return None


MSG_TYPE_MAP = {
    0: 'text', 1: 'text', 2: 'image', 3: 'audio',
    4: 'video', 5: 'goods', 6: 'order', 7: 'withdraw',
    8: 'system', 9: 'custom', 10: 'withdraw',
}

# 非聊天消息的 cmd/type 字符串值，遇到直接忽略
_NON_MSG_TYPES = frozenset({
    'request', 'response', 'push', 'notify', 'ping', 'pong',
    'ack', 'auth', 'heartbeat', 'connect', 'disconnect',
})

def parse_message(data: dict) -> Optional[dict]:
    if 'message' in data:
        return _parse_new_format(data['message'])
    if 'msgType' in data or 'type' in data or 'fromUser' in data or 'senderId' in data:
        return _parse_old_format(data)
    return None


def _extract_source_goods_from_biz(biz: dict) -> Optional[dict]:
    """从 biz 上下文提取浏览商品信息，支持扁平字段和 sourceGoods 对象两种格式"""
    goods_id = str(biz.get('goods_id') or biz.get('goodsId') or biz.get('sourceGoodsId') or '')
    goods_name = str(biz.get('goods_name') or biz.get('goodsName') or biz.get('sourceGoodsName') or '')
    goods_img = str(biz.get('goods_img') or biz.get('goodsImg') or biz.get('sourceGoodsImg') or biz.get('goodsImageUrl') or '')
    goods_price = biz.get('goods_price') or biz.get('goodsPrice') or biz.get('minGroupPrice') or 0

    source_obj = biz.get('sourceGoods') or biz.get('source_goods') or {}
    if isinstance(source_obj, dict) and source_obj:
        goods_id = goods_id or str(source_obj.get('goodsId') or source_obj.get('goods_id') or '')
        goods_name = goods_name or str(source_obj.get('goodsName') or source_obj.get('goods_name') or '')
        goods_img = goods_img or str(source_obj.get('goodsImg') or source_obj.get('thumbUrl') or source_obj.get('mainImgUrl') or '')
        goods_price = goods_price or source_obj.get('minGroupPrice') or source_obj.get('price') or 0

    for field in ('currentGoods', 'recommendGoods', 'linkGoods', 'goods'):
        obj = biz.get(field)
        if isinstance(obj, dict) and obj:
            goods_id = goods_id or str(obj.get('goodsId') or obj.get('goods_id') or '')
            goods_name = goods_name or str(obj.get('goodsName') or obj.get('goods_name') or '')
            goods_img = goods_img or str(obj.get('goodsImg') or obj.get('thumbUrl') or obj.get('mainImgUrl') or '')
            goods_price = goods_price or obj.get('minGroupPrice') or obj.get('price') or 0
            if goods_id or goods_name:
                break

    ctx_obj = biz.get('context')
    if isinstance(ctx_obj, dict):
        nested = ctx_obj.get('sourceGoods') or {}
        if isinstance(nested, dict) and nested:
            goods_id = goods_id or str(nested.get('goodsId') or nested.get('goods_id') or '')
            goods_name = goods_name or str(nested.get('goodsName') or nested.get('goods_name') or '')
            goods_img = goods_img or str(nested.get('goodsImg') or nested.get('thumbUrl') or nested.get('mainImgUrl') or '')
            goods_price = goods_price or nested.get('minGroupPrice') or nested.get('price') or 0

    if goods_id or goods_name:
        logger.debug('[biz] 提取到商品 id=%s name=%s，biz顶层keys=%s',
                     goods_id, goods_name, list(biz.keys()))
        return {
            'goods_id': goods_id,
            'goods_name': goods_name,
            'goods_img': goods_img,
            'goods_price': goods_price,
        }
    return None


def _parse_new_format(msg: dict) -> Optional[dict]:
    from_info = msg.get('from') or {}
    role = from_info.get('role', '')
    if role not in ('user', 'buyer', ''):
        if role == 'mall_cs':
            return None

    buyer_id = str(from_info.get('uid') or msg.get('buyerId') or '')
    buyer_name = msg.get('nickname') or msg.get('buyerNick') or ''
    msg_id = str(msg.get('msg_id') or msg.get('msgId') or '')
    timestamp = msg.get('timestamp') or msg.get('createTime') or 0

    raw_type = msg.get('type') or msg.get('msgType') or 0
    msg_type = MSG_TYPE_MAP.get(int(raw_type) if str(raw_type).isdigit() else 0, 'text')

    biz = (msg.get('push_biz_context') or msg.get('bizContext') or
           msg.get('biz_context') or msg.get('pushBizContext') or {})
    msg_category = biz.get('msg_category') or biz.get('msgCategory') or 0

    content = ''
    image_url = ''
    order_id = ''
    order_info = {}

    raw_content = msg.get('content') or msg.get('msgContent') or ''

    if isinstance(raw_content, str) and raw_content.startswith('{'):
        try:
            content_obj = json.loads(raw_content)
            parsed = _parse_content_obj(content_obj, msg_type)
            content = parsed.get('content', '')
            image_url = parsed.get('image_url', '')
            order_id = parsed.get('order_id', '')
            order_info = parsed.get('order_info', {})
            if parsed.get('msg_type'):
                msg_type = parsed['msg_type']
        except Exception:
            content = raw_content
    elif isinstance(raw_content, dict):
        parsed = _parse_content_obj(raw_content, msg_type)
        content = parsed.get('content', '')
        image_url = parsed.get('image_url', '')
        order_id = parsed.get('order_id', '')
        order_info = parsed.get('order_info', {})
        if parsed.get('msg_type'):
            msg_type = parsed['msg_type']
    elif isinstance(raw_content, str):
        content = raw_content

    if msg_type == 'image' and not image_url:
        image_url = msg.get('imageUrl') or msg.get('url') or ''
        content = '[图片]'
    elif msg_type == 'withdraw':
        content = '[消息已撤回]'

    if not order_id:
        order_id = str(biz.get('order_sn') or biz.get('orderSn') or biz.get('order_id') or '')

    source_goods = _extract_source_goods_from_biz(biz)

    is_enter_session = int(msg_category) in (4, 5) or msg_type == 'system'

    if is_enter_session and not source_goods:
        for biz_key in ('push_biz_context', 'bizContext', 'biz_context', 'pushBizContext',
                        'context', 'msgContext'):
            alt_biz = msg.get(biz_key)
            if isinstance(alt_biz, dict) and alt_biz:
                source_goods = _extract_source_goods_from_biz(alt_biz)
                if source_goods:
                    break

    if msg_type == 'text' and content and not source_goods:
        extracted = _extract_goods_from_url(content)
        if extracted:
            source_goods = extracted
            msg_type = 'goods'
            order_info = {'goods_id': extracted['goods_id'], 'goods_name': ''}
            content = f"[商品链接] {content}"

    if not buyer_id and not content and not is_enter_session:
        return None

    return {
        'msg_id': msg_id,
        'buyer_id': buyer_id,
        'buyer_name': buyer_name,
        'content': content,
        'msg_type': msg_type,
        'image_url': image_url,
        'order_id': order_id,
        'order_info': order_info,
        'source_goods': source_goods,
        'is_enter_session': is_enter_session,
        'timestamp': int(timestamp) if timestamp else 0,
    }


def _parse_content_obj(obj: dict, current_type: str) -> dict:
    """解析JSON格式的消息内容（商品卡片、订单卡片等）"""
    result = {'content': '', 'image_url': '', 'order_id': '', 'order_info': {}, 'msg_type': ''}

    if 'goodsId' in obj or 'goods_id' in obj or 'goodsName' in obj:
        goods_id = str(obj.get('goodsId') or obj.get('goods_id') or '')
        goods_name = str(obj.get('goodsName') or obj.get('goods_name') or obj.get('name') or '')
        price = obj.get('minGroupPrice') or obj.get('price') or obj.get('minPrice') or 0
        price_yuan = f'{int(price)/100:.2f}' if price else ''
        thumb = obj.get('thumbUrl') or obj.get('imageUrl') or obj.get('goodsImageUrl') or ''
        result['msg_type'] = 'goods'
        result['content'] = f'[商品] {goods_name}' + (f' ¥{price_yuan}' if price_yuan else '')
        result['image_url'] = thumb
        result['order_info'] = {'goods_id': goods_id, 'goods_name': goods_name, 'price': price}
        return result

    if 'orderSn' in obj or 'order_sn' in obj or 'sn' in obj:
        order_sn = str(obj.get('orderSn') or obj.get('order_sn') or obj.get('sn') or '')
        goods_name = str(obj.get('goodsName') or obj.get('goods_name') or obj.get('skuName') or '')
        status = str(obj.get('orderStatusStr') or obj.get('statusStr') or obj.get('status') or '')
        amount = obj.get('payAmount') or obj.get('pay_amount') or 0
        amount_yuan = f'{int(amount)/100:.2f}' if amount else ''
        thumb = obj.get('goodsThumbUrl') or obj.get('thumbUrl') or obj.get('imageUrl') or ''
        result['msg_type'] = 'order'
        result['order_id'] = order_sn
        result['content'] = f'[订单] {order_sn}' + (f' {goods_name}' if goods_name else '') + (f' ¥{amount_yuan}' if amount_yuan else '') + (f' {status}' if status else '')
        result['image_url'] = thumb
        result['order_info'] = obj
        return result

    if 'url' in obj or 'imageUrl' in obj or 'picUrl' in obj:
        url = obj.get('url') or obj.get('imageUrl') or obj.get('picUrl') or ''
        result['msg_type'] = 'image'
        result['image_url'] = str(url)
        result['content'] = '[图片]'
        return result

    text = obj.get('text') or obj.get('content') or obj.get('message') or ''
    if text:
        result['content'] = str(text)

    return result


def _parse_old_format(body: dict) -> Optional[dict]:
    msg_type_code = body.get('msgType') or body.get('type') or 1
    # 非数字字符串（如 'request'、'push' 等控制帧）直接忽略
    if isinstance(msg_type_code, str) and msg_type_code.lower() in _NON_MSG_TYPES:
        return None
    msg_type = MSG_TYPE_MAP.get(int(msg_type_code) if str(msg_type_code).isdigit() else 0, 'text')
    from_user = body.get('fromUser') or body.get('senderId') or ''
    buyer_id = str(from_user) if from_user else ''
    buyer_name = body.get('fromNickname') or body.get('senderName') or body.get('nickName') or ''
    msg_id = str(body.get('msgId') or body.get('id') or '')
    timestamp = body.get('createTime') or body.get('timestamp') or 0
    content = ''
    image_url = ''
    order_id = ''
    order_info = {}

    if msg_type == 'text':
        for field in ('content', 'text', 'msgContent', 'message'):
            val = body.get(field)
            if val and isinstance(val, str):
                content = val
                break
    elif msg_type == 'image':
        for field in ('imageUrl', 'url', 'picUrl', 'imgUrl'):
            val = body.get(field)
            if val:
                image_url = str(val)
                break
        content = '[图片]'
    elif msg_type == 'withdraw':
        content = '[消息已撤回]'

    biz_old = body.get('push_biz_context') or body.get('bizContext') or {}
    source_goods = _extract_source_goods_from_biz(biz_old)

    if msg_type == 'text' and content and not source_goods:
        extracted = _extract_goods_from_url(content)
        if extracted:
            source_goods = extracted
            msg_type = 'goods'
            order_info = {'goods_id': extracted['goods_id'], 'goods_name': ''}
            content = f"[商品链接] {content}"

    if not buyer_id and not content:
        return None

    return {
        'msg_id': msg_id,
        'buyer_id': buyer_id,
        'buyer_name': buyer_name,
        'content': content,
        'msg_type': msg_type,
        'image_url': image_url,
        'order_id': order_id,
        'order_info': order_info,
        'source_goods': source_goods,
        'is_enter_session': False,
        'timestamp': int(timestamp) if timestamp else 0,
    }