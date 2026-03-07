# -*- coding: utf-8 -*-
"""
拼多多消息解析模块
解析WebSocket收到的原始消息数据，转换为标准格式
"""
import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# 消息类型映射
MSG_TYPE_MAP = {
    1: "text",       # 文字
    2: "image",      # 图片
    3: "goods",      # 商品咨询
    5: "withdraw",   # 撤回
    10: "order",     # 订单卡片
}


def parse_message(raw_data: dict) -> Optional[dict]:
    """
    解析原始WebSocket消息，返回标准格式。
    如果不是有效的买家消息，返回 None。

    标准格式：
    {
        "msg_id": str,
        "buyer_id": str,
        "buyer_name": str,
        "content": str,
        "msg_type": str,   # text/image/goods/withdraw/order
        "image_url": str,
        "order_id": str,
        "order_info": dict,
        "timestamp": int,
    }
    """
    try:
        # 拼多多WS消息通常有 msgBody / data 层
        body = raw_data
        if isinstance(raw_data.get("msgBody"), str):
            try:
                body = json.loads(raw_data["msgBody"])
            except Exception:
                body = raw_data

        msg_type_code = body.get("msgType") or body.get("type") or 1
        msg_type = MSG_TYPE_MAP.get(int(msg_type_code), "text")

        # 提取发送方信息（买家方向）
        from_user = body.get("fromUser") or body.get("senderId") or ""
        to_user = body.get("toUser") or body.get("receiverId") or ""

        # 判断消息方向：只处理买家发来的消息
        # 拼多多中 fromUser 通常是买家的用户ID
        buyer_id = str(from_user) if from_user else ""
        buyer_name = (
            body.get("fromNickname")
            or body.get("senderName")
            or body.get("nickName")
            or ""
        )

        msg_id = str(body.get("msgId") or body.get("id") or "")
        timestamp = body.get("createTime") or body.get("timestamp") or 0

        # 解析内容
        content = ""
        image_url = ""
        order_id = ""
        order_info = {}

        if msg_type == "text":
            content = _extract_text(body)
        elif msg_type == "image":
            image_url = _extract_image_url(body)
            content = "[图片]"
        elif msg_type == "goods":
            content, order_info = _extract_goods(body)
        elif msg_type == "order":
            content, order_id, order_info = _extract_order(body)
        elif msg_type == "withdraw":
            content = "[消息已撤回]"

        if not buyer_id and not content:
            return None

        return {
            "msg_id": msg_id,
            "buyer_id": buyer_id,
            "buyer_name": buyer_name,
            "content": content,
            "msg_type": msg_type,
            "image_url": image_url,
            "order_id": order_id,
            "order_info": order_info,
            "timestamp": int(timestamp),
        }

    except Exception as e:
        logger.debug("消息解析失败: %s, raw=%s", e, raw_data)
        return None


def _extract_text(body: dict) -> str:
    """提取文本内容"""
    # 尝试多个字段
    for field in ("content", "text", "msgContent", "message"):
        val = body.get(field)
        if val and isinstance(val, str):
            return val
        if val and isinstance(val, dict):
            inner = val.get("text") or val.get("content") or ""
            if inner:
                return str(inner)

    # msgBody 可能是JSON字符串
    msg_body = body.get("msgBody")
    if msg_body:
        if isinstance(msg_body, str):
            try:
                parsed = json.loads(msg_body)
                return str(parsed.get("content") or parsed.get("text") or "")
            except Exception:
                return str(msg_body)
        if isinstance(msg_body, dict):
            return str(msg_body.get("content") or msg_body.get("text") or "")

    return ""


def _extract_image_url(body: dict) -> str:
    """提取图片URL"""
    for field in ("imageUrl", "url", "picUrl", "imgUrl"):
        val = body.get(field)
        if val:
            return str(val)

    content = body.get("content") or body.get("msgBody") or {}
    if isinstance(content, str):
        try:
            content = json.loads(content)
        except Exception:
            return ""
    if isinstance(content, dict):
        for field in ("imageUrl", "url", "picUrl", "imgUrl"):
            val = content.get(field)
            if val:
                return str(val)

    return ""


def _extract_goods(body: dict) -> tuple:
    """提取商品信息，返回 (content_text, goods_info_dict)"""
    content_raw = body.get("content") or body.get("msgBody") or {}
    if isinstance(content_raw, str):
        try:
            content_raw = json.loads(content_raw)
        except Exception:
            return "[商品咨询]", {}

    if isinstance(content_raw, dict):
        goods_name = content_raw.get("goodsName") or content_raw.get("name") or ""
        goods_id = content_raw.get("goodsId") or content_raw.get("id") or ""
        price = content_raw.get("price") or content_raw.get("goodsPrice") or ""
        text = f"[商品咨询] {goods_name}" if goods_name else "[商品咨询]"
        return text, {"goods_id": str(goods_id), "goods_name": goods_name, "price": price}

    return "[商品咨询]", {}


def _extract_order(body: dict) -> tuple:
    """提取订单信息，返回 (content_text, order_id, order_info_dict)"""
    content_raw = body.get("content") or body.get("msgBody") or {}
    if isinstance(content_raw, str):
        try:
            content_raw = json.loads(content_raw)
        except Exception:
            return "[订单卡片]", "", {}

    if isinstance(content_raw, dict):
        order_sn = (
            content_raw.get("orderSn")
            or content_raw.get("order_sn")
            or content_raw.get("orderId")
            or ""
        )
        goods_name = content_raw.get("goodsName") or content_raw.get("name") or ""
        text = f"[订单] {order_sn}" if order_sn else "[订单卡片]"
        return text, str(order_sn), {"order_sn": str(order_sn), "goods_name": goods_name}

    return "[订单卡片]", "", {}
