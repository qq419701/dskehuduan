# -*- coding: utf-8 -*-
"""
买家意图信号检测工具
检测拼多多WS消息中的3类商品意图信号：
  ① 浏览足迹    - 买家打开会话时系统自动推送（买家无感知）
  ② 来自详情页  - 买家从商品详情页点"联系客服"进入
  ③ 商品链接    - 买家主动发送拼多多商品URL

用法:
  python tools/detect_buyer_signals.py --demo           # 运行内置演示
  python tools/detect_buyer_signals.py --file ws.json   # 检测JSON文件
  python tools/detect_buyer_signals.py --stdin          # 从stdin读取逐行JSON
"""
import sys
import os
import json
import re
import argparse

# 确保可以导入项目模块
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from channel.pinduoduo.pdd_message import (
        parse_message,
        _extract_goods_from_url,
        _extract_source_goods_from_biz,
    )
    _HAVE_PDD_MODULES = True
except ImportError:
    _HAVE_PDD_MODULES = False


# ──────────────────────────────────────────────────────────────────────────────
# 内部辅助
# ──────────────────────────────────────────────────────────────────────────────

def _get_biz(msg: dict) -> tuple:
    """从 WS 消息的 message 层取 biz 上下文，返回 (biz_dict, source_key)"""
    inner = msg.get('message') or msg
    for key in ('push_biz_context', 'bizContext', 'biz_context', 'pushBizContext'):
        biz = inner.get(key)
        if isinstance(biz, dict) and biz:
            return biz, key
    return {}, ''


def _extract_goods_from_biz_manual(biz: dict, path_prefix: str) -> dict:
    """手动扫描 biz 中所有可能包含商品信息的路径"""
    # 扁平字段
    goods_id = str(biz.get('goods_id') or biz.get('goodsId') or biz.get('sourceGoodsId') or '')
    goods_name = str(biz.get('goods_name') or biz.get('goodsName') or biz.get('sourceGoodsName') or '')
    goods_img = str(biz.get('goods_img') or biz.get('goodsImg') or biz.get('sourceGoodsImg') or biz.get('goodsImageUrl') or '')
    goods_price = biz.get('goods_price') or biz.get('goodsPrice') or biz.get('minGroupPrice') or 0
    if goods_id or goods_name:
        return {
            'goods_id': goods_id, 'goods_name': goods_name,
            'goods_img': goods_img, 'goods_price': goods_price,
            'source_path': f'{path_prefix}.goods_id/goodsId',
        }

    # sourceGoods / source_goods 对象
    for field in ('sourceGoods', 'source_goods'):
        obj = biz.get(field)
        if isinstance(obj, dict) and obj:
            gid = str(obj.get('goodsId') or obj.get('goods_id') or '')
            gname = str(obj.get('goodsName') or obj.get('goods_name') or '')
            gimg = str(obj.get('goodsImg') or obj.get('thumbUrl') or obj.get('mainImgUrl') or '')
            gprice = obj.get('minGroupPrice') or obj.get('price') or 0
            if gid or gname:
                return {'goods_id': gid, 'goods_name': gname, 'goods_img': gimg,
                        'goods_price': gprice, 'source_path': f'{path_prefix}.{field}'}

    # currentGoods / recommendGoods / linkGoods / goods
    for field in ('currentGoods', 'recommendGoods', 'linkGoods', 'goods'):
        obj = biz.get(field)
        if isinstance(obj, dict) and obj:
            gid = str(obj.get('goodsId') or obj.get('goods_id') or '')
            gname = str(obj.get('goodsName') or obj.get('goods_name') or '')
            gimg = str(obj.get('goodsImg') or obj.get('thumbUrl') or obj.get('mainImgUrl') or obj.get('goodsImageUrl') or '')
            gprice = obj.get('minGroupPrice') or obj.get('price') or 0
            if gid or gname:
                return {'goods_id': gid, 'goods_name': gname, 'goods_img': gimg,
                        'goods_price': gprice, 'source_path': f'{path_prefix}.{field}'}

    # context.sourceGoods 深层嵌套
    ctx = biz.get('context')
    if isinstance(ctx, dict):
        nested = ctx.get('sourceGoods') or {}
        if isinstance(nested, dict) and nested:
            gid = str(nested.get('goodsId') or nested.get('goods_id') or '')
            gname = str(nested.get('goodsName') or nested.get('goods_name') or '')
            gimg = str(nested.get('goodsImg') or nested.get('thumbUrl') or nested.get('mainImgUrl') or '')
            gprice = nested.get('minGroupPrice') or nested.get('price') or 0
            if gid or gname:
                return {'goods_id': gid, 'goods_name': gname, 'goods_img': gimg,
                        'goods_price': gprice, 'source_path': f'{path_prefix}.context.sourceGoods'}

    return None


def _extract_content(raw_ws_msg: dict) -> str:
    """提取消息的文本内容"""
    inner = raw_ws_msg.get('message') or raw_ws_msg
    return str(inner.get('content') or inner.get('msgContent') or '')


# ──────────────────────────────────────────────────────────────────────────────
# 三个核心检测函数
# ──────────────────────────────────────────────────────────────────────────────

def detect_browse_footprint(raw_ws_msg: dict) -> dict:
    """
    ① 检测浏览足迹（被动信号，买家无感知）
    买家打开会话时拼多多系统自动在 WS 消息的 push_biz_context 中携带浏览的商品信息。
    客户不发消息，我们也能知道他在看哪个商品。
    """
    result = {
        'found': False, 'goods_id': '', 'goods_name': '',
        'goods_img': '', 'goods_price': 0, 'source_path': '', 'raw_biz': {}
    }

    # 优先用已有模块（parse_message 已做过完整解析）
    if _HAVE_PDD_MODULES:
        parsed = parse_message(raw_ws_msg)
        if parsed:
            sg = parsed.get('source_goods')
            if sg and isinstance(sg, dict) and (sg.get('goods_id') or sg.get('goods_name')):
                result.update({
                    'found': True,
                    'goods_id': str(sg.get('goods_id') or ''),
                    'goods_name': str(sg.get('goods_name') or ''),
                    'goods_img': str(sg.get('goods_img') or ''),
                    'goods_price': sg.get('goods_price') or 0,
                    'source_path': '(via parse_message → source_goods)',
                })
                biz, _ = _get_biz(raw_ws_msg)
                result['raw_biz'] = biz
                return result

    # 手动扫描所有 biz 键
    inner = raw_ws_msg.get('message') or raw_ws_msg
    for key in ('push_biz_context', 'bizContext', 'biz_context', 'pushBizContext'):
        biz = inner.get(key)
        if not (isinstance(biz, dict) and biz):
            continue
        hit = _extract_goods_from_biz_manual(biz, key)
        if hit:
            result.update({
                'found': True,
                'goods_id': hit['goods_id'],
                'goods_name': hit['goods_name'],
                'goods_img': hit['goods_img'],
                'goods_price': hit['goods_price'],
                'source_path': hit['source_path'],
                'raw_biz': biz,
            })
            return result

    biz, _ = _get_biz(raw_ws_msg)
    result['raw_biz'] = biz
    return result


def detect_from_goods_detail(raw_ws_msg: dict) -> dict:
    """
    ② 检测买家是否从商品详情页点"客服"进入会话（被动信号）
    此时系统会推送一条 is_enter_session=True 的通知消息。
    """
    result = {
        'found': False, 'is_enter_session': False,
        'source_page': '', 'from_goods_detail': False,
        'buyer_id': '', 'raw_biz': {}
    }

    biz, _ = _get_biz(raw_ws_msg)
    result['raw_biz'] = biz

    source_page = str(biz.get('source_page') or biz.get('sourcePage') or biz.get('sourceType') or '')
    from_goods_detail = bool(biz.get('from_goods_detail') or biz.get('fromGoodsDetail'))
    result['source_page'] = source_page
    result['from_goods_detail'] = from_goods_detail

    if _HAVE_PDD_MODULES:
        parsed = parse_message(raw_ws_msg)
        if parsed:
            result['is_enter_session'] = parsed.get('is_enter_session', False)
            result['buyer_id'] = parsed.get('buyer_id', '')
            if not source_page:
                result['source_page'] = str(parsed.get('source_page') or '')
    else:
        inner = raw_ws_msg.get('message') or raw_ws_msg
        msg_category = int(biz.get('msg_category') or biz.get('msgCategory') or 0)
        raw_type = inner.get('type') or inner.get('msgType') or 0
        result['is_enter_session'] = msg_category in (4, 5) or str(raw_type) == '8'

    is_enter = result['is_enter_session']
    sp = result['source_page']
    fg = result['from_goods_detail']

    if (is_enter and sp == 'goods_detail') or (is_enter and fg) or sp == 'goods_detail':
        result['found'] = True

    return result


def detect_goods_link(raw_ws_msg: dict) -> dict:
    """
    ③ 检测买家主动发送的商品链接（主动信号）
    买家自己粘贴拼多多/yangkeduo商品URL到聊天框。
    """
    result = {'found': False, 'goods_id': '', 'goods_url': '', 'content': '', 'match_type': ''}

    content = _extract_content(raw_ws_msg)
    result['content'] = content
    if not content:
        return result

    if _HAVE_PDD_MODULES:
        extracted = _extract_goods_from_url(content)
        if extracted and extracted.get('goods_id'):
            strict_pat = (
                r'https?://(?:mobile\.yangkeduo\.com|mobile\.pinduoduo\.com|yangkeduo\.com)'
                r'/goods(?:\.html|/detail)[^\s]*goods_id=(\d+)'
            )
            match_type = 'strict' if re.search(strict_pat, content) else 'loose'
            url_match = re.search(r'https?://[^\s]+', content)
            goods_url = url_match.group(0) if url_match else ''
            result.update({
                'found': True,
                'goods_id': extracted['goods_id'],
                'goods_url': goods_url,
                'match_type': match_type,
            })
        return result

    # 无模块时手动检测
    strict_pat = (
        r'(https?://(?:mobile\.yangkeduo\.com|mobile\.pinduoduo\.com|yangkeduo\.com)'
        r'/goods(?:\.html|/detail)[^\s]*goods_id=(\d+)[^\s]*)'
    )
    m = re.search(strict_pat, content)
    if m:
        result.update({'found': True, 'goods_id': m.group(2), 'goods_url': m.group(1), 'match_type': 'strict'})
        return result
    if 'yangkeduo' in content or 'pinduoduo' in content:
        m2 = re.search(r'goods_id=(\d+)', content)
        if m2:
            url_match = re.search(r'https?://[^\s]+', content)
            result.update({
                'found': True,
                'goods_id': m2.group(1),
                'goods_url': url_match.group(0) if url_match else '',
                'match_type': 'loose',
            })
    return result


# ──────────────────────────────────────────────────────────────────────────────
# 综合检测
# ──────────────────────────────────────────────────────────────────────────────

def detect_all(raw_ws_msg: dict) -> dict:
    """综合检测全部3个信号，返回汇总结果。"""
    bf = detect_browse_footprint(raw_ws_msg)
    fd = detect_from_goods_detail(raw_ws_msg)
    gl = detect_goods_link(raw_ws_msg)

    signals = []
    best_goods_id = ''
    best_goods_name = ''

    if bf['found']:
        signals.append('browse_footprint')
        if not best_goods_id:
            best_goods_id = bf['goods_id']
            best_goods_name = bf['goods_name']

    if fd['found']:
        signals.append('from_goods_detail')

    if gl['found']:
        signals.append('goods_link')
        if not best_goods_id:
            best_goods_id = gl['goods_id']

    return {
        'browse_footprint': bf,
        'from_goods_detail': fd,
        'goods_link': gl,
        'summary': {
            'has_any_signal': bool(signals),
            'best_goods_id': best_goods_id,
            'best_goods_name': best_goods_name,
            'signal_count': len(signals),
            'signals': signals,
        },
    }


# ──────────────────────────────────────────────────────────────────────────────
# 输出格式化
# ──────────────────────────────────────────────────────────────────────────────

def _fmt_price(price) -> str:
    try:
        p = int(price)
        return f'¥{p/100:.2f}' if p > 0 else ''
    except Exception:
        return ''


def print_result(result: dict, label: str = ''):
    """美观打印 detect_all() 的结果。"""
    SEP = '━' * 52
    if label:
        print(f'\n{SEP}')
        print(label)
        print(SEP)

    bf = result['browse_footprint']
    fd = result['from_goods_detail']
    gl = result['goods_link']
    sm = result['summary']

    # ① 浏览足迹
    if bf['found']:
        price_str = _fmt_price(bf.get('goods_price', 0))
        parts = [f'goods_id={bf['goods_id']}', f'name={bf['goods_name'][:20]}']
        if price_str:
            parts.append(f'price={price_str}')
        parts.append(f'path={bf['source_path']}')
        print(f'① 浏览足迹:    ✅ 命中  {' '.join(parts)}')
    else:
        print('① 浏览足迹:    ❌ 未命中  (买家未打开会话或WS消息未携带商品上下文)')

    # ② 来自详情页
    if fd['found']:
        details = f'source_page={fd['source_page']}  is_enter_session={fd['is_enter_session']}'
        print(f'② 来自详情页:  ✅ 命中  {details}')
    else:
        print(f'② 来自详情页:  ❌ 未命中  (is_enter_session={fd['is_enter_session']}  source_page={repr(fd['source_page'])})')

    # ③ 商品链接
    if gl['found']:
        url_short = gl['goods_url'][:60] + ('...' if len(gl['goods_url']) > 60 else '')
        print(f'③ 商品链接:    ✅ 命中  goods_id={gl['goods_id']}  match={gl['match_type']}  url={url_short}')
    else:
        print('③ 商品链接:    ❌ 未命中  (消息内容中无拼多多商品URL)')

    # 综合
    print()
    if sm['has_any_signal']:
        print(f'综合判断: ✅ 有效信号  最佳商品ID={sm['best_goods_id']}  '
              f'最佳商品名={sm['best_goods_name'][:20] if sm['best_goods_name'] else '(无)'}  '
              f'命中信号数={sm['signal_count']}  信号={sm['signals']}')
    else:
        print('综合判断: ⚠️  无有效商品信号 — 客户咨询内容未关联任何商品')


# ──────────────────────────────────────────────────────────────────────────────
# Demo 测试用例
# ──────────────────────────────────────────────────────────────────────────────

DEMO_CASES = [
    (
        '用例 A: 浏览足迹（push_biz_context 扁平字段）',
        {
            'message': {
                'type': 8, 'from': {'uid': '123456', 'role': 'user'},
                'push_biz_context': {
                    'msg_category': 4,
                    'goods_id': '987654321', 'goods_name': '夏季连衣裙',
                    'goods_img': 'https://img.xxx.com/goods.jpg', 'minGroupPrice': 2999,
                },
            }
        },
    ),
    (
        '用例 B: 浏览足迹（sourceGoods 对象）',
        {
            'message': {
                'type': 8, 'from': {'uid': '123456', 'role': 'user'},
                'push_biz_context': {
                    'msg_category': 5,
                    'sourceGoods': {
                        'goodsId': '111222333', 'goodsName': '运动鞋',
                        'thumbUrl': 'https://img.xxx.com/shoe.jpg', 'minGroupPrice': 8900,
                    },
                },
            }
        },
    ),
    (
        '用例 C: 来自商品详情页（source_page=goods_detail）',
        {
            'message': {
                'type': 8, 'from': {'uid': '789000', 'role': 'user'},
                'push_biz_context': {
                    'msg_category': 4, 'source_page': 'goods_detail',
                    'sourceGoodsId': '555666777',
                },
            }
        },
    ),
    (
        '用例 D: 买家主动发送商品链接',
        {
            'message': {
                'type': 1, 'from': {'uid': '456789', 'role': 'user'},
                'content': '你好，这个商品还有货吗？https://mobile.yangkeduo.com/goods.html?goods_id=998877665&refer_page_name=goods',
            }
        },
    ),
    (
        '用例 E: 普通文字消息（无任何信号）',
        {
            'message': {
                'type': 1, 'from': {'uid': '111222', 'role': 'user'},
                'content': '你好，请问发货多久？',
            }
        },
    ),
    (
        '用例 F: 三个信号同时存在（最强场景）',
        {
            'message': {
                'type': 8, 'from': {'uid': '333444', 'role': 'user'},
                'content': '这个好吗 https://mobile.yangkeduo.com/goods.html?goods_id=112233445',
                'push_biz_context': {
                    'msg_category': 5, 'source_page': 'goods_detail',
                    'sourceGoods': {
                        'goodsId': '112233445', 'goodsName': '测试商品', 'minGroupPrice': 5000,
                    },
                },
            }
        },
    ),
]

def run_demo():
    print()
    print('=' * 52)
    print('  拼多多买家意图信号检测工具 — 内置演示')
    print('=' * 52)
    print()
    print('信号说明:')
    print('  ① 浏览足迹    买家打开会话时系统自动推送，买家无感知')
    print('               → 来源: push_biz_context 中的商品字段')
    print('  ② 来自详情页  买家从商品页点"联系客服"进入会话')
    print('               → 来源: source_page=goods_detail 或 is_enter_session=True')
    print('  ③ 商品链接    买家主动在聊天框发送拼多多/yangkeduo商品URL')
    print('               → 来源: 消息 content 中提取 goods_id')
    print()

    if not _HAVE_PDD_MODULES:
        print('⚠️  未找到 channel.pinduoduo.pdd_message，使用内置逻辑（功能可能受限）')
        print()

    for label, msg in DEMO_CASES:
        result = detect_all(msg)
        print_result(result, label)

    print()
    print('=' * 52)
    print('演示完毕')
    print()
    print('使用真实数据:')
    print('  python tools/detect_buyer_signals.py --file sniff_result.json')
    print('  python tools/detect_buyer_signals.py --file agents_result.json')


# ──────────────────────────────────────────────────────────────────────────────
# 命令行入口
# ──────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='拼多多买家意图信号检测工具（浏览足迹 / 来自详情页 / 商品链接）',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''示例:
  python tools/detect_buyer_signals.py --demo
  python tools/detect_buyer_signals.py --file sniff_result.json
  echo '{"message":{"type":1,"content":"goods_id=123"}}' | python tools/detect_buyer_signals.py --stdin
''',
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--demo', action='store_true', help='运行内置演示用例（默认）')
    group.add_argument('--file', metavar='FILE', help='从JSON文件读取WS消息（单条或数组）')
    group.add_argument('--stdin', action='store_true', help='从stdin逐行读取JSON')
    args = parser.parse_args()

    if args.file:
        with open(args.file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, list):
            print(f'共 {len(data)} 条消息')
            for i, item in enumerate(data, 1):
                result = detect_all(item)
                print_result(result, f'消息 #{i}')
        else:
            result = detect_all(data)
            print_result(result, '消息 #1')
    elif args.stdin:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
                result = detect_all(raw)
                print_result(result)
            except json.JSONDecodeError as e:
                print(f'JSON解析失败: {e}  原文: {line[:80]}')
    else:
        run_demo()


if __name__ == '__main__':
    main()