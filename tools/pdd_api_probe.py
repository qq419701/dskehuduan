# -*- coding: utf-8 -*-
"""
拼多多 HTTP API 探测工具
======================
用途：用你的 cookies 实际调用拼多多各个接口，把原始响应保存到 probe_result.json
      把 probe_result.json 发给 Copilot，它根据真实数据结构来修复代码。

用法：
    python tools/pdd_api_probe.py [买家ID]

前提：
    1. 先运行主程序完成登录，确保 ~/.aikefu-client/browser_data/shop_XXX/aikefu_cookies.json 存在
    2. 也可以手动把 cookies 填到下面的 MANUAL_COOKIES 字典（优先级更高）

输出文件：probe_result.json（保存在当前目录）
"""
import json
import os
import sys
import time
from pathlib import Path

import requests  # 改用 requests，与 pdd_transfer.py 保持一致

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
TEST_BUYER_ID = ""

# ──────────────────────────────────────────────
BROWSER_DATA_DIR = os.path.join(os.path.expanduser("~"), ".aikefu-client", "browser_data")
OUTPUT_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "probe_result.json")
PDD_CONFIG_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pdd_config.json")

def load_anti_content() -> str:
    """从 pdd_config.json 读取 anti_content"""
    try:
        if os.path.exists(PDD_CONFIG_FILE):
            with open(PDD_CONFIG_FILE, encoding="utf-8") as f:
                data = json.load(f)
            ac = data.get("anti_content", "")
            if ac:
                print("[anti_content] 加载成功，前30字: " + ac[:30] + "...")
                return ac
    except Exception as e:
        print("[WARN] 读取 pdd_config.json 失败: " + str(e))
    print("[WARN] anti_content 未找到，接口可能返回会话已过期！请先运行 sniff2.py")
    return ""


def make_session(cookies: dict, anti_content: str) -> requests.Session:
    """构造带 cookies + anti_content 的 Session（与 pdd_transfer.py 完全一致）"""
    sess = requests.Session()
    sess.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Referer": "https://mms.pinduoduo.com/chat-merchant/index.html",
        "Origin": "https://mms.pinduoduo.com",
        "Content-Type": "application/json",
        "X-Anti-Content": anti_content,
    })
    for k, v in cookies.items():
        sess.cookies.set(k, v, domain=".pinduoduo.com")
    return sess

# ──────────────────────────────────────────────
# 要探测的接口列表（逐一尝试）
# ──────────────────────────────────────────────
def build_probes(buyer_id: str) -> list:
    now = int(time.time())
    probes = []

    # ── 1. 客服列表接口 ──
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

    # ── 2. 最近订单列表 ──
    probes.append({
        "name": "订单列表_近7天",
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

    # ── 3. 按买家ID查订单 ──
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

    # ── 4. IM 历史消息 ──
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

    # ── 5. 商品列表 ──
    probes.append({
        "name": "商品列表_前5条",
        "url": "https://mms.pinduoduo.com/mms/goods/list",
        "method": "POST",
        "body": {"pageNum": 1, "pageSize": 5, "sortType": 0},
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
            "body": {"buyerUid": str(buyer_id), "pageNumber": 1, "pageSize": 10},
        })
        probes.append({
            "name": "买家订单_v2_uid=" + buyer_id,
            "url": "https://mms.pinduoduo.com/mms/order/buyerOrderList",
            "method": "POST",
            "body": {"buyerUid": str(buyer_id), "pageNum": 1, "pageSize": 10},
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
            "url": "https://mms.pinduoduo.com/chatbot/im/userBrowseGoods",
            "method": "POST",
            "body": {"uid": str(buyer_id), "pageSize": 10},
        })

    return probes

def probe_one(sess: requests.Session, probe: dict, anti_content: str) -> dict:
    """探测单个接口，返回结果字典"""
    name = probe["name"]
    url = probe["url"]
    method = probe["method"]
    body = probe["body"]

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
            resp = sess.post(url, json=body, timeout=12)
        elif method == "POST_FORM":
            form_headers = {"Content-Type": "application/x-www-form-urlencoded"}
            resp = sess.post(url, data=body, headers=form_headers, timeout=12)
        else:
            resp = sess.get(url, timeout=12)

        result["status"] = resp.status_code
        result["final_url"] = str(resp.url)

        text = resp.text
        result["response_text"] = text[:8000]

        try:
            jdata = resp.json()
            result["response_json"] = jdata

            success = jdata.get("success") or jdata.get("result") is not None
            err_msg = jdata.get("error_msg") or jdata.get("errorMsg") or jdata.get("error") or ""
            result_data = jdata.get("result") or jdata.get("data") or {} 

            if err_msg and ("过期" in str(err_msg) or "登录" in str(err_msg) or "session" in str(err_msg).lower()):
                result["error"] = err_msg
                result["summary"] = "FAIL 失败 error=" + str(err_msg)
            elif success and not err_msg:
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
                        result["summary"] = "OK 成功，keys=" + str(list(result_data.keys()))
                elif result_data:
                    result["summary"] = "OK 成功，data=" + str(result_data)[:100]
                else:
                    result["summary"] = "OK 成功（无数据）"
            else:
                result["summary"] = "WARN error_msg=" + str(err_msg) if err_msg else "WARN success=false"

        except ValueError:
            if "login" in text.lower() or "<!doctype" in text.lower():
                result["error"] = "响应为 HTML（可能被重定向到登录页，cookies 已失效）"
                result["summary"] = "FAIL HTML响应（cookies失效）"
            else:
                result["summary"] = "WARN 非JSON响应，status=" + str(resp.status_code)

    except Exception as e:
        result["error"] = str(e)
        result["summary"] = "ERR 异常: " + str(e)

    return result

def load_cookies() -> dict:
    """加载 cookies"""
    if MANUAL_COOKIES:
        print("[cookies] 使用手动填写的 MANUAL_COOKIES，共 " + str(len(MANUAL_COOKIES)) + " 个")
        return MANUAL_COOKIES

    candidates = []
    if os.path.isdir(BROWSER_DATA_DIR):
        for entry in sorted(os.listdir(BROWSER_DATA_DIR)):
            shop_dir = os.path.join(BROWSER_DATA_DIR, entry)
            if os.path.isdir(shop_dir):
                cfile = os.path.join(shop_dir, "aikefu_cookies.json")
                if os.path.exists(cfile):
                    candidates.append((entry, Path(cfile)))

    if not candidates:
        print("[ERROR] 找不到任何 aikefu_cookies.json 文件")
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

def main():
    print("=" * 60)
    print("  拼多多 HTTP API 探测工具")
    print("=" * 60)

    buyer_id = ""
    if len(sys.argv) > 1:
        buyer_id = sys.argv[1].strip()
        print("[buyer_id] 命令行传入: " + buyer_id)
    elif TEST_BUYER_ID:
        buyer_id = TEST_BUYER_ID
        print("[buyer_id] 使用脚本内 TEST_BUYER_ID: " + buyer_id)
    else:
        print("[buyer_id] 未指定买家ID，跳过买家相关接口")

    cookies = load_cookies()
    if not cookies:
        sys.exit(1)

    anti_content = load_anti_content()
    sess = make_session(cookies, anti_content)

    probes = build_probes(buyer_id)
    print("\n共探测 " + str(len(probes)) + " 个接口\n")

    results = []
    for i, probe in enumerate(probes):
        label = "[{0:02d}/{1:02d}] {2}".format(i + 1, len(probes), probe["name"])
        print(label + " ... ", end="", flush=True)
        r = probe_one(sess, probe, anti_content)
        print(r["summary"])
        results.append(r)

    safe_cookie_keys = list(cookies.keys())
    output = {
        "probe_time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "cookie_keys": safe_cookie_keys,
        "anti_content_present": bool(anti_content),
        "results": results,
    }
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2, default=str)
    print("\nOK 结果已保存到: " + OUTPUT_FILE)

    print("\n" + "=" * 60)
    print("  成功接口汇总（has_data=True）：")
    print("=" * 60)
    ok_list = [r for r in results if r["has_data"]]
    if ok_list:
        for r in ok_list:
            print("  OK " + r["name"] + " -> " + r["summary"])
    else:
        print("  WARN 没有任何接口返回有效数据！")
        if not anti_content:
            print("  anti_content 为空是主要原因，请先运行: python sniff2.py")
        else:
            print("  可能原因：")
            print("    1. cookies 已过期，请重新登录（运行 python app.py 后选择重新登录）")
            print("    2. 网络问题")

    print("\n请将 probe_result.json 发给 Copilot 以便根据真实数据结构修复代码。")
    print("注意：probe_result.json 不含 cookies 值，只含 key 名，安全可以分享。")


if __name__ == "__main__":
    main()