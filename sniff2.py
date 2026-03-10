# -*- coding: utf-8 -*-
"""
sniff2.py  —  拼多多商家后台 API 抓包工具
用途：注入已保存的 cookies，打开有头浏览器，监听并记录所有与"转人工"相关的 HTTP 请求。

使用方法：
  cd C:\Users\Administrator\Desktop\dskehuduan
  python sniff2.py

脚本会：
1. 读取本地 pdd_cookies.json（同目录）或 config.json 中的 cookies
2. 打开有头 Chromium，进入拼多多商家聊天页面
3. 实时打印捕获到的 API 请求 / 响应
4. 把所有结果写入 sniff_result.json，方便复查

你在浏览器里手动操作"转移会话"，脚本就会抓到真实接口。
按 Ctrl+C 退出，结果自动保存。
"""

import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# ── 关键词过滤（包含任意一个就记录）──────────────────────────────────────────
KEYWORDS = [
    "transfer", "move_conversation", "assign", "conv",
    "chat", "session", "csList", "staffList", "latitude",
    "plateau", "chats", "assistant",
]

# ── 输出文件 ──────────────────────────────────────────────────────────────────
OUTPUT_FILE = Path(__file__).parent / "sniff_result.json"

captured: list = []

def _load_cookies() -> dict:
    """
    按优先级读取 cookies：
    1. 同目录 pdd_cookies.json
    2. config.json -> pdd_settings.cookies 或 shop_cookies
    """
    base = Path(__file__).parent

    # 1) 独立 cookies 文件
    ck_file = base / "pdd_cookies.json"
    if ck_file.exists():
        try:
            data = json.loads(ck_file.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data:
                logger.info("从 pdd_cookies.json 读取到 %d 个 cookies", len(data))
                return data
        except Exception as e:
            logger.warning("读取 pdd_cookies.json 失败: %s", e)

    # 2) config.json
    cfg_file = base / "config.json"
    if cfg_file.exists():
        try:
            cfg = json.loads(cfg_file.read_text(encoding="utf-8"))
            # 尝试多个路径
            for path in [
                ["pdd_settings", "cookies"],
                ["shop_cookies"],
                ["cookies"],
            ]:
                obj = cfg
                for key in path:
                    obj = obj.get(key, {}) if isinstance(obj, dict) else {}
                if isinstance(obj, dict) and obj:
                    logger.info("从 config.json[%s] 读取到 %d 个 cookies",
                                ".".join(path), len(obj))
                    return obj
        except Exception as e:
            logger.warning("读取 config.json 失败: %s", e)

    logger.warning("未找到任何 cookies！浏览器将以未登录状态打开，请手动登录后再操作转移。")
    return {}

def _is_interesting(url: str) -> bool:
    url_lower = url.lower()
    return any(kw in url_lower for kw in KEYWORDS)

async def _handle_request(request):
    """拦截请求，过滤并记录"""
    url = request.url
    if not _is_interesting(url):
        return

    try:
        post_data = request.post_data or ""
    except Exception:
        post_data = ""

    entry = {
        "type": "request",
        "ts": time.strftime("%H:%M:%S"),
        "method": request.method,
        "url": url,
        "headers": dict(request.headers),
        "body": post_data,
    }
    captured.append(entry)

    logger.info(
        "\n%s\n▶ REQUEST  %s %s\n  Body: %s",
        "=" * 70,
        request.method,
        url,
        post_data[:500] if post_data else "(empty)",
    )

async def _handle_response(response):
    """拦截响应，过滤并记录"""
    url = response.url
    if not _is_interesting(url):
        return

    try:
        body = await response.text()
    except Exception:
        body = "(无法读取响应体)"

    entry = {
        "type": "response",
        "ts": time.strftime("%H:%M:%S"),
        "status": response.status,
        "url": url,
        "body": body[:2000],
    }
    captured.append(entry)

    logger.info(
        "◀ RESPONSE [%d] %s\n  Body: %s",
        response.status,
        url,
        body[:800],
    )


def _save_results():
    try:
        OUTPUT_FILE.write_text(
            json.dumps(captured, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("结果已保存到 %s（共 %d 条）", OUTPUT_FILE, len(captured))
    except Exception as e:
        logger.error("保存结果失败: %s", e)

async def main():
    from playwright.async_api import async_playwright

    cookies_dict = _load_cookies()

    logger.info("启动有头浏览器……")
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=False,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--start-maximized",
            ],
        )
        context = await browser.new_context(
            viewport=None,          # 最大化窗口
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )

        # 注入 cookies
        if cookies_dict:
            cookie_list = [
                {
                    "name": k, "value": v,
                    "domain": ".pinduoduo.com",
                    "path": "/",
                    "httpOnly": False,
                    "secure": True,
                }
                for k, v in cookies_dict.items()
            ]
            await context.add_cookies(cookie_list)
            logger.info("已注入 %d 个 cookies", len(cookie_list))
        else:
            logger.info("无 cookies，请在浏览器中手动登录")

        page = await context.new_page()

        # 监听请求 / 响应
        page.on("request",  lambda req:  asyncio.ensure_future(_handle_request(req)))
        page.on("response", lambda resp: asyncio.ensure_future(_handle_response(resp)))

        logger.info("正在打开拼多多商家聊天页面……")
        await page.goto(
            "https://mms.pinduoduo.com/chat-merchant/index.html#/"
            , wait_until="domcontentloaded",
            timeout=60000,
        )

        logger.info(
            "\n%s\n"
            "  ✅ 浏览器已就绪！\n"
            "  请在浏览器中手动操作"转移会话"，脚本会实时打印捕获到的 API。\n"
            "  按 Ctrl+C 退出，结果自动保存到 sniff_result.json\n"
            "%s",
            "=" * 70, "=" * 70,
        )

        try:
            # 保持运行，等待用户手动操作
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            logger.info("用户中断，正在保存结果……")
        finally:
            _save_results()
            await browser.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        _save_results()