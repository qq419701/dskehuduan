'# -*- coding: utf-8 -*-
# pdd_transfer.py - 纯 HTTP API 版本，不启动任何浏览器
# 直接用 cookies 调用拼多多接口转移会话
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
            import config as cfg
            anti = cfg.get_anti_content(self.shop_id)
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
            logger.info("[transfer] Session 初始化完成，注入 cookies: %d 个，key列表=%s，anti_content=%s",
                        len(self.cookies), list(self.cookies.keys())[:10],
                        "已配置" if anti else "未配置（风控风险）")
        return self._session

    def refresh_anti_content(self):
        import config as cfg
        anti = cfg.get_anti_content(self.shop_id)
        if self._session:
            self._session.headers.update({"X-Anti-Content": anti})
            logger.info("[transfer] 已刷新 anti_content: %s", "已配置" if anti else "未配置")
        return anti

    def reset_session(self):
        if self._session:
            try:
                self._session.close()
            except Exception:
                pass
            self._session = None
            logger.info("[transfer] Session 已重置，下次请求将重新初始化")

    # ------------------------------------------------------------------
    # 核心入口
    # ------------------------------------------------------------------

    async def transfer(self, buyer_id: str = "", order_sn: str = "",
                       buyer_name: str = "", target_agent: str = "") -> dict:
        if not target_agent:
            import config as cfg
            settings = cfg.get_pdd_transfer_settings()
            target_agent = settings.get("target_account", "")
            if target_agent:
                logger.info("[transfer] 从配置读取指定客服: %s", target_agent)
        logger.info("[transfer] 开始转人工: buyer_id=%s order_sn=%s buyer_name=%s target_agent=%s",
                    buyer_id, order_sn, buyer_name, target_agent)
        if not self.cookies:
            logger.error("[transfer] cookies 为空，无法调用接口")
            return {"success": False, "agent": "", "message": "cookies 为空，请先登录拼多多"}
        try:
            sess = self._get_session()

            agents = self._get_agent_list(sess)
            if agents is None:
                return {"success": False, "agent": "", "message": "获取客服列表失败，cookies 可能已失效"}
            if not agents:
                return {"success": False, "agent": "", "message": "没有可用客服"}

            logger.info("[transfer] 可用客服列表: %s",
                        [(a.get("name"), a.get("remark"), a.get("csid")) for a in agents])

            chosen = self._choose_agent(agents, target_agent=target_agent)
            if not chosen:
                return {"success": False, "agent": "", "message": "策略未能选出客服"}
            logger.info("[transfer] 选中客服: name=%s remark=%s csid=%s uid=%s",
                        chosen.get("name"), chosen.get("remark"), chosen.get("csid"), chosen.get("uid"))

            success = self._do_transfer(sess, chosen, buyer_id, order_sn, buyer_name)
            if not success:
                self.refresh_anti_content()
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
    # 获取客服列表（多接口依次尝试）
    # ------------------------------------------------------------------

    def _get_agent_list(self, sess: requests.Session):
        agents = self._try_agent_list_v1(sess)
        if agents is not None:
            return agents
        agents = self._try_agent_list_v2(sess)
        if agents is not None:
            return agents
        agents = self._try_agent_list_v3(sess)
        return agents

    def _parse_agents_from_data(self, data: dict) -> list:
        """从接口响应中解析客服列表，兼容多种字段名和数据结构"""
        # 打印完整原始响应，用于排查字段名
        logger.info("[transfer] 原始接口响应（完整）: %s", str(data)[:2000])

        result = data.get("result") or {}
        logger.info("[transfer] result字段类型=%s 内容=%s", type(result).__name__, str(result)[:1000])

        cs_map = None

        # 情形1：result 本身是列表
        if isinstance(result, list):
            cs_map = result
            logger.info("[transfer] result 是列表，直接用，长度=%d", len(result))
        # 情形2：result 是 dict，且包含已知的客服列表字段
        elif isinstance(result, dict):
            for field in ("csList", "staffList", "onlineList", "list", "csInfoList", "agentList", "data"):
                if result.get(field) is not None:
                    cs_map = result[field]
                    logger.info("[transfer] 从 result.%s 取到客服数据，类型=%s 内容=%s",
                                field, type(cs_map).__name__, str(cs_map)[:500])
                    break
            # 情形3：result 本身就是以 csid 为 key 的 dict（如 {"cs_xxx": {...}, "cs_yyy": {...}}）
            if cs_map is None and result:
                logger.info("[transfer] result 无已知列表字段，尝试把 result 整体作为 csid->info 字典使用")
                cs_map = result

        # 情形4：顶层 data 直接有列表字段（不通过 result 中转）
        if cs_map is None:
            for field in ("csList", "staffList", "onlineList", "list", "csInfoList", "agentList", "data"):
                if data.get(field) is not None:
                    cs_map = data[field]
                    logger.info("[transfer] 从顶层 data.%s 取到客服数据", field)
                    break

        if cs_map is None:
            cs_map = {}
            logger.warning("[transfer] 无法从响应中找到客服列表，响应结构: %s", list(data.keys()))

        # 将 list 转换为 dict（以索引为 key）
        if isinstance(cs_map, list):
            cs_map = {str(i): item for i, item in enumerate(cs_map)}

        agents = []
        if isinstance(cs_map, dict):
            for uid_key, item in cs_map.items():
                if not isinstance(item, dict):
                    continue
                name = (item.get("csName") or item.get("username") or
                        item.get("nickname") or item.get("staffName") or
                        item.get("name") or uid_key)
                uid = str(item.get("id") or item.get("uid") or uid_key)
                csid = uid_key
                # 兼容拼多多所有可能的备注字段名（完整枚举）
                remark = (item.get("remarkName") or item.get("remark") or
                          item.get("memo") or item.get("tag") or
                          item.get("comment") or item.get("note") or
                          item.get("csRemark") or item.get("label") or
                          item.get("alias") or item.get("mark") or
                          item.get("description") or item.get("desc") or "")
                # 打印每个客服的完整原始字段，便于排查
                logger.info("[transfer] 客服#%s 解析结果: name=%s remark=%s uid=%s 所有字段=%s",
                            uid_key, name, remark, uid, item)
                agents.append({
                    "name": name,
                    "uid": uid,
                    "csid": csid,
                    "unreplied": item.get("unreplyNum", 0),
                    "remark": remark,
                    "raw": item,
                })
        else:
            logger.warning("[transfer] cs_map 不是 dict，类型=%s", type(cs_map).__name__) 

        logger.info("[transfer] 共解析到 %d 个客服", len(agents))
        return agents

    def _try_agent_list_v1(self, sess: requests.Session):
        """主接口：latitude/assign/getAssignCsList（需要 anti_content）"""
        import config as cfg
        url = "https://mms.pinduoduo.com/latitude/assign/getAssignCsList"
        try:
            anti = cfg.get_anti_content(self.shop_id)
            r = sess.post(url, json={"wechatCheck": True, "anti_content": anti}, timeout=15)
            logger.info("客服列表接口v1响应 [%d]: %s", r.status_code, r.text[:2000])
            if r.status_code != 200:
                logger.warning("[transfer] 客服列表v1接口返回非200: %d", r.status_code)
                return None
            data = r.json()
            if not data.get("success"):
                logger.warning("getAssignCsList 返回 success=False: %s",
                               data.get("errorMsg") or data.get("error_msg") or str(data)[:300])
                return None
            agents = self._parse_agents_from_data(data)
            logger.info("[transfer] v1接口解析到 %d 个客服", len(agents))
            if agents:
                return agents
            logger.warning("客服列表v1为空，接口原始数据: %s", str(data)[:1000])
            return []
        except Exception as e:
            logger.warning("客服列表v1接口失败: %s", e)
            return None

    def _try_agent_list_v2(self, sess: requests.Session):
        """备用接口2：mms/api/cs/online_list（GET，通常无需 anti_content）"""
        url = "https://mms.pinduoduo.com/mms/api/cs/online_list"
        try:
            r = sess.get(url, timeout=15)
            logger.info("客服列表接口v2响应 [%d]: %s", r.status_code, r.text[:2000])
            if r.status_code != 200:
                return None
            data = r.json()
            if not (data.get("success") or data.get("result")):
                logger.warning("v2接口返回失败: %s", str(data)[:300])
                return None
            agents = self._parse_agents_from_data(data)
            logger.info("[transfer] v2接口解析到 %d 个客服", len(agents))
            return agents if agents else []
        except Exception as e:
            logger.warning("客服列表v2接口失败: %s", e)
            return None

    def _try_agent_list_v3(self, sess: requests.Session):
        """备用接口3：service/im/cs/list（GET，基础认证）"""
        url = "https://mms.pinduoduo.com/service/im/cs/list"
        try:
            r = sess.get(url, timeout=15)
            logger.info("客服列表接口v3响应 [%d]: %s", r.status_code, r.text[:2000])
            if r.status_code != 200:
                return None
            data = r.json()
            if not (data.get("success") or data.get("result")):
                logger.warning("v3接口返回失败: %s", str(data)[:300])
                return None
            agents = self._parse_agents_from_data(data)
            logger.info("[transfer] v3接口解析到 %d 个客服", len(agents))
            return agents if agents else []
        except Exception as e:
            logger.warning("客服列表v3接口失败: %s", e)
            return None

    # ------------------------------------------------------------------
    # 转移接口（依次尝试）
    # ------------------------------------------------------------------

    def _do_transfer(self, sess: requests.Session, agent: dict,
                     buyer_id: str, order_sn: str, buyer_name: str) -> bool:
        import config as cfg
        agent_uid  = agent.get("uid", "")
        agent_csid = agent.get("csid", "")
        anti = cfg.get_anti_content(self.shop_id)
        request_id = int(time.time() * 1000)

        attempts = [
            {
                "url": "https://mms.pinduoduo.com/plateau/chat/move_conversation",
                "json": {
                    "data": {
                        "cmd": "move_conversation",
                        "request_id": request_id,
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
                "success_check": lambda resp: (
                    resp.get("success") and
                    isinstance(resp.get("result"), dict) and
                    resp["result"].get("result") == "ok"
                ),
            },
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

        anti_preview = (anti[:20] + "...") if len(anti) > 20 else anti
        for attempt in attempts:
            url = attempt["url"]
            payload = attempt["json"]
            try:
                logger.info("转移接口请求: %s | csid=%s uid=%s anti=%s",
                            url, agent_csid, buyer_id, anti_preview)
                r = sess.post(url, json=payload, timeout=15)
                logger.info("转移接口 %s 响应 [%d]: %s", url, r.status_code, r.text[:500])

                if r.status_code == 200:
                    try:
                        resp = r.json()
                        custom_check = attempt.get("success_check")
                        if custom_check:
                            if custom_check(resp):
                                return True
                            result_obj = resp.get("result")
                            if isinstance(result_obj, dict):
                                err_code = result_obj.get("error_code", "")
                                err_msg = result_obj.get("error_msg", "")
                                if err_code or err_msg:
                                    logger.warning("转移接口业务失败: error_code=%s error_msg=%s",
                                                   err_code, err_msg)
                            logger.warning("转移接口返回失败: %s", str(resp)[:300])
                            continue
                        if resp.get("success") in (True, 1, "true", "ok"):
                            return True
                        error_code = resp.get("errorCode") or resp.get("error_code") or resp.get("code")
                        if error_code in (0, 1000000, 200, "0", "1000000"):
                            return True
                        result = resp.get("result")
                        nested_result = result.get("result") if isinstance(result, dict) else None
                        if result and isinstance(result, dict) and nested_result in ("ok", "success", True):
                            return True
                        if result and isinstance(result, str) and result in ("ok", "success"):
                            return True
                        logger.warning("转移接口返回失败: errorCode=%s, msg=%s",
                                       error_code,
                                       resp.get("errorMsg") or resp.get("error_msg") or resp.get("msg", ""))
                    except (ValueError, KeyError):
                        return True
            except Exception as e:
                logger.warning("转移接口失败 %s: %s", url, e)

        return False

    # ------------------------------------------------------------------
    # 策略选择（支持定向指定客服，按昵称或备注匹配）
    # ------------------------------------------------------------------

    def _choose_agent(self, agents: list, target_agent: str = ""):
        if not agents:
            return None
        if target_agent:
            for a in agents:
                name_match = target_agent in a.get("name", "")
                remark_match = target_agent in a.get("remark", "")
                if name_match or remark_match:
                    logger.info("[transfer] 指定客服匹配成功: name=%s remark=%s (关键词=%s)",
                                a.get("name"), a.get("remark"), target_agent)
                    return a
            logger.warning("[transfer] 未找到指定客服 '%s'（昵称和备注均未命中），回退到策略选择", target_agent)
        sub_agents = [a for a in agents if a.get("csid", "").startswith("cs_")]
        if sub_agents:
            candidates = sub_agents
        else:
            logger.warning("[transfer] 没有找到子账号（cs_ 前缀），将从全部客服中选择")
            candidates = agents
        if self.strategy == "random":
            return random.choice(candidates)
        if self.strategy == "least_busy":
            return min(candidates, key=lambda a: a.get("unreplied", 0))
        if self.strategy == "round_robin":
            global _round_robin_index
            idx    = _round_robin_index.get(self.shop_id, 0)
            chosen = candidates[idx % len(candidates)]
            _round_robin_index[self.shop_id] = (idx + 1) % len(candidates)
            return chosen
        return candidates[0]  # first（默认）

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
'