# -*- coding: utf-8 -*-
"""
WS 原始消息调试抓包脚本
用法：
  1. 先确保 pdd_config.json 里已有登录 cookies 和 im_token
  2. python debug_ws_sniffer.py
  3. 用小号打开任意商品详情页 → 点击客服咨询 → 发一条文字消息
  4. 观察终端输出，所有原始WS帧和解析结果都会打印并保存到 debug_ws_dump.jsonl

关注字段：
  - push_biz_context / bizContext / biz_context 中有没有 goods_id / sourceGoods
  - msg_category 是不是 4 或 5
  - source_goods 字段能否被解析到
"""
import asyncio
import json
import logging
import time
import sys
import os

# 把项目根目录加入 sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import websockets
from websockets.exceptions import ConnectionClosed

# ── 日志设置 ──────────────────────────────────────────────
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger('debug_sniffer')

DUMP_FILE = 'debug_ws_dump.jsonl'
HEARTBEAT_INTERVAL = 30

# ── 读取配置 ──────────────────────────────────────────────
def load_config():
    config_path = os.path.join(os.path.dirname(__file__), 'pdd_config.json')
    if not os.path.exists(config_path):
        logger.error('找不到 pdd_config.json，请先配置')
        sys.exit(1)
    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)

# ── 打印高亮字段 ──────────────────────────────────────────
def highlight_fields(data: dict, depth=0, path=''):
    """递归找出和浏览足迹/商品相关的所有字段，高亮打印"""
    INTEREST_KEYS = {
        'goods_id', 'goodsId', 'sourceGoodsId',
        'goods_name', 'goodsName', 'sourceGoodsName',
        'goods_img', 'goodsImg', 'sourceGoodsImg',
        'goods_url', 'goodsUrl',
        'sourceGoods', 'source_goods',
        'currentGoods', 'recommendGoods', 'linkGoods',
        'push_biz_context', 'bizContext', 'biz_context', 'pushBizContext',
        'msg_category', 'msgCategory',
        'source_page', 'sourcePage',
        'from_goods_detail', 'fromGoodsDetail',
        'context', 'msgContext',
        'minGroupPrice', 'price',
        'thumbUrl', 'mainImgUrl', 'goodsImageUrl',
    }
    if not isinstance(data, dict):
        return
    for k, v in data.items():
        cur_path = f'{path}.{k}' if path else k
        if k in INTEREST_KEYS:
            print(f'  ★ [{cur_path}] = {repr(v)[:300]}')
        if isinstance(v, dict):
            highlight_fields(v, depth+1, cur_path)
        elif isinstance(v, list):
            for i, item in enumerate(v):
                if isinstance(item, dict):
                    highlight_fields(item, depth+1, f'{cur_path}[{i}]')
        # 嵌套JSON字符串
        elif isinstance(v, str) and v.startswith('{'):
            try:
                inner = json.loads(v)
                if isinstance(inner, dict):
                    highlight_fields(inner, depth+1, cur_path + '(json)')
            except Exception:
                pass


def dump_message(raw: str, parsed_msg: dict = None, index: int = 0):
    """保存原始消息到 JSONL 文件"""
    record = {
        'index': index,
        'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
        'raw': raw[:5000],  # 最多存5000字符
        'parsed': parsed_msg,
    }
    with open(DUMP_FILE, 'a', encoding='utf-8') as f:
        f.write(json.dumps(record, ensure_ascii=False) + '\n')


def try_parse_message(data: dict):
    """用项目自带解析器解析，捕获结果"""
    try:
        from channel.pinduoduo.pdd_message import parse_message
        return parse_message(data)
    except Exception as e:
        return {'parse_error': str(e)}

# ── 核心连接循环 ──────────────────────────────────────────
async def sniff(im_token: str, cookies: dict, shop_id: str = 'debug'):
    version = time.strftime('%Y%m%d%H%M', time.localtime())
    ws_url = f'wss://m-ws.pinduoduo.com/?access_token={im_token}&role=mall_cs&client=web&version={version}'
    cookie_str = '; '.join(f'{k}={v}' for k, v in cookies.items())
    headers = {
        'Cookie': cookie_str,
        'Origin': 'https://mms.pinduoduo.com',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    }

    ver = tuple(int(x) for x in websockets.__version__.split('.')[:2])
    kw = 'additional_headers' if ver >= (14, 0) else 'extra_headers'

    logger.info('═' * 60)
    logger.info('开始连接 WS: %s', ws_url[:80])
    logger.info('输出文件: %s', os.path.abspath(DUMP_FILE))
    logger.info('═' * 60)
    logger.info('⏳ 等待消息中... 请用小号打开商品详情页并发起咨询')
    logger.info('═' * 60)

    msg_index = 0

    async with websockets.connect(ws_url, **{kw: headers},
                                   ping_interval=None,
                                   open_timeout=15, close_timeout=10) as ws:
        logger.info('✅ WS 连接成功！')

        # 心跳任务
        async def heartbeat():
            while True:
                await asyncio.sleep(HEARTBEAT_INTERVAL)
                try:
                    await ws.send(json.dumps({'cmd': 'ping', 'timestamp': int(time.time() * 1000)}))
                    logger.debug('💓 心跳已发送')
                except Exception:
                    break

        hb_task = asyncio.create_task(heartbeat())

        try:
            async for raw_msg in ws:
                if isinstance(raw_msg, bytes):
                    raw_msg = raw_msg.decode('utf-8')

                # 解析JSON
                try:
                    data = json.loads(raw_msg)
                except Exception:
                    logger.warning('非JSON消息: %s', raw_msg[:200])
                    continue

                cmd = data.get('cmd') or data.get('type') or data.get('response') or ''

                # 过滤心跳
                if cmd in ('pong', 'ack', 'ping', 'auth'):
                    logger.debug('⚙️  系统帧: cmd=%s', cmd)
                    continue

                msg_index += 1
                print('\n' + '─' * 60)
                print(f'📨 消息 #{msg_index}  时间: {time.strftime("%H:%M:%S")}  cmd={cmd!r}')
                print('─' * 60)

                # 打印原始JSON（格式化）
                print('【原始数据】')
                try:
                    print(json.dumps(data, ensure_ascii=False, indent=2)[:3000])
                except Exception:
                    print(raw_msg[:3000])

                # 高亮关键字段
                print('\n【关键字段扫描】')
                highlight_fields(data)

                # 用项目解析器解析
                parsed = try_parse_message(data)
                print('\n【parse_message() 解析结果】')
                if parsed:
                    print(json.dumps(parsed, ensure_ascii=False, indent=2))
                    # 重点输出
                    sg = parsed.get('source_goods')
                    ie = parsed.get('is_enter_session')
                    print(f'\n  → source_goods   = {sg}')
                    print(f'  → is_enter_session = {ie}')
                    print(f'  → msg_type         = {parsed.get("msg_type")}')
                    print(f'  → content          = {parsed.get("content", "")[:100]}')
                    if sg:
                        print('  🎯 ✅ 浏览足迹已捕获！goods_id=%s  goods_name=%s' % (
                            sg.get('goods_id', ''), sg.get('goods_name', ''))) 
                    elif ie:
                        print('  ⚠️  进入会话但未捕获到浏览足迹（source_goods=None）')
                        print('     → 请检查上方原始数据中是否有 goods_id/sourceGoods 等字段')
                else:
                    print('  parse_message() 返回 None（消息被过滤或不识别）')

                print('─' * 60)

                # 保存到文件
                dump_message(raw_msg, parsed, msg_index)
                logger.info('已保存到 %s（共 %d 条）', DUMP_FILE, msg_index)

        except ConnectionClosed as e:
            logger.warning('连接断开: %s', e)
        except KeyboardInterrupt:
            logger.info('用户中断')
        finally:
            hb_task.cancel()
            try:
                await hb_task
            except asyncio.CancelledError:
                pass

    logger.info('\n═' * 60)
    logger.info('共接收 %d 条有效消息，已保存到: %s', msg_index, os.path.abspath(DUMP_FILE))
    logger.info('═' * 60)

# ── 入口 ──────────────────────────────────────────────────
def main():
    cfg = load_config()

    # 支持多店铺配置，取第一个
    shops = cfg.get('shops') or cfg.get('shop_list') or []
    if not shops and cfg.get('im_token'):
        # 单店铺配置
        im_token = cfg['im_token']
        cookies = cfg.get('cookies') or {}
        shop_id = cfg.get('shop_id', 'default')
    elif shops:
        shop = shops[0]
        im_token = shop.get('im_token') or shop.get('imToken') or ''
        cookies = shop.get('cookies') or {}
        shop_id = str(shop.get('shop_id') or shop.get('shopId') or 'shop0')
    else:
        logger.error('pdd_config.json 中未找到 im_token 或 shops 配置')
        logger.error('请确认格式，参考：{"im_token": "xxx", "cookies": {"key": "val"}}')
        sys.exit(1)

    if not im_token:
        logger.error('im_token 为空，请先在 pdd_config.json 中配置')
        sys.exit(1)

    logger.info('使用店铺: %s  im_token前缀: %s...', shop_id, im_token[:20])

    # 清空上次的 dump 文件（可选）
    if os.path.exists(DUMP_FILE):
        os.rename(DUMP_FILE, DUMP_FILE + '.bak')
        logger.info('已备份上次记录到 %s.bak', DUMP_FILE)

    asyncio.run(sniff(im_token, cookies, shop_id))


if __name__ == '__main__':
    main()