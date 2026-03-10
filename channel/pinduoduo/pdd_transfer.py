# -*- coding: utf-8 -*-
# pdd_transfer.py - 纯 HTTP API 版本，不启动任何浏览器
import logging
import random
import time
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
            self._session.headers.update({
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Referer": "https://mms.pinduoduo.com/",
                "Origin": "https://mms.pinduoduo.com",
                "Content-Type": "application/json",
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
            r = sess.post(url, json={"wechatCheck": True}, timeout=15)
            logger.info("[transfer] getAssignCsList 状态码=%d 响应=%s",
                        r.status_code, r.text[:800])
            if r.status_code != 200:
                logger.warning("[transfer] 客服列表接口返回非200: %d", r.status_code)
                return None
            data = r.json()
            if not data.get("success"):
                logger.warning("[transfer] 客服列表 success=False: %s", data)
                return None

            result = data.get("result") or {}
            # csList 是 dict: {csId字符串: {...}} 或 list
            cs_map = result.get("csList") or {}
            agents = []

            if isinstance(cs_map, dict):
                for uid_key, item in cs_map.items():
                    name = (item.get("csName") or item.get("username") or
                            item.get("nickname") or uid_key)
                    # csId / id 都可能是数字型客服ID
                    csid = str(item.get("csId") or item.get("id") or uid_key)
                    agents.append({
                        "name": name,
                        "csid": csid,
                        "uid": uid_key,
                        "unreplied": item.get("unreplyNum", 0),
                        "raw": item,
                    })
            elif isinstance(cs_map, list):
                for item in cs_map:
                    name = (item.get("csName") or item.get("username") or
                            item.get("nickname") or str(item.get("csId", "")))
                    csid = str(item.get("csId") or item.get("id") or "")
                    agents.append({
                        "name": name,
                        "csid": csid,
                        "uid": csid,
                        "unreplied": item.get("unreplyNum", 0),
                        "raw": item,
                    })

            logger.info("[transfer] 解析到 %d 个客服", len(agents))
            return agents if agents else []

        except Exception as e:
            logger.error("[transfer] getAssignCsList 异常: %s", e, exc_info=True)
            return None

    # ------------------------------------------------------------------
    # 转移接口（依次尝试）
    # ------------------------------------------------------------------

    def _do_transfer(self, sess: requests.Session, agent: dict,
                     buyer_id: str, order_sn: str, buyer_name: str) -> bool:
        csid = agent.get("csid", "")
        uid  = agent.get("uid", "")
        name = agent.get("name", "")

        # 注意：拼多多官方字段名区分大小写
        # latitude/assign/transferConv 是最真实的转移接口
        attempts = [
            # ── 接口1: latitude/assign/transferConv（最可能有效）──
            {
                "url":  "https://mms.pinduoduo.com/latitude/assign/transferConv",
                "json": {
                    "csId":       csid,           # 目标客服ID（数字字符串）
                    "buyerId":    buyer_id,        # 买家ID
                    "orderSn":    order_sn,
                    "buyerName":  buyer_name,
                    "transReason": 10000,
                },
            },
            # ── 接口2: 同上，字段名变体 ──
            {
                "url":  "https://mms.pinduoduo.com/latitude/assign/transferConv",
                "json": {
                    "toUid":      csid,
                    "toBuyerId":  buyer_id,
                    "buyerId":    buyer_id,
                    "orderSn":    order_sn,
                    "buyerName":  buyer_name,
                    "transReason": 10000,
                },
            },
            # ── 接口3: plateau/chat/move_conversation（类似JS版本）──
            {
                "url":  "https://mms.pinduoduo.com/plateau/chat/move_conversation",
                "json": {
                    "data": {
                        "cmd": "move_conversation",
                        "request_id": int(time.time() * 1000),
                        "conversation": {
                            "csid":    csid,
                            "uid":     buyer_id,
                            "need_wx": False,
                            "remark":  "无原因直接转移",
                        },
                        "anti_content": "",
                    },
                    "client": "WEB",
                    "anti_content": "",
                },
            },
            # ── 接口4: chats/transferSession ──
            {
                "url":  "https://mms.pinduoduo.com/chats/transferSession",
                "json": {
                    "staffId":   csid,
                    "buyerId":   buyer_id,
                    "orderSn":   order_sn,
                    "buyerName": buyer_name,
                },
            },
            # ── 接口5: assistant/session/transfer（form-data）──
            {
                "url":  "https://mms.pinduoduo.com/assistant/session/transfer",
                "data": {
                    "staffId":   csid,
                    "buyerId":   buyer_id,
                    "orderSn":   order_sn,
                    "buyerName": buyer_name,
                },
            },
        ]

        for attempt in attempts:
            url = attempt["url"]
            try:
                if "json" in attempt:
                    r = sess.post(url, json=attempt["json"], timeout=15)
                else:
                    # form-data：临时修改 Content-Type
                    hdrs = {"Content-Type": "application/x-www-form-urlencoded"}
                    r = sess.post(url, data=attempt["data"], headers=hdrs, timeout=15)

                logger.info("[transfer] 接口 %s 状态=%d 响应=%s",
                            url, r.status_code, r.text[:400])

                if r.status_code == 200:
                    try:
                        resp = r.json()
                        ok = (
                            resp.get("success") is True
                            or resp.get("errorCode") in (0, 1000000)
                            or resp.get("code") in (0, 200)
                            or (isinstance(resp.get("result"), dict)
                                and resp["result"].get("result") == "ok")
                        )
                        if ok:
                            logger.info("[transfer] 接口 %s 转移成功！", url)
                            return True
                        else:
                            logger.warning("[transfer] 接口 %s 返回但未成功: %s", url, resp)
                    except Exception:
                        # 非JSON但200，谨慎视为成功
                        logger.warning("[transfer] 接口 %s 非JSON响应但200，视为成功尝试", url)
                        return True
            except Exception as e:
                logger.warning("[transfer] 接口 %s 请求异常: %s", url, e)

        logger.error("[transfer] 所有接口均失败，buyer_id=%s csid=%s", buyer_id, csid)
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
