# -*- coding: utf-8 -*-
# pdd_transfer.py - HTTP API version, no browser launch
import logging
import random
import requests

logger = logging.getLogger(__name__)
_round_robin_index = {}


class PddTransferHuman:
    def __init__(self, shop_id: str, cookies: dict, strategy: str = "first"):
        self.shop_id = shop_id
        self.cookies = cookies or {}
        self.strategy = strategy
        self._session = None

    def _get_session(self):
        if self._session is None:
            self._session = requests.Session()
            self._session.headers.update({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Referer": "https://mms.pinduoduo.com/",
                "Origin": "https://mms.pinduoduo.com",
                "Content-Type": "application/json",
            })
            for k, v in self.cookies.items():
                self._session.cookies.set(k, v, domain=".pinduoduo.com")
        return self._session

    async def transfer(self, buyer_id="", order_sn="", buyer_name=""):
        try:
            sess = self._get_session()
            agents = self._get_agent_list(sess)
            if agents is None:
                return {"success": False, "agent": "", "message": "获取客服列表失败，cookies可能已失效"}
            if not agents:
                return {"success": False, "agent": "", "message": "没有可用客服"}
            logger.info("获取到 %d 个客服: %s", len(agents), [a.get("name") for a in agents])
            chosen = self._choose_agent(agents)
            if not chosen:
                return {"success": False, "agent": "", "message": "策略未能选出客服"}
            success = self._do_transfer(sess, chosen, buyer_id, order_sn, buyer_name)
            if success:
                logger.info("HTTP转移会话成功，目标客服: %s", chosen.get("name", ""))
                return {"success": True, "agent": chosen.get("name", ""), "message": "已转移给客服 " + chosen.get("name", "")}
            return {"success": False, "agent": "", "message": "转移接口调用失败"}
        except Exception as e:
            logger.error("HTTP转移会话异常: %s", e)
            return {"success": False, "agent": "", "message": str(e)}

    def _get_agent_list(self, sess):
        try:
            r = sess.post(
                "https://mms.pinduoduo.com/latitude/assign/getAssignCsList",
                json={},
                timeout=10
            )
            logger.info("客服列表接口响应: %s", r.text[:500])
            if r.status_code == 200:
                data = r.json()
                if data.get("success"):
                    cs_map = (data.get("result") or {}).get("csList") or {}
                    agents = []
                    for uid_key, item in cs_map.items():
                        name = (item.get("csName") or item.get("username") or item.get("nickname") or uid_key)
                        uid = str(item.get("id") or uid_key)
                        agents.append({
                            "name": name,
                            "uid": uid,
                            "unreplied": item.get("unreplyNum", 0),
                            "raw": item,
                        })
                    if agents:
                        return agents
        except Exception as e:
            logger.warning("客服列表接口失败: %s", e)
        return None

    def _do_transfer(self, sess, agent, buyer_id, order_sn, buyer_name):
        agent_uid = agent.get("uid", "")

        # 真实转移接口: plateau/chat/move_conversation (抓包确认)
        # 同时带上 buyer_id 作为 uid
        uid = buyer_id or ""

        attempts = [
            {
                "url": "https://mms.pinduoduo.com/plateau/chat/move_conversation",
                "data": {
                    "uid": uid,
                    "to_cs_uid": agent_uid,
                    "trans_reason": 10000,
                },
            },
            {
                "url": "https://mms.pinduoduo.com/latitude/assign/transferConv",
                "data": {
                    "toUid": agent_uid,
                    "buyerId": uid,
                    "toBuyerId": uid,
                    "orderSn": order_sn,
                    "buyerName": buyer_name,
                    "transReason": 10000,
                },
            },
            {
                "url": "https://mms.pinduoduo.com/plateau/conv/transfer",
                "data": {
                    "to_uid": agent_uid,
                    "buyer_id": uid,
                    "order_sn": order_sn,
                },
            },
        ]

        for attempt in attempts:
            try:
                r = sess.post(attempt["url"], json=attempt["data"], timeout=10)
                logger.info("转移接口 %s 响应: %s", attempt["url"], r.text[:300])
                if r.status_code == 200:
                    try:
                        resp = r.json()
                        if (resp.get("success") or
                                (isinstance(resp.get("result"), dict) and resp["result"].get("result") == "ok") or
                                resp.get("errorCode") == 1000000 or
                                resp.get("code") in (0, 200)):
                            return True
                    except Exception:
                        pass
            except Exception as e:
                logger.warning("转移接口失败 %s: %s", attempt["url"], e)
        return False

    def _choose_agent(self, agents):
        if not agents:
            return None
        if self.strategy == "random":
            return random.choice(agents)
        if self.strategy == "least_busy":
            return min(agents, key=lambda a: a.get("unreplied", 0))
        if self.strategy == "round_robin":
            global _round_robin_index
            idx = _round_robin_index.get(self.shop_id, 0)
            chosen = agents[idx % len(agents)]
            _round_robin_index[self.shop_id] = (idx + 1) % len(agents)
            return chosen
        return agents[0]

    async def close(self):
        if self._session:
            self._session.close()
            self._session = None
