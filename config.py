# -*- coding: utf-8 -*-
"""
配置管理模块（v2.0 纯API模式）
配置存储到 ~/.aikefu-client/config.json，token/密码AES加密保存
"""
import os
import json
import logging
import uuid
from typing import Optional

# aikefu服务器地址
AIKEFU_SERVER = "http://8.145.43.255:5000"

# 应用版本
APP_VERSION = "2.0.0"
APP_NAME = "爱客服采集客户端"

# 任务执行器默认参数
TASK_RUNNER_POLL_INTERVAL = 2        # 轮询间隔（秒）
TASK_RUNNER_HEARTBEAT_INTERVAL = 30  # 心跳间隔（秒）

# 本地配置文件路径
CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".aikefu-client")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

# 插件 ID 持久化文件路径
PLUGIN_ID_FILE = os.path.join(CONFIG_DIR, "plugin_id.txt")


def load_config() -> dict:
    """从配置文件加载配置"""
    if not os.path.exists(CONFIG_FILE):
        return {}
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_config(config: dict) -> bool:
    """保存配置到文件"""
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def get_server_url() -> str:
    """获取aikefu服务器地址"""
    cfg = load_config()
    return cfg.get("server_url", AIKEFU_SERVER)


def get_client_token() -> str:
    """获取登录后的 client_token"""
    cfg = load_config()
    return cfg.get("client_token", "")


def save_client_token(token: str) -> bool:
    """保存 client_token 到本地配置"""
    cfg = load_config()
    cfg["client_token"] = token
    return save_config(cfg)


def get_client_username() -> str:
    """获取已登录的用户名"""
    cfg = load_config()
    return cfg.get("client_username", "")


def save_client_username(username: str) -> bool:
    """保存已登录的用户名"""
    cfg = load_config()
    cfg["client_username"] = username
    return save_config(cfg)


def get_active_shops() -> list:
    """获取已激活的店铺列表（含 shop_token）"""
    cfg = load_config()
    return cfg.get("active_shops", [])


def save_active_shops(shops: list) -> bool:
    """保存激活的店铺列表"""
    cfg = load_config()
    cfg["active_shops"] = shops
    return save_config(cfg)


def remove_shops_by_ids(shop_ids: list):
    """从本地配置中移除指定ID的店铺（服务端已删除时调用）"""
    if not shop_ids:
        return
    ids_to_remove = set(str(sid) for sid in shop_ids)
    data = load_config()
    shops = data.get("active_shops", [])
    new_shops = [
        s for s in shops
        if str(s.get("id", s.get("shop_id", ""))) not in ids_to_remove
    ]
    removed = len(shops) - len(new_shops)
    if removed > 0:
        data["active_shops"] = new_shops
        save_config(data)
        logging.getLogger(__name__).info(
            "已从本地配置移除 %d 个已删除店铺: %s", removed, list(ids_to_remove)
        )


def get_notify_enabled() -> bool:
    """获取桌面通知开关"""
    cfg = load_config()
    return cfg.get("notify_enabled", True)


def get_startup_enabled() -> bool:
    """获取开机自启开关"""
    cfg = load_config()
    return cfg.get("startup_enabled", False)


def is_logged_in() -> bool:
    """检查是否已完成账号登录（有有效 client_token）"""
    return bool(get_client_token())


# ── 插件 ID 管理 ───────────────────────────────────────────────────────────────


def get_plugin_id() -> str:
    """
    获取本机插件唯一ID（首次生成并持久化到本地文件）
    文件路径：~/.aikefu-client/plugin_id.txt
    格式：dskehuduan_{uuid4前8位}
    """
    os.makedirs(CONFIG_DIR, exist_ok=True)
    if os.path.exists(PLUGIN_ID_FILE):
        try:
            with open(PLUGIN_ID_FILE, "r", encoding="utf-8") as f:
                plugin_id = f.read().strip()
                if plugin_id:
                    return plugin_id
        except Exception:
            pass
    plugin_id = f"dskehuduan_{str(uuid.uuid4())[:8]}"
    try:
        with open(PLUGIN_ID_FILE, "w", encoding="utf-8") as f:
            f.write(plugin_id)
    except Exception:
        pass
    return plugin_id


# ── 任务执行器相关配置 ─────────────────────────────────────────────────────────

# 默认启用状态
TASK_RUNNER_ENABLED = False


def get_task_runner_config() -> dict:
    """读取任务执行器配置"""
    cfg = load_config()
    runner = cfg.get("task_runner", {})
    return {
        "enabled": runner.get("enabled", TASK_RUNNER_ENABLED),
        "server_url": get_server_url(),
        "poll_interval": runner.get("poll_interval", TASK_RUNNER_POLL_INTERVAL),
        "heartbeat_interval": runner.get(
            "heartbeat_interval", TASK_RUNNER_HEARTBEAT_INTERVAL
        ),
    }


def save_task_runner_config(enabled: bool,
                            poll_interval: int = TASK_RUNNER_POLL_INTERVAL,
                            heartbeat_interval: int = TASK_RUNNER_HEARTBEAT_INTERVAL) -> bool:
    """保存任务执行器配置"""
    cfg_data = load_config()
    cfg_data["task_runner"] = {
        "enabled": enabled,
        "poll_interval": poll_interval,
        "heartbeat_interval": heartbeat_interval,
    }
    return save_config(cfg_data)


def get_default_uhaozu_account() -> Optional[dict]:
    """
    获取默认U号租账号。
    v2.0 中账号列表从 aikefu 服务端获取，此处仅返回本地缓存的默认账号（兼容旧任务执行器）。
    """
    cfg = load_config()
    accounts = cfg.get("uhaozu_accounts_cache", [])
    for acc in accounts:
        if acc.get("is_default"):
            return acc
    return accounts[0] if accounts else None


# ── 转人工插件相关配置 ──────────────────────────────────────────────────────────

DEFAULT_TRANSFER_REPLY = "您好，正在为您转接人工客服，请稍候～"


def get_transfer_strategy() -> str:
    """获取转人工分配策略，可选：first/random/least_busy/round_robin，默认 first"""
    cfg = load_config()
    return cfg.get("transfer_strategy", "first")


def save_transfer_strategy(strategy: str) -> bool:
    """保存转人工分配策略"""
    cfg = load_config()
    cfg["transfer_strategy"] = strategy
    return save_config(cfg)


def get_transfer_reply() -> str:
    """获取转人工前发给买家的话术"""
    cfg = load_config()
    return cfg.get("transfer_reply", DEFAULT_TRANSFER_REPLY)


def save_transfer_reply(reply: str) -> bool:
    """保存转人工话术"""
    cfg = load_config()
    cfg["transfer_reply"] = reply
    return save_config(cfg)


# ── 拼多多设置（统一配置入口）──────────────────────────────────────────────────


def get_pdd_transfer_settings() -> dict:
    """获取转人工设置（从 pdd_settings.transfer 字段读取，兼容旧配置）"""
    conf = load_config()
    pdd = conf.get("pdd_settings", {})
    transfer = pdd.get("transfer", {})
    # 兼容旧版顶层字段
    return {
        "strategy":       transfer.get("strategy", conf.get("transfer_strategy", "least_busy")),
        "target_account": transfer.get("target_account", ""),
        "reply":          transfer.get("reply", conf.get("transfer_reply", DEFAULT_TRANSFER_REPLY)),
        "timeout":        transfer.get("timeout", 30),
    }


def save_pdd_transfer_settings(settings: dict) -> bool:
    """保存转人工设置到 pdd_settings.transfer 字段"""
    conf = load_config()
    if "pdd_settings" not in conf:
        conf["pdd_settings"] = {}
    conf["pdd_settings"]["transfer"] = settings
    return save_config(conf)


# ── anti_content 管理（拼多多设备指纹，JS动态生成，需单独存储）──────────────────


def get_anti_content(shop_id: str) -> str:
    """
    获取指定店铺的 anti_content（拼多多设备指纹字符串）。
    anti_content 是拼多多页面 JS 动态生成的，不存储在 cookie 中，需单独保存。
    返回空字符串表示未配置。
    """
    conf = load_config()
    anti_map = conf.get("pdd_anti_content", {})
    return anti_map.get(str(shop_id), "")


def save_anti_content(shop_id: str, anti: str) -> bool:
    """
    保存指定店铺的 anti_content（拼多多设备指纹字符串）。
    anti_content 是拼多多页面 JS 动态生成的，需在浏览器中抓包后手动配置。
    """
    conf = load_config()
    if "pdd_anti_content" not in conf:
        conf["pdd_anti_content"] = {}
    conf["pdd_anti_content"][str(shop_id)] = anti
    return save_config(conf)


# ── 拼多多各店铺转人工客服配置 ─────────────────────────────────────────────────


def get_shop_transfer_agent(shop_id: str) -> str:
    """
    获取指定拼多多店铺的转人工指定客服账号名。
    返回空字符串表示未指定，由分配策略自动选择。
    """
    conf = load_config()
    agents = conf.get("pdd_shop_transfer_agents", {})
    return agents.get(str(shop_id), "")


def save_shop_transfer_agent(shop_id: str, agent_name: str) -> bool:
    """
    保存指定拼多多店铺的转人工客服账号名。
    agent_name 为空字符串表示清除（不指定），由分配策略自动选择。
    """
    conf = load_config()
    if "pdd_shop_transfer_agents" not in conf:
        conf["pdd_shop_transfer_agents"] = {}
    conf["pdd_shop_transfer_agents"][str(shop_id)] = agent_name.strip()
    return save_config(conf)
