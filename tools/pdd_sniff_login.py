# -*- coding: utf-8 -*-
"""
拼多多一键登录+全量信息抓取工具
================================
用途：打开浏览器 → 你扫码登录 → 自动抓取：
      ✅ PDDAccessToken（cookies，有则保存，无则跳过）
      ✅ im_token（WebSocket 连接用）
      ✅ anti_content（HTTP 接口风控用）
      并自动保存到对应的文件，无需手动操作。

用法：
    python tools/pdd_sniff_login.py [店铺ID]
    #   python tools/pdd_sniff_login.py 1   ← 店铺1
    #   python tools/pdd_sniff_login.py 2   ← 店铺2
    #   python tools/pdd_sniff_login.py 3   ← 店铺3

前提：pip install playwright && python -m playwright install chromium
"""
import asyncio
import json
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("sniff_login")

BROWSER_DATA_DIR = Path.home() / ".aikefu-client" / "browser_data"
PDD_CONFIG_FILE  = ROOT / "pdd_config.json"
PDD_HOME         = "https://mms.pinduoduo.com/"

# 触发 PDDAccessToken 写入的页面（依次尝试）
_TRIGGER_PAGES = [
    "https://mms.pinduoduo.com/",
    "https://mms.pinduoduo.com/home",
    "https://mms.pinduoduo.com/mms/index.html",
    "https://mms.pinduoduo.com/chat-merchant/index.html",
]

# 能拿到 im_token 的接口
_TOKEN_APIS = [
    ("POST", "https://mms.pinduoduo.com/chats/getToken",        "version=3", "application/x-www-form-urlencoded"),
    ("POST", "https://mms.pinduoduo.com/chatbot/im/getImToken", "{}",        "application/json"),
]

# anti_content 可能的 header 名称（拼多多有时用 x-anti-content，有时用 anti-content）
_ANTI_HEADER_NAMES = ["anti-content", "x-anti-content", "Anti-Content", "X-Anti-Content"]


def _load_pdd_config() -> dict:
    try:
        if PDD_CONFIG_FILE.exists():
            return json.loads(PDD_CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_pdd_config(cfg: dict):
    PDD_CONFIG_FILE.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _save_cookies(shop_id: str, cookies: dict):
    shop_dir = BROWSER_DATA_DIR / f"shop_{shop_id}"
    shop_dir.mkdir(parents=True, exist_ok=True)
    path = shop_dir / "aikefu_cookies.json"
    path.write_text(json.dumps(cookies, ensure_ascii=False), encoding="utf-8")
    logger.info("cookies 已保存 -> %s  (共 %d 个)", path, len(cookies))


def _save_im_token(shop_id: str, im_token: str):
    cfg = _load_pdd_config()
    key = f"shop_{shop_id}"
    if key not in cfg:
        cfg[key] = {}
    cfg[key]["im_token"] = im_token
    cfg[key]["im_token_updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _save_pdd_config(cfg)
    logger.info("im_token 已保存 -> pdd_config.json[%s]  前20字: %s...", key, im_token[:20])


def _save_anti_content(anti: str):
    cfg = _load_pdd_config()
    cfg["anti_content"] = anti
    cfg["anti_content_updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    for key in list(cfg.keys()):
        if key.startswith("shop_") and isinstance(cfg[key], dict):
            cfg[key]["anti_content"] = anti
    _save_pdd_config(cfg)
    logger.info("anti_content 已保存 -> pdd_config.json  长度:%d 前30字:%s...", len(anti), anti[:30])

    # 同步写入 config.json（config.py get_anti_content 读这里）
    try:
        import config as _cfg
        main_cfg_path = Path.home() / ".aikefu-client" / "config.json"
        main_cfg = {}
        if main_cfg_path.exists():
            try:
                main_cfg = json.loads(main_cfg_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        shop_ids = []
        for s in main_cfg.get("active_shops", main_cfg.get("shops", [])):
            sid = s.get("id") or s.get("shop_id")
            if sid:
                shop_ids.append(str(sid))
        if not shop_ids:
            shop_ids = ["1"]
        for sid in shop_ids:
            _cfg.save_anti_content(sid, anti)
        logger.info("anti_content 同步写入 config.json shop_ids=%s ✅", shop_ids)
    except Exception as e:
        logger.warning("同步写入 config.json 失败（不影响主功能）: %s", e)


def _extract_token_from_json(data: dict) -> str:
    return (
        data.get("token")
        or (data.get("result") or {}).get("token")
        or (data.get("result") or {}).get("imToken")
        or (data.get("data")   or {}).get("token")
        or (data.get("data")   or {}).get("imToken")
        or ""
    )


async def run(shop_id: str):
    logger.info("=" * 60)
    logger.info("  拼多多一键登录+全量信息抓取  店铺ID: %s", shop_id)
    logger.info("=" * 60)

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.error("缺少 playwright，请先执行：pip install playwright && python -m playwright install chromium")
        sys.exit(1)

    user_data_dir = BROWSER_DATA_DIR / f"shop_{shop_id}"
    user_data_dir.mkdir(parents=True, exist_ok=True)

    result = {
        "cookies":      {},
        "im_token":     "",
        "anti_content": "",
    }

    async with async_playwright() as pw:
        ctx = await pw.chromium.launch_persistent_context(
            str(user_data_dir),
            headless=False,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()

        # ── 拦截网络请求，捞 anti_content 和 im_token ──────────────────────
        async def on_request(req):
            if "pinduoduo" not in req.url:
                return
            if not result["anti_content"]:
                headers = req.headers  # Playwright 返回的 headers key 全是小写
                for name in _ANTI_HEADER_NAMES:
                    anti = headers.get(name.lower(), "")
                    if anti and len(anti) > 20:
                        result["anti_content"] = anti
                        logger.info("[请求拦截] anti_content 已捕获 header=%s 长度:%d", name, len(anti))
                        break

        async def on_response(resp):
            if "pinduoduo" not in resp.url:
                return
            if result["im_token"]:
                return
            url_lower = resp.url.lower()
            if "gettoken" in url_lower or "getimtoken" in url_lower or "imtoken" in url_lower:
                try:
                    body = await resp.text()
                    data = json.loads(body)
                    token = _extract_token_from_json(data)
                    if token:
                        result["im_token"] = token
                        logger.info("[响应拦截] im_token 已捕获 前20字: %s...", token[:20])
                except Exception:
                    pass

        ctx.on("request",  on_request)
        ctx.on("response", on_response)

        # ── 步骤1：等待登录完成 ─────────────────────────────────────────────
        logger.info("")
        logger.info("步骤1：打开拼多多商家后台，请在弹出的浏览器中扫码登录...")
        await page.goto(PDD_HOME, wait_until="domcontentloaded", timeout=30000)
        logger.info("       等待登录完成（最多5分钟）...")

        try:
            await page.wait_for_function(
                """() => {
                    const url = window.location.href;
                    return url.includes('mms.pinduoduo.com') &&
                           !url.includes('login') && !url.includes('verify') &&
                           !url.includes('captcha') && !url.includes('slide') &&
                           !url.includes('passport');
                }""",
                timeout=300_000,
            )
        except Exception as e:
            logger.error("等待登录超时: %s", e)
            await ctx.close()
            return

        logger.info("步骤1 完成：已通过登录页，当前URL: %s", page.url)

        # ── 步骤2：依次访问商家后台页面，触发 PDDAccessToken 写入 + anti_content ──
        logger.info("")
        logger.info("步骤2：访问商家后台页面...")
        for trigger_url in _TRIGGER_PAGES:
            try:
                logger.info("       访问: %s", trigger_url)
                await page.goto(trigger_url, wait_until="domcontentloaded", timeout=20000)
                await asyncio.sleep(4)

                raw = await ctx.cookies()
                cookies_dict = {c["name"]: c["value"] for c in raw}
                if "PDDAccessToken" in cookies_dict:
                    logger.info("       PDDAccessToken 写入成功！")
                    result["cookies"] = cookies_dict
                    break
            except Exception as nav_e:
                logger.warning("       访问 %s 异常（忽略）: %s", trigger_url, nav_e)

        # 收集最新 cookies
        raw = await ctx.cookies()
        result["cookies"] = {c["name"]: c["value"] for c in raw}

        # ── 步骤3：主动调接口获取 im_token ─────────────────────────────────
        if not result["im_token"]:
            logger.info("")
            logger.info("步骤3：主动调接口获取 im_token...")
            for method, url, body, content_type in _TOKEN_APIS:
                try:
                    js = """async () => {
                        const r = await fetch("%s", {
                            method: "POST",
                            headers: {"Content-Type": "%s"},
                            body: %s,
                            credentials: "include"
                        });
                        return await r.text();
                    }""" % (url, content_type, json.dumps(body))
                    resp_text = await page.evaluate(js)
                    logger.info("       [%s] 响应: %s", url, resp_text[:200])
                    data = json.loads(resp_text)
                    token = _extract_token_from_json(data)
                    if token:
                        result["im_token"] = token
                        logger.info("       im_token 获取成功: %s...", token[:20])
                        break
                except Exception as e:
                    logger.warning("       调用 %s 失败: %s", url, e)

        # ── 步骤4：等待 anti_content（最多40秒，每10秒主动触发一次请求）──────
        if not result["anti_content"]:
            logger.info("")
            logger.info("步骤4：等待 anti_content（最多40秒）...")
            for i in range(40):
                if result["anti_content"]:
                    break
                await asyncio.sleep(1)
                # 每10秒主动发一个带 anti-content header 的接口请求
                if i % 10 == 3:
                    try:
                        await page.evaluate("""async () => {
                            await fetch('https://mms.pinduoduo.com/plateau/gray/check',
                                {method:'POST',
                                 headers:{'Content-Type':'application/json'},
                                 body:'{}', credentials:'include'});
                            await fetch('https://mms.pinduoduo.com/chats/getCsRealTimeReplyData',
                                {method:'GET', credentials:'include'});
                        }""")
                    except Exception:
                        pass

        await asyncio.sleep(1)
        await ctx.close()

    # ── 保存结果 ────────────────────────────────────────────────────────────
    logger.info("")
    logger.info("=" * 60)
    logger.info("  抓取结果汇总 (店铺 %s)", shop_id)
    logger.info("=" * 60)

    cookies = result["cookies"]
    ok_pdd   = "PDDAccessToken" in cookies
    ok_token = bool(result["im_token"])
    ok_anti  = bool(result["anti_content"])

    logger.info("cookies 总数   : %d 个", len(cookies))
    logger.info("PDDAccessToken : %s", "OK 已获取" if ok_pdd else "-- 未获取（此账号可能不下发，不影响主功能）")
    logger.info("im_token       : %s", ("OK " + result["im_token"][:20] + "...") if ok_token else "MISS 未获取！")
    logger.info("anti_content   : %s", ("OK 长度=" + str(len(result["anti_content"]))) if ok_anti else "MISS 未获取！")
    logger.info("")

    _save_cookies(shop_id, cookies)

    if ok_token:
        _save_im_token(shop_id, result["im_token"])

    if ok_anti:
        _save_anti_content(result["anti_content"])

    logger.info("")
    logger.info("=" * 60)
    if ok_token and ok_anti:
        logger.info("✅ 关键信息已就绪！现在可以直接运行 python app.py")
    else:
        missing = []
        if not ok_token: missing.append("im_token")
        if not ok_anti:  missing.append("anti_content")
        if missing:
            logger.warning("❌ 以下信息未能获取: %s", ", ".join(missing))
            logger.warning("   建议：重新运行本脚本，登录后多等几秒再操作")
        else:
            logger.info("✅ im_token 和 anti_content 均已获取，可以运行 python app.py")
    logger.info("=" * 60)


if __name__ == "__main__":
    sid = sys.argv[1].strip() if len(sys.argv) > 1 else "1"
    asyncio.run(run(sid))
