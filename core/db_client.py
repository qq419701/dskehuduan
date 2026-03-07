# -*- coding: utf-8 -*-
"""
MySQL数据库客户端
直接连接 aikefu MySQL 数据库，操作 shops / messages / pdd_orders 表
"""
import logging
from datetime import datetime
from typing import Optional

import pymysql
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)


class DBClient:
    """aikefu MySQL数据库客户端"""

    def __init__(self, host: str, port: int, database: str, user: str, password: str):
        url = (
            f"mysql+pymysql://{user}:{password}@{host}:{port}/{database}"
            f"?charset=utf8mb4"
        )
        self.engine = create_engine(
            url,
            pool_pre_ping=True,
            pool_recycle=3600,
            echo=False,
        )
        self.Session = sessionmaker(bind=self.engine)

    # ------------------------------------------------------------------
    # 连接测试
    # ------------------------------------------------------------------

    def test_connection(self) -> bool:
        """测试数据库连接是否正常"""
        try:
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        except Exception as e:
            logger.error("数据库连接失败: %s", e)
            return False

    # ------------------------------------------------------------------
    # shops 表操作
    # ------------------------------------------------------------------

    def get_shops(self) -> list:
        """获取所有启用的店铺列表"""
        sql = text(
            "SELECT id AS shop_id, name, platform, platform_shop_id, shop_token, "
            "auto_reply_enabled, is_active "
            "FROM shops WHERE is_active = 1"
        )
        try:
            with self.engine.connect() as conn:
                result = conn.execute(sql)
                rows = result.mappings().all()
                return [dict(row) for row in rows]
        except SQLAlchemyError as e:
            logger.error("获取店铺列表失败: %s", e)
            return []

    def get_shop_by_token(self, shop_token: str) -> Optional[dict]:
        """通过shop_token获取店铺信息"""
        sql = text(
            "SELECT id AS shop_id, name, platform, platform_shop_id, shop_token, "
            "auto_reply_enabled, is_active "
            "FROM shops WHERE shop_token = :token LIMIT 1"
        )
        try:
            with self.engine.connect() as conn:
                result = conn.execute(sql, {"token": shop_token})
                row = result.mappings().first()
                return dict(row) if row else None
        except SQLAlchemyError as e:
            logger.error("通过token获取店铺失败: %s", e)
            return None

    def update_shop_token(self, shop_id: int, access_token: str, expires_at: datetime) -> bool:
        """更新店铺的平台access_token"""
        sql = text(
            "UPDATE shops SET access_token = :token, token_expires_at = :expires "
            "WHERE id = :shop_id"
        )
        try:
            with self.engine.begin() as conn:
                conn.execute(sql, {
                    "token": access_token,
                    "expires": expires_at,
                    "shop_id": shop_id,
                })
            return True
        except SQLAlchemyError as e:
            logger.error("更新access_token失败: %s", e)
            return False

    # ------------------------------------------------------------------
    # messages 表操作
    # ------------------------------------------------------------------

    def insert_message(
        self,
        shop_id: int,
        buyer_id: str,
        buyer_name: str,
        order_id: str,
        direction: str,
        content: str,
        msg_type: str,
        image_url: str = "",
        needs_human: bool = False,
        status: str = "pending",
    ) -> int:
        """插入消息记录到messages表，返回新记录id"""
        sql = text(
            "INSERT INTO messages "
            "(shop_id, buyer_id, buyer_name, order_id, direction, content, "
            "msg_type, image_url, needs_human, status, msg_time) "
            "VALUES (:shop_id, :buyer_id, :buyer_name, :order_id, :direction, "
            ":content, :msg_type, :image_url, :needs_human, :status, :msg_time)"
        )
        try:
            with self.engine.begin() as conn:
                result = conn.execute(sql, {
                    "shop_id": shop_id,
                    "buyer_id": buyer_id,
                    "buyer_name": buyer_name,
                    "order_id": order_id or "",
                    "direction": direction,
                    "content": content,
                    "msg_type": msg_type,
                    "image_url": image_url or "",
                    "needs_human": needs_human,
                    "status": status,
                    "msg_time": datetime.now(),
                })
                return result.lastrowid
        except SQLAlchemyError as e:
            logger.error("插入消息失败: %s", e)
            return 0

    def update_message_reply(
        self,
        message_id: int,
        reply_content: str,
        process_by: str,
        needs_human: bool,
        token_used: int = 0,
    ) -> bool:
        """更新消息的AI回复信息"""
        sql = text(
            "UPDATE messages SET status = 'processed', process_by = :process_by, "
            "needs_human = :needs_human, token_used = :token_used, "
            "processed_at = :processed_at "
            "WHERE id = :message_id"
        )
        try:
            with self.engine.begin() as conn:
                conn.execute(sql, {
                    "process_by": process_by,
                    "needs_human": needs_human,
                    "token_used": token_used,
                    "processed_at": datetime.now(),
                    "message_id": message_id,
                })
            return True
        except SQLAlchemyError as e:
            logger.error("更新消息回复失败: %s", e)
            return False

    def get_pending_messages(self, shop_id: int) -> list:
        """获取待处理消息（status=pending）"""
        sql = text(
            "SELECT id, shop_id, buyer_id, buyer_name, order_id, direction, "
            "content, msg_type, image_url, needs_human, status, msg_time "
            "FROM messages WHERE shop_id = :shop_id AND status = 'pending' "
            "ORDER BY msg_time ASC LIMIT 100"
        )
        try:
            with self.engine.connect() as conn:
                result = conn.execute(sql, {"shop_id": shop_id})
                return [dict(row) for row in result.mappings()]
        except SQLAlchemyError as e:
            logger.error("获取待处理消息失败: %s", e)
            return []

    def get_today_stats(self, shop_id: Optional[int] = None) -> dict:
        """获取今日统计数据（查messages表）"""
        base_where = "DATE(msg_time) = CURDATE()"
        params: dict = {}
        if shop_id:
            base_where += " AND shop_id = :shop_id"
            params["shop_id"] = shop_id

        sql_total = text(
            f"SELECT COUNT(*) FROM messages WHERE {base_where} AND direction = 'in'"
        )
        sql_ai = text(
            f"SELECT COUNT(*) FROM messages WHERE {base_where} "
            f"AND process_by IN ('rule', 'knowledge', 'ai')"
        )
        sql_human = text(
            f"SELECT COUNT(*) FROM messages WHERE {base_where} AND needs_human = 1"
        )

        try:
            with self.engine.connect() as conn:
                total = conn.execute(sql_total, params).scalar() or 0
                ai_count = conn.execute(sql_ai, params).scalar() or 0
                human_count = conn.execute(sql_human, params).scalar() or 0
            return {
                "total": total,
                "ai_handled": ai_count,
                "human_handled": human_count,
            }
        except SQLAlchemyError as e:
            logger.error("获取统计数据失败: %s", e)
            return {"total": 0, "ai_handled": 0, "human_handled": 0}

    def get_recent_messages(self, shop_id: int, limit: int = 50) -> list:
        """获取最近消息列表"""
        sql = text(
            "SELECT id, buyer_id, buyer_name, order_id, direction, content, "
            "msg_type, image_url, process_by, needs_human, status, msg_time "
            "FROM messages WHERE shop_id = :shop_id "
            "ORDER BY msg_time DESC LIMIT :limit"
        )
        try:
            with self.engine.connect() as conn:
                result = conn.execute(sql, {"shop_id": shop_id, "limit": limit})
                rows = [dict(row) for row in result.mappings()]
                return list(reversed(rows))
        except SQLAlchemyError as e:
            logger.error("获取最近消息失败: %s", e)
            return []

    # ------------------------------------------------------------------
    # pdd_orders 表操作
    # ------------------------------------------------------------------

    def insert_order(self, shop_id: int, order_data: dict) -> bool:
        """插入或更新订单记录（ON DUPLICATE KEY UPDATE）"""
        sql = text(
            "INSERT INTO pdd_orders "
            "(shop_id, order_sn, order_status, goods_name, goods_count, "
            "goods_price, pay_amount, buyer_id, buyer_name, receiver_name, "
            "receiver_phone, receiver_address, created_time, pay_time, "
            "remark, raw_data) "
            "VALUES (:shop_id, :order_sn, :order_status, :goods_name, "
            ":goods_count, :goods_price, :pay_amount, :buyer_id, :buyer_name, "
            ":receiver_name, :receiver_phone, :receiver_address, :created_time, "
            ":pay_time, :remark, :raw_data) "
            "ON DUPLICATE KEY UPDATE "
            "order_status = VALUES(order_status), "
            "goods_name = VALUES(goods_name), "
            "goods_count = VALUES(goods_count), "
            "goods_price = VALUES(goods_price), "
            "pay_amount = VALUES(pay_amount), "
            "receiver_name = VALUES(receiver_name), "
            "receiver_phone = VALUES(receiver_phone), "
            "receiver_address = VALUES(receiver_address), "
            "pay_time = VALUES(pay_time), "
            "remark = VALUES(remark), "
            "raw_data = VALUES(raw_data)"
        )
        import json

        created_time = None
        if order_data.get("created_time"):
            try:
                created_time = datetime.fromtimestamp(order_data["created_time"])
            except Exception:
                created_time = None

        pay_time = None
        if order_data.get("pay_time"):
            try:
                pay_time = datetime.fromtimestamp(order_data["pay_time"])
            except Exception:
                pay_time = None

        try:
            with self.engine.begin() as conn:
                conn.execute(sql, {
                    "shop_id": shop_id,
                    "order_sn": order_data.get("order_sn", ""),
                    "order_status": order_data.get("order_status", 0),
                    "goods_name": order_data.get("goods_name", ""),
                    "goods_count": order_data.get("goods_count", 1),
                    "goods_price": order_data.get("goods_price", 0),
                    "pay_amount": order_data.get("pay_amount", 0),
                    "buyer_id": order_data.get("buyer_id", ""),
                    "buyer_name": order_data.get("buyer_name", ""),
                    "receiver_name": order_data.get("receiver_name", ""),
                    "receiver_phone": order_data.get("receiver_phone", ""),
                    "receiver_address": order_data.get("receiver_address", ""),
                    "created_time": created_time,
                    "pay_time": pay_time,
                    "remark": order_data.get("remark", ""),
                    "raw_data": json.dumps(order_data, ensure_ascii=False),
                })
            return True
        except SQLAlchemyError as e:
            logger.error("插入订单失败: %s", e)
            return False
