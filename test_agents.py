# -*- coding: utf-8 -*-
"""诊断脚本：直接调用拼多多接口，打印客服列表完整原始数据"""
import sys, json, requests
sys.path.insert(0, '.')
import config as cfg

# 读取两个店铺的 cookies
import os
browser_data = os.path.join(os.path.expanduser('~'), '.aikefu-client', 'browser_data')

def get_cookies_from_browser(shop_id):
    import glob
    pattern = os.path.join(browser_data, f'shop_{shop_id}', '*.json')
    files = glob.glob(pattern)
    print(f'  浏览器cookies文件: {files}')
    return {}

def test_shop(shop_id, cookies):
    if not cookies:
        print(f'  [!] 无 cookies，跳过')
        return

    anti = cfg.get_anti_content(str(shop_id))
    sess = requests.Session()
    sess.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': 'https://mms.pinduoduo.com/chat-merchant/index.html',
        'Origin': 'https://mms.pinduoduo.com',
        'Content-Type': 'application/json',
        'X-Anti-Content': anti,
    })
    for k, v in cookies.items():
        sess.cookies.set(k, v, domain='.pinduoduo.com')

    url = 'https://mms.pinduoduo.com/latitude/assign/getAssignCsList'
    print(f'\n  调用接口: {url}')
    try:
        r = sess.post(url, json={'wechatCheck': True, 'anti_content': anti}, timeout=15)
        print(f'  HTTP状态: {r.status_code}')
        data = r.json()
        print(f'  完整响应:')
        print(json.dumps(data, ensure_ascii=False, indent=2)[:5000])

        # 找出客服列表字段
        result = data.get('result') or {}
        if isinstance(result, dict):
            for key, val in result.items():
                print(f'\n  result.{key} = {str(val)[:200]}')
    except Exception as e:
        print(f'  错误: {e}')

# 从 pdd_settings 读取 shop_cookies
conf = cfg.load_config()
pdd = conf.get('pdd_settings', {})
shop_cookies_map = pdd.get('shop_cookies', {})

shops = cfg.get_active_shops()
for shop in shops:
    sid = str(shop['id'])
    name = shop['name']
    print(f'\n======== 店铺: {name} (id={sid}) ========')
    cookies = shop_cookies_map.get(sid, {})
    if not cookies:
        print(f'  pdd_settings.shop_cookies[{sid}] 无数据')
        # 尝试从 task_runner 的持久化读取
        ck_file = os.path.join(os.path.expanduser('~'), '.aikefu-client', f'shop_{sid}_cookies.json')
        if os.path.exists(ck_file):
            with open(ck_file) as f:
                cookies = json.load(f)
            print(f'  从 {ck_file} 读取到 {len(cookies)} 个cookies')
    test_shop(sid, cookies)