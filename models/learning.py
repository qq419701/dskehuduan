# -*- coding: utf-8 -*-
"""
学习记录模型（学习中心）
功能说明：记录AI回复中需要人工审核的问题，人工确认后自动入库知识库
每日凌晨自动筛选低置信度/错误回复，供运营人员每天5分钟审核
"""

from .database import db, get_beijing_time


class LearningRecord(db.Model):
    """
    AI学习记录表（学习中心）
    说明：存储待人工审核的AI问答对
    运营人员审核通过后，直接入库到知识库供后续使用
    """
    __tablename__ = 'learning_records'

    # 主键ID
    id = db.Column(db.Integer, primary_key=True)

    # 所属行业ID（知识库按行业共享）
    industry_id = db.Column(db.Integer, db.ForeignKey('industries.id'), nullable=False)

    # 所属店铺ID（记录来源店铺）
    shop_id = db.Column(db.Integer, db.ForeignKey('shops.id'), nullable=True)

    # 买家原始消息（原话）
    buyer_message = db.Column(db.Text, nullable=False)

    # AI给出的回复
    ai_reply = db.Column(db.Text, nullable=False)

    # AI处理方式（rule/knowledge/ai）
    process_by = db.Column(db.String(20), default='ai')

    # AI意图识别结果
    intent = db.Column(db.String(50), default='other')

    # AI置信度（0.0-1.0，低于阈值的才需要审核）
    confidence = db.Column(db.Float, default=0.5)

    # 审核状态：
    #   pending  = 待审核
    #   approved = 已审核确认（入库知识库）
    #   rejected = 已审核拒绝（AI回复不合适，丢弃）
    #   modified = 已修改后入库（用正确答案替换AI回复）
    review_status = db.Column(db.String(20), default='pending')

    # 运营人员填写的正确答案（如果AI回复有误）
    correct_answer = db.Column(db.Text, default='')

    # 是否已入库知识库
    is_added_to_kb = db.Column(db.Boolean, default=False)

    # 关联的知识库条目ID（入库后记录）
    kb_item_id = db.Column(db.Integer, db.ForeignKey('knowledge_base.id'), nullable=True)

    # 审核人（操作员用户名）
    reviewed_by = db.Column(db.String(100), default='')

    # 审核时间（北京时间）
    reviewed_at = db.Column(db.DateTime, nullable=True)

    # 记录创建时间（北京时间）
    created_at = db.Column(db.DateTime, default=get_beijing_time)

    # 关联行业
    industry = db.relationship('Industry', foreign_keys=[industry_id])

    def get_final_answer(self) -> str:
        """
        获取最终答案（优先使用运营人员修正的答案）
        返回：用于入库的最终回复内容
        """
        if self.correct_answer and self.correct_answer.strip():
            return self.correct_answer.strip()
        return self.ai_reply

    def __repr__(self):
        return f'<LearningRecord {self.id}: status={self.review_status}>'
