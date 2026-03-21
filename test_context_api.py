# -*- coding: utf-8 -*-
"""
test_context_api.py — 订单和浏览足迹接口全面诊断脚本

使用方法：
    python test_context_api.py

功能：
  1. 使用已有的 Chromium profile（browser_data/default 或 browser_data/sniff_profile）
  2. 等待用户打开拼多多聊天页面并点击买家会话
  3. 从 WebSocket 帧实时捕获 buyer_id
  4. 用页面 cookies 测试所有订单/足迹接口，打印完整响应结构
  5. 把所有响应（完整JSON）保存到 test_context_result.json
  6. 打印诊断报告
"""
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any, Optional

BASE = Path(__file__).parent
OUTPUT_FILE = BASE / "test_context_result.json"

# ---------- 颜色前缀（与 sniff_pdd_chat.py 风格一致）----------
_USE_COLOR = sys.platform != "win32" or "ANSICON" in __import__("os").environ


def _c(code: str, text: str) -> str:
    if _USE_COLOR:
        return f"\033[{code}m{text}\033[0m"
    return text


def _http(text: str) -> str:
    return _c("36", f"[HTTP] {text}")       # 青色


def _info(text: str) -> str:
    return _c("34", f"[INFO] {text}")       # 蓝色


def _warn(text: str) -> str:
    return _c("31", f"[WARN] {text}")       # 红色


def _ok(text: str) -> str:
    return _c("32", f"[OK]   {text}")       # 绿色


def _diag_line(text: str) -> str:
    return _c("33", f"[DIAG] {text}")       # 黄色


def _ts() -> str:
    return time.strftime("%H:%M:%S")


def _dump(obj: Any) -> str:
    """完整 JSON 字符串，不截断"""
    return json.dumps(obj, ensure_ascii=False, indent=2)


# ---------- 接口 URL ----------
PDD_ORDER_LATITUDE_URL = "https://mms.pinduoduo.com/latitude/order/userAllOrder"
PDD_ORDER_FALLBACK_URL = "https://mms.pinduoduo.com/mangkhut/mms/recentOrderList"
PDD_FOOTPRINT_URL = "https://mms.pinduoduo.com/latitude/goods/singleRecommendGoods"

# 用于检查 cookies 是否失效导致的重定向
_REDIRECT_MARKERS = ("/other/404", "__from=")

# 全部订单字段候选
_ORDER_FIELDS = (
    "orderList", "list", "orders", "items", "data", "records",
    "orderSnList", "orderInfoList", "orderVOList", "orderDetailList",
    "content", "rows", "orderInfos",
)

# 全局状态
captured_buyer_id: Optional[str] = None
captured_cookies: dict = {}
all_results: dict = {
    "captured_at": "",
    "buyer_id": "",
    "order_latitude": {},
    "order_fallback": {},
    "footprint_type1": {},
    "footprint_type2": {},
    "footprint_type3": {},
    "ws_footprint": {},
    "diagnosis": {},
}


# ================================================================
# WebSocket 帧解析 — 实时捕获 buyer_id
# ================================================================

def _get_ws_payload(frame: Any) -> str:
    if isinstance(frame, (bytes, bytearray)):
        try:
            return frame.decode("utf-8", errors="replace")
        except Exception:
            return ""
    if isinstance(frame, str):
        return frame
    if isinstance(frame, dict):
        return frame.get("payload", "")
    return str(frame)


def _handle_ws_frame(raw_payload: str) -> None:
    global captured_buyer_id
    try:
        msg = json.loads(raw_payload)
    except Exception:
        return
    if not isinstance(msg, dict):
        return

    inner = msg.get("message") or msg
    from_info = inner.get("from") or {}
    role = from_info.get("role", "")
    uid = str(from_info.get("uid") or inner.get("buyerId") or inner.get("buyer_id") or "")

    if uid and role in ("user", "buyer") and not captured_buyer_id:
        captured_buyer_id = uid
        print(_ok(f"[{_ts()}] 从WebSocket捕获到 buyer_id: {uid}"))
        return

    # 也尝试从 push_biz_context / bizContext 里找 uid
    for biz_key in ("push_biz_context", "bizContext", "biz_context"):
        biz = inner.get(biz_key) or msg.get(biz_key)
        if isinstance(biz, dict):
            uid2 = str(biz.get("uid") or biz.get("buyerId") or biz.get("buyer_id") or "")
            if uid2 and not captured_buyer_id:
                captured_buyer_id = uid2
                print(_ok(f"[{_ts()}] 从WS biz上下文捕获到 buyer_id: {uid2}"))
                return


# ================================================================
# HTTP 接口测试
# ================================================================

def _is_redirected(url: str) -> bool:
    return any(m in url for m in _REDIRECT_MARKERS)


def _build_headers(cookies: dict) -> dict:
    cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
    return {
        "Cookie": cookie_str,
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Referer": "https://mms.pinduoduo.com/",
        "Content-Type": "application/json",
        "Origin": "https://mms.pinduoduo.com",
    }


def _find_order_list(result: Any) -> tuple[Optional[list], Optional[str]]:
    """
    从 result（dict 或 list）中尝试所有候选字段提取订单列表。
    返回 (order_list_or_None, field_name_or_None)
    """
    if isinstance(result, list):
        return result, "(result itself is list)"
    if isinstance(result, dict):
        for field in _ORDER_FIELDS:
            val = result.get(field)
            if val and isinstance(val, list):
                return val, field
    return None, None


async def _test_order_latitude(buyer_id: str, cookies: dict) -> dict:
    """测试 latitude/order/userAllOrder 接口"""
    print()
    print(_http(f"=== 测试1a：latitude/order/userAllOrder (buyer_id={buyer_id}) ==="))
    payload = {"uid": str(buyer_id), "pageSize": 10, "pageNum": 1}
    result_entry: dict = {
        "url": PDD_ORDER_LATITUDE_URL,
        "payload": payload,
        "status": None,
        "redirected": False,
        "response": None,
        "result_keys": None,
        "found_field": None,
        "order_count": 0,
        "error": None,
    }
    try:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.post(
                PDD_ORDER_LATITUDE_URL,
                json=payload,
                headers=_build_headers(cookies),
                timeout=aiohttp.ClientTimeout(total=12),
            ) as resp:
                result_entry["status"] = resp.status
                final_url = str(resp.url)
                if _is_redirected(final_url):
                    result_entry["redirected"] = True
                    print(_warn(f"  接口被重定向（session过期）: {final_url}"))
                    return result_entry
                print(_http(f"  HTTP状态: {resp.status}"))
                try:
                    data = await resp.json(content_type=None)
                except Exception as e:
                    result_entry["error"] = f"JSON解析失败: {e}"
                    print(_warn(f"  响应非JSON: {e}"))
                    return result_entry

        result_entry["response"] = data
        success = data.get("success")
        print(_http(f"  success={success}"))

        # 打印完整 key 列表
        r = data.get("result") or data.get("data") or {}
        if isinstance(r, dict):
            result_entry["result_keys"] = list(r.keys())
            print(_http(f"  result 的完整 key 列表: {list(r.keys())}"))
        elif isinstance(r, list):
            result_entry["result_keys"] = f"(list, len={len(r)})"
            print(_http(f"  result 是列表，长度={len(r)}"))
        else:
            result_entry["result_keys"] = type(r).__name__
            print(_http(f"  result 类型: {type(r).__name__}"))

        # 尝试所有候选字段
        order_list, found_field = _find_order_list(r)
        if order_list:
            result_entry["found_field"] = found_field
            result_entry["order_count"] = len(order_list)
            print(_ok(f"  ✅ 找到订单列表！字段名='{found_field}' 数量={len(order_list)}"))
            if order_list:
                first = order_list[0]
                print(_ok(f"  首条订单字段: {list(first.keys()) if isinstance(first, dict) else type(first).__name__}"))
        else:
            print(_warn(f"  ❌ 所有候选字段均未找到订单列表"))
            print(_warn(f"     已尝试字段: {_ORDER_FIELDS}"))
            if success:
                print(_diag_line(f"  完整 result（前500字符）:\n{json.dumps(r, ensure_ascii=False, indent=2)[:500]}"))

    except Exception as e:
        result_entry["error"] = str(e)
        print(_warn(f"  异常: {e}"))
    return result_entry


async def _test_order_fallback(buyer_id: str, cookies: dict) -> dict:
    """测试 mangkhut/mms/recentOrderList 接口"""
    print()
    print(_http(f"=== 测试1b：mangkhut/mms/recentOrderList (buyer_id={buyer_id}) ==="))
    now = int(time.time())
    payload = {
        "orderType": 0,
        "afterSaleType": 0,
        "remarkStatus": -1,
        "urgeShippingStatus": -1,
        "groupStartTime": now - 7 * 86400,
        "groupEndTime": now,
        "pageNumber": 1,
        "pageSize": 10,
        "hideRegionBlackDelayShipping": False,
        "mobileMarkSearch": False,
        "buyerUid": str(buyer_id),
    }
    result_entry: dict = {
        "url": PDD_ORDER_FALLBACK_URL,
        "payload": payload,
        "status": None,
        "redirected": False,
        "response": None,
        "result_keys": None,
        "found_field": None,
        "order_count": 0,
        "error": None,
    }
    try:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.post(
                PDD_ORDER_FALLBACK_URL,
                json=payload,
                headers=_build_headers(cookies),
                timeout=aiohttp.ClientTimeout(total=12),
            ) as resp:
                result_entry["status"] = resp.status
                final_url = str(resp.url)
                if _is_redirected(final_url):
                    result_entry["redirected"] = True
                    print(_warn(f"  接口被重定向（session过期）: {final_url}"))
                    return result_entry
                print(_http(f"  HTTP状态: {resp.status}"))
                try:
                    data = await resp.json(content_type=None)
                except Exception as e:
                    result_entry["error"] = f"JSON解析失败: {e}"
                    print(_warn(f"  响应非JSON: {e}"))
                    return result_entry

        result_entry["response"] = data
        success = data.get("success")
        print(_http(f"  success={success}"))

        r = data.get("result") or data.get("data") or {}
        if isinstance(r, dict):
            result_entry["result_keys"] = list(r.keys())
            print(_http(f"  result 的完整 key 列表: {list(r.keys())}"))
        elif isinstance(r, list):
            result_entry["result_keys"] = f"(list, len={len(r)})"
            print(_http(f"  result 是列表，长度={len(r)}"))
        else:
            result_entry["result_keys"] = type(r).__name__
            print(_http(f"  result 类型: {type(r).__name__}"))

        order_list, found_field = _find_order_list(r)
        if order_list:
            result_entry["found_field"] = found_field
            result_entry["order_count"] = len(order_list)
            print(_ok(f"  ✅ 找到订单列表！字段名='{found_field}' 数量={len(order_list)}"))
            if order_list:
                first = order_list[0]
                print(_ok(f"  首条订单字段: {list(first.keys()) if isinstance(first, dict) else type(first).__name__}"))
        else:
            print(_warn(f"  ❌ 所有候选字段均未找到订单列表"))
            print(_warn(f"     已尝试字段: {_ORDER_FIELDS}"))
            if success:
                print(_diag_line(f"  完整 result（前500字符）:\n{json.dumps(r, ensure_ascii=False, indent=2)[:500]}"))

    except Exception as e:
        result_entry["error"] = str(e)
        print(_warn(f"  异常: {e}"))
    return result_entry


async def _test_footprint(buyer_id: str, cookies: dict, fp_type: int) -> dict:
    """测试 latitude/goods/singleRecommendGoods 接口（指定 type 值）"""
    print()
    print(_http(f"=== 测试2（type={fp_type}）：latitude/goods/singleRecommendGoods ==="))
    payload = {
        "type": fp_type,
        "uid": str(buyer_id),
        "conversationId": "",
        "pageSize": 5,
        "pageNum": 1,
    }
    result_entry: dict = {
        "url": PDD_FOOTPRINT_URL,
        "payload": payload,
        "type": fp_type,
        "status": None,
        "redirected": False,
        "response": None,
        "result_keys": None,
        "goods_count": 0,
        "error": None,
    }
    try:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.post(
                PDD_FOOTPRINT_URL,
                json=payload,
                headers=_build_headers(cookies),
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                result_entry["status"] = resp.status
                final_url = str(resp.url)
                if _is_redirected(final_url):
                    result_entry["redirected"] = True
                    print(_warn(f"  接口被重定向（session过期）: {final_url}"))
                    return result_entry
                print(_http(f"  HTTP状态: {resp.status}"))
                try:
                    data = await resp.json(content_type=None)
                except Exception as e:
                    result_entry["error"] = f"JSON解析失败: {e}"
                    print(_warn(f"  响应非JSON: {e}"))
                    return result_entry

        result_entry["response"] = data
        success = data.get("success")
        print(_http(f"  success={success}"))

        r = data.get("result") or data.get("data") or {}
        if isinstance(r, list):
            result_entry["result_keys"] = f"(list, len={len(r)})"
            print(_http(f"  result 是列表，长度={len(r)}"))
            # singleRecommendGoods 可能返回列表，取第一个元素
            first_item = r[0] if r else {}
            if isinstance(first_item, dict):
                print(_http(f"  result[0] 的 key 列表: {list(first_item.keys())}"))
                goods_list = first_item.get("goodsList") or first_item.get("list") or []
                if goods_list:
                    result_entry["goods_count"] = len(goods_list)
                    print(_ok(f"  ✅ 找到商品列表！type={fp_type} 数量={len(goods_list)}"))
                    first_g = goods_list[0]
                    if isinstance(first_g, dict):
                        print(_ok(f"  首条商品字段: {list(first_g.keys())}"))
                else:
                    print(_warn(f"  ❌ result[0] 中 goodsList/list 为空"))
                    print(_diag_line(f"  result[0]（前300字符）:\n{json.dumps(first_item, ensure_ascii=False, indent=2)[:300]}"))
            else:
                print(_warn(f"  result[0] 类型: {type(first_item).__name__}"))
        elif isinstance(r, dict):
            result_entry["result_keys"] = list(r.keys())
            print(_http(f"  result 的完整 key 列表: {list(r.keys())}"))
            goods_list = r.get("goodsList") or r.get("list") or []
            if goods_list:
                result_entry["goods_count"] = len(goods_list)
                print(_ok(f"  ✅ 找到商品列表！type={fp_type} 数量={len(goods_list)}"))
                first_g = goods_list[0]
                if isinstance(first_g, dict):
                    print(_ok(f"  首条商品字段: {list(first_g.keys())}"))
            else:
                print(_warn(f"  ❌ goodsList/list 为空"))
                if success:
                    print(_diag_line(f"  完整 result（前300字符）:\n{json.dumps(r, ensure_ascii=False, indent=2)[:300]}"))
        else:
            result_entry["result_keys"] = type(r).__name__
            print(_http(f"  result 类型: {type(r).__name__}"))

    except Exception as e:
        result_entry["error"] = str(e)
        print(_warn(f"  异常: {e}"))
    return result_entry


async def _test_ws_footprint(buyer_id: str, cookies: dict) -> dict:
    """
    步骤4：实时监听 WebSocket，验证 source_goods / bizContext 字段能被正确捕获。
    重新打开浏览器，等待用户点击该买家会话，检测 WS 消息中的浏览足迹信息。
    """
    print()
    print(_http("=== 测试4：实时WS捕获浏览足迹（source_goods / bizContext）==="))
    print(_info("  该测试会重新打开浏览器，等待 WebSocket 消息以验证浏览足迹字段"))

    result_entry: dict = {
        "description": "实时WS捕获浏览足迹",
        "buyer_id": buyer_id,
        "source_goods_found": False,
        "source_goods": None,
        "biz_context_keys": None,
        "ws_messages_seen": 0,
        "error": None,
    }

    captured_goods: dict = {}
    ws_count = [0]

    def _handle_footprint_frame(raw: str) -> None:
        try:
            msg = json.loads(raw)
        except Exception:
            return
        if not isinstance(msg, dict):
            return

        ws_count[0] += 1
        inner = msg.get("message") or msg

        # 检查 push_biz_context / bizContext 中的商品信息
        for biz_key in ("push_biz_context", "bizContext", "biz_context"):
            biz = inner.get(biz_key) or msg.get(biz_key)
            if not isinstance(biz, dict):
                continue
            result_entry["biz_context_keys"] = list(biz.keys())
            # 提取商品字段
            goods_id = str(
                biz.get("goods_id") or biz.get("goodsId") or
                biz.get("sourceGoodsId") or ""
            )
            goods_name = str(
                biz.get("goods_name") or biz.get("goodsName") or
                biz.get("sourceGoodsName") or ""
            )
            goods_img = str(
                biz.get("goods_img") or biz.get("goodsImg") or
                biz.get("goodsImageUrl") or ""
            )
            # 从 sourceGoods 子对象提取
            source_obj = biz.get("sourceGoods") or biz.get("source_goods") or {}
            if isinstance(source_obj, dict):
                goods_id = goods_id or str(source_obj.get("goodsId") or source_obj.get("goods_id") or "")
                goods_name = goods_name or str(source_obj.get("goodsName") or source_obj.get("goods_name") or "")
                goods_img = goods_img or str(source_obj.get("goodsImg") or source_obj.get("thumbUrl") or "")
            if goods_id or goods_name:
                captured_goods["goods_id"] = goods_id
                captured_goods["goods_name"] = goods_name
                captured_goods["goods_img"] = goods_img
                print(_ok(f"  ✅ [{_ts()}] WS bizContext 中检测到浏览商品: id={goods_id} name={goods_name}"))

        # 检查 source_goods 顶层字段（经 pdd_message 解析后的格式）
        sg = inner.get("source_goods")
        if isinstance(sg, dict) and (sg.get("goods_id") or sg.get("goods_name") or
                                      sg.get("goodsId") or sg.get("goodsName")):
            gid = str(sg.get("goods_id") or sg.get("goodsId") or "")
            gname = str(sg.get("goods_name") or sg.get("goodsName") or "")
            if not captured_goods.get("goods_name") and not captured_goods.get("goods_id"):
                captured_goods["goods_id"] = gid
                captured_goods["goods_name"] = gname
                captured_goods["goods_img"] = str(sg.get("goods_img") or sg.get("goodsImg") or "")
            print(_ok(f"  ✅ [{_ts()}] WS source_goods 字段检测到浏览商品: id={gid} name={gname}"))

    try:
        from playwright.async_api import async_playwright

        candidate_profiles = []
        browser_data_dir = BASE / "browser_data"
        if browser_data_dir.exists():
            for p in browser_data_dir.iterdir():
                if p.is_dir():
                    candidate_profiles.append(p)

        user_data: Optional[Path] = None
        for p in candidate_profiles:
            if p.exists():
                user_data = p
                break

        if user_data is None:
            result_entry["error"] = "未找到 browser_data profile，跳过WS测试"
            print(_warn(f"  {result_entry['error']}"))
            return result_entry

        async with async_playwright() as pw:
            ctx2 = await pw.chromium.launch_persistent_context(
                str(user_data),
                headless=False,
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
                locale="zh-CN",
            )
            page2 = ctx2.pages[0] if ctx2.pages else await ctx2.new_page()

            def _on_ws2(ws) -> None:
                url = ws.url
                if "pinduoduo" not in url and "pdd" not in url.lower():
                    return
                ws.on("framesent", lambda f: _handle_footprint_frame(_get_ws_payload(f)))
                ws.on("framereceived", lambda f: _handle_footprint_frame(_get_ws_payload(f)))

            page2.on("websocket", _on_ws2)

            try:
                await page2.goto(
                    "https://mms.pinduoduo.com/chat-merchant/index.html#/",
                    timeout=30000,
                )
            except Exception:
                pass

            print()
            print(_c("1;33", ">>> 请点击买家会话（查看是否能捕获到 source_goods / bizContext）<<<"))
            print(_info("  最长等待 30 秒..."))

            for i in range(6):
                await asyncio.sleep(5)
                if captured_goods.get("goods_name") or captured_goods.get("goods_id"):
                    break
                print(_info(f"  [{_ts()}] 等待WS消息... ({(i + 1) * 5}s)，已收到 {ws_count[0]} 条WS消息"))

            await ctx2.close()

        result_entry["ws_messages_seen"] = ws_count[0]
        if captured_goods.get("goods_id") or captured_goods.get("goods_name"):
            result_entry["source_goods_found"] = True
            result_entry["source_goods"] = captured_goods
            print(_ok(f"  ✅ WS浏览足迹捕获成功: {captured_goods}"))
        else:
            print(_warn(f"  ⚠️ 未从WS消息捕获到商品信息（共收到 {ws_count[0]} 条WS消息）"))
            print(_info("  说明：浏览足迹只在买家正在浏览商品时才会出现在 bizContext 中"))
            print(_info("  如果买家没有正在浏览的商品，source_goods 为空是正常的"))

    except Exception as e:
        result_entry["error"] = str(e)
        print(_warn(f"  WS测试异常: {e}"))

    return result_entry


# ================================================================
# 诊断报告
# ================================================================

def _print_diagnosis(buyer_id: str, results: dict) -> dict:
    sep = "=" * 60
    print(f"\n{sep}")
    print("  === 接口诊断报告 ===")
    print(sep)

    diag: dict = {
        "buyer_id": buyer_id,
        "order_latitude_success": False,
        "order_latitude_field": None,
        "order_fallback_success": False,
        "order_fallback_field": None,
        "footprint_working_type": None,
        "footprint_goods_count": 0,
        "ws_footprint_captured": False,
        "recommendations": [],
    }

    # 订单接口 latitude
    lat = results.get("order_latitude", {})
    lat_success = (
        isinstance(lat.get("response"), dict)
        and lat["response"].get("success")
        and not lat.get("redirected")
    )
    if lat.get("found_field"):
        diag["order_latitude_success"] = True
        diag["order_latitude_field"] = lat["found_field"]
        print(_ok(f"  latitude 接口：✅ 成功，字段='{lat['found_field']}'，订单数={lat.get('order_count', 0)}"))
    elif lat.get("redirected"):
        print(_warn(f"  latitude 接口：❌ 被重定向（cookies 已失效）"))
        diag["recommendations"].append("cookies 已失效，需要重新登录拼多多客服端")
    elif not lat_success:
        err = lat.get("error") or ""
        resp = lat.get("response") or {}
        err_msg = resp.get("error_msg") or resp.get("errorMsg") or ""
        print(_warn(f"  latitude 接口：❌ 失败（{err or err_msg or '未知错误'}）"))
    else:
        print(_warn(f"  latitude 接口：⚠️ success=True 但未找到订单列表"))
        print(_diag_line(f"    result keys={lat.get('result_keys')}"))
        diag["recommendations"].append(
            f"latitude接口返回了数据但字段名未知，result keys={lat.get('result_keys')}，"
            f"需要在 _extract_orders() 中添加对应字段"
        )

    # 订单接口 fallback
    fb = results.get("order_fallback", {})
    fb_success = (
        isinstance(fb.get("response"), dict)
        and fb["response"].get("success")
        and not fb.get("redirected")
    )
    if fb.get("found_field"):
        diag["order_fallback_success"] = True
        diag["order_fallback_field"] = fb["found_field"]
        print(_ok(f"  fallback 接口：✅ 成功，字段='{fb['found_field']}'，订单数={fb.get('order_count', 0)}"))
    elif fb.get("redirected"):
        print(_warn(f"  fallback 接口：❌ 被重定向（cookies 已失效）"))
    elif not fb_success:
        err = fb.get("error") or ""
        resp = fb.get("response") or {}
        err_msg = resp.get("error_msg") or resp.get("errorMsg") or ""
        print(_warn(f"  fallback 接口：❌ 失败（{err or err_msg or '未知错误'}）"))
    else:
        print(_warn(f"  fallback 接口：⚠️ success=True 但未找到订单列表"))
        print(_diag_line(f"    result keys={fb.get('result_keys')}"))
        diag["recommendations"].append(
            f"fallback接口返回了数据但字段名未知，result keys={fb.get('result_keys')}，"
            f"需要在 _extract_orders() 中添加对应字段"
        )

    # 浏览足迹
    best_type = None
    best_count = 0
    for tp in (1, 2, 3):
        key = f"footprint_type{tp}"
        fp = results.get(key, {})
        cnt = fp.get("goods_count", 0)
        if cnt > best_count:
            best_count = cnt
            best_type = tp
        status = "✅" if cnt > 0 else ("❌" if not fp.get("redirected") else "🔄")
        print(_ok(f"  浏览足迹 type={tp}：{status} goods_count={cnt}") if cnt > 0
              else _warn(f"  浏览足迹 type={tp}：{status} goods_count={cnt}"))

    if best_type is not None and best_count > 0:
        diag["footprint_working_type"] = best_type
        diag["footprint_goods_count"] = best_count
        if best_type != 2:
            diag["recommendations"].append(
                f"浏览足迹接口 type 参数应改为 {best_type}（当前代码用的是 2），"
                f"修改 pdd_context_fetcher.py fetch_buyer_footprint() 中 payload 的 'type' 值为 {best_type}"
            )
    else:
        diag["recommendations"].append(
            "所有浏览足迹 type 值（1/2/3）均未返回商品数据，"
            "可能是 cookies 失效或接口参数有误"
        )

    # WS实时浏览足迹
    ws_fp = results.get("ws_footprint", {})
    if ws_fp.get("source_goods_found"):
        diag["ws_footprint_captured"] = True
        sg = ws_fp.get("source_goods", {})
        print(_ok(f"  WS浏览足迹捕获：✅ 成功，商品={sg.get('goods_name', '')}（id={sg.get('goods_id', '')}）"))
    elif ws_fp.get("error"):
        print(_warn(f"  WS浏览足迹捕获：⚠️ 出错（{ws_fp['error']}）"))
    else:
        ws_msgs = ws_fp.get("ws_messages_seen", 0)
        print(_warn(f"  WS浏览足迹捕获：未捕获到商品（共收到 {ws_msgs} 条WS消息）"))
        print(_info("    说明：source_goods 只在买家正在浏览商品时才会出现，空值为正常情况"))

    print(f"\n{_diag_line('【修复建议】')}")
    if diag["recommendations"]:
        for i, rec in enumerate(diag["recommendations"], 1):
            print(_diag_line(f"  {i}. {rec}"))
    else:
        print(_ok("  无需修复，接口均正常工作！"))

    print(f"\n  详细结果已保存到: {OUTPUT_FILE}")
    print(sep)
    return diag


# ================================================================
# 主流程
# ================================================================

async def main() -> None:
    global captured_buyer_id, captured_cookies, all_results

    print("=" * 60)
    print("  订单和浏览足迹接口全面诊断脚本 (test_context_api.py)")
    print("=" * 60)

    # 检查 playwright 是否已安装
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print(_warn("缺少 playwright，正在自动安装..."))
        import subprocess
        subprocess.run([sys.executable, "-m", "pip", "install", "playwright"], check=True)
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
        from playwright.async_api import async_playwright

    # 检查 aiohttp 是否已安装
    try:
        import aiohttp  # noqa: F401
    except ImportError:
        print(_warn("缺少 aiohttp，正在自动安装..."))
        import subprocess
        subprocess.run([sys.executable, "-m", "pip", "install", "aiohttp"], check=True)

    # 查找可用的 browser_data profile
    candidate_profiles = [
        BASE / "browser_data" / "default",
        BASE / "browser_data" / "sniff_profile",
    ]
    # 也搜索所有 browser_data 子目录
    browser_data_dir = BASE / "browser_data"
    if browser_data_dir.exists():
        for p in browser_data_dir.iterdir():
            if p.is_dir() and p not in candidate_profiles:
                candidate_profiles.append(p)

    user_data: Optional[Path] = None
    for p in candidate_profiles:
        if p.exists():
            user_data = p
            print(_info(f"找到已有 profile: {p}"))
            break

    if user_data is None:
        print(_warn("未找到任何已有的 browser_data profile！"))
        print(_warn("请先运行 sniff_pdd_chat.py 建立 profile（会自动创建 browser_data/sniff_profile）"))
        # 创建 sniff_profile 作为备用
        user_data = BASE / "browser_data" / "sniff_profile"
        user_data.mkdir(parents=True, exist_ok=True)
        print(_info(f"已创建新 profile 目录: {user_data}（需要手动登录拼多多）"))

    async with async_playwright() as pw:
        ctx = await pw.chromium.launch_persistent_context(
            str(user_data),
            headless=False,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
            locale="zh-CN",
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()

        # ---- 注册 WebSocket 监听（捕获 buyer_id）----
        def _on_websocket(ws) -> None:
            url = ws.url
            if "pinduoduo" not in url and "pdd" not in url.lower():
                return
            ws.on("framesent",
                  lambda frame: _handle_ws_frame(_get_ws_payload(frame)))
            ws.on("framereceived",
                  lambda frame: _handle_ws_frame(_get_ws_payload(frame)))

        page.on("websocket", _on_websocket)

        # ---- 打开聊天页面 ----
        print(_info("正在打开拼多多聊天页面..."))
        try:
            await page.goto(
                "https://mms.pinduoduo.com/chat-merchant/index.html#/",
                timeout=30000,
            )
        except Exception as e:
            print(_warn(f"打开页面超时或出错: {e}"))
            print(_info("请在浏览器里手动导航到聊天页面"))

        print()
        print(_c("1;33", ">>> 请点击任意一个买家会话，脚本将自动捕获 buyer_id <<<"))
        print(_info("最长等待 60 秒..."))
        print()

        # 等待 buyer_id（最多60秒）
        for i in range(12):
            await asyncio.sleep(5)
            if captured_buyer_id:
                break
            print(_info(f"  [{_ts()}] 等待中... ({(i + 1) * 5}s)"))

        if not captured_buyer_id:
            print(_warn("未能从 WebSocket 自动捕获 buyer_id"))
            print(_warn("请在下方手动输入买家UID（从拼多多客服端URL或会话信息中查看）"))
            print(_warn("也可以直接按回车跳过（会使用演示 buyer_id=0）"))
            try:
                uid_input = input("请输入 buyer_id（或按回车跳过）: ").strip()
                if uid_input:
                    captured_buyer_id = uid_input
                else:
                    captured_buyer_id = "0"
                    print(_warn("使用演示 buyer_id=0，接口可能不返回真实数据"))
            except (EOFError, KeyboardInterrupt):
                captured_buyer_id = "0"

        buyer_id = captured_buyer_id
        print(_ok(f"使用 buyer_id: {buyer_id}"))

        # ---- 从页面提取 cookies ----
        print(_info("正在从页面提取 cookies..."))
        try:
            raw_cookies = await ctx.cookies()
            captured_cookies = {c["name"]: c["value"] for c in raw_cookies
                                if "pinduoduo" in c.get("domain", "")}
            print(_ok(f"提取到 {len(captured_cookies)} 个 pinduoduo cookies"))
            if not captured_cookies:
                print(_warn("未提取到 pinduoduo cookies，可能需要重新登录"))
        except Exception as e:
            print(_warn(f"提取 cookies 失败: {e}"))

        print(_info("正在关闭浏览器..."))
        await ctx.close()

    # ---- 运行所有接口测试 ----
    print()
    print(_c("1;34", "=" * 60))
    print(_c("1;34", "  开始接口测试..."))
    print(_c("1;34", "=" * 60))

    cookies = captured_cookies
    results: dict = {}

    results["order_latitude"] = await _test_order_latitude(buyer_id, cookies)
    results["order_fallback"] = await _test_order_fallback(buyer_id, cookies)
    results["footprint_type1"] = await _test_footprint(buyer_id, cookies, 1)
    results["footprint_type2"] = await _test_footprint(buyer_id, cookies, 2)
    results["footprint_type3"] = await _test_footprint(buyer_id, cookies, 3)
    results["ws_footprint"] = await _test_ws_footprint(buyer_id, cookies)

    # ---- 诊断报告 ----
    diagnosis = _print_diagnosis(buyer_id, results)

    # ---- 保存结果 ----
    all_results["captured_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    all_results["buyer_id"] = buyer_id
    all_results.update(results)
    all_results["diagnosis"] = diagnosis

    _save_results()


def _save_results() -> None:
    try:
        OUTPUT_FILE.write_text(
            json.dumps(all_results, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(_info(f"完整响应已保存到: {OUTPUT_FILE}"))
    except Exception as e:
        print(_warn(f"保存结果失败: {e}"))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n用户中断，正在保存已采集的数据...")
        all_results["captured_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        all_results["buyer_id"] = captured_buyer_id or ""
        all_results["_interrupted"] = True
        _save_results()
        print(_info("数据已保存，程序退出"))
