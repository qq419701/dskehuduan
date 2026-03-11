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
    for k, v in cookies.items():
        sess.cookies.set(k, v, domain=".pinduoduo.com")
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
        print("  WARNING: wu fa zhao dao ke fu lie biao, xiang ying ding ceng zi duan: " + str(list(data.keys())))
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
        print("  WARNING: cs_map lei xing yi chang: " + str(type(cs_map)))

    return agents

def try_v1(sess, anti):
    url = "https://mms.pinduoduo.com/latitude/assign/getAssignCsList"
    print("\n" + "="*60)
    print("[jie kou v1] " + url)
    try:
        r = sess.post(url, json={"wechatCheck": True, "anti_content": anti}, timeout=15)
        print("  zhuang tai ma: " + str(r.status_code))
        if r.status_code != 200:
            print("  ERROR: fei 200, tiao guo")
            return None
        data = r.json()
        if not data.get("success"):
            msg = data.get("errorMsg") or data.get("error_msg") or str(data)[:200]
            print("  ERROR: success=False: " + str(msg))
            return None
        agents = parse_agents(data, "v1")
        print("  OK: jie xi dao " + str(len(agents)) + " ge ke fu")
        return agents
    except Exception as e:
        print("  ERROR: yi chang: " + str(e))
        return None

def try_v2(sess):
    url = "https://mms.pinduoduo.com/mms/api/cs/online_list"
    print("\n" + "="*60)
    print("[jie kou v2] " + url)
    try:
        r = sess.get(url, timeout=15)
        print("  zhuang tai ma: " + str(r.status_code))
        if r.status_code != 200:
            print("  ERROR: fei 200, tiao guo")
            return None
        data = r.json()
        if not (data.get("success") or data.get("result")):
            print("  ERROR: jie kou fan hui shi bai: " + str(data)[:200])
            return None
        agents = parse_agents(data, "v2")
        print("  OK: jie xi dao " + str(len(agents)) + " ge ke fu")
        return agents
    except Exception as e:
        print("  ERROR: yi chang: " + str(e))
        return None

def try_v3(sess):
    url = "https://mms.pinduoduo.com/service/im/cs/list"
    print("\n" + "="*60)
    print("[jie kou v3] " + url)
    try:
        r = sess.get(url, timeout=15)
        print("  zhuang tai ma: " + str(r.status_code))
        if r.status_code != 200:
            print("  ERROR: fei 200, tiao guo")
            return None
        data = r.json()
        if not (data.get("success") or data.get("result")):
            print("  ERROR: jie kou fan hui shi bai: " + str(data)[:200])
            return None
        agents = parse_agents(data, "v3")
        print("  OK: jie xi dao " + str(len(agents)) + " ge ke fu")
        return agents
    except Exception as e:
        print("  ERROR: yi chang: " + str(e))
        return None

def run_for_shop(shop_id, cookies, anti):
    print("\n" + "#"*60)
    print("# shop_id=" + str(shop_id) + "  cookies=" + str(len(cookies)) + "ge  anti=" + ("yi pei zhi" if anti else "wei pei zhi"))
    print("#"*60)

    if not cookies:
        print("  WARNING: cookies wei kong, tiao guo gai dian pu")
        return {}

    sess = make_session(cookies, anti)
    result = {"shop_id": shop_id, "v1": None, "v2": None, "v3": None}

    agents = try_v1(sess, anti)
    result["v1"] = agents

    if agents is None:
        agents = try_v2(sess)
        result["v2"] = agents

    if agents is None:
        agents = try_v3(sess)
        result["v3"] = agents

    if agents is None:
        print("\n  ERROR: san ge jie kou jun shi bai, cookies ke neng yi guo qi")
    elif len(agents) == 0:
        print("\n  WARNING: jie kou cheng gong dan ke fu lie biao wei kong")
    else:
        print("\n  OK: gong zhao dao " + str(len(agents)) + " ge ke fu")

    return result

def main():
    print("=" * 60)
    print("  PDD ke fu lie biao zi duan zhen duan gong ju")
    print("=" * 60)

    cfg = load_config()
    shops = cfg.get("active_shops", [])
    anti_map = cfg.get("pdd_anti_content", {})

    if not shops:
        print("ERROR: config.json li mei you active_shops")
        sys.exit(1)

    print("\n zhao dao " + str(len(shops)) + " ge dian pu")

    all_results = []
    for shop in shops:
        shop_id = str(shop.get("id") or shop.get("shop_id") or "")
        cookies = shop.get("cookies") or shop.get("pdd_cookies") or {}
        anti = anti_map.get(shop_id, "")
        res = run_for_shop(shop_id, cookies, anti)
        all_results.append(res)

    out_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agents_result.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)

    print("\n" + "="*60)
    print("OK: zhen duan wan cheng! jie guo yi bao cun dao: " + out_file)
    print("="*60)

if __name__ == "__main__":
    main()