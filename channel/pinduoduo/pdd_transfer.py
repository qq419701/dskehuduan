# -*- coding: utf-8 -*-
# pdd_transfer.py - 纯 HTTP API 版本，不启动任何浏览器
import logging
import random
import requests

logger = logging.getLogger(__name__)
_round_robin_index = {}

def get_transfer_config() -> dict:
    import config as cfg
    return cfg.get_pdd_transfer_settings()

class PddTransferHuman:
    """
    拼多多转人工 - 纯 HTTP API 方式。
    直接用 cookies 调用拼多多接口，不启动任何浏览器，不占用 user_data_dir。

    :param shop_id:  店铺唯一标识（用于 round_robin 轮询隔离）
    :param cookies:  登录后保存的 cookies 字典 {name: value}
    :param strategy: 分配策略：first / random / least_busy / round_robin
    """

    def __init__(self, shop_id: str, cookies: dict, strategy: str = "first"):
        self.shop_id = shop_id
        self.cookies = cookies or {}
        self.strategy = strategy
        self._session = None

    # ------------------------------------------------------------------
    # 内部：复用 requests.Session（懒初始化）
    # ------------------------------------------------------------------

    def _get_session(self) -> requests.Session:
        if self._session is None:
            self._session = requests.Session()
            self._session.headers.update({
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) \
                    AppleWebKit/537.36 (KHTML, like Gecko) \
                    Chrome/120.0.0.0 Safari/537.36"
                ),
                "Referer": "https://mms.pinduoduo.com/",
                "Origin":  "https://mms.pinduoduo.com",
                "Content-Type": "application/json",
            })
            for k, v in self.cookies.items():
                self._session.cookies.set(k, v, domain=".pinduoduo.com")
        return self._session

    # ------------------------------------------------------------------
    # 核心：转移会话
    # ------------------------------------------------------------------

    async def transfer(self, buyer_id: str = "", order_sn: str = "",
                       buyer_name: str = "") -> dict:
        """
        调用拼多多 HTTP 接口完成转移会话。

        :param buyer_id:   买家 ID
        :param order_sn:   订单号
        :param buyer_name: 买家昵称
        :return: {"success": bool, "agent": str, "message": str}
        """
        try:
            sess = self._get_session()

            # 1. 获取客服列表
            agents = self._get_agent_list(sess)
            if agents is None:
                return {"success": False, "agent": "", "message": "获取客服列表失败，cookies 可能已失效"}
            if not agents:
                return {"success": False, "agent": "", "message": "没有可用客服"}

            logger.info("获取到 %d 个客服: %s", len(agents), [a.get("name") for a in agents])

            # 2. 按策略选择目标客服
            chosen = self._choose_agent(agents)
            if not chosen:
                return {"success": False, "agent": "", "message": "策略未能选出客服"}

            # 3. 调用转移接口
            success = self._do_transfer(sess, chosen, buyer_id, order_sn, buyer_name)
            if success:
                logger.info("HTTP 转移会话成功，目标客服: %s", chosen.get("name", ""))
                return {
                    "success": True,
                    "agent": chosen.get("name", ""),
                    "message": "已成功转移给客服 " + chosen.get("name", ""),
                }
            return {"success": False, "agent": "", "message": "转移接口调用失败"}

        except Exception as e:
            logger.error("HTTP 转移会话异常: %s", e)
            return {"success": False, "agent": "", "message": str(e)}

    # ------------------------------------------------------------------
    # 获取客服列表
    # ------------------------------------------------------------------

    def _get_agent_list(self, sess: requests.Session):
        """
        调用 getAssignCsList 接口获取可接受转移的客服列表。
        返回 None 表示接口异常（cookies 失效等），返回 [] 表示没有可用客服。
        """
        try:
            r = sess.post(
                "https://mms.pinduoduo.com/latitude/assign/getAssignCsList",
                json={"wechatCheck": True},
                timeout=10,
            )
            logger.info("客服列表接口响应: %s", r.text[:500])
            if r.status_code == 200:
                data = r.json()
                if data.get("success"):
                    cs_map = (data.get("result") or {}).get("csList") or {}
                    agents = []
                    for uid_key, item in cs_map.items():
                        name = (
                            item.get("csName") or item.get("username") or
                            item.get("nickname") or uid_key
                        )
                        uid = str(item.get("id") or uid_key)
                        agents.append({
                            "name": name,
                            "uid": uid,
                            "csid": uid_key,
                            "unreplied": item.get("unreplyNum", 0),
                            "raw": item,
                        })
                    if agents:
                        return agents
                    # success=True 但 csList 为空
                    return []
        except Exception as e:
            logger.warning("客服列表接口失败: %s", e)
        return None   # 表示接口异常

    # ------------------------------------------------------------------
    # 调用转移接口
    # ------------------------------------------------------------------

    def _do_transfer(self, sess: requests.Session, agent: dict,
                     buyer_id: str, order_sn: str, buyer_name: str) -> bool:
        """
        依次尝试多个已知的转移接口，任意一个成功即返回 True。
        """
        agent_uid  = agent.get("uid", "")
        agent_csid = agent.get("csid", "")

        attempts = [
            # 接口 1：latitude/assign/transferConv（最常用）
            {
                "url": "https://mms.pinduoduo.com/latitude/assign/transferConv",
                "json": {
                    "toUid":      agent_uid,
                    "toBuyerId":  buyer_id,
                    "buyerId":    buyer_id,
                    "orderSn":    order_sn,
                    "buyerName":  buyer_name,
                    "transReason": 10000,
                },
            },
            # 接口 2：plateau/conv/transfer
            {
                "url": "https://mms.pinduoduo.com/plateau/conv/transfer",
                "json": {
                    "to_uid":   agent_uid,
                    "buyer_id": buyer_id,
                    "order_sn": order_sn,
                },
            },
            # 接口 3：chats/transferSession
            {
                "url": "https://mms.pinduoduo.com/chats/transferSession",
                "json": {
                    "staffId":    agent_uid,
                    "buyerId":    buyer_id,
                    "orderSn":    order_sn,
                    "buyerName":  buyer_name,
                },
            },
            # 接口 4：assistant/session/transfer（form-data 格式）
            {
                "url": "https://mms.pinduoduo.com/assistant/session/transfer",
                "data": {
                    "staffId":    agent_uid,
                    "buyerId":    buyer_id,
                    "orderSn":    order_sn,
                    "buyerName":  buyer_name,
                },
            },
        ]

        for attempt in attempts:
            try:
                url = attempt["url"]
                if "json" in attempt:
                    r = sess.post(url, json=attempt["json"], timeout=10)
                else:
                    r = sess.post(url, data=attempt["data"], timeout=10)

                logger.info("转移接口 %s 响应 [%d]: %s", url, r.status_code, r.text[:300])

                if r.status_code == 200:
                    try:
                        resp = r.json()
                        if (resp.get("success") or
                                resp.get("result") is not None or
                                resp.get("errorCode") in (0, 1000000) or
                                resp.get("code") in (0, 200)):
                            return True
                    except Exception:
                        # 非 JSON 响应但状态码 200，也视为成功
                        pass
            except Exception as e:
                logger.warning("转移接口失败 %s: %s", attempt["url"], e)

        return False

    # ------------------------------------------------------------------
    # 策略选择
    # ------------------------------------------------------------------

    def _choose_agent(self, agents: list) -> dict:
        if not agents:
            return None
        if self.strategy == "random":
            return random.choice(agents)
        if self.strategy == "least_busy":
            return min(agents, key=lambda a: a.get("unreplied", 0))
        if self.strategy == "round_robin":
            global _round_robin_index
            idx    = _round_robin_index.get(self.shop_id, 0)
            chosen = agents[idx % len(agents)]
            _round_robin_index[self.shop_id] = (idx + 1) % len(agents)
            return chosen
        # 默认 first
        return agents[0]

    # ------------------------------------------------------------------
    # 释放资源（保持与旧接口兼容，HTTP 版本无浏览器需要关闭）
    # ------------------------------------------------------------------

    async def close(self):
        if self._session:
            self._session.close()
            self._session = None