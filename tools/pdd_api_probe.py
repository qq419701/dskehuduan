# -*- coding: utf-8 -*-
"""
拼多多 HTTP API 探测工具
======================
用途：用你的 cookies 实际调用拼多多各个接口，把原始响应保存到 probe_result.json
      把 probe_result.json 发给 Copilot，它根据真实数据结构来修复代码。

用法：
    python tools/pdd_api_probe.py

前提：
    1. 先运行主程序完成登录，确保 ~/.aikefu-client/browser_data/shop_XXX/aikefu_cookies.json 存在
    2. 也可以手动把 cookies 填到下面的 MANUAL_COOKIES 字典（优先级更高）

输出文件：probe_result.json（保存在当前目录）
"""
import asyncio
import json
import os
import sys
import time
from pathlib import Path

import aiohttp

# ──────────────────────────────────────────────
# 可选：手动填入 cookies（留空则自动从文件读取）
# ──────────────────────────────────────────────
MANUAL_COOKIES: dict = {
    # "PDDAccessToken": "xxx",
    # "JSESSIONID": "xxx",
    # ... 把浏览器里拼多多商家后台的 cookies 粘贴进来
}

# 自动读取 cookies 时使用的店铺ID（留空则尝试读取第一个找到的）
SHOP_ID = ""

# 探测时用的买家ID（填一个真实的，用于测试按买家查订单接口）
# 可以从 WS 日志里找，或者随便填一个已知买家的 uid
TEST_BUYER_ID = ""

# ──────────────────────────────────────────────
BROWSER_DATA_DIR = os.path.join(os.path.expanduser("~"), ".aikefu-client", "browser_data")
OUTPUT_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "probe_result.json")

HEADERS_BASE = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://mms.pinduoduo.com/",
    "Origin": "https://mms.pinduoduo.com",
    "Content-Type": "application/json",
}

# ──────────────────────────────────────────────
# 要探测的接口列表（逐一尝试）
# ──────────────────────────────────────────────
def build_probes(buyer_id: str) -> list:
    now = int(time.time())
    probes = []

    # ── 1. 客服列表接口（获取当前在线会话/买家列表）──
    probes.append({
        "name": "客服会话列表_v1",
        "url": "https://mms.pinduoduo.com/chatbot/im/mallServiceAgentInfo",
        "method": "POST",
        "body": {},
    })
    probes.append({
        "name": "客服会话列表_v2",
        "url": "https://mms.pinduoduo.com/chatbot/conversation/list",
        "method": "POST",
        "body": {"pageIndex": 1, "pageSize": 20},
    })
    probes.append({
        "name": "客服会话列表_v3",
        "url": "https://mms.pinduoduo.com/chatbot/cs/session/list",
        "method": "POST",
        "body": {"page": 1, "pageSize": 20},
    })

    # ── 2. 最近订单列表（不带买家过滤）──
    probes.append({
        "name": "订单列表_近7��",
        "url": "https://mms.pinduoduo.com/mangkhut/mms/recentOrderList",
        "method": "POST",
        "body": {
            "orderType": 0,
            "afterSaleType": 0,
            "remarkStatus": -1,
            "urgeShippingStatus": -1,
            "groupStartTime": now - 7 * 86400,
            "groupEndTime": now,
            "pageNumber": 1,
            "pageSize": 5,
            "hideRegionBlackDelayShipping": False,
            "mobileMarkSearch": False,
        },
    })

    # ── 3. 按买家ID查订单（核心：验证 buyerUid 参数是否有效）──
    if buyer_id:
        probes.append({
            "name": "按买家查订单_buyerUid=" + buyer_id,
            "url": "https://mms.pinduoduo.com/mangkhut/mms/recentOrderList",
            "method": "POST",
            "body": {
                "orderType": 0,
                "afterSaleType": 0,
                "remarkStatus": -1,
                "urgeShippingStatus": -1,
                "groupStartTime": now - 90 * 86400,
                "groupEndTime": now,
                "pageNumber": 1,
                "pageSize": 10,
                "hideRegionBlackDelayShipping": False,
                "mobileMarkSearch": False,
                "buyerUid": str(buyer_id),
            },
        })
        probes.append({
            "name": "按买家查订单_buyerId=" + buyer_id,
            "url": "https://mms.pinduoduo.com/mangkhut/mms/recentOrderList",
            "method": "POST",
            "body": {
                "orderType": 0,
                "afterSaleType": 0,
                "remarkStatus": -1,
                "urgeShippingStatus": -1,
                "groupStartTime": now - 90 * 86400,
                "groupEndTime": now,
                "pageNumber": 1,
                "pageSize": 10,
                "hideRegionBlackDelayShipping": False,
                "mobileMarkSearch": False,
                "buyerId": str(buyer_id),
            },
        })

    # ── 4. IM 历史消息（含商品/订单卡片的原始消息）──
    if buyer_id:
        probes.append({
            "name": "IM历史消息_v1_buyerId=" + buyer_id,
            "url": "https://mms.pinduoduo.com/chatbot/im/historyMessage",
            "method": "POST",
            "body": {"buyerId": str(buyer_id), "pageSize": 20},
        })
        probes.append({
            "name": "IM历史消息_v2_uid=" + buyer_id,
            "url": "https://mms.pinduoduo.com/chatbot/im/messageList",
            "method": "POST",
            "body": {"uid": str(buyer_id), "pageSize": 20, "pageIndex": 1},
        })
        probes.append({
            "name": "IM对话详情_buyerId=" + buyer_id,
            "url": "https://mms.pinduoduo.com/chatbot/conversation/detail",
            "method": "POST",
            "body": {"buyerId": str(buyer_id)},
        })

    # ── 5. 商品列表（验证cookies对商品接口是否有效）──
    probes.append({
        "name": "商品列表_前5条",
        "url": "https://mms.pinduoduo.com/mms/goods/list",
        "method": "POST",
        "body": {
            "pageNum": 1,
            "pageSize": 5,
            "sortType": 0,
        },
    })
    probes.append({
        "name": "商品列表_v2",
        "url": "https://mms.pinduoduo.com/mms/item/list",
        "method": "POST",
        "body": {"page": 1, "pageSize": 5},
    })

    # ── 6. WS token 接口（验证 cookies 有效性）──
    probes.append({
        "name": "获取IM_token",
        "url": "https://mms.pinduoduo.com/chats/getToken",
        "method": "POST_FORM",
        "body": {"version": "3"},
    })

    # ── 7. 买家信息查询 ──
    if buyer_id:
        probes.append({
            "name": "买家信息_uid=" + buyer_id,
            "url": "https://mms.pinduoduo.com/chatbot/user/info",
            "method": "POST",
            "body": {"uid": str(buyer_id)},
        })
        probes.append({
            "name": "买家订单_专用接口_uid=" + buyer_id,
            "url": "https://mms.pinduoduo.com/mangkhut/mms/buyerOrderList",
            "method": "POST",
            "body": {
                "buyerUid": str(buyer_id),
                "pageNumber": 1,
                "pageSize": 10,
            },
        })
        probes.append({
            "name": "买家订单_v2_uid=" + buyer_id,
            "url": "https://mms.pinduoduo.com/mms/order/buyerOrderList",
            "method": "POST",
            "body": {
                "buyerUid": str(buyer_id),
                "pageNum": 1,
                "pageSize": 10,
            },
        })

    # ── 8. 智能客服 / 会话浏览足迹 ──
    if buyer_id:
        probes.append({
            "name": "会话上下文_足迹_uid=" + buyer_id,
            "url": "https://mms.pinduoduo.com/chatbot/cs/context",
            "method": "POST",
            "body": {"buyerId": str(buyer_id)},
        })
        probes.append({
            "name": "买家浏览商品_uid=" + buyer_id,
            "url": "https://mms.pinduoduo.com/chatbot/im/recentGoods",
            "method": "POST",
            "body": {"buyerId": str(buyer_id)},
        })

    return probes


async def load_cookies() -> dict:
    """加载 cookies：优先用手动填写的，其次从文件读"""
    if MANUAL_COOKIES:
        print("[cookies] 使用手动填写的 cookies（" + str(len(MANUAL_COOKIES)) + " 个）")
        return MANUAL_COOKIES

    base = Path(BROWSER_DATA_DIR)
    if not base.exists():
        print("[ERROR] 浏览器数据目录不存在: " + str(base))
        print("  请先运行主程序完成登录，或手动填写脚本顶部的 MANUAL_COOKIES")
        return {}

    candidates = []
    for shop_dir in base.iterdir():
        if not shop_dir.is_dir():
            continue
        cfile = shop_dir / "aikefu_cookies.json"
        if cfile.exists():
            candidates.append((shop_dir.name, cfile))

    if not candidates:
        print("[ERROR] 在 " + str(base) + " 下没找到任何 aikefu_cookies.json")
        print("  请先运行主程序完成登录，或手动填写脚本顶部的 MANUAL_COOKIES")
        return {}

    chosen = None
    if SHOP_ID:
        for name, cfile in candidates:
            if SHOP_ID in name:
                chosen = cfile
                print("[cookies] 使用店铺 " + name + " 的 cookies: " + str(cfile))
                break
    if not chosen:
        chosen = candidates[0][1]
        print("[cookies] 自动选择第一个: " + candidates[0][0] + " -> " + str(chosen))

    try:
        with open(chosen, encoding="utf-8") as f:
            data = json.load(f)
        print("[cookies] 加载成功，共 " + str(len(data)) + " 个 cookie")
        return data
    except Exception as e:
        print("[ERROR] 读取 cookies 文件失败: " + str(e))
        return {}


async def probe_one(session: aiohttp.ClientSession, probe: dict, cookies: dict) -> dict:
    """探测单个接口，返回结果字典"""
    name = probe["name"]
    url = probe["url"]
    method = probe["method"]
    body = probe["body"]

    cookie_str = "; ".join(k + "=" + v for k, v in cookies.items())
    headers = dict(HEADERS_BASE)
    headers["Cookie"] = cookie_str

    result = {
        "name": name,
        "url": url,
        "method": method,
        "request_body": body,
        "status": None,
        "final_url": None,
        "response_text": None,
        "response_json": None,
        "error": None,
        "has_data": False,
        "summary": "",
    }

    try:
        if method == "POST":
            resp_cm = session.post(url, json=body, headers=headers,
                                   timeout=aiohttp.ClientTimeout(total=12), ssl=False)
        elif method == "POST_FORM":
            form_headers = dict(headers)
            form_headers["Content-Type"] = "application/x-www-form-urlencoded"
            resp_cm = session.post(url, data=body, headers=form_headers,
                                   timeout=aiohttp.ClientTimeout(total=12), ssl=False)
        else:
            resp_cm = session.get(url, headers=headers,
                                  timeout=aiohttp.ClientTimeout(total=12), ssl=False)

        async with resp_cm as resp:
            result["status"] = resp.status
            result["final_url"] = str(resp.url)
            text = await resp.text(errors="replace")
            result["response_text"] = text[:8000]

            try:
                jdata = json.loads(text)
                result["response_json"] = jdata

                success = jdata.get("success") or jdata.get("result") is not None
                err_msg = jdata.get("error_msg") or jdata.get("errorMsg") or jdata.get("error") or ""
                result_data = jdata.get("result") or jdata.get("data") or {}

                if success and not err_msg:
                    result["has_data"] = True
                    if isinstance(result_data, list):
                        result["summary"] = "OK 成功，list=" + str(len(result_data)) + "条"
                    elif isinstance(result_data, dict):
                        order_list = (result_data.get("orderList") or
                                      result_data.get("list") or
                                      result_data.get("orders") or [])
                        if order_list:
                            result["summary"] = "OK 成功，订单=" + str(len(order_list)) + "条"
                        else:
                            keys_preview = str(list(result_data.keys())[:8])
                            result["summary"] = "OK 成功，result keys=" + keys_preview
                    else:
                        result["summary"] = "OK 成功"
                else:
                    result["summary"] = "FAIL 失败 error=" + str(err_msg or "(无error_msg)")
            except Exception:
                result["summary"] = "WARN 非JSON响应，status=" + str(resp.status)

    except asyncio.TimeoutError:
        result["error"] = "超时"
        result["summary"] = "TIMEOUT 超时"
    except Exception as e:
        result["error"] = str(e)
        result["summary"] = "ERROR 异常: " + str(e)

    return result


async def main():
    print("=" * 60)
    print("  拼多多 HTTP API 探测工具")
    print("=" * 60)

    cookies = await load_cookies()
    if not cookies:
        sys.exit(1)

    buyer_id = TEST_BUYER_ID
    if len(sys.argv) > 1:
        buyer_id = sys.argv[1]
        print("[buyer_id] 命令行传入: " + buyer_id)
    elif buyer_id:
        print("[buyer_id] 使用脚本顶部填写的: " + buyer_id)
    else:
        print("[buyer_id] 未填写 TEST_BUYER_ID，跳过按买家查询的接口")
        print("  提示：运行 python tools/pdd_api_probe.py <buyer_id> 可传入买家ID")

    probes = build_probes(buyer_id)
    print("\n共探测 " + str(len(probes)) + " 个接口\n")

    results = []
    async with aiohttp.ClientSession() as session:
        for i, probe in enumerate(probes, 1):
            label = "[" + str(i).zfill(2) + "/" + str(len(probes)) + "] " + probe["name"] + " ..."
            print(label, end=" ", flush=True)
            r = await probe_one(session, probe, cookies)
            print(r["summary"])
            results.append(r)
            await asyncio.sleep(0.3)

    output = {
        "probe_time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "buyer_id_used": buyer_id,
        "cookies_count": len(cookies),
        "cookies_keys": list(cookies.keys()),
        "results": results,
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print("\nOK 结果已保存到: " + OUTPUT_FILE)

    print("\n" + "=" * 60)
    print("  成功接口汇总（has_data=True）：")
    print("=" * 60)
    ok_count = 0
    for r in results:
        if r["has_data"]:
            print("  OK " + r["name"])
            ok_count += 1
    if ok_count == 0:
        print("  WARN 没有任何接口返回有效数据！")
        print("  可能原因：")
        print("    1. cookies 已过期，请重新登录")
        print("    2. 网络问题")
        print("    3. 需要先填写 TEST_BUYER_ID 才能验证按买家查询的接口")

    print("\n请将 probe_result.json 发给 Copilot 以便根据真实数据结构修复代码。")
    print("注意：probe_result.json 不含 cookies 值，只含 key 名，安全可以分享。")


if __name__ == "__main__":
    asyncio.run(main())
