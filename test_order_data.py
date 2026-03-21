#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
验证订单数据是否正确存入上下文管理器
用法：python test_order_data.py --shop-id 1 --buyer-id 9560420983768
"""
import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--shop-id', required=True, help='店铺ID')
    parser.add_argument('--buyer-id', required=True, help='买家ID')
    args = parser.parse_args()

    try:
        from channel.pinduoduo.pdd_context import BuyerContextManager
        mgr = BuyerContextManager()
        ctx = mgr.get_context(args.shop_id, args.buyer_id)
        print(f"上下文内容：")
        print(f"  order_sn: {ctx.get('order_sn', '(空)')}")
        print(f"  order_info: {ctx.get('order_info', '(空)')}")
        print(f"  current_goods: {ctx.get('current_goods', '(空)')}")
        print(f"  orders: {len(ctx.get('orders', []))} 条")
    except Exception as e:
        print(f"错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()
