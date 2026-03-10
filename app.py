# -*- coding: utf-8 -*-
"""
爱客服采集客户端 v2.0 - 主入口
启动流程：初始化配置 → 显示主窗口 → 主窗口内部检查登录状态
"""
import sys
import logging

from PyQt6.QtWidgets import QApplication

import config as cfg
from utils.logger import setup_logger


def main():
    # 初始化日志
    setup_logger("aikefu", logging.DEBUG)
    logger = logging.getLogger("aikefu")
    logger.info("爱客服采集客户端 v%s 启动", cfg.APP_VERSION)

    app = QApplication(sys.argv)
    app.setApplicationName(cfg.APP_NAME)
    app.setApplicationVersion(cfg.APP_VERSION)
    app.setQuitOnLastWindowClosed(False)

    # 启动主窗口（登录检查在 MainWindow.__init__ 内部完成）
    from ui.main_window import MainWindow
    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
