import asyncio, json, os, glob
from playwright.async_api import async_playwright

paths = glob.glob(os.path.join(os.path.expanduser("~"), ".aikefu-client", "browser_data", "shop_*"))
if not paths:
    print("未找到browser_data")
    exit()

user_data_dir = paths[0]
print("使用:", user_data_dir)

captured = []

async def main():
    async with async_playwright() as pw:
        ctx = await pw.chromium.launch_persistent_context(
            user_data_dir,
            headless=False,
            args=["--no-sandbox"],
            locale="zh-CN",
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()

        async def on_response(response):
            url = response.url
            if "pinduoduo" in url and response.status == 200:
                ct = response.headers.get("content-type", "")
                if "json" in ct:
                    try:
                        body = await response.json()
                        print(f"\n[API] {url}")
                        print(f"  响应: {str(body)[:300]}")
                        captured.append({"url": url, "body": body})
                    except Exception:
                        pass

        page.on("response", on_response)
        await page.goto("https://mms.pinduoduo.com/chat-merchant/index.html#/", timeout=30000)
        print("\n>>> 请在弹出的浏览器里点击「转移会话」按钮，我会抓取接口 <<<")
        print(">>> 等待60秒... <<<")
        await asyncio.sleep(60)

        print("\n\n=== 抓到的所有JSON接口 ===")
        for c in captured:
            print(c["url"])

        await ctx.close()

asyncio.run(main())
