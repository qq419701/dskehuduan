# -*- coding: utf-8 -*-
"""
自动选号处理器
识别买家的游戏租号意图（游戏名 + 时长），自动搜号、加价报价、待买家确认后下单发号。
与 ExchangeHandler 共用换号次数记录读写工具函数（exchange_records.json）。
"""
import asyncio
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# 从 exchange_number 模块复用记录读写工具
from core.exchange_number import (
    load_exchange_records,
    save_exchange_records,
    get_order_exchange_count,
    increment_order_exchange_count,
)

# ── 游戏名关键词映射 ────────────────────────────────────────────────────────────

GAME_KEYWORDS = {
    "王者荣耀": ["王者", "王者荣耀", "wzry"],
    "火影忍者": ["火影", "火影忍者", "naruto"],
    "和平精英": ["和平精英", "吃鸡", "pubgm"],
}

# ── 时长解析正则 ────────────────────────────────────────────────────────────────

# 匹配如 "1小时"、"2h"、"30分钟"、"半小时" 等
_DURATION_PATTERNS = [
    (r"(\d+)\s*小时", lambda m: int(m.group(1))),
    (r"(\d+)\s*h(?:our)?s?", lambda m: int(m.group(1))),
    (r"半\s*小时", lambda _: 0.5),
    (r"(\d+)\s*分钟", lambda m: round(int(m.group(1)) / 60, 2)),
]

# 待确认状态存储（内存，进程重启后清空）
# key: buyer_id, value: {"game": str, "duration": float, "options": list, "selected": int}
_pending_confirm: dict = {}


def detect_game(content: str) -> Optional[str]:
    """从买家消息中识别游戏名，返回标准游戏名或 None"""
    content_lower = content.lower()
    for game, keywords in GAME_KEYWORDS.items():
        for kw in keywords:
            if kw.lower() in content_lower:
                return game
    return None


def parse_duration(content: str) -> Optional[float]:
    """从买家消息中解析租用时长（小时），返回 float 或 None"""
    for pattern, extractor in _DURATION_PATTERNS:
        m = re.search(pattern, content, re.IGNORECASE)
        if m:
            return extractor(m)
    return None


def is_select_number_request(content: str) -> bool:
    """判断买家消息是否包含选号意图（游戏名 + 时长）"""
    return detect_game(content) is not None and parse_duration(content) is not None


class NumberSelector:
    """自动选号处理器，可作为 PddChannel 的实例属性缓存"""

    def is_select_request(self, content: str) -> bool:
        """判断是否为选号请求"""
        return is_select_number_request(content)

    async def handle_select(
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
        执行选号流程。
        返回 True 表示已处理，False 表示需要 fallback 到 AI。
        """
        import config

        game = detect_game(content)
        duration = parse_duration(content)

        if game is None or duration is None:
            return False

        settings = config.get_uhaozu_settings()
        game_cfg = settings.get("game_configs", {}).get(game)
        if not game_cfg:
            logger.info("游戏 %s 无配置，选号 fallback 到 AI", game)
            return False

        account = config.get_default_uhaozu_account()
        if not account:
            logger.info("未配置默认U号租账号，选号 fallback 到 AI")
            return False

        try:
            options = await self._search_numbers(account, game, game_cfg, duration)
        except Exception as e:
            logger.error("搜号异常: %s", e)
            return False

        if not options:
            await self._send_reply(
                sender, buyer_id,
                f"抱歉，暂时没有符合条件的{game}账号，请稍后再试或联系客服～"
            )
            return True

        # 加价报价
        markup_rules = settings.get("price_markup_rules", [])
        quoted = self._apply_markup(options[:3], markup_rules)

        # 保存待确认状态
        _pending_confirm[buyer_id] = {
            "game": game,
            "duration": duration,
            "options": quoted,
            "shop_id": shop_id,
            "account": account,
        }

        lines = [f"为您找到以下{game}账号（租用{duration}小时），请回复序号选择："]
        for i, opt in enumerate(quoted, 1):
            lines.append(f"{i}. {opt.get('title', '')} - ¥{opt.get('quoted_price', 0):.1f}/小时")
        lines.append("（回复 1/2/3 确认，回复\u300c取消\u300d放弃）")

        await self._send_reply(sender, buyer_id, "\n".join(lines))
        return True

    async def handle_confirm(
        self,
        buyer_id: str,
        buyer_name: str,
        content: str,
        sender,
        shop_id: str,
        db_client=None,
    ) -> bool:
        """
        处理买家的确认回复（1/2/3/取消）。
        返回 True 表示已处理，False 表示需要 fallback 到 AI。
        """
        state = _pending_confirm.get(buyer_id)
        if not state:
            return False

        content = content.strip()
        if content in ("取消", "算了", "不要了"):
            _pending_confirm.pop(buyer_id, None)
            await self._send_reply(sender, buyer_id, "好的，已为您取消，有需要随时告知😊")
            return True

        if content in ("1", "2", "3"):
            idx = int(content) - 1
            options = state.get("options", [])
            if idx >= len(options):
                return False

            selected = options[idx]
            account = state["account"]
            _pending_confirm.pop(buyer_id, None)

            try:
                result = await self._place_order(account, selected.get("id", ""))
            except Exception as e:
                logger.error("下单异常: %s", e)
                await self._send_reply(
                    sender, buyer_id,
                    "下单遇到问题，请稍后重试或联系客服～"
                )
                return True

            if result.get("success"):
                acc_str = result.get("account", "")
                pwd_str = result.get("password", "")
                await self._send_reply(
                    sender, buyer_id,
                    f"下单成功！账号：{acc_str}，密码：{pwd_str}，祝您游戏愉快😊"
                )
            else:
                await self._send_reply(
                    sender, buyer_id,
                    "下单遇到问题，请联系客服为您处理～"
                )
            return True

        return False

    def _apply_markup(self, options: list, markup_rules: list) -> list:
        """根据加价规则对候选号列表加价"""
        result = []
        for opt in options:
            price = opt.get("price", 0)
            markup = 0
            for rule in markup_rules:
                if rule.get("min", 0) <= price < rule.get("max", 0):
                    markup = rule.get("markup", 0)
                    break
            opt = dict(opt)
            opt["quoted_price"] = round(price + markup, 2)
            result.append(opt)
        return result

    async def _search_numbers(self, account: dict, game: str, game_cfg: dict, duration: float) -> list:
        """在 executor 中运行 UHaozuAutomation.search_numbers()"""
        from automation.uhaozu import UHaozuAutomation

        filters = game_cfg.get("filters", {})

        def _run():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                automation = UHaozuAutomation(
                    phone=account.get("phone", ""),
                    employee_account=account.get("employee_account", ""),
                    password=account.get("password", ""),
                )
                return loop.run_until_complete(automation.search_numbers(game, filters))
            finally:
                loop.close()

        return await asyncio.get_event_loop().run_in_executor(None, _run)

    async def _place_order(self, account: dict, product_id: str) -> dict:
        """在 executor 中运行 UHaozuAutomation.place_order()"""
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
                return loop.run_until_complete(automation.place_order(product_id))
            finally:
                loop.close()

        return await asyncio.get_event_loop().run_in_executor(None, _run)

    async def _send_reply(self, sender, buyer_id: str, text: str):
        """安全地发送回复消息"""
        if sender and buyer_id:
            try:
                await sender.send_text(buyer_id, text)
            except Exception as e:
                logger.error("发送选号回复失败: %s", e)
