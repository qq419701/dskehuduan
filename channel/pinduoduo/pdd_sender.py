# -*- coding: utf-8 -*-
"""
通过 Playwright 在拼多多商家后台发送消息
"""
import asyncio
import logging

logger = logging.getLogger(__name__)

# 输入框候选选择器（按优先级排列）
INPUT_SELECTORS = [
    'div[contenteditable="true"][class*="input"]',
    'div[contenteditable="true"][class*="editor"]',
    'div[contenteditable="true"][class*="chat"]',
    'div[contenteditable="true"]',
    '[placeholder*="输入"]',
    '[placeholder*="消息"]',
    'textarea[class*="input"]',
]

# 发送按钮候选选择器
SEND_BUTTON_SELECTORS = [
    'button:has-text("发送")',
    'button[class*="send"]',
    '[class*="send-btn"]',
    '[class*="sendBtn"]',
]


class PddSender:
    """通过 Playwright 在拼多多商家后台发送消息"""

    def __init__(self, page):
        """
        :param page: Playwright Page 对象（已登录的拼多多商家后台页面）
        """
        self.page = page

    async def send_text(self, buyer_id: str, text: str) -> bool:
        """
        向指定买家发送文字消息。
        1. 切换到买家会话（如果需要）
        2. 找到输入框并填入文字
        3. 点击发送或按 Ctrl+Enter

        :param buyer_id: 买家平台ID
        :param text: 要发送的文本内容
        :return: 是否发送成功
        """
        try:
            # 先尝试切换到对应买家会话
            await self._switch_to_conversation(buyer_id)

            # 找到输入框
            input_box = await self.find_input_box()
            if input_box is None:
                logger.error("找不到聊天输入框，无法发送消息")
                return False

            # 清空并填入内容
            await input_box.click()
            await asyncio.sleep(0.3)

            # 使用 JavaScript 设置内容（适配 contenteditable）
            await self.page.evaluate(
                """
                (args) => {
                    const el = document.querySelector(args.selector);
                    if (!el) return;
                    el.focus();
                    if (el.tagName === 'TEXTAREA' || el.tagName === 'INPUT') {
                        el.value = args.text;
                        el.dispatchEvent(new Event('input', { bubbles: true }));
                        el.dispatchEvent(new Event('change', { bubbles: true }));
                    } else {
                        // contenteditable
                        el.innerText = args.text;
                        el.dispatchEvent(new InputEvent('input', { bubbles: true }));
                    }
                }
                """,
                {"selector": await self._get_input_selector(), "text": text},
            )
            await asyncio.sleep(0.3)

            # 尝试点击发送按钮
            sent = await self._click_send_button()
            if not sent:
                # 回退方案：按 Enter 键发送
                await input_box.press("Enter")

            logger.info("发送消息到买家 %s 成功", buyer_id)
            return True

        except Exception as e:
            logger.error("发送消息失败: %s", e)
            return False

    async def find_input_box(self):
        """找到聊天输入框，返回 ElementHandle 或 None"""
        for selector in INPUT_SELECTORS:
            try:
                element = await self.page.wait_for_selector(selector, timeout=2000)
                if element and await element.is_visible():
                    return element
            except Exception:
                continue
        return None

    async def _get_input_selector(self) -> str:
        """返回当前可用的输入框选择器"""
        for selector in INPUT_SELECTORS:
            try:
                element = await self.page.query_selector(selector)
                if element and await element.is_visible():
                    return selector
            except Exception:
                continue
        return INPUT_SELECTORS[0]

    async def _click_send_button(self) -> bool:
        """尝试点击发送按钮"""
        for selector in SEND_BUTTON_SELECTORS:
            try:
                btn = await self.page.query_selector(selector)
                if btn and await btn.is_visible() and await btn.is_enabled():
                    await btn.click()
                    return True
            except Exception:
                continue
        return False

    async def _switch_to_conversation(self, buyer_id: str):
        """
        切换到指定买家的对话（如果当前不在该对话）。
        尝试在会话列表中查找并点击。
        """
        if not buyer_id:
            return
        try:
            # 查找包含买家ID的会话列表项
            conversation = await self.page.query_selector(
                f'[data-buyer-id="{buyer_id}"], '
                f'[data-uid="{buyer_id}"], '
                f'[class*="conversation"][data-id="{buyer_id}"]'
            )
            if conversation:
                await conversation.click()
                await asyncio.sleep(0.5)
        except Exception:
            pass
