# -*- coding: utf-8 -*-
"""
sniff_pdd_chat.py — 拼多多聊天窗口全能接口嗅探脚本
专门捕获：
  1. recentOrderList HTTP 接口（完整请求/响应）
  2. WebSocket 消息里的 push_biz_context / bizContext（买家进入会话、浏览足迹）
  3. 买家发消息时携带的完整 biz 上下文

使用方法：python sniff_pdd_chat.py
结果保存到：sniff_chat_result.json
"""
import asyncio
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

BASE = Path(__file__).parent
OUTPUT_FILE = BASE / "sniff_chat_result.json"

# ---------- 颜色前缀（仅在支持 ANSI 的终端生效）----------
_USE_COLOR = sys.platform != "win32" or "ANSICON" in __import__("os").environ


def _c(code: str, text: str) -> str:
    if _USE_COLOR:
        return f"\033[{code}m{text}\033[0m"
    return text


def _http(text: str) -> str:
    return _c("36", f"[HTTP] {text}")       # 青色


def _ws_biz(text: str) -> str:
    return _c("35", f"[WS-BIZ] {text}")     # 紫色


def _ws_order(text: str) -> str:
    return _c("33", f"[WS-ORDER] {text}")   # 黄色


def _ws_msg(text: str) -> str:
    return _c("32", f"[WS-MSG] {text}")     # 绿色


def _info(text: str) -> str:
    return _c("34", f"[INFO] {text}")       # 蓝色


def _warn(text: str) -> str:
    return _c("31", f"[WARN] {text}")       # 红色


# ---------- 全局采集容器 ----------
http_apis: list[dict] = []
ws_messages: list[dict] = []

# ---------- 诊断分析辅助变量 ----------
_diag: dict[str, Any] = {
    "order_api_ok": False,
    "order_field_name": None,
    "order_data_path": None,
    "biz_field_name": None,
    "msg_category_values": [],
    "source_goods_path": None,
    "mismatches": [],
}

# ---------- 关键字 ----------
_HTTP_KEYWORDS = ("order", "goods", "buyer", "product")
_WS_BIZ_KEYWORDS = (
    "push_biz_context", "bizContext",
    "source_goods", "sourceGoods",
    "msg_category", "msgCategory",
    "orderSn", "order_sn",
    "goodsId", "goods_id",
)


def _ts() -> str:
    return time.strftime("%H:%M:%S")


def _dump(obj: Any) -> str:
    """完整 JSON 字符串，不截断"""
    return json.dumps(obj, ensure_ascii=False, indent=2)


# ================================================================
# HTTP 响应处理
# ================================================================

async def _handle_response(response) -> None:
    url = response.url
    if "pinduoduo" not in url:
        return
    if response.request.resource_type not in ("xhr", "fetch"):
        return

    # 只处理订单相关和含关键字的接口
    is_order_list = "recentOrderList" in url
    is_keyword = any(k in url.lower() for k in _HTTP_KEYWORDS)
    if not (is_order_list or is_keyword):
        return

    try:
        # 读取请求 payload
        try:
            req_body_raw = response.request.post_data or ""
            try:
                req_payload = json.loads(req_body_raw) if req_body_raw else {}
            except Exception:
                req_payload = req_body_raw
        except Exception:
            req_payload = {}

        # 读取响应
        text = await response.text()
        try:
            resp_json = json.loads(text)
        except Exception:
            resp_json = {"_raw": text}

        label = "ORDER_LIST" if is_order_list else "HTTP_API"
        entry = {
            "label": label,
            "url": url,
            "request_payload": req_payload,
            "response_full": resp_json,
            "time": _ts(),
        }
        http_apis.append(entry)
        print(_http(f"捕获 [{label}] {url}"))
        # 只打印请求关键字段，不打印完整 payload
        if isinstance(req_payload, dict):
            key_fields = {k: v for k, v in req_payload.items()
                          if k in ('buyerUid', 'buyer_uid', 'pageNumber', 'pageSize', 'orderType')}
            print(_http(f"  请求关键字段: {key_fields}"))
        else:
            print(_http(f"  请求: {str(req_payload)[:100]}"))

        # 响应只打印成功状态和数据条数
        if isinstance(resp_json, dict):
            success = resp_json.get('success')
            result = resp_json.get('result') or resp_json.get('data') or {}
            order_list = []
            if isinstance(result, dict):
                order_list = result.get('orderList') or result.get('list') or []
            elif isinstance(result, list):
                order_list = result
            print(_http(f"  响应: success={success} | 订单条数={len(order_list)}"))
            if order_list:
                first = order_list[0]
                order_sn = first.get('orderSn') or first.get('order_sn') or first.get('sn') or ''
                goods_name = first.get('goodsName') or first.get('goods_name') or ''
                buyer_uid = first.get('buyerId') or first.get('buyerUid') or ''
                print(_http(f"  第一条订单: order_sn={order_sn} | goods_name={str(goods_name)[:30]} | buyer={buyer_uid}"))
        # 完整响应依然写入文件（通过 http_apis 列表在结尾保存）

        # 更新诊断
        if is_order_list:
            _update_order_diag(req_payload, resp_json)

    except Exception as e:
        print(_warn(f"读取响应失败 {url}: {e}"))


def _update_order_diag(req: Any, resp: Any) -> None:
    """分析 recentOrderList 响应，更新诊断信息"""
    if not isinstance(resp, dict):
        return
    success = resp.get("success", False)
    _diag["order_api_ok"] = bool(success)

    # 探测订单数据路径
    data_val = resp.get("data")
    paths_to_try = [
        ("result.orderList", resp.get("result", {}).get("orderList")),
        ("result.list", resp.get("result", {}).get("list")),
        ("data.orderList", data_val.get("orderList") if isinstance(data_val, dict) else None),
        ("data", data_val if isinstance(data_val, list) else None),
        ("result", resp.get("result") if isinstance(resp.get("result"), list) else None),
    ]
    order_list = None
    for path, val in paths_to_try:
        if val and isinstance(val, list):
            order_list = val
            _diag["order_data_path"] = path
            break

    if order_list:
        first = order_list[0] if order_list else {}
        # 探测订单号字段名
        for field in ("orderSn", "order_sn", "sn", "orderId", "order_id"):
            if field in first:
                _diag["order_field_name"] = field
                break

    # 检查请求里是否包含 buyerUid
    req_has_buyer_uid = False
    if isinstance(req, dict):
        req_has_buyer_uid = "buyerUid" in req or "buyer_uid" in req
    elif isinstance(req, str):
        req_has_buyer_uid = "buyerUid" in req or "buyer_uid" in req
    _diag["req_has_buyer_uid"] = req_has_buyer_uid


# ================================================================
# WebSocket 消息处理
# ================================================================

def _classify_ws(msg: Any) -> list[str]:
    """返回消息标签列表（一条消息可能属于多个类型）"""
    if not isinstance(msg, dict):
        return []
    labels = []
    raw = json.dumps(msg, ensure_ascii=False)

    # 含 biz 上下文
    if "push_biz_context" in raw or "bizContext" in raw:
        labels.append("WS-BIZ")
    # 含浏览足迹商品
    if "source_goods" in raw or "sourceGoods" in raw:
        labels.append("WS-BIZ")
    # 含订单号/商品ID
    if "orderSn" in raw or "order_sn" in raw or "goodsId" in raw or "goods_id" in raw:
        labels.append("WS-ORDER")

    # 买家消息（from.role == user/buyer）
    msg_inner = msg.get("message") or msg
    from_info = msg_inner.get("from") or {}
    role = from_info.get("role", "")
    if role in ("user", "buyer"):
        labels.append("WS-MSG")

    # 含 msg_category
    if "msg_category" in raw or "msgCategory" in raw:
        if "WS-BIZ" not in labels:
            labels.append("WS-BIZ")

    return list(dict.fromkeys(labels)) or ["WS-RAW"]


def _extract_biz(msg: Any) -> dict:
    """从 WS 消息中提取 biz 上下文字段"""
    if not isinstance(msg, dict):
        return {}
    # 顶层 or message.xxx
    inner = msg.get("message") or msg
    biz = (inner.get("push_biz_context")
           or inner.get("bizContext")
           or inner.get("biz_context")
           or inner.get("bizCtx")
           or {})
    # 同时也尝试从顶层取
    if not biz:
        biz = (msg.get("push_biz_context")
               or msg.get("bizContext")
               or msg.get("biz_context")
               or {})
    return biz if isinstance(biz, dict) else {}


def _handle_ws_frame(raw_payload: str, direction: str) -> None:
    """处理单帧 WS 文本消息"""
    try:
        msg = json.loads(raw_payload)
    except Exception:
        return  # 非 JSON 跳过

    labels = _classify_ws(msg)
    if not labels or labels == ["WS-RAW"]:
        return

    biz = _extract_biz(msg)
    msg_inner = msg.get("message") or msg

    # 读取 msg_category
    msg_category_raw = biz.get("msg_category") or biz.get("msgCategory")
    if msg_category_raw is None:
        msg_category_raw = msg_inner.get("msg_category") or msg_inner.get("msgCategory")
    msg_category = int(msg_category_raw) if msg_category_raw is not None else None

    # 读取 source_goods
    source_goods_found = bool(
        biz.get("sourceGoods") or biz.get("source_goods")
        or biz.get("goodsId") or biz.get("goods_id")
        or biz.get("sourceGoodsId")
    )

    # 买家 ID
    from_info = msg_inner.get("from") or {}
    buyer_id = (str(from_info.get("uid") or "")
                or str(msg_inner.get("buyerId") or "")
                or str(msg_inner.get("buyer_id") or ""))

    # 消息内容
    content = msg_inner.get("content") or msg_inner.get("msgContent") or ""

    entry: dict[str, Any] = {
        "label": labels[0],
        "labels": labels,
        "direction": direction,
        "raw": msg,
        "biz_context": biz,
        "source_goods_found": source_goods_found,
        "msg_category": msg_category,
        "buyer_id": buyer_id,
        "content": content,
        "has_biz": bool(biz),
        "time": _ts(),
    }
    ws_messages.append(entry)

    # 控制台输出（只打印摘要，完整JSON写入文件）
    if "WS-BIZ" in labels:
        goods_name = biz.get('goodsName') or biz.get('goods_name') or biz.get('sourceGoodsName') or ''
        goods_id = biz.get('goodsId') or biz.get('goods_id') or biz.get('sourceGoodsId') or ''
        order_sn = biz.get('orderSn') or biz.get('order_sn') or ''
        print(_ws_biz(
            f"[{direction}] BIZ上下文 | msg_category={msg_category} | "
            f"source_goods={source_goods_found} | goods_id={goods_id} | "
            f"goods_name={str(goods_name)[:30] if goods_name else ''} | order_sn={order_sn}"
        ))
        _update_biz_diag(msg, biz, msg_category, source_goods_found)

    if "WS-ORDER" in labels and "WS-BIZ" not in labels:
        raw_str = json.dumps(msg, ensure_ascii=False)
        order_sn = ''
        for k in ('orderSn', 'order_sn', 'sn'):
            m2 = re.search(rf'"{k}"\s*:\s*"([^"]+)"', raw_str)
            if m2:
                order_sn = m2.group(1)
                break
        print(_ws_order(f"[{direction}] 订单/商品字段 | order_sn={order_sn}"))

    if "WS-MSG" in labels:
        print(_ws_msg(
            f"[{direction}] 买家消息 | buyer_id={buyer_id or '(空)'} | "
            f"content={str(content)[:100]}"
        ))


def _update_biz_diag(msg: Any, biz: dict, msg_category: Any, source_goods_found: bool) -> None:
    """更新 biz 相关诊断"""
    msg_inner = msg.get("message") or msg
    # 确定实际 biz 字段名
    for fname in ("push_biz_context", "bizContext", "biz_context", "bizCtx"):
        if fname in msg_inner or fname in msg:
            _diag["biz_field_name"] = fname
            break

    if msg_category is not None:
        cats = _diag["msg_category_values"]
        if msg_category not in cats:
            cats.append(msg_category)

    if source_goods_found and not _diag["source_goods_path"]:
        # 探测 source_goods 路径
        if biz.get("sourceGoods"):
            _diag["source_goods_path"] = f"{_diag.get('biz_field_name', 'push_biz_context')}.sourceGoods"
        elif biz.get("source_goods"):
            _diag["source_goods_path"] = f"{_diag.get('biz_field_name', 'push_biz_context')}.source_goods"
        elif biz.get("goodsId"):
            _diag["source_goods_path"] = f"{_diag.get('biz_field_name', 'push_biz_context')}.goodsId"
        elif biz.get("sourceGoodsId"):
            _diag["source_goods_path"] = f"{_diag.get('biz_field_name', 'push_biz_context')}.sourceGoodsId"


# ================================================================
# 诊断报告生成
# ================================================================

def _build_diagnosis() -> dict:
    """构建最终诊断字典"""
    mismatches = []

    # 检查订单字段是否与 pdd_context.py 期望匹配
    # pdd_context.py 的 update_from_http_orders 尝试: orderSn, order_sn, sn
    actual_order_field = _diag.get("order_field_name")
    expected_order_fields = {"orderSn", "order_sn", "sn"}
    if actual_order_field and actual_order_field not in expected_order_fields:
        mismatches.append(
            f"订单字段名不匹配: 实际={actual_order_field}, "
            f"pdd_context.py 期望={expected_order_fields}"
        )

    # 检查 biz 字段名
    actual_biz_field = _diag.get("biz_field_name")
    expected_biz_fields = {"push_biz_context", "bizContext"}
    if actual_biz_field and actual_biz_field not in expected_biz_fields:
        mismatches.append(
            f"BIZ 字段名不匹配: 实际={actual_biz_field}, "
            f"pdd_message.py 期望={expected_biz_fields}"
        )

    # 检查 msg_category 值
    actual_cats = _diag.get("msg_category_values", [])
    expected_cats = {4, 5}
    unexpected = [c for c in actual_cats if c not in expected_cats]
    if unexpected:
        mismatches.append(
            f"msg_category 有非预期值: {unexpected}, "
            f"pdd_message.py 只处理 [4,5]"
        )

    return {
        "order_api_ok": _diag.get("order_api_ok", False),
        "order_field_name": actual_order_field,
        "order_data_path": _diag.get("order_data_path"),
        "req_has_buyer_uid": _diag.get("req_has_buyer_uid", None),
        "biz_field_name": actual_biz_field,
        "msg_category_values": actual_cats,
        "source_goods_path": _diag.get("source_goods_path"),
        "mismatches": mismatches,
    }


def _print_report(diagnosis: dict) -> None:
    sep = "=" * 60
    print(f"\n{sep}")
    print("  === 接口嗅探诊断报告 ===")
    print(sep)

    print("\n【订单接口】recentOrderList")
    print(f"  URL: https://mms.pinduoduo.com/mangkhut/mms/recentOrderList")
    req_uid = diagnosis.get("req_has_buyer_uid")
    print(f"  请求 buyerUid 字段: {'是' if req_uid else '否' if req_uid is not None else '未捕获到请求'}")
    api_ok = diagnosis.get("order_api_ok")
    print(f"  响应 success: {'true' if api_ok else 'false（或未捕获）'}")
    field = diagnosis.get("order_field_name")
    print(f"  响应订单字段名: {field or '未检测到'}")
    path = diagnosis.get("order_data_path")
    print(f"  响应数据路径: {path or '未检测到'}")

    print("\n【WS消息】买家进入会话通知")
    cats = diagnosis.get("msg_category_values")
    print(f"  msg_category 实际值: {cats if cats else '未捕获到'}")
    biz_field = diagnosis.get("biz_field_name")
    print(f"  biz上下文字段: {biz_field or '未捕获到'}")
    sg_path = diagnosis.get("source_goods_path")
    print(f"  浏览商品字段路径: {sg_path or '未检测到'}")

    print("\n【WS消息】买家发送消息")
    buyer_msgs = [m for m in ws_messages if "WS-MSG" in m.get("labels", [])]
    print(f"  已捕获买家消息数: {len(buyer_msgs)}")
    if buyer_msgs:
        bm = buyer_msgs[0]["raw"]
        inner = bm.get("message") or bm
        content_field = next(
            (f for f in ("content", "msgContent") if f in inner), "未检测到"
        )
        from_info = inner.get("from") or {}
        uid_field = next(
            (f for f in ("uid", "buyerId", "buyer_id") if f in from_info or f in inner), "未检测到"
        )
        print(f"  content 字段名: {content_field}")
        print(f"  from.uid / buyerId 字段名: {uid_field}")
        has_biz_list = [m.get("has_biz", False) for m in buyer_msgs]
        print(f"  biz上下文是否含商品信息: {'是' if any(has_biz_list) else '否'}")

    print("\n【结论】")
    mismatches = diagnosis.get("mismatches", [])
    order_field_ok = (
        diagnosis.get("order_field_name") in {"orderSn", "order_sn", "sn"}
        if diagnosis.get("order_field_name")
        else None
    )
    biz_ok = (
        diagnosis.get("biz_field_name") in {"push_biz_context", "bizContext"}
        if diagnosis.get("biz_field_name")
        else None
    )

    ok_sym = "✅"
    fail_sym = "❌"
    unknown_sym = "❓"

    def _symbol(val: Any) -> str:
        if val is True:
            return ok_sym
        if val is False:
            return fail_sym
        return unknown_sym

    print(f"  订单接口字段匹配: {_symbol(order_field_ok)} "
          f"({'与 pdd_context.py 一致' if order_field_ok else '与 pdd_context.py 不一致或未捕获'})")
    print(f"  浏览足迹字段匹配: {_symbol(biz_ok)} "
          f"({'与 pdd_message.py 一致' if biz_ok else '与 pdd_message.py 不一致或未捕获'})")
    if mismatches:
        print(f"  需要修复的字段:")
        for m in mismatches:
            print(f"    - {m}")
    else:
        if order_field_ok is not None or biz_ok is not None:
            print(f"  需要修复的字段: 无（字段名与代码期望一致）")
        else:
            print(f"  需要修复的字段: 未获得足够数据，请重新运行并按提示操作")

    print(f"\n  详细结果已保存到: {OUTPUT_FILE}")
    print(sep)


# ================================================================
# 主流程
# ================================================================

async def main() -> None:
    print("=" * 60)
    print("  拼多多聊天窗口接口嗅探工具 (sniff_pdd_chat.py)")
    print("=" * 60)

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("\n❌ 缺少 playwright，正在自动安装...")
        import subprocess
        subprocess.run([sys.executable, "-m", "pip", "install", "playwright"], check=True)
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
        from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        user_data = BASE / "browser_data" / "sniff_profile"
        user_data.mkdir(parents=True, exist_ok=True)

        ctx = await pw.chromium.launch_persistent_context(
            str(user_data),
            headless=False,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
            locale="zh-CN",
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()

        # ---- 注册 HTTP 响应监听 ----
        page.on("response", lambda resp: asyncio.ensure_future(_handle_response(resp)))

        # ---- 注册 WebSocket 监听 ----
        def _on_websocket(ws) -> None:
            url = ws.url
            print(_info(f"WebSocket 已连接: {url}"))
            if "pinduoduo" not in url and "pdd" not in url.lower():
                return

            ws.on(
                "framesent",
                lambda frame: _handle_ws_frame(frame.get("payload", ""), "SEND"),
            )
            ws.on(
                "framereceived",
                lambda frame: _handle_ws_frame(frame.get("payload", ""), "RECV"),
            )

        page.on("websocket", _on_websocket)

        # ---- 步骤1：打开聊天页面 ----
        print(_info("正在打开聊天页面..."))
        try:
            await page.goto(
                "https://mms.pinduoduo.com/chat-merchant/index.html#/",
                timeout=30000,
            )
        except Exception as e:
            print(_warn(f"打开聊天页面超时或出错: {e}"))
            print(_info("请在浏览器里手动导航到聊天页面"))

        print()
        print(_c("1;33", ">>> 步骤1：请点击任意一个买家会话 <<<"))
        print(_info("等待你点击买家会话（30秒内）..."))
        print()

        # 等待30秒，期间捕获"进入会话"通知
        for _ in range(6):
            await asyncio.sleep(5)
            enter_msgs = [m for m in ws_messages if m.get("msg_category") in (4, 5)]
            print(_info(
                f"  [{_ts()}] 已捕获: HTTP={len(http_apis)} WS={len(ws_messages)} "
                f"进入会话消息={len(enter_msgs)}"
            ))
            if enter_msgs:
                print(_c("1;32", "  ✅ 已捕获到买家进入会话通知！"))

        print()
        print(_c("1;33", ">>> 步骤2：请发一条测试消息，或等买家发消息 <<<"))
        print(_info("等待买家/你发消息（30秒内）..."))
        print()

        for _ in range(6):
            await asyncio.sleep(5)
            buyer_msgs = [m for m in ws_messages if "WS-MSG" in m.get("labels", [])]
            print(_info(
                f"  [{_ts()}] 已捕获: HTTP={len(http_apis)} WS={len(ws_messages)} "
                f"买家消息={len(buyer_msgs)}"
            ))
            if buyer_msgs:
                print(_c("1;32", "  ✅ 已捕获到买家消息！"))

        print()
        print(_c("1;33", ">>> 步骤3：请手动复制一个商品链接，在聊天窗口发给买家（或让买家发给你）<<<"))
        print(_info("目的：测试 yangkeduo.com/goods.html?goods_id=xxx 链接是否被正确识别"))
        print(_info("等待30秒捕获商品链接消息..."))
        print()

        for _ in range(6):
            await asyncio.sleep(5)
            goods_link_msgs = [
                m for m in ws_messages
                if 'yangkeduo' in str(m.get('content', '')) or 'pinduoduo' in str(m.get('content', ''))
            ]
            print(_info(
                f"  [{_ts()}] 已捕获: HTTP={len(http_apis)} WS={len(ws_messages)} "
                f"商品链接消息={len(goods_link_msgs)}"
            ))
            if goods_link_msgs:
                last = goods_link_msgs[-1]
                print(_c("1;32", f"  ✅ 捕获到商品链接消息！content={str(last.get('content',''))[:80]}"))

        print()
        print(_info("嗅探完成，正在关闭浏览器..."))
        await ctx.close()

    # ---- 保存结果 ----
    diagnosis = _build_diagnosis()
    result = {
        "captured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "http_apis": http_apis,
        "ws_messages": ws_messages,
        "diagnosis": diagnosis,
    }
    OUTPUT_FILE.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(_info(f"结果已保存到: {OUTPUT_FILE}"))

    # ---- 打印诊断报告 ----
    _print_report(diagnosis)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n用户中断，正在保存数据...")
        diagnosis = _build_diagnosis()
        result = {
            "captured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "http_apis": http_apis,
            "ws_messages": ws_messages,
            "diagnosis": diagnosis,
        }
        OUTPUT_FILE.write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"已保存到: {OUTPUT_FILE}")
        _print_report(diagnosis)
