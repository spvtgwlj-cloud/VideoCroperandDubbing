#! /usr/bin/env python3
"""AI Video Dubbing Pro — 主入口

用法:
    python entry.py
"""

import sys
import warnings

# 抑制 urllib3 版本不兼容警告（不影响功能，仅造成视觉干扰）
warnings.filterwarnings("ignore", message=".*urllib3.*", category=UserWarning)

from PyQt5.QtWidgets import QApplication
from ui.ui_main import MainWindow


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())

