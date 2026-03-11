# -*- coding: utf-8 -*-
# pdd_transfer.py - 纯 HTTP API 版本，不启动任何浏览器
# 直接用 cookies 调用拼多多接口转移会话
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
    直接用 cookies 调用拼多多接口，不启动任何浏览器。
    """

    def __init__(self, shop_id: str, cookies: dict, strategy: str = "first"):
        self.shop_id = shop_id
        self.cookies = cookies or {}
        self.strategy = strategy
        self._session = None

    # ------------------------------------------------------------------
    # Session 懒初始化
    # ------------------------------------------------------------------

    def _get_session(self) -> requests.Session:
        if self._session is None:
            self._session = requests.Session()
            anti = self.cookies.get("anti_content", "") or self.cookies.get("ANTI_CONTENT", "")
            self._session.headers.update({
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Referer": "https://mms.pinduoduo.com/chat-merchant/index.html",
                "Origin": "https://mms.pinduoduo.com",
                "Content-Type": "application/json",
                "X-Anti-Content": anti,
            })
            for k, v in self.cookies.items():
                self._session.cookies.set(k, v, domain=".pinduoduo.com")
            logger.info("[transfer] Session 初始化完成，注入 cookies: %d 个，key列表=%s",
                        len(self.cookies), list(self.cookies.keys())[:10])
        return self._session

    # ------------------------------------------------------------------
    # 核心入口
    # ------------------------------------------------------------------

    async def transfer(self, buyer_id: str = "", order_sn: str = "",
                       buyer_name: str = "") -> dict:
        logger.info("[transfer] 开始转人工: buyer_id=%s order_sn=%s buyer_name=%s",
                    buyer_id, order_sn, buyer_name)
        if not self.cookies:
            logger.error("[transfer] cookies 为空，无法调用接口")
            return {"success": False, "agent": "", "message": "cookies 为空，请先登录拼多多"}
        try:
            sess = self._get_session()

            # 1. 获取客服列表
            agents = self._get_agent_list(sess)
            if agents is None:
                return {"success": False, "agent": "", "message": "获取客服列表失败，cookies 可能已失效"}
            if not agents:
                return {"success": False, "agent": "", "message": "没有可用客服"}

            logger.info("[transfer] 可用客服列表: %s",
                        [(a.get("name"), a.get("csid")) for a in agents])

            # 2. 按策略选择
            chosen = self._choose_agent(agents)
            if not chosen:
                return {"success": False, "agent": "", "message": "策略未能选出客服"}
            logger.info("[transfer] 选中客服: name=%s csid=%s uid=%s",
                        chosen.get("name"), chosen.get("csid"), chosen.get("uid"))

            # 3. 调用转移接口
            success = self._do_transfer(sess, chosen, buyer_id, order_sn, buyer_name)
            if success:
                logger.info("[transfer] 转移成功 -> %s", chosen.get("name", ""))
                return {
                    "success": True,
                    "agent": chosen.get("name", ""),
                    "message": "已成功转移给客服 " + chosen.get("name", ""),
                }
            return {"success": False, "agent": "", "message": "所有转移接口均失败，请查看日志"}

        except Exception as e:
            logger.error("[transfer] 异常: %s", e, exc_info=True)
            return {"success": False, "agent": "", "message": str(e)}

    # ------------------------------------------------------------------
    # 获取客服列表
    # ------------------------------------------------------------------

    def _get_agent_list(self, sess: requests.Session):
        """
        调用 getAssignCsList 获取可接收转移的客服列表。
        返回 None = 接口异常，返回 [] = 接口正常但无客服。
        """
        url = "https://mms.pinduoduo.com/latitude/assign/getAssignCsList"
        try:
            anti = self.cookies.get("anti_content", "")
            r = sess.post(url, json={"wechatCheck": True, "anti_content": anti}, timeout=15)
            logger.info("客服列表接口响应 [%d]: %s", r.status_code, r.text[:800])
            if r.status_code != 200:
                logger.warning("[transfer] 客服列表接口返回非200: %d", r.status_code)
                return None
            data = r.json()
            if not data.get("success"):
                logger.warning("getAssignCsList 返回 success=False: %s",
                               data.get("errorMsg") or data.get("error_msg") or str(data)[:300])
                return None

            result = data.get("result") or {}
            # 兼容多种字段名（用 is not None 以免空列表被跳过）
            cs_map = (result.get("csList") if result.get("csList") is not None
                      else result.get("staffList") if result.get("staffList") is not None
                      else result.get("onlineList") if result.get("onlineList") is not None
                      else {})

            if isinstance(cs_map, list):
                # 有时返回列表而非dict
                cs_map = {str(i): item for i, item in enumerate(cs_map)}

            agents = []
            if isinstance(cs_map, dict):
                for uid_key, item in cs_map.items():
                    name = (item.get("csName") or item.get("username") or
                            item.get("nickname") or item.get("staffName") or uid_key)
                    uid = str(item.get("id") or item.get("uid") or uid_key)
                    csid = str(item.get("csId") or item.get("csid") or uid_key)
                    agents.append({
                        "name": name,
                        "uid": uid,
                        "csid": csid,
                        "unreplied": item.get("unreplyNum", 0),
                        "raw": item,
                    })

            logger.info("[transfer] 解析到 %d 个客服", len(agents))
            if agents:
                return agents
            logger.warning("客服列表为空，接口原始数据: %s", str(data)[:500])
            return []

        except Exception as e:
            logger.warning("客服列表接口失败: %s", e)
            return None

    # ------------------------------------------------------------------
    # 转移接口（依次尝试）
    # ------------------------------------------------------------------

    def _do_transfer(self, sess: requests.Session, agent: dict,
                     buyer_id: str, order_sn: str, buyer_name: str) -> bool:
        agent_uid  = agent.get("uid", "")
        agent_csid = agent.get("csid", "")
        anti = self.cookies.get("anti_content", "")

        attempts = [
            # 接口 1：latitude/assign/transferConv（最常用）
            {
                "url": "https://mms.pinduoduo.com/latitude/assign/transferConv",
                "json": {
                    "toUid":       agent_uid,
                    "toCsId":      agent_csid,
                    "toBuyerId":   buyer_id,
                    "buyerId":     buyer_id,
                    "orderSn":     order_sn,
                    "buyerName":   buyer_name,
                    "transReason": 10000,
                    "anti_content": anti,
                },
            },
            # 接口 2：plateau/chat/move_conversation
            {
                "url": "https://mms.pinduoduo.com/plateau/chat/move_conversation",
                "json": {
                    "data": {
                        "cmd": "move_conversation",
                        "conversation": {
                            "csid": agent_csid,
                            "uid": buyer_id,
                            "need_wx": False,
                            "remark": "无原因直接转移",
                        },
                        "anti_content": anti,
                    },
                    "client": "WEB",
                    "anti_content": anti,
                },
            },
            # 接口 3：chats/transferSession
            {
                "url": "https://mms.pinduoduo.com/chats/transferSession",
                "json": {
                    "staffId":    agent_uid,
                    "staffCsId":  agent_csid,
                    "buyerId":    buyer_id,
                    "orderSn":    order_sn,
                    "buyerName":  buyer_name,
                    "anti_content": anti,
                },
            },
            # 接口 4：assistant/session/transfer
            {
                "url": "https://mms.pinduoduo.com/assistant/session/transfer",
                "json": {
                    "staffId":    agent_uid,
                    "buyerId":    buyer_id,
                    "orderSn":    order_sn,
                    "buyerName":  buyer_name,
                },
            },
        ]

        for attempt in attempts:
            url = attempt["url"]
            try:
                r = sess.post(url, json=attempt["json"], timeout=15)
                logger.info("转移接口 %s 响应 [%d]: %s", url, r.status_code, r.text[:500])

                if r.status_code == 200:
                    try:
                        resp = r.json()
                        # 严格的成功判断
                        error_code = resp.get("errorCode") or resp.get("error_code") or resp.get("code")
                        if resp.get("success") is True:
                            return True
                        if error_code in (0, 1000000, 200):
                            return True
                        # 检查嵌套结果
                        result = resp.get("result")
                        if isinstance(result, dict) and result.get("result") == "ok":
                            return True
                        logger.warning("转移接口返回失败: errorCode=%s, msg=%s",
                                       error_code,
                                       resp.get("errorMsg") or resp.get("error_msg") or resp.get("msg", ""))
                    except (ValueError, KeyError):
                        # 非 JSON 响应但状态码 200，也视为成功
                        return True
            except Exception as e:
                logger.warning("转移接口失败 %s: %s", url, e)

        return False

    # ------------------------------------------------------------------
    # 策略选择
    # ------------------------------------------------------------------

    def _choose_agent(self, agents: list):
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
        return agents[0]  # first（默认）

    # ------------------------------------------------------------------
    # 关闭（保持 async 兼容旧接口）
    # ------------------------------------------------------------------

    async def close(self):
        if self._session:
            try:
                self._session.close()
            except Exception:
                pass
            self._session = None
