# -*- coding: utf-8 -*-
"""
多轮对话上下文模型
功能说明：存储买家与AI的多轮对话历史，支持连续对话上下文传递
同一买家在同一店铺的对话会话，超时后自动重置
"""

import json
from .database import db, get_beijing_time


class ConversationContext(db.Model):
    """
    多轮对话上下文表
    说明：记录每个买家的对话历史，AI回复时携带历史上下文
    会话超时（默认30分钟）后自动重置，重新开始新会话
    """
    __tablename__ = 'conversation_contexts'

    # 主键ID
    id = db.Column(db.Integer, primary_key=True)

    # 所属店铺ID
    shop_id = db.Column(db.Integer, db.ForeignKey('shops.id'), nullable=False)

    # 买家平台ID
    buyer_id = db.Column(db.String(100), nullable=False)

    # 会话ID（同一买家多次会话的标识）
    session_id = db.Column(db.String(64), nullable=False)

    # 对话历史（JSON格式存储，[{'role':'user','content':'...'},{'role':'assistant','content':'...'}]）
    context_json = db.Column(db.Text, default='[]')

    # 对话轮次（买家发消息次数）
    turn_count = db.Column(db.Integer, default=0)

    # 意图（最近识别的买家意图）
    last_intent = db.Column(db.String(50), default='other')

    # 最后活跃时间（北京时间，用于判断会话是否超时）
    last_active_at = db.Column(db.DateTime, default=get_beijing_time)

    # 创建时间（北京时间）
    created_at = db.Column(db.DateTime, default=get_beijing_time)

    def get_context(self) -> list:
        """
        获取对话历史列表
        返回：[{'role':'user','content':'...'}, ...]
        """
        try:
            return json.loads(self.context_json or '[]')
        except Exception:
            return []

    def add_turn(self, user_message: str, assistant_reply: str,
                 max_turns: int = 10):
        """
        添加一轮对话（买家消息+AI回复）
        功能：将新一轮对话追加到上下文，超出最大轮次时删除最旧的轮次
        参数：
            user_message - 买家消息
            assistant_reply - AI回复
            max_turns - 最大保留轮次（每轮=用户+AI各一条）
        """
        context = self.get_context()
        context.append({'role': 'user', 'content': user_message})
        context.append({'role': 'assistant', 'content': assistant_reply})

        # 超出最大轮次时，删除最旧的对话（每轮2条消息）
        max_messages = max_turns * 2
        if len(context) > max_messages:
            context = context[-max_messages:]

        self.context_json = json.dumps(context, ensure_ascii=False)
        self.turn_count += 1
        self.last_active_at = get_beijing_time()

    def is_expired(self, timeout_minutes: int = 30) -> bool:
        """
        检查会话是否超时
        参数：timeout_minutes - 超时时间（分钟）
        返回：True=已超时，False=会话有效
        """
        from datetime import timedelta
        if not self.last_active_at:
            return True
        now = get_beijing_time()
        deadline = self.last_active_at + timedelta(minutes=timeout_minutes)
        return now > deadline

    def reset(self):
        """
        重置对话上下文（会话超时后调用）
        功能：清空历史对话，重新开始
        """
        self.context_json = '[]'
        self.turn_count = 0
        self.last_active_at = get_beijing_time()

    def __repr__(self):
        return f'<ConversationContext shop={self.shop_id} buyer={self.buyer_id} turns={self.turn_count}>'
