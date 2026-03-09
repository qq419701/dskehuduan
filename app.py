# -*- coding: utf-8 -*-
"""
爱客服采集客户端 - 主入口
"""
import sys
import logging

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

import config as cfg
from utils.logger import setup_logger


def start_task_runner_if_enabled():
    """如果配置了任务执行器，在后台异步启动"""
    runner_cfg = cfg.get_task_runner_config()
    if not runner_cfg.get("enabled"):
        return

    import asyncio
    from core.task_runner import AikefuTaskRunner

    logger = logging.getLogger("aikefu")
    logger.info(
        "启动任务执行器 plugin_id=%s server=%s",
        runner_cfg["plugin_id"],
        runner_cfg["server_url"],
    )

    runner = AikefuTaskRunner(
        server_url=runner_cfg["server_url"],
        shop_token=runner_cfg["shop_token"],
        plugin_id=runner_cfg["plugin_id"],
        poll_interval=runner_cfg.get("poll_interval", cfg.TASK_RUNNER_POLL_INTERVAL),
        heartbeat_interval=runner_cfg.get(
            "heartbeat_interval", cfg.TASK_RUNNER_HEARTBEAT_INTERVAL
        ),
    )

    # 在当前事件循环中创建后台任务（兼容 qasync）
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(runner.start())
        else:
            loop.create_task(runner.start())
    except Exception as e:
        logger.warning("任务执行器启动失败: %s", e)


def main():
    # 初始化日志
    setup_logger("aikefu", logging.DEBUG)
    logger = logging.getLogger("aikefu")
    logger.info("爱客服采集客户端 v%s 启动", cfg.APP_VERSION)

    app = QApplication(sys.argv)
    app.setApplicationName(cfg.APP_NAME)
    app.setApplicationVersion(cfg.APP_VERSION)
    app.setQuitOnLastWindowClosed(False)

    # 首次运行 - 显示配置向导
    if not cfg.is_configured():
        from ui.login_ui import SetupDialog
        dialog = SetupDialog()
        result = dialog.exec()
        if result != SetupDialog.DialogCode.Accepted:
            logger.info("用户取消配置，退出")
            sys.exit(0)

    # 启动主窗口
    from ui.main_window import MainWindow
    window = MainWindow()
    window.show()

    # 启动任务执行器（如果已启用）
    start_task_runner_if_enabled()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
