#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
转人工功能快速测试脚本
用法：python tools/test_transfer.py --shop_id 1 --buyer_id xxx --buyer_name 超
"""
import asyncio
import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from channel.pinduoduo.pdd_transfer import PddTransferHuman


async def main():
    parser = argparse.ArgumentParser(description='测试拼多多转人工')
    parser.add_argument('--shop_id', default='1', help='店铺ID')
    parser.add_argument('--buyer_id', default='', help='买家ID')
    parser.add_argument('--buyer_name', default='', help='买家昵称')
    parser.add_argument('--order_sn', default='', help='订单号')
    parser.add_argument('--target_agent', default='', help='指定客服名')
    args = parser.parse_args()

    # 读取配置
    cfg = config.load_config()
    shop_cookies = {}
    for shop in cfg.get("active_shops", []):
        if str(shop.get("id", "")) == str(args.shop_id):
            shop_cookies = shop.get("cookies", {})
            break

    anti = config.get_anti_content(args.shop_id)

    print(f"Cookies 数量: {len(shop_cookies)}")
    print(f"Anti content: {'已配置' if anti else '❌ 未配置（这是转人工失败的主要原因！）'}")
    print(f"开始测试转人工: buyer_id={args.buyer_id} buyer_name={args.buyer_name}")

    if not shop_cookies:
        print("❌ 未找到店铺 cookies，请先登录拼多多")
        sys.exit(1)

    transfer = PddTransferHuman(
        shop_id=args.shop_id,
        cookies=shop_cookies,
        strategy='first',
    )

    result = await transfer.transfer(
        buyer_id=args.buyer_id,
        order_sn=args.order_sn,
        buyer_name=args.buyer_name,
        target_agent=args.target_agent,
    )
    await transfer.close()

    print(f"\n结果: {result}")
    if result.get('success'):
        print(f"✅ 成功！已转移给: {result.get('agent')}")
    else:
        print(f"❌ 失败: {result.get('message')}")


if __name__ == '__main__':
    asyncio.run(main())
