# -*- coding: utf-8 -*-
# sniff_agents.py -- yi jian zhen duan ke fu lie biao zi duan ming
# yong fa: python sniff_agents.py
import json
import os
import sys
import requests

CONFIG_FILE = os.path.join(os.path.expanduser("~"), ".aikefu-client", "config.json")

REMARK_KEYS = {
    "remarkName", "remark", "memo", "tag", "comment", "note",
    "csRemark", "label", "alias", "mark", "description", "desc",
    "staffRemark", "csNote", "staffNote", "agentRemark",
}

def load_config():
    if not os.path.exists(CONFIG_FILE):
        print("ERROR: config file not found: " + CONFIG_FILE)
        print("Please login to pdd first in the main app")
        sys.exit(1)
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def make_session(cookies, anti):
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
        "X-Anti-Content": anti,
    })
    # ★ 修复：同时绑定到 mms.pinduoduo.com 和 .pinduoduo.com 两个域
    # requests 对子域名 cookie 匹配规则与浏览器不同，必须双绑才能覆盖所有拼多多接口
    for k, v in cookies.items():
        sess.cookies.set(k, v, domain="mms.pinduoduo.com", path="/")
        sess.cookies.set(k, v, domain=".pinduoduo.com", path="/")
    return sess

def print_agent(uid_key, item):
    print("  --- ke fu key=" + str(uid_key) + " ---")
    for k, v in item.items():
        star = "  REMARK FIELD!" if k in REMARK_KEYS else ""
        print("    " + str(k) + ": " + repr(v) + star)

def parse_agents(data, label):
    print("\n  [jie xi] " + label + " yuan shi xiang ying (qian 2000 zi):")
    print("  " + str(data)[:2000])

    result = data.get("result") or {}
    cs_map = None

    if isinstance(result, list):
        cs_map = result
        print("  -> result shi lie biao, chang du=" + str(len(result)))
    elif isinstance(result, dict):
        for field in ("csList", "staffList", "onlineList", "list", "csInfoList", "agentList", "data"):
            if result.get(field) is not None:
                cs_map = result[field]
                print("  -> cong result." + field + " qu dao ke fu shu ju")
                break
        if cs_map is None and result:
            cs_map = result
            print("  -> result wu yi zhi lie biao zi duan, ba result zheng ti dang csid->info zi dian shi yong")

    if cs_map is None:
        for field in ("csList", "staffList", "onlineList", "list", "csInfoList", "agentList", "data"):
            if data.get(field) is not None:
                cs_map = data[field]
                print("  -> cong ding ceng data." + field + " qu dao ke fu shu ju")
                break

    if cs_map is None:
        print("  [WARN] mei you zhao dao ke fu lie biao zi duan!")
        return

    if isinstance(cs_map, list):
        print("  -> ke fu lie biao chang du=" + str(len(cs_map)))
        for i, item in enumerate(cs_map[:3]):
            print_agent(i, item)
    elif isinstance(cs_map, dict):
        print("  -> ke fu zi dian, jian shu=" + str(len(cs_map)))
        for uid_key, item in list(cs_map.items())[:3]:
            if isinstance(item, dict):
                print_agent(uid_key, item)
            else:
                print("  --- key=" + str(uid_key) + " value=" + repr(item)[:80])

def main():
    cfg = load_config()
    shops = cfg.get("shops", [])
    if not shops:
        print("ERROR: no shops found in config")
        sys.exit(1)

    shop = shops[0]
    shop_id = str(shop.get("shop_id", "1"))
    cookies = shop.get("cookies") or {}
    anti = shop.get("anti_content") or cfg.get("anti_content") or ""

    print("shop_id=" + shop_id)
    print("cookies keys: " + str(list(cookies.keys())[:8]))
    print("anti_content: " + (anti[:30] + "..." if anti else "(EMPTY)"))

    sess = make_session(cookies, anti)

    urls = [
        ("POST", "https://mms.pinduoduo.com/assistant/staff/getOnlineStaffList", {}),
        ("POST", "https://mms.pinduoduo.com/im/cs/getOnlineStaff", {}),
        ("POST", "https://mms.pinduoduo.com/chatbot/cs/onlineList", {}),
        ("POST", "https://mms.pinduoduo.com/mangkhut/mms/getOnlineCsList", {}),
        ("GET",  "https://mms.pinduoduo.com/assistant/staff/getOnlineStaffList", None),
        ("POST", "https://mms.pinduoduo.com/assistant/chat/getTransferStaffList", {}),
        ("POST", "https://mms.pinduoduo.com/chats/getStaffList", {}),
    ]

    found = False
    for method, url, body in urls:
        try:
            if method == "POST":
                r = sess.post(url, json=body, timeout=8)
            else:
                r = sess.get(url, timeout=8)
            print("\n[" + method + "] " + url)
            print("  status=" + str(r.status_code))
            try:
                data = r.json()
                parse_agents(data, url)
                found = True
            except Exception:
                print("  fei JSON xiang ying: " + r.text[:200])
        except Exception as e:
            print("\n[" + method + "] " + url + " -> ERROR: " + str(e))

    if not found:
        print("\n[WARN] suo you jie kou jun wei fan hui ke fu lie biao, qing jian cha cookies shi fou you xiao")

if __name__ == "__main__":
    main()