# -*- coding: utf-8 -*-
"""
sniff_agents.py — 一键诊断客服列表字段名
用法：
  cd C:\Users\Administrator\Desktop\dskehuduan
  python sniff_agents.py

脚本会：
1. 自动读取本地 config.json 里所有店铺的 cookies
2. 调用三个客服列表接口（v1/v2/v3）
3. 完整打印每个客服的所有字段，用 ★ 标出备注相关字段
4. 把结果保存到 agents_result.json
"""
import json
import os
import sys
import time
import requests

CONFIG_FILE = os.path.join(os.path.expanduser("~"), ".aikefu-client", "config.json")

# 备注类字段名（出现时用 ★ 标记）
REMARK_KEYS = {
    "remarkName", "remark", "memo", "tag", "comment", "note",
    "csRemark", "label", "alias", "mark", "description", "desc",
    "staffRemark", "csNote", "staffNote", "agentRemark",
}

def load_config():
    if not os.path.exists(CONFIG_FILE):
        print(f"❌ 找不到配置文件: {CONFIG_FILE}")
        print("   请先启动主程序并登录拼多多店铺")
        sys.exit(1)
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def make_session(cookies: dict, anti: str) -> requests.Session:
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
    for k, v in cookies.items():
        sess.cookies.set(k, v, domain=".pinduoduo.com")
    return sess

def print_agent(uid_key, item):
    print(f"  --- 客服 key={uid_key} ---")
    for k, v in item.items():
        star = " ★ 可能是备注字段！" if k in REMARK_KEYS else ""
        print(f"    {k}: {repr(v)}{star}")

def parse_agents(data: dict, label: str):
    print(f"\n  [解析] {label} 原始响应（前2000字）:")
    print("  " + str(data)[:2000])

    result = data.get("result") or {}
    cs_map = None

    if isinstance(result, list):
        cs_map = result
        print(f"  → result 是列表，长度={len(result)}")
    elif isinstance(result, dict):
        for field in ("csList", "staffList", "onlineList", "list", "csInfoList", "agentList", "data"):
            if result.get(field) is not None:
                cs_map = result[field]
                print(f"  → 从 result.{field} 取到客服数据")
                break
        if cs_map is None and result:
            cs_map = result
            print("  → result 无已知列表字段，把 result 整体当 csid→info 字典使用")

    if cs_map is None:
        for field in ("csList", "staffList", "onlineList", "list", "csInfoList", "agentList", "data"):
            if data.get(field) is not None:
                cs_map = data[field]
                print(f"  → 从顶层 data.{field} 取到客服数据")
                break

    if cs_map is None:
        print(f"  ⚠ 无法找到客服列表，响应顶层字段: {list(data.keys())}")
        return []

    if isinstance(cs_map, list):
        cs_map = {str(i): item for i, item in enumerate(cs_map)}

    agents = []
    if isinstance(cs_map, dict):
        for uid_key, item in cs_map.items():
            if not isinstance(item, dict):
                continue
            print_agent(uid_key, item)
            agents.append({"key": uid_key, "data": item})
    else:
        print(f"  ⚠ cs_map 类型异常: {type(cs_map)}")

    return agents

def try_v1(sess, shop_id, anti):
    url = "https://mms.pinduoduo.com/latitude/assign/getAssignCsList"
    print(f"\n{'='*60}")
    print(f"[接口v1] {url}")
    try:
        r = sess.post(url, json={"wechatCheck": True, "anti_content": anti}, timeout=15)
        print(f"  状态码: {r.status_code}")
        if r.status_code != 200:
            print(f"  ❌ 非200，跳过")
            return None
        data = r.json()
        if not data.get("success"):
            msg = data.get("errorMsg") or data.get("error_msg") or str(data)[:200]
            print(f"  ❌ success=False: {msg}")
            return None
        agents = parse_agents(data, "v1")
        print(f"  ✅ 解析到 {len(agents)} 个客服")
        return agents
    except Exception as e:
        print(f"  ❌ 异常: {e}")
        return None

def try_v2(sess):
    url = "https://mms.pinduoduo.com/mms/api/cs/online_list"
    print(f"\n{'='*60}")
    print(f"[接口v2] {url}")
    try:
        r = sess.get(url, timeout=15)
        print(f"  状态码: {r.status_code}")
        if r.status_code != 200:
            print(f"  ❌ 非200，跳过")
            return None
        data = r.json()
        if not (data.get("success") or data.get("result")):
            print(f"  ❌ 接口返回失败: {str(data)[:200]}")
            return None
        agents = parse_agents(data, "v2")
        print(f"  ✅ 解析到 {len(agents)} 个客服")
        return agents
    except Exception as e:
        print(f"  ❌ 异常: {e}")
        return None

def try_v3(sess):
    url = "https://mms.pinduoduo.com/service/im/cs/list"
    print(f"\n{'='*60}")
    print(f"[接口v3] {url}")
    try:
        r = sess.get(url, timeout=15)
        print(f"  状态码: {r.status_code}")
        if r.status_code != 200:
            print(f"  ❌ 非200，跳过")
            return None
        data = r.json()
        if not (data.get("success") or data.get("result")):
            print(f"  ❌ 接口返回失败: {str(data)[:200]}")
            return None
        agents = parse_agents(data, "v3")
        print(f"  ✅ 解析到 {len(agents)} 个客服")
        return agents
    except Exception as e:
        print(f"  ❌ 异常: {e}")
        return None

def run_for_shop(shop_id, cookies, anti):
    print(f"\n{'#'*60}")
    print(f"# 店铺 shop_id={shop_id}  cookies={len(cookies)}个  anti={'已配置' if anti else '未配置'}")
    print(f"{'#'*60}")

    if not cookies:
        print("  ⚠ cookies 为空，跳过该店铺")
        return {}

    sess = make_session(cookies, anti)
    result = {"shop_id": shop_id, "v1": None, "v2": None, "v3": None}

    agents = try_v1(sess, shop_id, anti)
    result["v1"] = agents

    if agents is None:
        agents = try_v2(sess)
        result["v2"] = agents

    if agents is None:
        agents = try_v3(sess)
        result["v3"] = agents

    if agents is None:
        print(f"\n  ❌ 三个接口均失败，cookies 可能已过期")
    elif len(agents) == 0:
        print(f"\n  ⚠ 接口成功但客服列表为空（当前无在线客服？）")
    else:
        print(f"\n  ✅ 共找到 {len(agents)} 个客服")

    return result

def main():
    print("=" * 60)
    print("  拼多多客服列表字段诊断工具")
    print("=" * 60)

    cfg = load_config()
    shops = cfg.get("active_shops", [])
    anti_map = cfg.get("pdd_anti_content", {})

    if not shops:
        print("❌ config.json 里没有 active_shops，请先在主程序登录拼多多店铺")
        sys.exit(1)

    print(f"\n找到 {len(shops)} 个店铺")

    all_results = []
    for shop in shops:
        shop_id = str(shop.get("id") or shop.get("shop_id") or "")
        cookies = shop.get("cookies") or shop.get("pdd_cookies") or {}
        anti = anti_map.get(shop_id, "")
        res = run_for_shop(shop_id, cookies, anti)
        all_results.append(res)

    # 保存结果
    out_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agents_result.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*60}")
    print(f"✅ 诊断完成！完整结果已保存到: {out_file}")
    print(f"   把上面输出（或 agents_result.json）发给我，我来修复备注字段名")
    print(f"{'='*60}")

if __name__ == "__main__":
    main()