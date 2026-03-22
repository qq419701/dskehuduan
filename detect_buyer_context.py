# -*- coding: utf-8 -*-
"""
买家上下文检测脚本 - detect_buyer_context.py

离线分析脚本：载入模拟 WS 原始消息，检测三类买家上下文数据能否被正确识别。

用法:
    python detect_buyer_context.py

不依赖数据库或网络，直接运行即可。
"""
import json
import sys
import re

# ── ANSI 颜色码 ──
GREEN  = '\033[92m'
RED    = '\033[91m'
YELLOW = '\033[93m'
CYAN   = '\033[96m'
BOLD   = '\033[1m'
RESET  = '\033[0m'

def _ok(s):   return f'{GREEN}✅ {s}{RESET}'
def _fail(s): return f'{RED}❌ {s}{RESET}'
def _warn(s): return f'{YELLOW}⚠️  {s}{RESET}'
def _head(s): return f'{BOLD}{CYAN}{s}{RESET}'


# ── 5 个内置测试消息 ──
TEST_MESSAGES = [
    # 1. type=5 + biz_context.sourceGoods — 浏览足迹标准格式
    {
        '_desc': '浏览足迹标准格式（sourceGoods对象）',
        '_expect_type': 'footfall',
        'message': {
            'from': {'uid': '100001', 'role': 'user'},
            'type': 5,
            'msg_id': 'msg001',
            'timestamp': 1700000001000,
            'push_biz_context': {
                'msg_category': 5,
                'sourceGoods': {
                    'goodsId': '999888777666',
                    'goodsName': '珊瑚绒睡衣冬季加厚女款',
                    'thumbUrl': 'https://img.pddpic.com/goods/img1.jpg',
                    'minGroupPrice': 5990,
                },
            },
        },
    },
    # 2. type=5 + biz_context.goodsId 扁平格式 — 浏览足迹另一种格式
    {
        '_desc': '浏览足迹扁平格式（顶层goodsId字段）',
        '_expect_type': 'footfall',
        'message': {
            'from': {'uid': '100002', 'role': 'buyer'},
            'type': 5,
            'msg_id': 'msg002',
            'timestamp': 1700000002000,
            'push_biz_context': {
                'msg_category': 4,
                'goodsId': '665066079868',
                'goodsName': '加绒加厚运动裤男',
                'goodsImg': 'https://img.pddpic.com/goods/img2.jpg',
            },
        },
    },
    # 3. 买家发送商品链接（含 &_oak_rcto=... 参数）
    {
        '_desc': '买家发送商品链接（含&参数）',
        '_expect_type': 'goods_url',
        'message': {
            'from': {'uid': '100003', 'role': 'user'},
            'type': 1,
            'msg_id': 'msg003',
            'timestamp': 1700000003000,
            'content': 'https://mobile.yangkeduo.com/goods.html?goods_id=665066079868&_oak_rcto=YWJ-2&refer_page_name=goods',
        },
    },
    # 4. 买家发送来源页文字 [当前用户来自 商品详情页]
    {
        '_desc': '买家发送来源页通知文字',
        '_expect_type': 'source_page',
        'message': {
            'from': {'uid': '100004', 'role': 'user'},
            'type': 1,
            'msg_id': 'msg004',
            'timestamp': 1700000004000,
            'content': '[当前用户来自 商品详情页]',
            'push_biz_context': {
                'goods_id': '112233445566',
                'goods_name': '厚底老爹鞋女',
            },
        },
    },
    # 5. 买家发送商品卡片（type=5, content是JSON格式的goodsId/goodsName）
    {
        '_desc': '买家发送商品卡片（JSON内容）',
        '_expect_type': 'goods_card',
        'message': {
            'from': {'uid': '100005', 'role': 'user'},
            'type': 5,
            'msg_id': 'msg005',
            'timestamp': 1700000005000,
            'content': json.dumps({
                'goodsId': '998877665544',
                'goodsName': '真皮牛皮带男款自动扣',
                'minGroupPrice': 3980,
                'thumbUrl': 'https://img.pddpic.com/goods/img5.jpg',
            }),
        },
    },
]


def _scan_goods_fields(obj, path=''):
    """递归扫描对象，找出任何含 goods_id/goodsId/goodsName 的字段路径"""
    hits = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            cur_path = f'{path}.{k}' if path else k
            if k in ('goods_id', 'goodsId', 'goodsName', 'goods_name', 'goodsImg',
                      'thumbUrl', 'sourceGoodsId', 'sourceGoodsName', 'minGroupPrice'):
                hits.append((cur_path, v))
            hits.extend(_scan_goods_fields(v, cur_path))
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            hits.extend(_scan_goods_fields(item, f'{path}[{i}]'))
    return hits


def _detect_footfall(parsed, raw_msg):
    """检测浏览足迹"""
    source_goods = parsed.get('source_goods')
    is_enter = parsed.get('is_enter_session', False)
    if is_enter and source_goods:
        return True, f"goods_id={source_goods.get('goods_id','')} name={source_goods.get('goods_name','')[:20]}"
    # 未命中，扫描原始字段
    hits = _scan_goods_fields(raw_msg)
    if hits:
        paths = ', '.join(f'{p}={repr(v)[:40]}' for p, v in hits[:5])
        return False, f'is_enter_session={is_enter}，未提取到source_goods。原始字段: {paths}'
    return False, f'is_enter_session={is_enter}，未提取到source_goods，原始消息无商品字段'


def _detect_goods_url(parsed, raw_msg):
    """检测商品链接识别"""
    source_goods = parsed.get('source_goods')
    content = parsed.get('content', '')
    if source_goods and source_goods.get('goods_id'):
        return True, f"goods_id={source_goods['goods_id']} url={source_goods.get('goods_url','')[:60]}"
    # 检测原始content是否含拼多多URL
    raw_content = (raw_msg.get('message') or raw_msg).get('content', '')
    if isinstance(raw_content, str) and ('yangkeduo' in raw_content or 'pinduoduo' in raw_content):
        m = re.search(r'[?&]goods_id=(\d+)', raw_content)
        if m:
            return False, f'原始content含goods_id={m.group(1)}，但解析后未提取到source_goods（可能正则未匹配）'
        return False, f'原始content含拼多多URL但无goods_id参数'
    return False, '消息内容不含拼多多商品链接'


def _detect_source_page(parsed, raw_msg):
    """检测来源页识别"""
    from_goods_detail = parsed.get('from_goods_detail', False)
    source_page = parsed.get('source_page', '')
    if from_goods_detail or source_page:
        return True, f"from_goods_detail={from_goods_detail} source_page={source_page!r}"
    # 检查原始content
    raw_content = (raw_msg.get('message') or raw_msg).get('content', '')
    if isinstance(raw_content, str) and ('来自' in raw_content or 'detail' in raw_content.lower()):
        return False, f'原始content含"来自"关键词但未识别为来源页: {raw_content[:60]!r}'
    hits = _scan_goods_fields(raw_msg)
    if hits:
        paths = ', '.join(f'{p}={repr(v)[:40]}' for p, v in hits[:3])
        return False, f'未识别来源页，但原始消息含商品字段: {paths}'
    return False, '消息内容不含来源页标识'


def _detect_goods_card(parsed, raw_msg):
    """检测商品卡片识别"""
    msg_type = parsed.get('msg_type', '')
    source_goods = parsed.get('source_goods')
    order_info = parsed.get('order_info', {})
    if msg_type == 'goods' and (source_goods or order_info.get('goods_id')):
        gid = (source_goods or {}).get('goods_id') or order_info.get('goods_id', '')
        gname = (source_goods or {}).get('goods_name') or order_info.get('goods_name', '')
        return True, f"msg_type=goods goods_id={gid} name={str(gname)[:20]}"
    hits = _scan_goods_fields(raw_msg)
    if hits:
        paths = ', '.join(f'{p}={repr(v)[:40]}' for p, v in hits[:3])
        return False, f'未识别商品卡片，但原始消息含: {paths}'
    return False, f'msg_type={msg_type}，未提取到商品信息'


def run_detection():
    # 延迟导入，确保 channel 包可用
    try:
        from channel.pinduoduo.pdd_message import (
            parse_message, _extract_goods_from_url, _extract_source_goods_from_biz
        )
    except ImportError as e:
        print(f'{RED}无法导入 pdd_message: {e}{RESET}')
        sys.exit(1)

    # 统计
    hits = {'footfall': 0, 'goods_url': 0, 'source_page': 0, 'goods_card': 0}
    totals = {'footfall': 0, 'goods_url': 0, 'source_page': 0, 'goods_card': 0}

    print(_head('\n' + '='*60))
    print(_head('  买家上下文检测脚本 - detect_buyer_context.py'))
    print(_head('='*60 + '\n'))

    for i, raw_msg in enumerate(TEST_MESSAGES, 1):
        desc = raw_msg.get('_desc', f'消息#{i}')
        expect_type = raw_msg.get('_expect_type', 'footfall')
        # 去掉内部字段再解析
        msg_data = {k: v for k, v in raw_msg.items() if not k.startswith('_')}

        parsed = parse_message(msg_data)

        print(f'{BOLD}[{i}] {desc}{RESET}')

        if parsed is None:
            print(f'  消息摘要: {_fail("parse_message() 返回 None（解析失败）")}')
            print()
            continue

        buyer_id = parsed.get('buyer_id', '')
        content = parsed.get('content', '')
        msg_type = parsed.get('msg_type', '')
        is_enter = parsed.get('is_enter_session', False)
        source_goods = parsed.get('source_goods')
        from_goods_detail = parsed.get('from_goods_detail', False)
        source_page = parsed.get('source_page', '')

        print(f'  消息摘要: buyer_id={buyer_id!r}  msg_type={msg_type!r}  '
              f'is_enter={is_enter}  content={content[:50]!r}')
        print(f'  解析结果: source_goods={source_goods}  from_goods_detail={from_goods_detail}  '
              f'source_page={source_page!r}')

        # 根据 expect_type 做对应检测
        if expect_type == 'footfall':
            totals['footfall'] += 1
            ok, reason = _detect_footfall(parsed, msg_data)
            if ok: hits['footfall'] += 1
            status = _ok(reason) if ok else _fail(reason)
            print(f'  浏览足迹: {status}')

        elif expect_type == 'goods_url':
            totals['goods_url'] += 1
            ok, reason = _detect_goods_url(parsed, msg_data)
            if ok: hits['goods_url'] += 1
            status = _ok(reason) if ok else _fail(reason)
            print(f'  商品链接: {status}')

        elif expect_type == 'source_page':
            totals['source_page'] += 1
            ok, reason = _detect_source_page(parsed, msg_data)
            if ok: hits['source_page'] += 1
            status = _ok(reason) if ok else _fail(reason)
            print(f'  来源页面: {status}')
            # 来源页消息可能同时含商品字段
            biz_key = (msg_data.get('message') or msg_data).get('push_biz_context') or {}
            if biz_key:
                from channel.pinduoduo.pdd_message import _extract_source_goods_from_biz
                sg = _extract_source_goods_from_biz(biz_key)
                if sg:
                    sg_id = sg.get('goods_id', '')
                    sg_name = sg.get('goods_name', '')[:20]
                    print(f'  附带商品: {_ok(f"goods_id={sg_id} name={sg_name}")}')
        elif expect_type == 'goods_card':
            totals['goods_card'] += 1
            ok, reason = _detect_goods_card(parsed, msg_data)
            if ok: hits['goods_card'] += 1
            status = _ok(reason) if ok else _fail(reason)
            print(f'  商品卡片: {status}')

        # 未命中时输出全字段扫描
        if expect_type in ('footfall', 'goods_url', 'source_page', 'goods_card'):
            check_ok = hits.get(expect_type, 0) > (totals.get(expect_type, 1) - 1)
            if not check_ok:
                all_hits = _scan_goods_fields(msg_data)
                if all_hits:
                    print(f'  {YELLOW}全字段扫描（含商品相关字段）:{RESET}')
                    for path, val in all_hits[:8]:
                        print(f'    {path} = {repr(val)[:60]}')

        print()

    # ── 汇总 ──
    print(_head('='*60))
    print(_head('  检测结果汇总'))
    print(_head('='*60))
    categories = [
        ('浏览足迹 (footfall)', 'footfall'),
        ('商品链接 (goods_url)', 'goods_url'),
        ('来源页面 (source_page)', 'source_page'),
        ('商品卡片 (goods_card)', 'goods_card'),
    ]
    all_pass = True
    for label, key in categories:
        h = hits[key]
        t = totals[key]
        if t == 0:
            print(f'  {label}: {YELLOW}无测试用例{RESET}')
            continue
        rate = h / t * 100
        bar = '█' * h + '░' * (t - h)
        color = GREEN if h == t else (YELLOW if h > 0 else RED)
        print(f'  {label}: {color}{bar} {h}/{t} ({rate:.0f}%){RESET}')
        if h < t:
            all_pass = False

    print()
    if all_pass:
        print(_ok('所有检测项全部命中！'))
    else:
        print(_warn('部分检测项未命中，请检查上方详情'))
    print()


if __name__ == '__main__':
    run_detection()
