# -*- coding: utf-8 -*-
"""
自动换号处理器
当 AI 或关键词识别到买家提出换号请求时，自动从 pdd 订单中获取订单号，
调用 UHaozuAutomation.exchange_number() 完成换号，并将新账号密码发送给买家。
"""
import asyncio
import json
import logging
import os
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# 换号次数记录文件路径
EXCHANGE_RECORDS_FILE = os.path.join(
    os.path.expanduser("~"), ".aikefu-client", "exchange_records.json"
)

# 换号触发关键词
EXCHANGE_KEYWORDS = [
    "换号", "换个号", "换一个", "号不好用", "号有问题",
    "这个号", "换账号", "帮我换", "重新换",
]


def load_exchange_records() -> dict:
    """读取换号次数记录，失败时返回空字典"""
    try:
        if os.path.exists(EXCHANGE_RECORDS_FILE):
            with open(EXCHANGE_RECORDS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        logger.warning("读取换号记录失败: %s", e)
    return {}


def save_exchange_records(records: dict) -> bool:
    """保存换号次数记录"""
    try:
        os.makedirs(os.path.dirname(EXCHANGE_RECORDS_FILE), exist_ok=True)
        with open(EXCHANGE_RECORDS_FILE, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.warning("保存换号记录失败: %s", e)
        return False


def get_order_exchange_count(order_id: str) -> int:
    """获取指定订单的换号次数"""
    records = load_exchange_records()
    return records.get(order_id, {}).get("count", 0)


def increment_order_exchange_count(order_id: str) -> int:
    """递增指定订单的换号次数，返回新的次数"""
    records = load_exchange_records()
    entry = records.get(order_id, {"count": 0})
    entry["count"] = entry.get("count", 0) + 1
    entry["last_time"] = datetime.now().isoformat()
    records[order_id] = entry
    save_exchange_records(records)
    return entry["count"]


class ExchangeHandler:
    """自动换号处理器，可作为 PddChannel 的实例属性缓存"""

    def is_exchange_request(self, content: str) -> bool:
        """判断买家消息是否包含换号请求关键词"""
        if not content:
            return False
        return any(kw in content for kw in EXCHANGE_KEYWORDS)

    async def handle_exchange(
        self,
        buyer_id: str,
        buyer_name: str,
        content: str,
        order_id: Optional[str],
        order_info: dict,
        sender,
        shop_id: str,
        db_client=None,
    ) -> bool:
        """
        执行换号流程。
        返回 True 表示已处理（不需要再走 AI 流程），False 表示需要 fallback 到 AI。
        """
        import config

        # 1. 获取 order_id（优先使用传入值，再从 order_info 中取）
        if not order_id and order_info:
            order_id = str(order_info.get("order_id", ""))

        if not order_id:
            await self._send_reply(
                sender, buyer_id,
                "您好，请提供您的拼多多订单号，我们马上为您换号～"
            )
            return True

        # 2. 检查换号次数上限
        settings = config.get_uhaozu_settings()
        max_exchange = settings.get("max_exchange_per_order", 5)
        current_count = get_order_exchange_count(order_id)
        if current_count >= max_exchange:
            await self._send_reply(
                sender, buyer_id,
                f"您的订单换号次数已达上限（{max_exchange}次），如有其他问题欢迎联系客服"
            )
            return True

        # 3. 获取默认 U号租账号
        account = config.get_default_uhaozu_account()
        if not account:
            logger.info("未配置默认U号租账号，换号请求 fallback 到 AI 流程")
            return False

        # 4. 调用 UHaozuAutomation.exchange_number()
        try:
            result = await self._do_exchange(account, order_id)
        except Exception as e:
            logger.error("换号执行异常: %s", e)
            await self._send_reply(
                sender, buyer_id,
                "换号遇到了点问题，请稍后重试，或联系客服为您手动处理～"
            )
            return False

        if result.get("success"):
            new_account = result.get("new_account", "")
            # 解析账号密码（格式通常为 "账号----密码"）
            if "----" in new_account:
                parts = new_account.split("----", 1)
                acc_str = parts[0].strip()
                pwd_str = parts[1].strip()
                msg = f"已为您换号成功！新账号：{acc_str}，密码：{pwd_str}，如有问题请随时告知😊"
            else:
                msg = f"已为您换号成功！新账号：{new_account}，如有问题请随时告知😊"

            await self._send_reply(sender, buyer_id, msg)
            increment_order_exchange_count(order_id)
            return True
        else:
            err_msg = result.get("message", "")
            logger.warning("换号失败: %s", err_msg)
            await self._send_reply(
                sender, buyer_id,
                "换号遇到了点问题，请稍后重试，或联系客服为您手动处理～"
            )
            return False

    async def _do_exchange(self, account: dict, order_id: str) -> dict:
        """在 executor 中运行 UHaozuAutomation.exchange_number()"""
        from automation.uhaozu import UHaozuAutomation

        def _run():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                automation = UHaozuAutomation(
                    phone=account.get("phone", ""),
                    employee_account=account.get("employee_account", ""),
                    password=account.get("password", ""),
                )
                return loop.run_until_complete(automation.exchange_number(order_id))
            finally:
                loop.close()

        return await asyncio.get_event_loop().run_in_executor(None, _run)

    async def _send_reply(self, sender, buyer_id: str, text: str):
        """安全地发送回复消息"""
        if sender and buyer_id:
            try:
                await sender.send_text(buyer_id, text)
            except Exception as e:
                logger.error("发送换号回复失败: %s", e)
