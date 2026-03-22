# -*- coding: utf-8 -*-
"""
============================================================
  浏览足迹 / 商品详情页来源 / 商品链接  三大功能检测脚本
  Detect: ① 浏览足迹(source_goods)  ② 来自商品详情页(from_goods_detail)
          ③ 商品链接解析(goods_url)
============================================================
使用方法：
    python test_detect_footprint.py
不依赖任何外部服务，纯本地逻辑验证。
"""

import json
import sys
import re

# ─── 从客户端模块导入解析逻辑 ────────────────────────────────────────────────
try:
    from channel.pinduoduo.pdd_message import (
        parse_message,
        _extract_source_goods_from_biz,
        _extract_goods_from_url,
    )
    IMPORT_OK = True
except ImportError as e:
    print(f"[WARN] 无法导入 pdd_message 模块（{e}），将使用内联副本运行检测")
    IMPORT_OK = False

# ─── 如果导入失败，内联一份最小副本用于检测 ──────────────────────────────────
if not IMPORT_OK:
    def _extract_goods_from_url(text: str):
        goods_id = None
        pattern = (
            r'https?://(?:mobile\.yangkeduo\.com|mobile\.pinduoduo\.com|yangkeduo\.com)'
            r'/goods(?:\.html|/detail)[^\s]*goods_id=(\d+)[^\s]*'
        )
        m = re.search(pattern, text)
        if m:
            goods_id = m.group(1)
        elif 'yangkeduo' in text or 'pinduoduo' in text:
            m2 = re.search(r'goods_id=(\d+)', text)
            if m2:
                goods_id = m2.group(1)
        if goods_id:
            return {'goods_id': goods_id, 'goods_name': '', 'goods_img': ''}
        return None

    def _extract_source_goods_from_biz(biz: dict):
        goods_id   = str(biz.get('goods_id') or biz.get('goodsId') or biz.get('sourceGoodsId') or '')
        goods_name = str(biz.get('goods_name') or biz.get('goodsName') or biz.get('sourceGoodsName') or '')
        goods_img  = str(biz.get('goods_img') or biz.get('goodsImg') or biz.get('sourceGoodsImg') or biz.get('goodsImageUrl') or '')

        source_obj = biz.get('sourceGoods') or biz.get('source_goods') or {}
        if isinstance(source_obj, dict) and source_obj:
            goods_id   = goods_id   or str(source_obj.get('goodsId') or source_obj.get('goods_id') or '')
            goods_name = goods_name or str(source_obj.get('goodsName') or source_obj.get('goods_name') or '')
            goods_img  = goods_img  or str(source_obj.get('goodsImg') or source_obj.get('thumbUrl') or source_obj.get('mainImgUrl') or '')

        for field in ('currentGoods', 'recommendGoods', 'linkGoods', 'goods'):
            obj = biz.get(field)
            if isinstance(obj, dict) and obj:
                goods_id   = goods_id   or str(obj.get('goodsId') or obj.get('goods_id') or '')
                goods_name = goods_name or str(obj.get('goodsName') or obj.get('goods_name') or '')
                if goods_id or goods_name:
                    break

        ctx_obj = biz.get('context')
        if isinstance(ctx_obj, dict):
            nested = ctx_obj.get('sourceGoods') or {}
            if isinstance(nested, dict) and nested:
                goods_id   = goods_id   or str(nested.get('goodsId') or nested.get('goods_id') or '')
                goods_name = goods_name or str(nested.get('goodsName') or nested.get('goods_name') or '')

        if goods_id or goods_name:
            return {'goods_id': goods_id, 'goods_name': goods_name, 'goods_img': goods_img}
        return None

    def parse_message(data: dict):
        """简化版 parse_message，供检测使用"""
        MSG_TYPE_MAP = {0:'text',1:'text',2:'image',3:'audio',4:'video',
                        5:'goods',6:'order',7:'withdraw',8:'system',9:'custom',10:'withdraw'}
        if 'message' in data:
            msg = data['message']
        elif 'msgType' in data or 'type' in data or 'fromUser' in data:
            msg = data
        else:
            return None

        biz = (msg.get('push_biz_context') or msg.get('bizContext') or
               msg.get('biz_context') or msg.get('pushBizContext') or {})
        msg_category = int(biz.get('msg_category') or biz.get('msgCategory') or 0)

        raw_type = msg.get('type') or msg.get('msgType') or 0
        msg_type = MSG_TYPE_MAP.get(int(raw_type) if str(raw_type).isdigit() else 0, 'text')

        is_enter_session = msg_category in (4, 5) or msg_type == 'system'

        source_goods = _extract_source_goods_from_biz(biz)
        if is_enter_session and not source_goods:
            for biz_key in ('push_biz_context','bizContext','biz_context','pushBizContext','context','msgContext'):
                alt_biz = msg.get(biz_key)
                if isinstance(alt_biz, dict) and alt_biz:
                    source_goods = _extract_source_goods_from_biz(alt_biz)
                    if source_goods:
                        break

        buyer_id = str((msg.get('from') or {}).get('uid') or msg.get('buyerId') or
                       msg.get('fromUser') or msg.get('senderId') or '')
        content = msg.get('content') or msg.get('msgContent') or msg.get('text') or ''
        if isinstance(content, dict):
            content = json.dumps(content)

        if not source_goods and msg_type == 'text' and content:
            extracted = _extract_goods_from_url(str(content))
            if extracted:
                source_goods = extracted
                msg_type = 'goods'

        return {
            'buyer_id': buyer_id,
            'content': str(content),
            'msg_type': msg_type,
            'source_goods': source_goods,
            'is_enter_session': is_enter_session,
            'msg_category': msg_category,
        }


# ─── 测试工具 ────────────────────────────────────────────────────────────────
PASS = '\033[92m[PASS]\033[0m'
FAIL = '\033[91m[FAIL]\033[0m'
WARN = '\033[93m[WARN]\033[0m'
results = {'pass': 0, 'fail': 0}

def check(label: str, condition: bool, hint: str = ''):
    if condition:
        print(f"  {PASS} {label}")
        results['pass'] += 1
    else:
        print(f"  {FAIL} {label}" + (f"  → {hint}" if hint else ''))
        results['fail'] += 1
    return condition


# ════════════════════════════════════════════════════════════════════════════
# SECTION 1: 浏览足迹（source_goods / push_biz_context）
# ════════════════════════════════════════════════════════════════════════════
def test_section1_footprint():
    print("\n" + "="*60)
    print("SECTION 1: 浏览足迹（source_goods / push_biz_context）")
    print("="*60)

    # ── Case 1.1: 新格式 WS 消息，push_biz_context 含扁平 goods_id ──────────
    print("\n[Case 1.1] 新格式 WS，biz 扁平字段 goods_id / goods_name")
    ws_msg_1 = {
        "message": {
            "from": {"uid": "12345678", "role": "user"},
            "type": 1,
            "content": "你好，这个衣服有货吗",
            "push_biz_context": {
                "goods_id": "665066079868",
                "goods_name": "珊瑚绒睡衣女款",
                "msg_category": 4
            }
        }
    }
    r = parse_message(ws_msg_1)
    check("parse_message 返回非空", r is not None)
    check("source_goods 不为空", bool(r and r.get('source_goods')),
          hint="push_biz_context.goods_id 未被提取")
    if r and r.get('source_goods'):
        check("goods_id 正确", r['source_goods'].get('goods_id') == '665066079868',
              hint=f"实际={r['source_goods'].get('goods_id')}")
        check("goods_name 正确", r['source_goods'].get('goods_name') == '珊瑚绒睡衣女款',
              hint=f"实际={r['source_goods'].get('goods_name')}")
    check("is_enter_session 为 True（msg_category=4）", bool(r and r.get('is_enter_session')),
          hint="msg_category=4 未被识别为进入会话")

    # ── Case 1.2: 驼峰字段 bizContext + sourceGoods 对象 ──────────────────
    print("\n[Case 1.2] 驼峰 bizContext + sourceGoods 对象")
    ws_msg_2 = {
        "message": {
            "from": {"uid": "99887766", "role": "buyer"},
            "type": 8,
            "content": "",
            "bizContext": {
                "msgCategory": 5,
                "sourceGoods": {
                    "goodsId": "111222333444",
                    "goodsName": "加厚棉被冬季",
                    "thumbUrl": "https://img.xxx.com/goods.jpg"
                }
            }
        }
    }
    r2 = parse_message(ws_msg_2)
    check("source_goods 不为空（sourceGoods对象）", bool(r2 and r2.get('source_goods')),
          hint="bizContext.sourceGoods 对象未被提取")
    if r2 and r2.get('source_goods'):
        check("goods_id 正确", r2['source_goods'].get('goods_id') == '111222333444',
              hint=f"实际={r2['source_goods'].get('goods_id')}")

    # ── Case 1.3: 深层嵌套 context.sourceGoods ────────────────────────────
    print("\n[Case 1.3] 深层嵌套 biz.context.sourceGoods")
    ws_msg_3 = {
        "message": {
            "from": {"uid": "55443322", "role": "user"},
            "type": 8,
            "content": "",
            "push_biz_context": {
                "msg_category": 4,
                "context": {
                    "sourceGoods": {
                        "goodsId": "987654321",
                        "goodsName": "保暖羽绒服",
                    }
                }
            }
        }
    }
    r3 = parse_message(ws_msg_3)
    check("source_goods 不为空（context.sourceGoods）", bool(r3 and r3.get('source_goods')),
          hint="push_biz_context.context.sourceGoods 未被提取")
    if r3 and r3.get('source_goods'):
        check("goods_id 正确", r3['source_goods'].get('goods_id') == '987654321',
              hint=f"实际={r3['source_goods'].get('goods_id')}")

    # ── Case 1.4: 旧格式消息（无 message 包装）────────────────────────────
    print("\n[Case 1.4] 旧格式 WS 消息（无外层 message 包装）")
    ws_msg_4 = {
        "msgType": 1,
        "fromUser": "44332211",
        "content": "这件有M码吗",
        "push_biz_context": {
            "goods_id": "555666777",
            "goods_name": "连衣裙碎花款"
        }
    }
    r4 = parse_message(ws_msg_4)
    check("旧格式 source_goods 不为空", bool(r4 and r4.get('source_goods')),
          hint="旧格式 push_biz_context 未被提取")

    # ── Case 1.5: biz 为空，进入会话消息但无任何商品信息 ──────────────────
    print("\n[Case 1.5] biz 完全为空时，进入会话消息应返回 is_enter_session=True 但 source_goods=None")
    ws_msg_5 = {
        "message": {
            "from": {"uid": "12121212", "role": "user"},
            "type": 8,
            "content": "",
            "push_biz_context": {"msg_category": 4}
        }
    }
    r5 = parse_message(ws_msg_5)
    check("is_enter_session=True（空biz）", bool(r5 and r5.get('is_enter_session')))
    check("source_goods 为 None（无商品数据）", r5 is None or r5.get('source_goods') is None,
          hint="空 biz 不应伪造商品数据")


# ════════════════════════════════════════════════════════════════════════════
# SECTION 2: 当前用户来自商品详情页（from_goods_detail）
# ════════════════════════════════════════════════════════════════════════════
def test_section2_from_goods_detail():
    print("\n" + "="*60)
    print("SECTION 2: 来自商品详情页（from_goods_detail）字段检测")
    print("="*60)

    # 服务端 webhook 逻辑模拟（来自 aikefu routes/api.py）
    def simulate_webhook_pdd(data: dict) -> dict:
        current_goods = data.get('current_goods', {}) or {}
        source_goods = data.get('source_goods') or {}
        if source_goods:
            merged = dict(current_goods)
            merged.update({k: v for k, v in source_goods.items() if v})
            current_goods = merged

        from_goods_detail = bool(data.get('from_goods_detail', False))
        if from_goods_detail and current_goods and not current_goods.get('from_goods_detail'):
            current_goods['from_goods_detail'] = True

        return {'current_goods': current_goods, 'from_goods_detail': from_goods_detail}

    # ── Case 2.1: 正常携带 from_goods_detail=True ─────────────────────────
    print("\n[Case 2.1] 消息携带 from_goods_detail=True，current_goods 应有 from_goods_detail 标记")
    payload_1 = {
        "shop_token": "test_token",
        "buyer_id": "12345678",
        "content": "这件有折扣吗",
        "from_goods_detail": True,
        "current_goods": {
            "goods_id": "665066079868",
            "goods_name": "珊瑚绒睡衣",
        }
    }
    res1 = simulate_webhook_pdd(payload_1)
    check("from_goods_detail=True 被识别", res1['from_goods_detail'] is True)
    check("current_goods 含 from_goods_detail 标记",
          bool(res1['current_goods'].get('from_goods_detail')),
          hint="current_goods 未注入 from_goods_detail 标记")

    # ── Case 2.2: 未携带 from_goods_detail，不应被误设 ────────────────────
    print("\n[Case 2.2] 未携带 from_goods_detail，current_goods 不应有该标记")
    payload_2 = {
        "buyer_id": "99887766",
        "content": "几天到货",
        "current_goods": {"goods_id": "111222333", "goods_name": "加绒外套"}
    }
    res2 = simulate_webhook_pdd(payload_2)
    check("from_goods_detail 默认 False", res2['from_goods_detail'] is False)
    check("current_goods 不含 from_goods_detail", not res2['current_goods'].get('from_goods_detail'),
          hint="未携带 from_goods_detail 却被设置了标记")

    # ── Case 2.3: source_goods 优先级高于 current_goods ──────────────────
    print("\n[Case 2.3] source_goods 优先级高于 current_goods，merge 后商品信息应来自 source_goods")
    payload_3 = {
        "buyer_id": "55443322",
        "from_goods_detail": True,
        "current_goods": {"goods_id": "AAA", "goods_name": "旧商品名"},
        "source_goods": {"goods_id": "BBB", "goods_name": "新商品名（WS截获）", "goods_img": "https://img.test.com/x.jpg"}
    }
    res3 = simulate_webhook_pdd(payload_3)
    check("merge 后 goods_id 为 source_goods 的值",
          res3['current_goods'].get('goods_id') == 'BBB',
          hint=f"实际={res3['current_goods'].get('goods_id')}")
    check("merge 后 goods_name 为 source_goods 的值",
          res3['current_goods'].get('goods_name') == '新商品名（WS截获）',
          hint=f"实际={res3['current_goods'].get('goods_name')}\n")
    check("from_goods_detail 标记已注入", bool(res3['current_goods'].get('from_goods_detail')))

    # ── Case 2.4: current_goods 为空时 from_goods_detail 不注入（无商品） ─
    print("\n[Case 2.4] current_goods 为空时，from_goods_detail 不注入")
    payload_4 = {"buyer_id": "12121212", "from_goods_detail": True, "current_goods": {}}
    res4 = simulate_webhook_pdd(payload_4)
    check("current_goods 为空时不注入 from_goods_detail",
          not res4['current_goods'].get('from_goods_detail'),
          hint="空 current_goods 不应注入 from_goods_detail")


# ════════════════════════════════════════════════════════════════════════════
# SECTION 3: 商品链接解析（买家在聊天框发送商品URL）
# ════════════════════════════════════════════════════════════════════════════
def test_section3_goods_url():
    print("\n" + "="*60)
    print("SECTION 3: 商品链接解析（买家粘贴商品URL到聊天窗口）")
    print("="*60)

    # ── Case 3.1: 标准 yangkeduo.com 商品链接 ────────────────────────────
    print("\n[Case 3.1] 标准 yangkeduo.com 商品链接")
    url1 = "https://mobile.yangkeduo.com/goods.html?goods_id=665066079868&_oak_rcto=YWJ-2"
    r1 = _extract_goods_from_url(url1)
    check("识别到 goods_id", bool(r1 and r1.get('goods_id')),
          hint="yangkeduo.com URL 未被识别")
    if r1:
        check("goods_id 值正确", r1.get('goods_id') == '665066079868',
              hint=f"实际={r1.get('goods_id')}")

    # ── Case 3.2: mobile.pinduoduo.com 链接 ──────────────────────────────
    print("\n[Case 3.2] mobile.pinduoduo.com 商品链接")
    url2 = "https://mobile.pinduoduo.com/goods.html?goods_id=987654321&source=api"
    r2 = _extract_goods_from_url(url2)
    check("识别到 goods_id", bool(r2 and r2.get('goods_id')),
          hint="pinduoduo.com URL 未被识别")
    if r2:
        check("goods_id 值正确", r2.get('goods_id') == '987654321',
              hint=f"实际={r2.get('goods_id')}")

    # ── Case 3.3: 买家在文字消息里夹带商品链接 ────────────────────────────
    print("\n[Case 3.3] 买家文字消息中嵌入商品链接（WS text消息）")
    ws_link_msg = {
        "message": {
            "from": {"uid": "78901234", "role": "user"},
            "type": 1,
            "content": "老板，这个有吗 https://mobile.yangkeduo.com/goods.html?goods_id=112233445566 我想买"
        }
    }
    r3 = parse_message(ws_link_msg)
    check("parse_message 返回非空", r3 is not None)
    check("source_goods 被提取（文字中含商品链接）",
          bool(r3 and r3.get('source_goods')),
          hint="文字消息中的商品链接未被识别为 source_goods")
    if r3 and r3.get('source_goods'):
        check("goods_id 正确", r3['source_goods'].get('goods_id') == '112233445566',
              hint=f"实际={r3['source_goods'].get('goods_id')}")
    if r3:
        check("msg_type 变为 goods", r3.get('msg_type') == 'goods',
              hint=f"实际 msg_type={r3.get('msg_type')}\n")
        check("content 含 [商品链接] 前缀",
              '[商品链接]' in (r3.get('content') or ''),
              hint=f"实际 content={r3.get('content')[:80]}")

    # ── Case 3.4: 仅含 goods_id 参数的短链（宽泛匹配）─────────────────────
    print("\n[Case 3.4] 含拼多多域名的宽泛 URL（短链/转发链接）")
    url4 = "https://yangkeduo.com/goods.html?goods_id=998877665544&ref=xxx"
    r4 = _extract_goods_from_url(url4)
    check("宽泛匹配识别到 goods_id", bool(r4 and r4.get('goods_id')),
          hint="含拼多多域名的链接未被宽泛匹配识别")

    # ── Case 3.5: 非拼多多链接，不应被误识别 ─────────────────────────────
    print("\n[Case 3.5] 非拼多多链接，不应误识别")
    url5 = "https://item.taobao.com/item.htm?id=12345"
    r5 = _extract_goods_from_url(url5)
    check("淘宝链接不被识别", r5 is None,
          hint="淘宝链接被误识别为拼多多商品链接")

    # ── Case 3.6: 空字符串 / None ──────────────────────────────────────────
    print("\n[Case 3.6] 空字符串，不应崩溃")
    try:
        r6 = _extract_goods_from_url("")
        check("空字符串返回 None", r6 is None)
    except Exception as e:
        check("空字符串不崩溃", False, hint=str(e))


# ════════════════════════════════════════════════════════════════════════════
# SECTION 4: 端到端联合检测（模拟完整消息流）
# ════════════════════════════════════════════════════════════════════════════
def test_section4_end_to_end():
    print("\n" + "="*60)
    print("SECTION 4: 端到端联合检测（模拟买家进入会话完整流程）")
    print("="*60)

    # ── Case 4.1: 典型拼多多"买家进入会话"WS推送（最常见格式）─────────────
    print("\n[Case 4.1] 典型进入会话推送（msg_category=4，含 sourceGoods）")
    real_ws = {
        "message": {
            "from": {"uid": "36501987", "role": "buyer"},
            "type": 8,
            "content": "",
            "msg_id": "MSG20240322_001",
            "timestamp": 1710000000000,
            "push_biz_context": {
                "msg_category": 4,
                "sourceGoodsId": "665066079868",
                "sourceGoodsName": "珊瑚绒睡衣女款",
                "sourceGoodsImg": "https://img.yangkeduo.com/goods/xxx.jpg"
            }
        }
    }
    r = parse_message(real_ws)
    check("返回非空", r is not None)
    check("is_enter_session=True", bool(r and r.get('is_enter_session')))
    check("source_goods 不为空", bool(r and r.get('source_goods')),
          hint="常见格式 sourceGoodsId 未被提取！这是主要 bug 所在")
    if r and r.get('source_goods'):
        check("goods_id=665066079868",
              r['source_goods'].get('goods_id') == '665066079868',
              hint=f"实际={r['source_goods'].get('goods_id')}")
        check("goods_name=珊瑚绒睡衣女款",
              r['source_goods'].get('goods_name') == '珊瑚绒睡衣女款',
              hint=f"实际={r['source_goods'].get('goods_name')}\n")

    # ── Case 4.2: 买家直接发送商品链接询价 ──────────────────────────────
    print("\n[Case 4.2] 买家发送商品详情页链接询价")
    link_ws = {
        "message": {
            "from": {"uid": "36501987", "role": "buyer"},
            "type": 1,
            "content": "https://mobile.yangkeduo.com/goods.html?goods_id=665066079868&_oak_rcto=YWJ-2 这个还有S码吗",
            "msg_id": "MSG20240322_002",
        }
    }
    r2 = parse_message(link_ws)
    check("识别商品链接，source_goods 不为空",
          bool(r2 and r2.get('source_goods')),
          hint="买家发送的商品URL未被识别")
    if r2 and r2.get('source_goods'):
        check("goods_id 正确", r2['source_goods'].get('goods_id') == '665066079868')

    # ── Case 4.3: 全链路字段输出展示 ─────────────────────────────────────
    print("\n[Case 4.3] 完整字段输出（供人工核查）")
    full_ws = {
        "message": {
            "from": {"uid": "36501987", "role": "buyer"},
            "type": 8,
            "content": "",
            "push_biz_context": {
                "msg_category": 5,
                "sourceGoods": {
                    "goodsId": "665066079868",
                    "goodsName": "珊瑚绒睡衣女款",
                    "goodsImg": "https://img.test.com/goods.jpg",
                    "minGroupPrice": 4990
                }
            }
        }
    }
    r3 = parse_message(full_ws)
    if r3:
        print("  解析结果:")
        print(f"    buyer_id         = {r3.get('buyer_id')}")
        print(f"    msg_type         = {r3.get('msg_type')}")
        print(f"    is_enter_session = {r3.get('is_enter_session')}")
        sg = r3.get('source_goods')
        if sg:
            print(f"    source_goods:")
            print(f"      goods_id    = {sg.get('goods_id')}")
            print(f"      goods_name  = {sg.get('goods_name')}")
            print(f"      goods_img   = {sg.get('goods_img')}")
            print(f"      goods_price = {sg.get('goods_price')}")
            check("完整字段输出正常", True)
        else:
            check("source_goods 存在", False, hint="Case 4.3 source_goods 为空")
    else:
        check("parse_message 返回非空", False)


# ════════════════════════════════════════════════════════════════════════════
# SECTION 5: _extract_source_goods_from_biz 单元测试
# ════════════════════════════════════════════════════════════════════════════
def test_section5_biz_extractor():
    print("\n" + "="*60)
    print("SECTION 5: _extract_source_goods_from_biz 单元测试")
    print("="*60)

    cases = [
        ("扁平 goods_id/goods_name",
         {"goods_id": "111", "goods_name": "商品A"},
         "111", "商品A"),
        ("驼峰 goodsId/goodsName",
         {"goodsId": "222", "goodsName": "商品B"},
         "222", "商品B"),
        ("sourceGoodsId/sourceGoodsName",
         {"sourceGoodsId": "333", "sourceGoodsName": "商品C"},
         "333", "商品C"),
        ("sourceGoods 对象",
         {"sourceGoods": {"goodsId": "444", "goodsName": "商品D"}},
         "444", "商品D"),
        ("source_goods 对象（下划线）",
         {"source_goods": {"goods_id": "555", "goods_name": "商品E"}},
         "555", "商品E"),
        ("currentGoods 对象",
         {"currentGoods": {"goodsId": "666", "goodsName": "商品F"}},
         "666", "商品F"),
        ("context.sourceGoods 深层嵌套",
         {"context": {"sourceGoods": {"goodsId": "777", "goodsName": "商品G"}}},
         "777", "商品G"),
        ("空 biz 应返回 None",
         {}, None, None),
    ]

    for label, biz, expected_id, expected_name in cases:
        print(f"\n[Case 5.x] {label}")
        result = _extract_source_goods_from_biz(biz)
        if expected_id is None:
            check("返回 None", result is None,
                  hint=f"空 biz 返回了 {result}")
        else:
            check("返回非空 dict", result is not None,
                  hint=f"biz={biz} 应返回商品信息但返回了 None")
            if result:
                check(f"goods_id={expected_id}",
                      result.get('goods_id') == expected_id,
                      hint=f"实际={result.get('goods_id')}")
                check(f"goods_name={expected_name}",
                      result.get('goods_name') == expected_name,
                      hint=f"实际={result.get('goods_name')}")


# ════════════════════════════════════════════════════════════════════════════
# 主入口
# ════════════════════════════════════════════════════════════════════════════
def main():
    print("\n" + "★"*60)
    print("  浏览足迹 / 来自商品详情页 / 商品链接  检测脚本")
    print("  Repo: qq419701/dskehuduan + aikefu")
    print("★"*60)

    if IMPORT_OK:
        print(f"\n✅ 成功导入 channel.pinduoduo.pdd_message（真实代码）")
    else:
        print(f"\n⚠️  使用内联副本运行（pdd_message 导入失败，逻辑可能与最新代码有差异）")

    test_section1_footprint()
    test_section2_from_goods_detail()
    test_section3_goods_url()
    test_section4_end_to_end()
    test_section5_biz_extractor()

    total = results['pass'] + results['fail']
    print("\n" + "="*60)
    print(f"  检测完成：{total} 项检测  ✅ {results['pass']} 通过  ❌ {results['fail']} 失败")
    print("="*60)

    if results['fail'] > 0:
        print("\n❌ 有失败项，请根据 hint 修复对应逻辑")
        sys.exit(1)
    else:
        print("\n✅ 全部通过！浏览足迹/商品详情页来源/商品链接检测均正常")
        sys.exit(0)


if __name__ == '__main__':
    main()