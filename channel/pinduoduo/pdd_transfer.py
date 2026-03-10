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
                "Content-Type": "application/x-www-form-urlencoded",
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
        urls = [
            "https://mms.pinduoduo.com/assistant/staff/getOnlineStaffList",
            "https://mms.pinduoduo.com/chats/getStaffList",
            "https://mms.pinduoduo.com/assistant/staff/list",
        ]
        for url in urls:
            try:
                r = sess.post(url, data={}, timeout=10)
                logger.info("客服列表接口 %s 响应: %s", url, r.text[:300])
                if r.status_code == 200:
                    data = r.json()
                    items = (data.get("result") or data.get("data") or
                             data.get("staffList") or data.get("list") or [])
                    if isinstance(items, list) and items:
                        agents = []
                        for i, item in enumerate(items):
                            name = (item.get("staffName") or item.get("name") or
                                    item.get("nick") or item.get("username") or str(i))
                            uid = (item.get("staffId") or item.get("id") or
                                   item.get("uid") or item.get("userId") or "")
                            agents.append({
                                "name": name,
                                "uid": str(uid),
                                "unreplied": item.get("waitingCount", 0),
                                "raw": item,
                            })
                        if agents:
                            return agents
            except Exception as e:
                logger.warning("客服列表接口失败 %s: %s", url, e)
        return None

    def _do_transfer(self, sess, agent, buyer_id, order_sn, buyer_name):
        agent_uid = agent.get("uid", "")
        urls = [
            "https://mms.pinduoduo.com/assistant/session/transfer",
            "https://mms.pinduoduo.com/chats/transferSession",
            "https://mms.pinduoduo.com/assistant/chat/transfer",
        ]
        data = {
            "staffId": agent_uid,
            "buyerId": buyer_id,
            "orderSn": order_sn,
            "buyerName": buyer_name,
        }
        for url in urls:
            try:
                r = sess.post(url, data=data, timeout=10)
                logger.info("转移接口 %s 响应: %s", url, r.text[:300])
                if r.status_code == 200:
                    resp = r.json()
                    if (resp.get("success") or resp.get("result") is not None
                            or resp.get("code") in (0, 200, "0", "200")):
                        return True
            except Exception as e:
                logger.warning("转移接���失败 %s: %s", url, e)
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
