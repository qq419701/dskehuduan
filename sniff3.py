import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False, args=["--no-sandbox"])
        ctx = await browser.new_context()
        page = await ctx.new_page()

        async def on_request(request):
            url = request.url
            if "pinduoduo" in url and request.resource_type in ("xhr", "fetch"):
                if any(k in url for k in ("move_conversation", "transfer", "assign")):
                    try:
                        body = request.post_data
                        print(f"\n[REQ] {request.method} {url}")
                        print(f"  Body: {body}")
                    except Exception:
                        pass

        async def on_response(response):
            url = response.url
            if "pinduoduo" in url and response.request.resource_type in ("xhr", "fetch"):
                if any(k in url for k in ("move_conversation", "transfer", "assign")):
                    try:
                        text = await response.text()
                        print(f"\n[RESP] {url}")
                        print(f"  {text[:500]}")
                    except Exception:
                        pass

        page.on("request", on_request)
        page.on("response", on_response)

        await page.goto("https://mms.pinduoduo.com/chat-merchant/index.html#/", timeout=30000)
        print(">>> 登录后点「转移会话」，等待120秒... <<<")
        await asyncio.sleep(120)
        await browser.close()

asyncio.run(main())
