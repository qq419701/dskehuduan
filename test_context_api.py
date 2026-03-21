#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
订单和浏览足迹接口诊断脚本 - test_context_api.py
=====================================================
用途：验证拼多多订单接口和浏览足迹接口是否正常工作

使用方法：
  python test_context_api.py                                             # 自动捕获买家UID（需要打开浏览器点击会话）
  python test_context_api.py --buyer-id 1234567                         # 指定buyer_id，浏览器加载后立即读cookies
  python test_context_api.py --buyer-id 1234567 --cookies-file cks.json # 完全跳过浏览器，从文件读cookies

输出文件：test_context_result.json（完整响应数据）

前置条件：
  1. 已安装 playwright: pip install playwright && playwright install chromium
  2. 已安装 aiohttp:    pip install aiohttp
  3. browser_data 目录下有登录过的 profile
"""

import sys
import argparse
import asyncio
import json
import time
import logging
from pathlib import Path
from typing import Optional

# ── 常量 ──
BASE = Path(__file__).parent
OUTPUT_FILE = BASE / "test_context_result.json"

PDD_ORDER_LATITUDE_URL = 'https://mms.pinduoduo.com/latitude/order/userAllOrder'
PDD_ORDER_FALLBACK_URL = 'https://mms.pinduoduo.com/mangkhut/mms/recentOrderList'
PDD_FOOTPRINT_URL = 'https://mms.pinduoduo.com/latitude/goods/singleRecommendGoods'

# pdd_context_fetcher.py 中默认优先使用的 footprint type 值
DEFAULT_FOOTPRINT_TYPE = 2

# ── 颜色输出 ──
def ok(s): return f"\033[32m{s}\033[0m"
def err(s): return f"\033[31m{s}\033[0m"
def warn(s): return f"\033[33m{s}\033[0m"
def info(s): return f"\033[36m{s}\033[0m"

# ── 全局状态 ──
captured_buyer_id = ''
captured_cookies = {}
all_results = {}

def _is_redirected(url: str) -> bool:
    return '/other/404' in url or '__from=' in url

def _build_headers(cookies: dict) -> dict:
    cookie_str = '; '.join(f'{k}={v}' for k, v in cookies.items())
    return {
        'Cookie': cookie_str,
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': 'https://mms.pinduoduo.com/',
        'Content-Type': 'application/json',
        'Origin': 'https://mms.pinduoduo.com',
    }

def _get_ws_payload(frame) -> str:
    try:
        return frame.payload if isinstance(frame.payload, str) else frame.payload.decode('utf-8', errors='ignore')
    except Exception:
        return ''

def _handle_ws_frame(raw: str) -> None:
    global captured_buyer_id
    if not raw or captured_buyer_id:
        return
    try:
        msg = json.loads(raw)
    except Exception:
        return
    if not isinstance(msg, dict):
        return
    inner = msg.get('message') or msg
    # 尝试从各种字段提取 buyer_id
    for field in ('uid', 'buyerUid', 'buyer_uid', 'userId', 'user_id', 'fromUid', 'from_uid'):
        val = inner.get(field) or msg.get(field)
        if val and str(val) not in ('0', ''):
            captured_buyer_id = str(val)
            print(ok(f"\n✅ 捕获到 buyer_id={captured_buyer_id}（字段: {field}）"))
            return
    # 从 URL 路径或会话 ID 提取
    conv_id = inner.get('conversationId') or inner.get('conversation_id') or msg.get('conversationId', '')
    if conv_id:
        parts = str(conv_id).split('-')
        for p in parts:
            if p.isdigit() and len(p) > 5:
                captured_buyer_id = p
                print(ok(f"\n✅ 从 conversationId 提取 buyer_id={captured_buyer_id}"))
                return

async def _capture_buyer_id_and_cookies(user_data: Path) -> tuple:
    """打开浏览器，等待用户点击会话，捕获 buyer_id 和 cookies"""
    from playwright.async_api import async_playwright

    global captured_buyer_id, captured_cookies

    async with async_playwright() as pw:
        ctx = await pw.chromium.launch_persistent_context(
            str(user_data),
            headless=False,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
            locale="zh-CN",
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()

        def on_ws(ws):
            if 'pinduoduo' not in ws.url and 'pdd' not in ws.url.lower():
                return
            ws.on('framesent', lambda f: _handle_ws_frame(_get_ws_payload(f)))
            ws.on('framereceived', lambda f: _handle_ws_frame(_get_ws_payload(f)))

        page.on('websocket', on_ws)

        try:
            await page.goto('https://mms.pinduoduo.com/chat-merchant/index.html#/', timeout=30000)
        except Exception:
            pass

        print(warn("\n>>> 请点击任意买家会话，脚本会自动捕获 buyer_id <<<"))
        print(info("最长等待 60 秒..."))

        for i in range(12):
            await asyncio.sleep(5)
            if captured_buyer_id:
                break
            print(info(f"  等待中... {(i+1)*5}s"))

        # 提取 cookies
        raw_cookies = await ctx.cookies()
        captured_cookies = {c['name']: c['value'] for c in raw_cookies if 'pinduoduo' in c.get('domain', '')}
        print(ok(f"提取到 {len(captured_cookies)} 个 pinduoduo cookies"))

        await ctx.close()

    return captured_buyer_id, captured_cookies

async def _load_cookies_from_browser(user_data: Path) -> dict:
    """
    打开浏览器 persistent context，加载拼多多页面，立即读取 cookies 后关闭浏览器。
    不等待 WS 消息 / 不需要用户操作。
    """
    from playwright.async_api import async_playwright

    cookies: dict = {}
    async with async_playwright() as pw:
        ctx = await pw.chromium.launch_persistent_context(
            str(user_data),
            headless=False,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
            locale="zh-CN",
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        try:
            await page.goto('https://mms.pinduoduo.com/', timeout=15000)
        except Exception:
            pass
        await asyncio.sleep(3)  # 3秒等待页面及 cookie 稳定
        raw_cookies = await ctx.cookies()
        cookies = {c['name']: c['value'] for c in raw_cookies if 'pinduoduo' in c.get('domain', '')}
        print(ok(f"提取到 {len(cookies)} 个 pinduoduo cookies"))
        await ctx.close()
    return cookies

async def test_order_latitude(buyer_id: str, cookies: dict) -> dict:
    """测试 latitude/order/userAllOrder 接口"""
    print(f"\n{info('='*50)}")
    print(info("测试1: latitude/order/userAllOrder（主订单接口）"))
    result = {'url': PDD_ORDER_LATITUDE_URL, 'success': False, 'orders': [], 'raw': None, 'error': None}

    payload = {
        'uid': str(buyer_id),
        'pageSize': 10,
        'pageNum': 1,
        'startTime': int(time.time()) - 90 * 86400,  # 近90天
        'endTime': int(time.time()),
    }

    try:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.post(
                PDD_ORDER_LATITUDE_URL, json=payload,
                headers=_build_headers(cookies),
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                result['status'] = resp.status
                final_url = str(resp.url)
                if _is_redirected(final_url):
                    print(err(f"  ❌ 被重定向！cookies 已失效: {final_url}"))
                    result['redirected'] = True
                    return result
                print(info(f"  HTTP 状态: {resp.status}"))
                data = await resp.json(content_type=None)

        result['raw'] = data
        print(info(f"  success={data.get('success')}"))

        if not data.get('success'):
            err_msg = data.get('error_msg') or data.get('errorMsg') or ''
            print(err(f"  ❌ 接口返回失败: {err_msg}"))
            result['error'] = err_msg
            return result

        # 打印 result 完整结构
        r = data.get('result') or data.get('data') or {}
        if isinstance(r, dict):
            print(info(f"  result 的 keys: {list(r.keys())}"))
        elif isinstance(r, list):
            print(info(f"  result 是列表，长度={len(r)}"))

        # 尝试各种字段名提取订单
        FIELDS = ['orderList', 'list', 'orders', 'items', 'data', 'records',
                  'orderSnList', 'orderInfoList', 'orderVOList', 'orderDetailList',
                  'content', 'rows', 'orderInfos']
        orders = []
        found_field = None
        if isinstance(r, list):
            orders = r
            found_field = 'result(list)'
        elif isinstance(r, dict):
            for f in FIELDS:
                v = r.get(f)
                if v and isinstance(v, list):
                    orders = v
                    found_field = f
                    break

        if orders:
            result['success'] = True
            result['orders'] = orders
            result['found_field'] = found_field
            print(ok(f"  ✅ 找到订单！字段='{found_field}'，数量={len(orders)}"))
            if orders:
                print(ok(f"  首条订单 keys: {list(orders[0].keys()) if isinstance(orders[0], dict) else type(orders[0])}"))
        else:
            print(warn(f"  ⚠️ success=True 但订单列表为空！result keys={list(r.keys()) if isinstance(r, dict) else type(r)}"))
            if isinstance(r, dict):
                print(warn(f"  完整 result（前400字符）:\n  {json.dumps(r, ensure_ascii=False)[:400]}"))

    except Exception as e:
        print(err(f"  异常: {e}"))
        result['error'] = str(e)

    return result

async def test_order_fallback(buyer_id: str, cookies: dict) -> dict:
    """测试 mangkhut/mms/recentOrderList 兜底接口"""
    print(f"\n{info('='*50)}")
    print(info("测试2: mangkhut/mms/recentOrderList（兜底订单接口）"))
    result = {'url': PDD_ORDER_FALLBACK_URL, 'success': False, 'orders': [], 'raw': None, 'error': None}

    now = int(time.time())
    payload = {
        'orderType': 0, 'afterSaleType': 0, 'remarkStatus': -1, 'urgeShippingStatus': -1,
        'groupStartTime': now - 7 * 86400, 'groupEndTime': now,
        'pageNumber': 1, 'pageSize': 10,
        'hideRegionBlackDelayShipping': False, 'mobileMarkSearch': False,
        'buyerUid': str(buyer_id),
    }

    try:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.post(
                PDD_ORDER_FALLBACK_URL, json=payload,
                headers=_build_headers(cookies),
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                result['status'] = resp.status
                final_url = str(resp.url)
                if _is_redirected(final_url):
                    print(err(f"  ❌ 被重定向！cookies 已失效"))
                    result['redirected'] = True
                    return result
                print(info(f"  HTTP 状态: {resp.status}"))
                data = await resp.json(content_type=None)

        result['raw'] = data
        print(info(f"  success={data.get('success')}"))

        if not data.get('success'):
            err_msg = data.get('error_msg') or data.get('errorMsg') or ''
            print(err(f"  ❌ 接口返回失败: {err_msg}"))
            result['error'] = err_msg
            return result

        r = data.get('result') or data.get('data') or {}
        if isinstance(r, dict):
            print(info(f"  result 的 keys: {list(r.keys())}"))

        FIELDS = ['orderList', 'list', 'orders', 'items', 'data', 'records',
                  'orderSnList', 'orderInfoList', 'orderVOList', 'orderDetailList',
                  'content', 'rows', 'orderInfos']
        orders = []
        found_field = None
        if isinstance(r, list):
            orders = r
            found_field = 'result(list)'
        elif isinstance(r, dict):
            for f in FIELDS:
                v = r.get(f)
                if v and isinstance(v, list):
                    orders = v
                    found_field = f
                    break

        if orders:
            result['success'] = True
            result['orders'] = orders
            result['found_field'] = found_field
            print(ok(f"  ✅ 找到订单！字段='{found_field}'，数量={len(orders)}"))
            if orders:
                print(ok(f"  首条订单 keys: {list(orders[0].keys()) if isinstance(orders[0], dict) else type(orders[0])}"))
        else:
            print(warn(f"  ⚠️ success=True 但订单列表为空！"))
            if isinstance(r, dict):
                print(warn(f"  完整 result（前400字符）:\n  {json.dumps(r, ensure_ascii=False)[:400]}"))

    except Exception as e:
        print(err(f"  异常: {e}"))
        result['error'] = str(e)

    return result

async def test_footprint(buyer_id: str, cookies: dict, fp_type: int) -> dict:
    """测试 latitude/goods/singleRecommendGoods 足迹接口，指定 type 值"""
    print(f"\n{info(f'--- 浏览足迹 type={fp_type} ---')}")
    result = {'type': fp_type, 'success': False, 'goods_count': 0, 'raw': None, 'error': None}

    payload = {
        'type': fp_type,
        'uid': str(buyer_id),
        'conversationId': '',
        'pageSize': 5,
        'pageNum': 1,
    }

    try:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.post(
                PDD_FOOTPRINT_URL, json=payload,
                headers=_build_headers(cookies),
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                result['status'] = resp.status
                final_url = str(resp.url)
                if _is_redirected(final_url):
                    print(err(f"  ❌ 被重定向（cookies失效）"))
                    result['redirected'] = True
                    return result
                print(info(f"  HTTP 状态: {resp.status}"))
                data = await resp.json(content_type=None)

        result['raw'] = data
        print(info(f"  success={data.get('success')}"))

        if not data.get('success'):
            print(warn(f"  ⚠️ success=False"))
            return result

        r = data.get('result') or data.get('data') or {}
        # result 可能是列表
        if isinstance(r, list):
            print(info(f"  result 是列表，长度={len(r)}"))
            first = r[0] if r and isinstance(r[0], dict) else {}
            goods_list = first.get('goodsList') or first.get('list') or []
        elif isinstance(r, dict):
            print(info(f"  result keys: {list(r.keys())}"))
            goods_list = r.get('goodsList') or r.get('list') or []
        else:
            goods_list = []

        if goods_list:
            result['success'] = True
            result['goods_count'] = len(goods_list)
            g = goods_list[0] if isinstance(goods_list[0], dict) else {}
            goods_name = g.get('goodsName') or g.get('goods_name') or ''
            goods_id = g.get('goodsId') or g.get('goods_id') or ''
            print(ok(f"  ✅ 找到 {len(goods_list)} 个商品！首条: id={goods_id} name={goods_name}"))
            print(ok(f"  首条商品 keys: {list(g.keys())}"))
        else:
            print(warn(f"  ❌ 商品列表为空（success=True 但没有商品）"))
            if isinstance(r, dict):
                print(warn(f"  result（前300字符）: {json.dumps(r, ensure_ascii=False)[:300]}"))
            elif isinstance(r, list) and r:
                print(warn(f"  result[0]（前300字符）: {json.dumps(r[0], ensure_ascii=False)[:300]}"))

    except Exception as e:
        print(err(f"  异常: {e}"))
        result['error'] = str(e)

    return result

def print_diagnosis(buyer_id: str, results: dict):
    """打印诊断报告"""
    print(f"\n{'='*60}")
    print("  === 诊断报告 ===")
    print('='*60)

    recommendations = []

    # 订单接口
    lat = results.get('order_latitude', {})
    if lat.get('success'):
        print(ok(f"  ✅ 订单接口（latitude）：成功，字段='{lat.get('found_field')}'，{len(lat.get('orders', []))} 条"))
    elif lat.get('redirected'):
        print(err("  ❌ 订单接口（latitude）：cookies已失效，需要重新登录"))
        recommendations.append("cookies 已失效，运行 sniff_pdd_chat.py 重新登录拼多多")
    else:
        print(err(f"  ❌ 订单接口（latitude）：失败（{lat.get('error', '')}）"))

    fb = results.get('order_fallback', {})
    if fb.get('success'):
        print(ok(f"  ✅ 订单接口（fallback）：成功，字段='{fb.get('found_field')}'，{len(fb.get('orders', []))} 条"))
    elif fb.get('redirected'):
        print(err("  ❌ 订单接口（fallback）：cookies已失效"))
    else:
        print(err(f"  ❌ 订单接口（fallback）：失败（{fb.get('error', '')}）"))

    if not lat.get('success') and not fb.get('success') and not lat.get('redirected') and not fb.get('redirected'):
        recommendations.append("两个订单接口都失败，可能是该买家没有近7天订单，或者 buyer_id 不正确")

    # 浏览足迹
    best_type = None
    for tp in (1, 2, 3):
        fp = results.get(f'footprint_type{tp}', {})
        if fp.get('success') and fp.get('goods_count', 0) > 0:
            print(ok(f"  ✅ 浏览足迹 type={tp}：成功，{fp['goods_count']} 个商品"))
            if best_type is None:
                best_type = tp
        elif fp.get('redirected'):
            print(err(f"  ❌ 浏览足迹 type={tp}：cookies已失效"))
        else:
            print(warn(f"  ⚠️ 浏览足迹 type={tp}：无商品数据"))

    if best_type is not None and best_type != DEFAULT_FOOTPRINT_TYPE:
        recommendations.append(
            f"pdd_context_fetcher.py 中足迹接口 type 参数应优先使用 {best_type}（当前默认用2）"
        )
    elif best_type is None:
        recommendations.append("所有 type 值均未返回商品，可能是买家当前没有浏览记录，或 cookies 失效")

    print(f"\n  【修复建议】")
    if recommendations:
        for i, r in enumerate(recommendations, 1):
            print(warn(f"  {i}. {r}"))
    else:
        print(ok("  无需额外修复！接口工作正常。"))

    print('='*60)

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--buyer-id', default='', help='直接指定买家UID，跳过WS捕获')
    parser.add_argument('--cookies-file', default='', help='从JSON文件加载cookies，完全跳过浏览器启动')
    args = parser.parse_args()

    print("="*60)
    print("  订单和浏览足迹接口诊断脚本")
    print("="*60)

    # 检查依赖
    for pkg in ('playwright', 'aiohttp'):
        try:
            __import__(pkg)
        except ImportError:
            import subprocess
            print(warn(f"正在安装 {pkg}..."))
            subprocess.run([sys.executable, '-m', 'pip', 'install', pkg], check=True)
            if pkg == 'playwright':
                subprocess.run([sys.executable, '-m', 'playwright', 'install', 'chromium'], check=True)

    # 查找 browser_data profile
    candidate_profiles = []
    browser_data_dir = BASE / 'browser_data'
    if browser_data_dir.exists():
        for p in browser_data_dir.iterdir():
            if p.is_dir():
                candidate_profiles.append(p)

    user_data = candidate_profiles[0] if candidate_profiles else BASE / 'browser_data' / 'sniff_profile'
    if not user_data.exists():
        user_data.mkdir(parents=True, exist_ok=True)
    print(info(f"使用 profile: {user_data}"))

    global captured_buyer_id, captured_cookies

    if args.cookies_file:
        # 从文件加载 cookies，完全跳过浏览器
        cookies_path = Path(args.cookies_file)
        if not cookies_path.exists():
            print(err(f"❌ cookies 文件不存在: {cookies_path}"))
            return
        try:
            raw = json.loads(cookies_path.read_text(encoding='utf-8'))
            if isinstance(raw, list):
                # playwright 格式：[{"name": ..., "value": ...}, ...]
                captured_cookies = {c['name']: c['value'] for c in raw if 'name' in c and 'value' in c}
            elif isinstance(raw, dict):
                # 简单 key-value 格式
                captured_cookies = raw
            else:
                print(err("❌ cookies 文件格式不支持（需要 dict 或 list）"))
                return
            print(ok(f"从文件加载到 {len(captured_cookies)} 个 cookies"))
        except Exception as e:
            print(err(f"❌ 读取 cookies 文件失败: {e}"))
            return
        if args.buyer_id:
            captured_buyer_id = args.buyer_id
        else:
            print(warn("使用 --cookies-file 时请同时指定 --buyer-id"))
            try:
                uid = input("buyer_id: ").strip()
                captured_buyer_id = uid or '0'
            except (EOFError, KeyboardInterrupt):
                captured_buyer_id = '0'
    elif args.buyer_id:
        captured_buyer_id = args.buyer_id
        print(info(f"使用指定 buyer_id: {captured_buyer_id}"))
        print(info("正在打开浏览器读取 cookies（无需操作，自动完成）..."))
        # 直接读取 cookies，不进入 WS 等待循环
        captured_cookies = await _load_cookies_from_browser(user_data)
    else:
        buyer_id, cookies = await _capture_buyer_id_and_cookies(user_data)

        if not captured_buyer_id:
            print(warn("未自动捕获到 buyer_id，请手动输入："))
            try:
                uid = input("buyer_id（按回车使用 '0'）: ").strip()
                captured_buyer_id = uid or '0'
            except (EOFError, KeyboardInterrupt):
                captured_buyer_id = '0'

    buyer_id = captured_buyer_id
    cookies = captured_cookies

    print(info(f"\nbuyer_id: {buyer_id}"))
    print(info(f"cookies 数量: {len(cookies)}"))

    if not cookies:
        print(err("❌ 没有 cookies！无法测试接口。请先在浏览器中登录拼多多。"))
        return

    # 运行测试
    results = {}
    results['order_latitude'] = await test_order_latitude(buyer_id, cookies)
    results['order_fallback'] = await test_order_fallback(buyer_id, cookies)

    print(f"\n{info('='*50)}")
    print(info("测试3: latitude/goods/singleRecommendGoods（浏览足迹接口）"))
    for tp in (1, 2, 3):
        results[f'footprint_type{tp}'] = await test_footprint(buyer_id, cookies, tp)

    print_diagnosis(buyer_id, results)

    # 保存结果
    all_results.update({
        'captured_at': time.strftime('%Y-%m-%d %H:%M:%S'),
        'buyer_id': buyer_id,
        'cookies_count': len(cookies),
    })
    all_results.update(results)

    try:
        OUTPUT_FILE.write_text(json.dumps(all_results, ensure_ascii=False, indent=2), encoding='utf-8')
        print(info(f"\n完整结果已保存到: {OUTPUT_FILE}"))
    except Exception as e:
        print(warn(f"保存失败: {e}"))

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(warn("\n已中断"))
