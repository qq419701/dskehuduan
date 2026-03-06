# -*- coding: utf-8 -*-
"""
拼多多订单管理路由模块
功能说明：展示浏览器插件抓取的拼多多订单数据
支持按店铺、买家、订单状态筛选，及关联聊天记录查看
预留扩展：其他平台（淘宝、京东、抖店）可参照此文件创建对应路由
"""

from flask import Blueprint, render_template, request
from flask_login import login_required, current_user
from models import Shop, Message
from models.pdd_order import PddOrder

# 创建PDD订单蓝图
pdd_orders_bp = Blueprint('pdd_orders', __name__)


@pdd_orders_bp.route('/')
@login_required
def index():
    """
    拼多多订单列表页
    功能：分页展示所有已抓取的订单，支持按店铺、买家、状态筛选
    """
    page = request.args.get('page', 1, type=int)
    shop_id = request.args.get('shop_id', type=int)
    buyer_q = request.args.get('buyer', '').strip()
    order_q = request.args.get('order', '').strip()
    status_filter = request.args.get('status', '').strip()

    # 获取当前用户可见的店铺
    if current_user.is_admin():
        shops = Shop.query.filter_by(is_active=True).all()
    else:
        shops = Shop.query.filter_by(
            industry_id=current_user.industry_id, is_active=True
        ).all()

    shop_ids = [s.id for s in shops]

    # 构建订单查询
    query = PddOrder.query.filter(PddOrder.shop_id.in_(shop_ids))

    if shop_id and shop_id in shop_ids:
        query = query.filter_by(shop_id=shop_id)
    if buyer_q:
        query = query.filter(
            (PddOrder.buyer_id.contains(buyer_q)) |
            (PddOrder.buyer_name.contains(buyer_q))
        )
    if order_q:
        query = query.filter(PddOrder.order_id.contains(order_q))
    if status_filter:
        query = query.filter_by(status=status_filter)

    orders = query.order_by(PddOrder.captured_at.desc()).paginate(
        page=page, per_page=20
    )

    return render_template(
        'pdd_orders/index.html',
        orders=orders,
        shops=shops,
        selected_shop=shop_id,
        buyer_q=buyer_q,
        order_q=order_q,
        status_filter=status_filter,
        status_options=['待付款', '待发货', '已发货', '已完成', '退款中', '已退款'],
    )


@pdd_orders_bp.route('/<order_id>')
@login_required
def detail(order_id: str):
    """
    拼多多订单详情页
    功能：展示订单完整信息，以及该买家在该店铺的所有聊天记录
    """
    # 权限：只查看当前用户可访问店铺下的订单
    if current_user.is_admin():
        shop_ids = [s.id for s in Shop.query.filter_by(is_active=True).all()]
    else:
        shop_ids = [s.id for s in Shop.query.filter_by(
            industry_id=current_user.industry_id, is_active=True
        ).all()]

    order = PddOrder.query.filter(
        PddOrder.order_id == order_id,
        PddOrder.shop_id.in_(shop_ids),
    ).first_or_404()

    # 查询该买家在该店铺的聊天记录
    messages = Message.query.filter_by(
        shop_id=order.shop_id,
        buyer_id=order.buyer_id,
    ).order_by(Message.msg_time.desc()).limit(50).all()

    return render_template(
        'pdd_orders/detail.html',
        order=order,
        messages=messages,
    )
