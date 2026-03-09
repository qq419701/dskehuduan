# -*- coding: utf-8 -*-
"""
aikefu 服务器 REST API 客户端
主接口：POST /api/webhook/message
"""
import logging
import requests

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 15


class ServerAPI:
    """调用 aikefu Flask 服务器的 REST API"""

    def __init__(self, base_url: str = "http://8.145.43.255:6000"):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})

    # ------------------------------------------------------------------
    # 主消息处理接口
    # ------------------------------------------------------------------

    def send_message(
        self,
        shop_id: int,
        buyer_id: str,
        buyer_name: str,
        content: str,
        order_id: str = "",
        msg_type: str = "text",
        image_url: str = "",
    ) -> dict:
        """
        推送买家消息到aikefu服务器，获取AI回复
        POST /api/webhook/message
        返回：{"success": true, "reply": "...", "needs_human": false, "process_by": "rule"}
        """
        payload = {
            "shop_id": shop_id,
            "buyer_id": buyer_id,
            "buyer_name": buyer_name,
            "order_id": order_id or "",
            "content": content,
            "msg_type": msg_type,
            "image_url": image_url or "",
        }
        try:
            resp = self.session.post(
                f"{self.base_url}/api/webhook/message",
                json=payload,
                timeout=DEFAULT_TIMEOUT,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.error("调用服务器API失败: %s", e)
            return {"success": False, "error": str(e)}

    def send_message_by_token(
        self,
        shop_token: str,
        buyer_id: str,
        buyer_name: str,
        content: str,
        order_id: str = "",
        msg_type: str = "text",
        order_info: dict = None,
    ) -> dict:
        """
        通过shop_token推送买家消息（插件接口）
        POST /api/webhook/pdd
        """
        payload = {
            "shop_token": shop_token,
            "buyer_id": buyer_id,
            "buyer_name": buyer_name,
            "content": content,
            "msg_type": msg_type,
            "order_id": order_id or "",
            "order_info": order_info or {},
        }
        try:
            resp = self.session.post(
                f"{self.base_url}/api/webhook/pdd",
                json=payload,
                timeout=DEFAULT_TIMEOUT,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.error("调用pdd webhook失败: %s", e)
            return {"success": False, "error": str(e)}

    # ------------------------------------------------------------------
    # 健康检查
    # ------------------------------------------------------------------

    def health_check(self) -> bool:
        """检查服务器是否可达"""
        try:
            resp = self.session.get(
                f"{self.base_url}/api/health",
                timeout=5,
            )
            return resp.status_code < 500
        except requests.RequestException:
            return False

    # ------------------------------------------------------------------
    # 插件相关接口（X-Shop-Token 鉴权）
    # ------------------------------------------------------------------

    def plugin_register(
        self,
        shop_token: str,
        plugin_id: str,
        name: str,
        action_codes: list,
        version: str = "2.0.0",
    ) -> dict:
        """
        注册插件能力
        POST /api/plugin/register
        """
        payload = {
            "plugin_id": plugin_id,
            "name": name,
            "description": "dskehuduan 自动化客户端",
            "action_codes": action_codes,
            "client_version": version,
        }
        try:
            resp = self.session.post(
                f"{self.base_url}/api/plugin/register",
                json=payload,
                headers={"X-Shop-Token": shop_token},
                timeout=DEFAULT_TIMEOUT,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.error("插件注册失败: %s", e)
            return {"success": False, "error": str(e)}

    def plugin_heartbeat(self, shop_token: str, plugin_id: str) -> dict:
        """
        发送心跳，保持插件在线状态
        POST /api/plugin/heartbeat
        """
        try:
            resp = self.session.post(
                f"{self.base_url}/api/plugin/heartbeat",
                json={"plugin_id": plugin_id},
                headers={"X-Shop-Token": shop_token},
                timeout=10,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.warning("心跳发送失败: %s", e)
            return {"success": False, "error": str(e)}

    def plugin_get_tasks(self, shop_token: str) -> list:
        """
        获取待执行任务列表
        GET /api/plugin/tasks
        返回：[{id, task_id, action_code, payload, status, ...}]
        """
        try:
            resp = self.session.get(
                f"{self.base_url}/api/plugin/tasks",
                headers={"X-Shop-Token": shop_token},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                return data
            return data.get("tasks", []) if isinstance(data, dict) else []
        except requests.RequestException as e:
            logger.warning("拉取任务失败: %s", e)
            return []

    def plugin_task_done(self, shop_token: str, task_id: str, result: dict) -> dict:
        """
        上报任务执行成功
        POST /api/plugin/tasks/{task_id}/done
        """
        try:
            resp = self.session.post(
                f"{self.base_url}/api/plugin/tasks/{task_id}/done",
                json={"result": result},
                headers={"X-Shop-Token": shop_token},
                timeout=DEFAULT_TIMEOUT,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.error("上报任务成功失败: %s", e)
            return {"success": False, "error": str(e)}

    def plugin_task_fail(self, shop_token: str, task_id: str, error: str) -> dict:
        """
        上报任务执行失败
        POST /api/plugin/tasks/{task_id}/fail
        """
        try:
            resp = self.session.post(
                f"{self.base_url}/api/plugin/tasks/{task_id}/fail",
                json={"error": error},
                headers={"X-Shop-Token": shop_token},
                timeout=DEFAULT_TIMEOUT,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.error("上报任务失败状态失败: %s", e)
            return {"success": False, "error": str(e)}
