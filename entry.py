#! /usr/bin/env python3
"""AI Video Dubbing Pro — 主入口

用法:
    python entry.py
"""

import os
import sys
import warnings

# 抑制 urllib3 版本不兼容警告（不影响功能，仅造成视觉干扰）
warnings.filterwarnings("ignore", message=".*urllib3.*", category=UserWarning)

from PyQt5.QtWidgets import QApplication
from ui.ui_main import MainWindow


if __name__ == "__main__":
    app = QApplication(sys.argv)

    # 启动画面（MainWindow 构造期间可见，构造完成后自动淡出）
    from ui.splash_screen import SplashScreen
    splash = SplashScreen()
    splash.show()
    app.processEvents()

    # 检查 API 配置（首次运行无配置时弹出设置对话框）
    from core.llm_config import load_llm_config
    splash.set_status("正在检查 API 配置...")
    app.processEvents()
    config = load_llm_config()
    translation_key = config.get("translation", {}).get("api_key", "")
    env_key = os.environ.get("DASHSCOPE_API_KEY", "")
    if not translation_key and not env_key:
        from ui.api_config_dialog import ApiConfigDialog
        splash.set_status("首次使用，请配置 API...")
        app.processEvents()
        dialog = ApiConfigDialog(config)
        dialog.exec_()

    splash.set_status("正在加载主界面...")
    app.processEvents()
    window = MainWindow()
    window.show()
    splash.finish(window)
    sys.exit(app.exec_())
