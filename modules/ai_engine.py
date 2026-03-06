# -*- coding: utf-8 -*-
"""
AI主引擎模块（三层处理核心 + 意图识别 + 多轮对话）
功能说明：整合规则引擎、知识库引擎、豆包AI，实现三层递进处理
处理流程：
  第一层：规则引擎 → 0成本，目标覆盖20%消息
  第二层：知识库 → 0成本，目标覆盖55%消息
  第三层：豆包AI → 有成本，处理剩余25%消息
增强功能：
  - 意图识别（doubao-lite，快速判断退款/换号/查询等）
  - 多轮对话上下文（30分钟内保持会话连续性）
  - 情绪安抚（doubao-pro，高质量回复）
  - 退款AI决策（doubao-pro，关键决策）
"""

import uuid
import time
import random
from .rules_engine import RulesEngine
from .knowledge_engine import KnowledgeEngine
from .doubao_ai import DoubaoAI
from .emotion_detector import EmotionDetector
from models import Message, Blacklist, Shop, ConversationContext
from models.database import db, get_beijing_time
import config


class AIEngine:
    """
    AI主引擎（三层处理 + 意图识别 + 多轮对话）
    说明：统一入口，协调三层处理流程
    每条消息按顺序尝试三层处理，越早处理成本越低
    """

    def __init__(self):
        """初始化三层引擎、情绪识别器"""
        self.rules_engine = RulesEngine()
        self.knowledge_engine = KnowledgeEngine(
            similarity_threshold=config.KNOWLEDGE_SIMILARITY_THRESHOLD
        )
        self.doubao_ai = DoubaoAI()
        self.emotion_detector = EmotionDetector()

    def process_message(self, shop_id: int, buyer_id: str, buyer_name: str,
                        message: str, order_id: str = '', msg_type: str = 'text',
                        image_url: str = '') -> dict:
        """
        处理买家消息（三层处理主入口）
        功能：
            1. 检查黑名单
            2. 意图识别（doubao-lite，快速判断）
            3. 情绪识别
            4. 依次尝试：规则引擎 → 知识库 → 豆包AI
            5. 多轮对话上下文管理
            6. 记录消息日志
        参数：
            shop_id - 店铺ID
            buyer_id - 买家平台ID
            buyer_name - 买家昵称
            message - 消息内容
            order_id - 订单号（可选）
            msg_type - 消息类型（text/image）
            image_url - 图片URL（图片消息时）
        返回：
            {
                'reply': '回复内容',
                'process_by': '处理方式（rule/knowledge/ai/human）',
                'needs_human': 是否转人工,
                'emotion_level': 情绪级别（0-4）,
                'intent': 意图类型（refund/exchange/query等）,
                'action': 动作类型（如换号）
            }
        """
        # 获取店铺和行业信息
        shop = Shop.query.get(shop_id)
        if not shop or not shop.industry:
            return self._make_result('抱歉，系统配置错误，请联系客服。', 'error')

        industry_id = shop.industry_id

        # 1. 检查黑名单（行业内共享）
        is_blacklisted = self._check_blacklist(buyer_id, industry_id)

        # 2. 情绪识别（本地关键词规则，无成本）
        emotion = self.emotion_detector.detect(message)
        emotion_level = emotion['level']
        needs_human = emotion['needs_human'] or is_blacklisted

        # 3. 意图识别（doubao-lite，快速低成本）
        intent = 'other'
        if config.DOUBAO_API_KEY:
            intent_result = self.doubao_ai.recognize_intent(message)
            intent = intent_result.get('intent', 'other')

        # 4. 初始化消息记录
        msg_record = self._save_incoming_message(
            shop_id=shop_id,
            buyer_id=buyer_id,
            buyer_name=buyer_name,
            order_id=order_id,
            content=message,
            msg_type=msg_type,
            image_url=image_url,
            emotion_level=emotion_level,
            needs_human=needs_human,
            intent=intent,
        )

        # 5. 情绪严重 → 使用doubao-pro安抚后转人工
        if needs_human:
            if emotion_level >= 2 and config.DOUBAO_API_KEY:
                # 使用doubao-pro生成高质量安抚回复
                soothe_result = self.doubao_ai.soothe_emotion(
                    message, emotion_level, shop.get_effective_prompt()
                )
                appease = soothe_result.get('reply', '')
            else:
                appease = self.emotion_detector.get_appease_message(emotion_level)
            if is_blacklisted and not appease:
                appease = '您好，您的消息已收到，专属客服将尽快为您处理。'

            self._update_message_record(msg_record, 'human', 0, True)
            return {
                'reply': appease or '您的问题正在处理中，请稍候。',
                'process_by': 'human',
                'needs_human': True,
                'emotion_level': emotion_level,
                'intent': intent,
                'action': '',
                'success': True,
            }

        # 6. 退款意图 → 直接走退款决策流程（doubao-pro）
        if intent == 'refund' and config.DOUBAO_API_KEY:
            # 优先从PddOrder表查询真实订单数据，提升退款决策质量
            order_info = self._get_order_info_string(shop_id, order_id)
            refund_result = self.doubao_ai.handle_refund_decision(
                message, order_info, shop.get_effective_prompt()
            )
            if refund_result['success']:
                process_by = 'ai'
                # 退款决策为需要人工时，转人工处理
                if refund_result['decision'] == 'human':
                    process_by = 'human'
                    needs_human = True
                self._update_message_record(
                    msg_record, process_by, refund_result.get('tokens', 0), needs_human
                )
                return {
                    'reply': refund_result['reply'],
                    'process_by': process_by,
                    'needs_human': needs_human,
                    'emotion_level': emotion_level,
                    'intent': intent,
                    'action': 'refund_decision',
                    'ai_decision': refund_result.get('decision', ''),
                    'success': True,
                }

        # 7. 图片消息处理（doubao-vision-pro）
        if msg_type == 'image' and image_url:
            if shop.industry.vision_enabled:
                system_prompt = shop.get_effective_prompt()
                result = self.doubao_ai.analyze_image(image_url, message, system_prompt)
                self._update_message_record(msg_record, 'ai', result.get('tokens', 0))
                return {
                    'reply': result['reply'],
                    'process_by': 'ai_vision',
                    'needs_human': False,
                    'emotion_level': emotion_level,
                    'intent': intent,
                    'action': '',
                    'success': result.get('success', False),
                }
            else:
                self._update_message_record(msg_record, 'human', 0, True)
                return {
                    'reply': '收到您的图片，请稍候，客服将为您处理。',
                    'process_by': 'human',
                    'needs_human': True,
                    'emotion_level': emotion_level,
                    'intent': intent,
                    'action': '',
                    'success': True,
                }

        # === 三层文字消息处理 ===

        # 第一层：规则引擎（0成本）
        rule_result = self.rules_engine.match(message, industry_id)
        if rule_result:
            self._update_message_record(msg_record, 'rule', 0)
            return {
                'reply': rule_result['reply'],
                'process_by': 'rule',
                'needs_human': False,
                'emotion_level': emotion_level,
                'intent': intent,
                'action': rule_result.get('action', ''),
                'action_params': rule_result.get('action_params', {}),
                'success': True,
            }

        # 第二层：知识库检索（0成本）
        kb_result = self.knowledge_engine.search(message, industry_id)
        if kb_result:
            self._update_message_record(msg_record, 'knowledge', 0)
            return {
                'reply': kb_result['reply'],
                'process_by': 'knowledge',
                'needs_human': False,
                'emotion_level': emotion_level,
                'intent': intent,
                'action': '',
                'success': True,
            }

        # 第三层：豆包AI多轮对话（doubao-lite，有成本）
        system_prompt = shop.get_effective_prompt()
        context = self._get_or_create_context(shop_id, buyer_id)
        context_history = context.get_context() if context else []

        ai_result = self.doubao_ai.chat(
            message, system_prompt, industry_id,
            use_cache=(len(context_history) == 0),  # 有上下文时不用缓存
            context=context_history,
        )

        # 更新多轮对话上下文
        if context and ai_result.get('success'):
            context.add_turn(message, ai_result['reply'],
                             max_turns=config.MAX_CONTEXT_TURNS)
            context.last_intent = intent
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()

        self._update_message_record(msg_record, 'ai', ai_result.get('tokens', 0))

        return {
            'reply': ai_result['reply'],
            'process_by': 'ai',
            'needs_human': False,
            'emotion_level': emotion_level,
            'intent': intent,
            'action': '',
            'from_cache': ai_result.get('from_cache', False),
            'success': ai_result.get('success', False),
        }

    def _get_or_create_context(self, shop_id: int, buyer_id: str):
        """
        获取或创建买家的多轮对话上下文
        功能：查询现有会话，超时则重置；不存在则新建
        参数：shop_id - 店铺ID，buyer_id - 买家ID
        返回：ConversationContext 对象
        """
        try:
            context = ConversationContext.query.filter_by(
                shop_id=shop_id,
                buyer_id=buyer_id,
            ).first()

            if context:
                # 超时则重置会话
                if context.is_expired(config.CONTEXT_TIMEOUT_MINUTES):
                    context.reset()
                    context.session_id = uuid.uuid4().hex
                    db.session.commit()
                return context
            else:
                # 创建新会话
                context = ConversationContext(
                    shop_id=shop_id,
                    buyer_id=buyer_id,
                    session_id=uuid.uuid4().hex,
                    created_at=get_beijing_time(),
                )
                db.session.add(context)
                db.session.commit()
                return context
        except Exception:
            db.session.rollback()
            return None

    def _check_blacklist(self, buyer_id: str, industry_id: int) -> bool:
        """
        检查买家是否在黑名单中
        功能：同一行业的所有店铺共享黑名单
        参数：buyer_id - 买家ID，industry_id - 行业ID
        返回：True=在黑名单中，False=正常
        """
        entry = Blacklist.query.filter_by(
            buyer_id=buyer_id,
            industry_id=industry_id,
            is_active=True,
        ).first()
        return entry is not None

    def _save_incoming_message(self, shop_id, buyer_id, buyer_name, order_id,
                               content, msg_type, image_url, emotion_level,
                               needs_human, intent='other') -> Message:
        """
        保存买家消息到数据库
        功能：记录所有消息，用于数据分析、人工复核、AI学习
        """
        msg = Message(
            shop_id=shop_id,
            buyer_id=buyer_id,
            buyer_name=buyer_name,
            order_id=order_id,
            direction='in',
            content=content,
            msg_type=msg_type,
            image_url=image_url,
            emotion_level=emotion_level,
            needs_human=needs_human,
            status='pending',
            msg_time=get_beijing_time(),
        )
        db.session.add(msg)
        db.session.commit()
        return msg

    def _update_message_record(self, msg: Message, process_by: str,
                               token_used: int, needs_human: bool = False):
        """
        更新消息处理记录
        功能：记录消息的处理方式和token消耗
        """
        msg.process_by = process_by
        msg.token_used = token_used
        msg.needs_human = needs_human
        msg.is_transferred = needs_human
        msg.status = 'processed'
        msg.processed_at = get_beijing_time()
        db.session.commit()

    def _get_order_info_string(self, shop_id: int, order_id: str) -> str:
        """
        获取订单信息字符串，供AI退款决策使用
        功能：优先从PddOrder表查询真实订单数据；如无数据则降级为简单字符串
        参数：
            shop_id - 店铺ID
            order_id - 订单号
        返回：订单信息自然语言字符串
        """
        if not order_id:
            return '未提供订单号'
        try:
            from models.pdd_order import PddOrder
            order = PddOrder.query.filter_by(
                shop_id=shop_id, order_id=order_id
            ).first()
            if order:
                return order.to_info_string()
        except Exception:
            pass
        # 降级：没有真实数据时返回简单字符串
        return f'订单号：{order_id}'

    def _make_result(self, reply: str, process_by: str) -> dict:
        """
        生成标准错误结果格式
        功能：统一返回格式（用于错误情况）
        """
        return {
            'reply': reply,
            'process_by': process_by,
            'needs_human': False,
            'emotion_level': 0,
            'intent': 'other',
            'action': '',
            'success': False,
        }

    def add_to_blacklist(self, buyer_id: str, buyer_name: str,
                         industry_id: int, reason: str, level: int = 1):
        """
        将买家加入黑名单
        功能：手动或自动将恶意买家加入黑名单（行业内共享）
        参数：
            buyer_id - 买家平台ID
            buyer_name - 买家昵称
            industry_id - 行业ID（行业内共享黑名单）
            reason - 加入原因
            level - 黑名单级别（1=观察，2=警告，3=封禁）
        """
        from models import Blacklist
        existing = Blacklist.query.filter_by(
            buyer_id=buyer_id,
            industry_id=industry_id,
        ).first()

        if existing:
            existing.level = max(existing.level, level)
            existing.reason = reason
            existing.is_active = True
            existing.updated_at = get_beijing_time()
        else:
            entry = Blacklist(
                industry_id=industry_id,
                buyer_id=buyer_id,
                buyer_name=buyer_name,
                reason=reason,
                level=level,
                is_active=True,
                created_at=get_beijing_time(),
            )
            db.session.add(entry)

        db.session.commit()

