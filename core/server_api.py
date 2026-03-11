# -*- coding: utf-8 -*-
"""
aikefu 服务器 REST API 客户端
主接口：POST /api/webhook/message
"""
import logging
import time

import requests

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 15


class ServerAPI:
    """调用 aikefu Flask 服务器的 REST API"""

    def __init__(self, base_url: str = "http://8.145.43.255:5000"):
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
        order_sn: str = "",
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
            "order_sn": order_sn or order_id or "",
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
        order_sn: str = "",
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
            "order_sn": order_sn or order_id or "",
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
    # 客户端账号认证接口
    # ------------------------------------------------------------------

    def client_login(self, username: str, password: str) -> dict:
        """
        客户端账号登录
        POST /api/client/login
        返回: {"success": true, "client_token": "xxx", "username": "admin"}
        """
        try:
            resp = self.session.post(
                f"{self.base_url}/api/client/login",
                json={"username": username, "password": password},
                timeout=DEFAULT_TIMEOUT,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.error("客户端登录失败: %s", e)
            return {"success": False, "error": str(e)}

    def client_get_shops(self, client_token: str) -> list:
        """
        获取登录用户名下的所有店铺（含 shop_token）
        GET /api/client/shops
        Header: X-Client-Token: <client_token>
        返回: [{"id":1, "name":"店铺名", "shop_token":"xxx", "platform":"pdd", ...}]
        """
        try:
            resp = self.session.get(
                f"{self.base_url}/api/client/shops",
                headers={"X-Client-Token": client_token},
                timeout=DEFAULT_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                return data
            return data.get("shops", []) if isinstance(data, dict) else []
        except requests.RequestException as e:
            logger.error("获取店铺列表失败: %s", e)
            return []

    def client_logout(self, client_token: str) -> dict:
        """
        客户端登出
        POST /api/client/logout
        """
        try:
            resp = self.session.post(
                f"{self.base_url}/api/client/logout",
                json={},
                headers={"X-Client-Token": client_token},
                timeout=DEFAULT_TIMEOUT,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.warning("登出请求失败: %s", e)
            return {"success": False, "error": str(e)}

    def client_refresh_token(self, client_token: str) -> dict:
        """
        刷新 client_token 有效期
        POST /api/client/refresh
        """
        try:
            resp = self.session.post(
                f"{self.base_url}/api/client/refresh",
                json={},
                headers={"X-Client-Token": client_token},
                timeout=DEFAULT_TIMEOUT,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.warning("刷新Token失败: %s", e)
            return {"success": False, "error": str(e)}

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
        for attempt in range(2):
            try:
                resp = self.session.post(
                    f"{self.base_url}/api/plugin/register",
                    json=payload,
                    headers={"X-Shop-Token": shop_token},
                    timeout=DEFAULT_TIMEOUT,
                )
                resp.raise_for_status()
                return resp.json()
            except requests.ConnectionError as e:
                if attempt == 0:
                    logger.debug("插件注册连接中断，静默重试: %s", e)
                    time.sleep(0.5)
                else:
                    logger.debug("插件注册重试仍失败: %s", e)
                    return {"success": False, "error": str(e)}
            except requests.RequestException as e:
                logger.error("插件注册失败: %s", e)
                return {"success": False, "error": str(e)}

    def plugin_heartbeat(self, shop_token: str, plugin_id: str) -> dict:
        """
        发送心跳，保持插件在线状态
        POST /api/plugin/heartbeat
        """
        for attempt in range(2):
            try:
                resp = self.session.post(
                    f"{self.base_url}/api/plugin/heartbeat",
                    json={"plugin_id": plugin_id},
                    headers={"X-Shop-Token": shop_token},
                    timeout=10,
                )
                resp.raise_for_status()
                return resp.json()
            except requests.ConnectionError as e:
                if attempt == 0:
                    logger.debug("心跳连接中断，静默重试: %s", e)
                    time.sleep(0.5)
                else:
                    logger.debug("心跳重试仍失败: %s", e)
                    return {"success": False, "error": str(e)}
            except requests.RequestException as e:
                logger.warning("心跳发送失败: %s", e)
                return {"success": False, "error": str(e)}

    def plugin_get_tasks(self, shop_token: str) -> list:
        """
        获取待执行任务列表
        GET /api/plugin/tasks
        返回：[{id, task_id, action_code, payload, status, ...}]
        """
        for attempt in range(2):
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
            except requests.ConnectionError as e:
                if attempt == 0:
                    logger.debug("拉取任务连接中断，静默重试: %s", e)
                    time.sleep(0.5)
                else:
                    logger.debug("拉取任务重试仍失败: %s", e)
                    return []
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

    def reply_to_buyer(
        self,
        shop_token: str,
        buyer_id: str,
        reply: str,
        task_id: str = "",
    ) -> dict:
        """
        将 AI 回复内容发送给买家（v2.1 新增）
        POST /api/plugin/reply_to_buyer
        payload: {buyer_id, reply, task_id}
        Header: X-Shop-Token
        返回: {success, message}
        """
        try:
            resp = self.session.post(
                f"{self.base_url}/api/plugin/reply_to_buyer",
                json={
                    "buyer_id": buyer_id,
                    "reply": reply,
                    "task_id": task_id or "",
                },
                headers={"X-Shop-Token": shop_token},
                timeout=DEFAULT_TIMEOUT,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.error("发送AI回复给买家失败: %s", e)
            return {"success": False, "error": str(e)}
