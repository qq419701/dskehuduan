# -*- coding: utf-8 -*-
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
            # anti_content 是拼多多页面 JS 动态生成的设备指纹，不存储在 cookie 中，
            # 需要从配置文件单独读取（由用户在浏览器抓包后手动配置）
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
        """
        刷新 anti_content 到当前 session 的请求头。
        在转移失败后重试前调用，以获取最新的设备指纹。
        """
        import config as cfg
        anti = cfg.get_anti_content(self.shop_id)
        if self._session:
            self._session.headers.update({"X-Anti-Content": anti})
            logger.info("[transfer] 已刷新 anti_content: %s", "已配置" if anti else "未配置")
        return anti

    def reset_session(self):
        """
        重置并关闭当前 session，下次调用 _get_session() 时会重新初始化。
        在 anti_content 更新后调用，确保新 session 使用最新的设备指纹。
        """
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
        # 如果调用方没有传 target_agent，从配置文件读取
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

            # 1. 获取客服列表
            agents = self._get_agent_list(sess)
            if agents is None:
                return {"success": False, "agent": "", "message": "获取客服列表失败，cookies 可能已失效"}
            if not agents:
                return {"success": False, "agent": "", "message": "没有可用客服"}

            logger.info("[transfer] 可用客服列表: %s",
                        [(a.get("name"), a.get("csid")) for a in agents])

            # 2. 按策略选择（支持定向指定客服）
            chosen = self._choose_agent(agents, target_agent=target_agent)
            if not chosen:
                return {"success": False, "agent": "", "message": "策略未能选出客服"}
            logger.info("[transfer] 选中客服: name=%s csid=%s uid=%s",
                        chosen.get("name"), chosen.get("csid"), chosen.get("uid"))

            # 3. 调用转移接口（实时获取最新 anti_content）
            success = self._do_transfer(sess, chosen, buyer_id, order_sn, buyer_name)
            if not success:
                # 刷新 anti_content 后重试一次
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
        """
        依次尝试多个接口获取可接收转移的客服列表，任一成功即返回。
        返回 None = 所有接口均异常，返回 [] = 接口正常但无客服。
        """
        # 接口1：主接口（可能需要 anti_content）
        agents = self._try_agent_list_v1(sess)
        if agents is not None:
            return agents
        # 接口2：备用接口（通常不需要 anti_content）
        agents = self._try_agent_list_v2(sess)
        if agents is not None:
            return agents
        # 接口3：再备用
        agents = self._try_agent_list_v3(sess)
        return agents

    def _parse_agents_from_data(self, data: dict) -> list:
        """从接口响应中解析客服列表，兼容多种字段名"""
        result = data.get("result") or {}
        # 兼容多种字段名（用 is not None 以免空列表被跳过）
        cs_map = None
        if isinstance(result, list):
            cs_map = result
        else:
            for field in ("csList", "staffList", "onlineList", "list"):
                if result.get(field) is not None:
                    cs_map = result[field]
                    break
        if cs_map is None:
            cs_map = {}

        if isinstance(cs_map, list):
            cs_map = {str(i): item for i, item in enumerate(cs_map)}

        agents = []
        if isinstance(cs_map, dict):
            for uid_key, item in cs_map.items():
                name = (item.get("csName") or item.get("username") or
                        item.get("nickname") or item.get("staffName") or
                        item.get("name") or uid_key)
                uid = str(item.get("id") or item.get("uid") or uid_key)
                # csList 的 key 本身就是 csid（如 "cs_106324383_180462738"），
                # 不要用 item 内的 id 数字字段，那是数字 id 而非字符串 csid
                csid = uid_key
                agents.append({
                    "name": name,
                    "uid": uid,
                    "csid": csid,
                    "unreplied": item.get("unreplyNum", 0),
                    "remark": (item.get("remark") or item.get("comment") or
                               item.get("note") or item.get("csRemark") or ""),
                    "raw": item,
                })
        return agents

    def _try_agent_list_v1(self, sess: requests.Session):
        """主接口：latitude/assign/getAssignCsList（需要 anti_content）"""
        import config as cfg
        url = "https://mms.pinduoduo.com/latitude/assign/getAssignCsList"
        try:
            anti = cfg.get_anti_content(self.shop_id)
            r = sess.post(url, json={"wechatCheck": True, "anti_content": anti}, timeout=15)
            logger.info("客服列表接口v1响应 [%d]: %s", r.status_code, r.text[:800])
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
            logger.warning("客服列表v1为空，接口原始数据: %s", str(data)[:500])
            return []
        except Exception as e:
            logger.warning("客服列表v1接口失败: %s", e)
            return None

    def _try_agent_list_v2(self, sess: requests.Session):
        """备用接口2：mms/api/cs/online_list（GET，通常无需 anti_content）"""
        url = "https://mms.pinduoduo.com/mms/api/cs/online_list"
        try:
            r = sess.get(url, timeout=15)
            logger.info("客服列表接口v2响应 [%d]: %s", r.status_code, r.text[:800])
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
            logger.info("客服列表接口v3响应 [%d]: %s", r.status_code, r.text[:800])
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
        # 每次实时从配置读取最新 anti_content（它会定期更新，不能缓存）
        anti = cfg.get_anti_content(self.shop_id)
        # request_id 需为毫秒时间戳（抓包确认）
        request_id = int(time.time() * 1000)

        attempts = [
            # 接口 1：plateau/chat/move_conversation（抓包确认可用，优先级最高）
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
                # 成功判断：result.result == "ok"
                "success_check": lambda resp: (
                    resp.get("success") and
                    isinstance(resp.get("result"), dict) and
                    resp["result"].get("result") == "ok"
                ),
            },
            # 接口 2：latitude/assign/transferConv（备用）
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
            # 接口 3：chats/transferSession（备用）
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
            # 接口 4：assistant/session/transfer（备用）
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
                        # 优先用接口自定义的成功判断函数
                        custom_check = attempt.get("success_check")
                        if custom_check:
                            if custom_check(resp):
                                return True
                            # 自定义检查明确失败，记录详细错误信息，跳过通用判断
                            result_obj = resp.get("result")
                            if isinstance(result_obj, dict):
                                err_code = result_obj.get("error_code", "")
                                err_msg = result_obj.get("error_msg", "")
                                if err_code or err_msg:
                                    logger.warning("转移接口业务失败: error_code=%s error_msg=%s",
                                                   err_code, err_msg)
                            logger.warning("转移接口返回失败: %s", str(resp)[:300])
                            continue
                        # 通用成功判断（仅在无自定义 success_check 时使用）
                        # success 字段：True 或 1 或 "true"/"ok" 都算成功
                        if resp.get("success") in (True, 1, "true", "ok"):
                            return True
                        # errorCode 为 0 或 1000000 算成功
                        error_code = resp.get("errorCode") or resp.get("error_code") or resp.get("code")
                        if error_code in (0, 1000000, 200, "0", "1000000"):
                            return True
                        # result 字段有值也算成功（部分接口这样返回）
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
                        # 非 JSON 响应但状态码 200，也视为成功
                        return True
            except Exception as e:
                logger.warning("转移接口失败 %s: %s", url, e)

        return False

    # ------------------------------------------------------------------
    # 策略选择（支持定向指定客服）
    # ------------------------------------------------------------------

    def _choose_agent(self, agents: list, target_agent: str = ""):
        if not agents:
            return None
        # 优先：按名字或备注定向匹配（在所有客服中查找，不限制主子账号）
        if target_agent:
            for a in agents:
                name_match = target_agent in a.get("name", "")
                remark_match = target_agent in a.get("remark", "")
                if name_match or remark_match:
                    logger.info("[transfer] 指定客服匹配: name=%s remark=%s (关键词=%s)",
                                a.get("name"), a.get("remark"), target_agent)
                    return a
            # 昵称和备注均未命中，记日志后回退到策略选择
            logger.warning("[transfer] 未找到指定客服 '%s'（昵称和备注均未命中），回退到策略选择", target_agent)
        # 过滤掉主账号（csid 不含 cs_ 前缀），只选子账号
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
