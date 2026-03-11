# -*- coding: utf-8 -*-
"""
sniff2.py — 自动抓取 anti_content 并保存到配置文件
使用方法：python sniff2.py
脚本会自动打开浏览器 → 你登录拼多多 → 随便点几下 → 自动保存 anti_content
"""
import asyncio, json, time, sys
from pathlib import Path

BASE = Path(__file__).parent
OUTPUT_FILE = BASE / "sniff_result.json"
captured = []
anti_content_found = [""]   # 用列表让闭包可修改


def _save_anti_content(anti: str):
    """把抓到的 anti_content 写入 pdd_config.json，同时兼容 config.py 的读取格式"""
    cfg_file = BASE / "pdd_config.json"
    try:
        cfg = json.loads(cfg_file.read_text(encoding="utf-8")) if cfg_file.exists() else {}
    except Exception:
        cfg = {}

    # 写顶层（config.py get_anti_content 读这里）
    cfg["anti_content"] = anti
    cfg["anti_content_updated"] = time.strftime("%Y-%m-%d %H:%M:%S")

    # 同时写入所有 shop_x 子项（如果有）
    for key in list(cfg.keys()):
        if key.startswith("shop_") and isinstance(cfg[key], dict):
            cfg[key]["anti_content"] = anti

    cfg_file.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✅ anti_content 已自动保存到: {cfg_file}")
    print(f"   长度: {len(anti)} 字符，前30字: {anti[:30]}...")


async def main():
    print("=" * 60)
    print("  拼多多 anti_content 自动抓取工具")
    print("=" * 60)
    print("步骤：")
    print("  1. 等待浏览器自动打开")
    print("  2. 如未登录，请在浏览器里登录拼多多商家后台")
    print("  3. 随便点几下页面（不需要点转移会话）")
    print("  4. 看到「✅ anti_content 已自动保存」就成功了")
    print("  5. 按 Ctrl+C 退出，重启 app.py 即可")
    print("=" * 60)

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("\n❌ 缺少 playwright，正在自动安装...")
        import subprocess
        subprocess.run([sys.executable, "-m", "pip", "install", "playwright"], check=True)
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
        from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        # 用持久化上下文，保留登录状态
        user_data = BASE / "browser_data" / "sniff_profile"
        user_data.mkdir(parents=True, exist_ok=True)

        ctx = await pw.chromium.launch_persistent_context(
            str(user_data),
            headless=False,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
            locale="zh-CN",
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()

        async def on_request(request):
            url = request.url
            if "pinduoduo" not in url:
                return
            if request.resource_type not in ("xhr", "fetch", "document"):
                return

            # ★ 核心：从每个请求的 Headers 里提取 anti_content
            if not anti_content_found[0]:
                headers = request.headers
                anti = (headers.get("anti-content", "")
                        or headers.get("Anti-Content", "")
                        or headers.get("ANTI-CONTENT", ""))
                if anti and len(anti) > 20:
                    anti_content_found[0] = anti
                    _save_anti_content(anti)

            # 记录转移相关接口
            if any(k in url for k in ("move_conversation", "transfer", "assign", "csList")):
                try:
                    body = request.post_data or ""
                    print(f"\n[请求] {request.method} {url}")
                    if body:
                        print(f"  Body: {body[:200]}")
                    captured.append({"type": "request", "url": url, "body": body,
                                     "time": time.strftime("%H:%M:%S")})
                except Exception:
                    pass

        async def on_response(response):
            url = response.url
            if "pinduoduo" not in url:
                return
            if response.request.resource_type not in ("xhr", "fetch"):
                return
            if any(k in url for k in ("move_conversation", "transfer", "assign", "csList")):
                try:
                    text = await response.text()
                    print(f"\n[响应] {url}")
                    print(f"  {text[:300]}")
                    captured.append({"type": "response", "url": url, "body": text[:500],
                                     "time": time.strftime("%H:%M:%S")})
                except Exception:
                    pass

        page.on("request", on_request)
        page.on("response", on_response)

        print("\n🌐 正在打开浏览器...")
        await page.goto("https://mms.pinduoduo.com/home/", timeout=30000)
        print("✅ 浏览器已打开，请在浏览器里操作（等待180秒）")

        # 每隔10秒提示一次状态
        for i in range(18):
            await asyncio.sleep(10)
            remaining = 180 - (i + 1) * 10
            if anti_content_found[0]:
                print(f"  [{time.strftime('%H:%M:%S')}] anti_content ✅ 已保存 | 还剩 {remaining}s | 按 Ctrl+C 可提前退出")
            else:
                print(f"  [{time.strftime('%H:%M:%S')}] 等待抓取 anti_content... | 还剩 {remaining}s | 请点击页面触发请求")

        await ctx.close()

    # 保存抓包结果
    OUTPUT_FILE.write_text(json.dumps(captured, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n" + "=" * 60)
    print("=== 抓包完成 ===")
    if anti_content_found[0]:
        print(f"anti_content : ✅ 已自动保存到 pdd_config.json")
    else:
        print(f"anti_content : ❌ 未抓到（请重新运行，登录后多点几下页面）")
    print(f"转移接口     : 抓到 {len(captured)} 条")
    print(f"详细结果     : {OUTPUT_FILE}")
    print("=" * 60)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        OUTPUT_FILE.write_text(json.dumps(captured, ensure_ascii=False, indent=2), encoding="utf-8")
        print("\n\n用户退出。")
        if anti_content_found[0]:
            print("✅ anti_content 已保存，重启 app.py 即可！")
        else:
            print("❌ 未抓到 anti_content，请重试。")