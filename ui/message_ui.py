# -*- coding: utf-8 -*-
"""
实时消息监控界面
左侧：买家会话列表，右侧：消息详情
"""
from PyQt6.QtCore import Qt, pyqtSignal, QDateTime
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QListWidget, QListWidgetItem,
    QLabel, QScrollArea, QFrame, QSizePolicy, QSplitter,
)


class MessageBubble(QFrame):
    """消息气泡组件"""

    def __init__(self, content: str, direction: str, process_by: str = "", parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(2)

        is_outbound = direction == "out"

        # 消息内容
        text = QLabel(content)
        text.setWordWrap(True)
        text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        if is_outbound:
            text.setStyleSheet(
                "background: #1890ff; color: white; border-radius: 8px; padding: 8px 12px;"
            )
            text.setAlignment(Qt.AlignmentFlag.AlignRight)
        else:
            text.setStyleSheet(
                "background: #f0f0f0; color: #333; border-radius: 8px; padding: 8px 12px;"
            )
            text.setAlignment(Qt.AlignmentFlag.AlignLeft)

        layout.addWidget(text)

        # 处理方式标签
        if process_by and is_outbound:
            tag_map = {
                "rule": "规则",
                "knowledge": "知识库",
                "ai": "豆包AI",
                "human": "人工",
            }
            tag_text = tag_map.get(process_by, process_by)
            tag = QLabel(f"[{tag_text}]")
            tag.setStyleSheet("color: #999; font-size: 10px;")
            tag.setAlignment(Qt.AlignmentFlag.AlignRight)
            layout.addWidget(tag)


class ConversationItem(QListWidgetItem):
    """会话列表项"""

    def __init__(self, shop_id: int, buyer_id: str, buyer_name: str):
        super().__init__()
        self.shop_id = shop_id
        self.buyer_id = buyer_id
        self.buyer_name = buyer_name
        self.setText(f"{buyer_name or buyer_id}")


class MessagePage(QWidget):
    """实时消息监控页面"""

    def __init__(self, db_client=None, parent=None):
        super().__init__(parent)
        self.db_client = db_client
        self._conversations: dict = {}  # buyer_id -> ConversationItem
        self._current_buyer: str = ""
        self._current_shop: int = 0
        self._init_ui()

    def _init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # 左侧：会话列表
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(8, 8, 8, 8)

        left_title = QLabel("💬 买家会话")
        left_title.setStyleSheet("font-size: 14px; font-weight: bold;")
        left_layout.addWidget(left_title)

        self.conversation_list = QListWidget()
        self.conversation_list.setMaximumWidth(220)
        self.conversation_list.currentItemChanged.connect(self._on_conversation_selected)
        left_layout.addWidget(self.conversation_list)

        # 右侧：消息详情
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(8, 8, 8, 8)

        # 顶部买家信息
        self.buyer_info_label = QLabel("请选择左侧会话")
        self.buyer_info_label.setStyleSheet("font-size: 14px; font-weight: bold; padding: 4px;")
        right_layout.addWidget(self.buyer_info_label)

        # 消息滚动区域
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.message_container = QWidget()
        self.message_layout = QVBoxLayout(self.message_container)
        self.message_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.message_layout.setSpacing(8)
        self.message_layout.setContentsMargins(8, 8, 8, 8)

        self.scroll_area.setWidget(self.message_container)
        right_layout.addWidget(self.scroll_area)

        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setSizes([220, 600])

        layout.addWidget(splitter)

    def set_db_client(self, db_client):
        self.db_client = db_client

    def add_message(self, shop_id: int, msg: dict):
        """
        添加新消息（由采集线程通过信号槽调用）。
        更新会话列表，如果当前正在查看该会话则实时刷新消息区域。
        """
        buyer_id = msg.get("buyer_id", "")
        buyer_name = msg.get("buyer_name", "") or buyer_id

        # 更新或新建会话项
        key = f"{shop_id}_{buyer_id}"
        if key not in self._conversations:
            item = ConversationItem(shop_id, buyer_id, buyer_name)
            self.conversation_list.insertItem(0, item)
            self._conversations[key] = item
        else:
            # 把会话移到顶部
            item = self._conversations[key]
            row = self.conversation_list.row(item)
            self.conversation_list.takeItem(row)
            self.conversation_list.insertItem(0, item)

        # 如果当前正在查看此会话，刷新消息
        if self._current_buyer == buyer_id and self._current_shop == shop_id:
            self._append_bubble(msg)

    def _on_conversation_selected(self, current: QListWidgetItem, _previous):
        """切换会话"""
        if not isinstance(current, ConversationItem):
            return
        self._current_buyer = current.buyer_id
        self._current_shop = current.shop_id
        self.buyer_info_label.setText(f"👤 {current.buyer_name or current.buyer_id}")
        self._load_messages()

    def _load_messages(self):
        """从数据库加载消息记录"""
        self._clear_messages()
        if not self.db_client or not self._current_buyer:
            return

        try:
            messages = self.db_client.get_recent_messages(self._current_shop, limit=50)
            for msg in messages:
                if msg.get("buyer_id") == self._current_buyer:
                    self._append_bubble(msg)
        except Exception:
            pass

        # 滚动到底部
        self._scroll_to_bottom()

    def _append_bubble(self, msg: dict):
        """添加一个消息气泡"""
        content = msg.get("content", "")
        direction = msg.get("direction", "in")
        process_by = msg.get("process_by", "")

        bubble = MessageBubble(content, direction, process_by)
        self.message_layout.addWidget(bubble)
        self._scroll_to_bottom()

    def _clear_messages(self):
        """清空消息区域"""
        while self.message_layout.count():
            item = self.message_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _scroll_to_bottom(self):
        """滚动到消息底部"""
        scrollbar = self.scroll_area.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
