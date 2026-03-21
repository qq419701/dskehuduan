#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
拼多多接口全面诊断脚本 - test_all_apis.py
==========================================
用途：验证订单、浏览足迹接口及 WebSocket 足迹捕获是否正常

Cookies 读取优先级：
  1. --cookies-file 命令行参数指定的 JSON 文件
  2. browser_data/ 目录下第一个子目录的 Chromium Cookies SQLite 文件
  3. pdd_config.json 里的 cookies 字段

使用方法：
  python test_all_apis.py --buyer-id 123456
      （直接指定 buyer_id，从已有 cookies 测试 HTTP 接口）

  python test_all_apis.py --ws-only
      （只做 WebSocket 监听，捕获 bizContext/sourceGoods 字段，持续 30 秒）

  python test_all_apis.py
      （先做 HTTP 测试再做 WS 监听）

  python test_all_apis.py --buyer-id 123456 --cookies-file my_cookies.json
      （从指定 JSON 文件读取 cookies）

输出文件：test_all_apis_result.json

前置条件：
  pip install aiohttp
  如需 WS 监听：pip install playwright && playwright install chromium

颜色说明：
  ✅ 绿色 = 接口返回 success=true 且有数据
  ⚠️ 黄色 = 接口返回 success=true 但数据为空
  ❌ 红色 = 接口返回失败/重定向/异常
  🔵 蓝色 = WebSocket 消息
"""

import sys
import argparse
import asyncio
import json
import time
import sqlite3
import logging
import re
from pathlib import Path
from typing import Optional

try:
    import aiohttp
except ImportError:
    print('请先安装 aiohttp: pip install aiohttp')
    sys.exit(1)

BASE = Path(__file__).parent
OUTPUT_FILE = BASE / 'test_all_apis_result.json'

# ── 接口 URL ──
PDD_ORDER_LATITUDE_URL = 'https://mms.pinduoduo.com/latitude/order/userAllOrder'
PDD_ORDER_FALLBACK_URL = 'https://mms.pinduoduo.com/mangkhut/mms/recentOrderList'
PDD_FOOTPRINT_URL = 'https://mms.pinduoduo.com/latitude/goods/singleRecommendGoods'
PDD_MMS_BASE = 'https://mms.pinduoduo.com'

# ── 颜色输出 ──
GREEN = '\033[32m'
YELLOW = '\033[33m'
RED = '\033[31m'
BLUE = '\033[34m'
CYAN = '\033[36m'
RESET = '\033[0m'

def ok(s):   return f'{GREEN}{s}{RESET}'
def warn(s): return f'{YELLOW}{s}{RESET}'
def err(s):  return f'{RED}{s}{RESET}'
def info(s): return f'{CYAN}{s}{RESET}'
def ws(s):   return f'{BLUE}{s}{RESET}'

def _log(tag, msg, color=None):
    color_fn = {
        'ok': ok, 'warn': warn, 'err': err, 'info': info, 'ws': ws,
    }.get(tag, lambda x: x)
    print(color_fn(f'[{tag.upper():6s}] {msg}'))

def _is_redirected(url: str) -> bool:
    return '/other/404' in url or '__from=' in url or 'login' in url.lower()

def _build_headers(cookies: dict) -> dict:
    cookie_str = '; '.join(f'{k}={v}' for k, v in cookies.items())
    return {
        'Cookie': cookie_str,
        'User-Agent': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
            '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        ),
        'Referer': 'https://mms.pinduoduo.com/',
        'Content-Type': 'application/json',
        'Origin': 'https://mms.pinduoduo.com',
    }


# ── Cookie 读取函数 ──

def _load_cookies_from_json(path: str) -> dict:
    """从 JSON 文件读取 cookies（支持列表和字典格式）"""
    with open(path, encoding='utf-8') as f:
        data = json.load(f)
    if isinstance(data, dict):
        return data
    if isinstance(data, list):
        result = {}
        for item in data:
            if isinstance(item, dict) and 'name' in item and 'value' in item:
                result[item['name']] = item['value']
        return result
    return {}


def _load_cookies_from_sqlite(profile_dir: Path) -> dict:
    """从 Chromium Cookies SQLite 文件读取 cookies（仅读取 pinduoduo 域名的 cookie）"""
    cookies_file = profile_dir / 'Cookies'
    if not cookies_file.exists():
        # 可能在 Default 子目录
        cookies_file = profile_dir / 'Default' / 'Cookies'
    if not cookies_file.exists():
        return {}
    import tempfile, shutil
    # 拷贝一份再读（避免文件锁）
    fd, tmp_path = tempfile.mkstemp(suffix='.sqlite')
    import os
    os.close(fd)
    tmp = Path(tmp_path)
    try:
        shutil.copy2(cookies_file, tmp)
        conn = sqlite3.connect(str(tmp))
        cur = conn.cursor()
        try:
            cur.execute(
                "SELECT name, value, encrypted_value, host_key "
                "FROM cookies WHERE host_key LIKE '%pinduoduo%' OR host_key LIKE '%yangkeduo%'"
            )
            rows = cur.fetchall()
        except sqlite3.OperationalError:
            rows = []
        conn.close()
        result = {}
        for name, value, enc_value, host in rows:
            if value:
                result[name] = value
            elif enc_value:
                # 尝试 Linux 解密（简单 AES-CBC with peanuts key）
                try:
                    decrypted = _decrypt_cookie_linux(enc_value)
                    if decrypted:
                        result[name] = decrypted
                except Exception:
                    pass
        return result
    finally:
        try:
            tmp.unlink()
        except Exception:
            pass


def _decrypt_cookie_linux(enc_value: bytes) -> Optional[str]:
    """Linux Chromium cookie 解密（AES-CBC，密钥=peanuts）"""
    try:
        from Crypto.Cipher import AES
        import hashlib
        # v10 header: b'v10' prefix
        if enc_value[:3] == b'v10':
            enc_value = enc_value[3:]
        # PBKDF2 from password 'peanuts'
        password = b'peanuts'
        salt = b'saltysalt'
        iv = b' ' * 16
        key = hashlib.pbkdf2_hmac('sha1', password, salt, 1, 16)
        cipher = AES.new(key, AES.MODE_CBC, IV=iv)
        decrypted = cipher.decrypt(enc_value)
        # Remove PKCS7 padding
        pad_len = decrypted[-1]
        decrypted = decrypted[:-pad_len]
        return decrypted.decode('utf-8', errors='ignore')
    except Exception:
        return None


def _load_cookies_from_config() -> dict:
    """从 pdd_config.json 读取 cookies"""
    config_file = BASE / 'pdd_config.json'
    if not config_file.exists():
        return {}
    try:
        with open(config_file, encoding='utf-8') as f:
            cfg = json.load(f)
        # 支持多种结构
        cookies = cfg.get('cookies') or cfg.get('cookie') or {}
        if isinstance(cookies, str):
            # 可能是 cookie 字符串
            result = {}
            for part in cookies.split(';'):
                part = part.strip()
                if '=' in part:
                    k, v = part.split('=', 1)
                    result[k.strip()] = v.strip()
            return result
        if isinstance(cookies, dict):
            return cookies
        if isinstance(cookies, list):
            result = {}
            for item in cookies:
                if isinstance(item, dict) and 'name' in item:
                    result[item['name']] = item.get('value', '')
            return result
        # Try shops
        shops = cfg.get('shops') or []
        for shop in shops:
            ck = shop.get('cookies') or {}
            if isinstance(ck, dict) and ck:
                return ck
    except Exception:
        pass
    return {}


def load_cookies(cookies_file: Optional[str] = None) -> dict:
    """
    按优先级加载 cookies：
    1. cookies_file 参数（JSON 文件路径）
    2. browser_data/ 目录下第一个子目录的 Chromium Cookies SQLite 文件
    3. pdd_config.json 里的 cookies 字段
    """
    # 1. 命令行指定的 cookies 文件
    if cookies_file:
        try:
            cookies = _load_cookies_from_json(cookies_file)
            if cookies:
                print(info(f'[cookies] 从 {cookies_file} 读取到 {len(cookies)} 个 cookies'))
                return cookies
        except Exception as e:
            print(warn(f'[cookies] 读取 {cookies_file} 失败: {e}'))

    # 2. browser_data/ 目录下的 Chromium profile
    browser_data = BASE / 'browser_data'
    if browser_data.exists():
        profiles = sorted([p for p in browser_data.iterdir() if p.is_dir()])
        for profile in profiles:
            try:
                cookies = _load_cookies_from_sqlite(profile)
                if cookies:
                    pdd_keys = [k for k in cookies if 'api' in k.lower() or len(k) > 5]
                    print(info(f'[cookies] 从 {profile.name} 读取到 {len(cookies)} 个 cookies'))
                    return cookies
            except Exception as e:
                print(warn(f'[cookies] 读取 {profile.name} 失败: {e}'))

    # 3. pdd_config.json
    try:
        cookies = _load_cookies_from_config()
        if cookies:
            print(info(f'[cookies] 从 pdd_config.json 读取到 {len(cookies)} 个 cookies'))
            return cookies
    except Exception as e:
        print(warn(f'[cookies] 读取 pdd_config.json 失败: {e}'))

    print(err('[cookies] 未找到 cookies！请使用 --cookies-file 参数指定'))
    return {}


# ── HTTP 接口测试 ──

ORDER_COMBINATIONS = [
    {
        'name': 'latitude_uid_only',
        'url': PDD_ORDER_LATITUDE_URL,
        'payload_fn': lambda uid: {'uid': str(uid), 'pageSize': 10, 'pageNum': 1},
    },
    {
        'name': 'latitude_uid_time',
        'url': PDD_ORDER_LATITUDE_URL,
        'payload_fn': lambda uid: {
            'uid': str(uid), 'pageSize': 10, 'pageNum': 1,
            'startTime': int(time.time()) - 180 * 86400, 'endTime': int(time.time()),
        },
    },
    {
        'name': 'latitude_buyerUid',
        'url': PDD_ORDER_LATITUDE_URL,
        'payload_fn': lambda uid: {'buyerUid': str(uid), 'pageSize': 10, 'pageNum': 1},
    },
    {
        'name': 'mangkhut_buyerUid',
        'url': PDD_ORDER_FALLBACK_URL,
        'payload_fn': lambda uid: {
            'buyerUid': str(uid), 'pageSize': 10, 'pageNumber': 1,
            'orderType': 0, 'afterSaleType': 0, 'remarkStatus': -1,
            'groupStartTime': int(time.time()) - 7 * 86400, 'groupEndTime': int(time.time()),
        },
    },
]

CANDIDATE_ORDER_FIELDS = (
    'orderList', 'orders', 'list', 'items', 'data', 'records',
    'orderSnList', 'orderInfoList', 'orderVOList', 'orderDetailList',
    'content', 'rows', 'orderInfos',
)

def _extract_orders(data: dict) -> tuple:
    """返回 (field_name, orders_list)"""
    result = data.get('result') or data.get('data') or {}
    if isinstance(result, list):
        return ('result', result)
    if isinstance(result, dict):
        for field in CANDIDATE_ORDER_FIELDS:
            val = result.get(field)
            if val and isinstance(val, list):
                return (field, val)
    return ('', [])


async def test_order_interface(session: aiohttp.ClientSession, name: str, url: str,
                               payload: dict, headers: dict, results: dict):
    print(f'\n[HTTP] --- 订单接口 [{name}] URL={url.split("pinduoduo.com/")[1]} ---')
    try:
        async with session.post(url, json=payload, headers=headers,
                                timeout=aiohttp.ClientTimeout(total=10)) as resp:
            final_url = str(resp.url)
            http_status = resp.status
            print(f'[HTTP]   HTTP状态: {http_status}')
            if _is_redirected(final_url):
                print(warn(f'[HTTP]   ❌ 被重定向（session过期）: {final_url}'))
                results[name] = {'status': 'redirected', 'url': final_url}
                return
            if http_status != 200:
                print(err(f'[HTTP]   ❌ 非200状态码: {http_status}'))
                results[name] = {'status': 'error', 'http_status': http_status}
                return
            try:
                data = await resp.json(content_type=None)
            except Exception as e:
                print(err(f'[HTTP]   ❌ 响应非JSON: {e}'))
                results[name] = {'status': 'parse_error'}
                return

        success = data.get('success')
        print(f'[HTTP]   success={success}')
        result_obj = data.get('result') or data.get('data') or {}
        result_keys = list(result_obj.keys()) if isinstance(result_obj, dict) else []
        print(f'[HTTP]   result keys: {result_keys}')

        field, orders = _extract_orders(data)
        if orders:
            print(ok(f'[OK]     ✅ 找到订单！字段=\'{field}\' 数量={len(orders)}'))
            print(ok(f'[OK]     首条订单号: {orders[0].get("orderSn") or orders[0].get("order_sn") or "N/A"}'))
            results[name] = {
                'status': 'ok', 'field': field, 'count': len(orders),
                'first_order_sn': orders[0].get('orderSn') or orders[0].get('order_sn') or '',
                'first_order_keys': list(orders[0].keys()) if orders[0] else [],
            }
        else:
            print(warn('[WARN]   ❌ 未找到订单列表'))
            print(f'[WARN]      已尝试字段: {CANDIDATE_ORDER_FIELDS}')
            results[name] = {
                'status': 'empty', 'success': success,
                'result_keys': result_keys,
                'raw_result': str(result_obj)[:300],
            }
    except Exception as e:
        print(err(f'[HTTP]   ❌ 异常: {e}'))
        results[name] = {'status': 'exception', 'error': str(e)}


async def test_footprint_interface(session: aiohttp.ClientSession, fp_type: int,
                                   buyer_id: str, headers: dict, results: dict):
    name = f'footprint_type_{fp_type}'
    payload = {
        'type': fp_type, 'uid': str(buyer_id),
        'pageSize': 5, 'pageNum': 1,
    }
    print(f'\n[HTTP] --- 浏览足迹 type={fp_type} ---')
    try:
        async with session.post(PDD_FOOTPRINT_URL, json=payload, headers=headers,
                                timeout=aiohttp.ClientTimeout(total=8)) as resp:
            http_status = resp.status
            print(f'[HTTP]   HTTP状态: {http_status}')
            final_url = str(resp.url)
            if _is_redirected(final_url):
                print(warn(f'[HTTP]   ❌ 被重定向（session过期）'))
                results[name] = {'status': 'redirected'}
                return
            if http_status != 200:
                results[name] = {'status': 'error', 'http_status': http_status}
                return
            try:
                data = await resp.json(content_type=None)
            except Exception as e:
                print(err(f'[HTTP]   ❌ 响应非JSON: {e}'))
                results[name] = {'status': 'parse_error'}
                return

        success = data.get('success')
        print(f'[HTTP]   success={success}')
        result_obj = data.get('result') or data.get('data') or {}
        result_keys = list(result_obj.keys()) if isinstance(result_obj, dict) else []
        print(f'[HTTP]   result keys: {result_keys}')

        if isinstance(result_obj, list):
            first = result_obj[0] if result_obj else {}
            result_obj = first if isinstance(first, dict) else {}

        goods_list = result_obj.get('goodsList') or result_obj.get('list') or []
        if goods_list:
            print(ok(f'[OK]     ✅ goodsList 数量={len(goods_list)}'))
            g = goods_list[0]
            gid = g.get('goodsId') or g.get('goods_id') or ''
            gname = g.get('goodsName') or g.get('goods_name') or ''
            print(ok(f'[OK]     首条商品: id={gid} name={gname}'))
            results[name] = {'status': 'ok', 'count': len(goods_list), 'first_goods_id': str(gid), 'first_goods_name': gname}
        else:
            print(warn(f'[WARN]   ❌ goodsList/list 为空'))
            print(f'[DIAG]   完整result（前500字符）: {str(result_obj)[:500]}')
            results[name] = {'status': 'empty', 'success': success, 'result': str(result_obj)[:300]}
    except Exception as e:
        print(err(f'[HTTP]   ❌ 异常: {e}'))
        results[name] = {'status': 'exception', 'error': str(e)}


async def run_http_tests(buyer_id: str, cookies: dict) -> dict:
    """运行所有 HTTP 接口测试"""
    headers = _build_headers(cookies)
    results = {}

    print(f'\n{"="*60}')
    print(f'  模块A：订单接口测试（buyer_id={buyer_id}）')
    print(f'{"="*60}')

    async with aiohttp.ClientSession() as session:
        for combo in ORDER_COMBINATIONS:
            payload = combo['payload_fn'](buyer_id)
            await test_order_interface(
                session, combo['name'], combo['url'], payload, headers, results
            )

    print(f'\n{"="*60}')
    print(f'  模块B：浏览足迹接口测试（buyer_id={buyer_id}）')
    print(f'{"="*60}')

    async with aiohttp.ClientSession() as session:
        for fp_type in range(6):
            await test_footprint_interface(session, fp_type, buyer_id, headers, results)

    return results


# ── WebSocket 监听 ──

GOODS_KEYWORDS = {'biz_context', 'bizContext', 'sourceGoods', 'source_goods', 'goodsId',
                  'goods_id', 'currentGoods', 'recommendGoods', 'linkGoods', 'goodsName'}


def _has_goods_info(raw: str) -> bool:
    """检查 WS 帧是否含有商品相关字段"""
    return any(kw in raw for kw in GOODS_KEYWORDS)


def _extract_goods_from_biz(biz: dict) -> Optional[dict]:
    """从 biz 对象提取商品信息"""
    goods_id = str(
        biz.get('goodsId') or biz.get('goods_id') or biz.get('sourceGoodsId') or ''
    )
    goods_name = str(
        biz.get('goodsName') or biz.get('goods_name') or biz.get('sourceGoodsName') or ''
    )

    for field in ('sourceGoods', 'source_goods', 'currentGoods', 'recommendGoods',
                  'linkGoods', 'goods'):
        obj = biz.get(field)
        if isinstance(obj, dict):
            goods_id = goods_id or str(obj.get('goodsId') or obj.get('goods_id') or '')
            goods_name = goods_name or str(obj.get('goodsName') or obj.get('goods_name') or '')

    ctx = biz.get('context')
    if isinstance(ctx, dict):
        nested = ctx.get('sourceGoods') or {}
        if isinstance(nested, dict):
            goods_id = goods_id or str(nested.get('goodsId') or nested.get('goods_id') or '')
            goods_name = goods_name or str(nested.get('goodsName') or nested.get('goods_name') or '')

    if goods_id or goods_name:
        return {'goods_id': goods_id, 'goods_name': goods_name}
    return None


async def run_ws_monitor(timeout_sec: int = 30) -> list:
    """使用 playwright 监听 WebSocket 消息，捕获商品信息（需要 playwright 已安装）"""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print(err('[WS] playwright 未安装，跳过 WS 监听。安装：pip install playwright && playwright install chromium'))
        return []

    captured = []
    all_frames = []

    print(f'\n{"="*60}')
    print(f'  模块C：WebSocket 实时监听（{timeout_sec}秒）')
    print(f'{"="*60}')
    print(info(f'[WS] 将打开浏览器，请在 {timeout_sec} 秒内点击买家会话以触发 WS 消息'))

    # 寻找已有的 browser_data profile
    profile_path = None
    browser_data = BASE / 'browser_data'
    if browser_data.exists():
        profiles = sorted([p for p in browser_data.iterdir() if p.is_dir()])
        if profiles:
            profile_path = str(profiles[0])

    async with async_playwright() as p:
        launch_kw = {}
        if profile_path:
            context = await p.chromium.launch_persistent_context(
                profile_path,
                headless=False,
                args=['--no-sandbox'],
            )
            page = context.pages[0] if context.pages else await context.new_page()
        else:
            browser = await p.chromium.launch(headless=False, args=['--no-sandbox'])
            context = await browser.new_context()
            page = await context.new_page()

        ws_messages = []

        def _on_ws(ws_conn):
            def _on_frame(frame):
                payload = frame.payload if isinstance(frame.payload, str) else ''
                if payload:
                    ws_messages.append(payload)
            ws_conn.on('framereceived', _on_frame)
            ws_conn.on('framesent', _on_frame)

        page.on('websocket', _on_ws)

        try:
            await page.goto('https://mms.pinduoduo.com/home', timeout=15000)
        except Exception:
            pass

        print(info(f'[WS] 请在 {timeout_sec} 秒内操作浏览器（点击买家会话）...'))
        start = time.time()
        while time.time() - start < timeout_sec:
            await asyncio.sleep(5)
            elapsed = int(time.time() - start)
            print(info(f'[WS]   已等待 {elapsed}s，收到 {len(ws_messages)} 条WS消息'))

            # 取出积累的消息并清空，避免下次重复处理
            pending = ws_messages[:]
            ws_messages.clear()
            for raw in pending:
                if not _has_goods_info(raw):
                    continue
                try:
                    msg = json.loads(raw)
                except Exception:
                    continue
                if not isinstance(msg, dict):
                    continue

                # 遍历所有可能的 biz 字段
                goods = None
                for biz_key in ('push_biz_context', 'bizContext', 'biz_context',
                                'pushBizContext', 'context', 'msgContext'):
                    biz_obj = msg.get(biz_key)
                    if isinstance(biz_obj, dict) and biz_obj:
                        goods = _extract_goods_from_biz(biz_obj)
                        if goods:
                            break

                # 也检查 message 子对象
                inner = msg.get('message') or {}
                if isinstance(inner, dict) and not goods:
                    for biz_key in ('push_biz_context', 'bizContext', 'biz_context'):
                        biz_obj = inner.get(biz_key)
                        if isinstance(biz_obj, dict) and biz_obj:
                            goods = _extract_goods_from_biz(biz_obj)
                            if goods:
                                break

                if goods:
                    print(ws(f'[WS] 🔵 捕获到商品信息: {goods}'))
                    captured.append({'goods': goods, 'raw_snippet': raw[:300]})
                else:
                    all_frames.append(raw[:200])

        await context.close()

    if captured:
        print(ok(f'[WS] ✅ 共捕获到 {len(captured)} 条含商品信息的 WS 消息'))
    else:
        print(warn(f'[WS] ⚠️ 未捕获到商品信息（共收到 {len(all_frames)} 条不含商品的 WS 消息）'))
        print(info('[WS] 说明：浏览足迹只在买家正在浏览商品时才会出现在 bizContext 中'))

    return captured


# ── 主函数 ──

def print_summary(http_results: dict, ws_results: list):
    print(f'\n{"="*60}')
    print('  === 接口诊断报告 ===')
    print(f'{"="*60}')

    # 订单接口汇总
    print(info('\n【订单接口】'))
    for combo in ORDER_COMBINATIONS:
        name = combo['name']
        r = http_results.get(name, {})
        if r.get('status') == 'ok':
            print(ok(f'  ✅ {name}: 字段=\'{r.get("field")}\' 数量={r.get("count")} 首条={r.get("first_order_sn")}'))
        elif r.get('status') == 'redirected':
            print(warn(f'  ❌ {name}: 被重定向（session过期）'))
        else:
            print(err(f'  ❌ {name}: {r.get("status")} success={r.get("success")}'))

    # 浏览足迹汇总
    print(info('\n【浏览足迹 HTTP 接口】'))
    for fp_type in range(6):
        name = f'footprint_type_{fp_type}'
        r = http_results.get(name, {})
        if r.get('status') == 'ok':
            print(ok(f'  ✅ type={fp_type}: 商品数={r.get("count")}'))
        elif r.get('status') == 'redirected':
            print(warn(f'  ❌ type={fp_type}: 被重定向'))
        else:
            print(warn(f'  ⚠️ type={fp_type}: {r.get("status")} success={r.get("success")}'))

    # WS 汇总
    print(info('\n【WebSocket 浏览足迹捕获】'))
    if ws_results:
        for item in ws_results:
            print(ok(f'  ✅ {item["goods"]}'))
    else:
        print(warn('  ⚠️ 未捕获到商品信息（买家未浏览商品，或WS监听时间不足）'))

    # 修复建议
    print(info('\n【修复建议】'))
    order_ok = any(
        http_results.get(c['name'], {}).get('status') == 'ok'
        for c in ORDER_COMBINATIONS
    )
    if order_ok:
        best = next(
            c['name'] for c in ORDER_COMBINATIONS
            if http_results.get(c['name'], {}).get('status') == 'ok'
        )
        print(ok(f'  ✅ 订单接口正常：使用 {best} 方式'))
    else:
        print(err('  ❌ 订单接口全部失败，请检查 cookies 是否有效'))

    footprint_ok = any(
        http_results.get(f'footprint_type_{t}', {}).get('status') == 'ok'
        for t in range(6)
    )
    if not footprint_ok:
        print(warn('  ⚠️ 浏览足迹 HTTP 接口无效，依赖 WebSocket 实时捕获是正确方向'))
        print(info('     → 确保 pdd_message.py 的 _extract_source_goods_from_biz 覆盖所有字段路径'))
        print(info('     → 确保买家进入会话时的消息（is_enter_session=True）不被过滤'))


async def main():
    parser = argparse.ArgumentParser(description='拼多多接口全面诊断脚本')
    parser.add_argument('--buyer-id', type=str, default='', help='直接指定买家UID')
    parser.add_argument('--ws-only', action='store_true', help='仅做 WebSocket 监听')
    parser.add_argument('--cookies-file', type=str, default='', help='指定 cookies JSON 文件路径')
    parser.add_argument('--ws-timeout', type=int, default=30, help='WS 监听超时（秒），默认30')
    args = parser.parse_args()

    all_results = {'timestamp': time.strftime('%Y-%m-%d %Human:%M:%S'), 'http': {}, 'ws': []}
    all_results['timestamp'] = time.strftime('%Y-%m-%d %H:%M:%S')

    if args.ws_only:
        ws_results = await run_ws_monitor(args.ws_timeout)
        all_results['ws'] = ws_results
        print_summary({}, ws_results)
    else:
        # 先加载 cookies
        cookies = load_cookies(args.cookies_file or None)
        if not cookies:
            print(err('[ERROR] 无法加载 cookies，HTTP 测试跳过'))
            all_results['http'] = {'error': 'no cookies'}
        else:
            buyer_id = args.buyer_id
            if not buyer_id:
                print(info('[INFO] 未指定 --buyer-id，将通过 WS 自动捕获'))
            else:
                # 先做 HTTP 测试
                http_results = await run_http_tests(buyer_id, cookies)
                all_results['http'] = http_results

        # WS 监听（除非只指定了 buyer_id 且有 cookies）
        print(f'\n[INFO] 即将进行 WebSocket 监听（{args.ws_timeout}s），可按 Ctrl+C 跳过')
        try:
            ws_results = await run_ws_monitor(args.ws_timeout)
        except KeyboardInterrupt:
            print(warn('[WS] 用户跳过 WS 监听'))
            ws_results = []
        all_results['ws'] = ws_results

        if 'http' in all_results and all_results['http'] and all_results['http'] != {'error': 'no cookies'}:
            print_summary(all_results['http'], ws_results)

    # 保存结果
    try:
        with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
            json.dump(all_results, f, ensure_ascii=False, indent=2)
        print(info(f'\n[INFO] 完整结果已保存到 {OUTPUT_FILE}'))
    except Exception as e:
        print(warn(f'[WARN] 保存结果失败: {e}'))


if __name__ == '__main__':
    asyncio.run(main())
