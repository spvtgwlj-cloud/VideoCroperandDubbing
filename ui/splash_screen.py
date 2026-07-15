"""启动画面 — SplashScreen"""

from PyQt5.QtWidgets import QSplashScreen
from PyQt5.QtGui import QPixmap, QPainter, QColor, QFont, QPen, QLinearGradient
from PyQt5.QtCore import Qt, QRect

# 版本号（与 HANDOFF 对齐）
VERSION = "v4.3.2"
APP_NAME = "AI 视频配音 Pro"


def _build_pixmap(width: int = 420, height: int = 240) -> QPixmap:
    """用代码绘制启动画面 Pixmap（零外部资源依赖）。"""
    pm = QPixmap(width, height)
    pm.fill(Qt.transparent)

    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing)

    # ---- 背景 ----
    gradient = QLinearGradient(0, 0, 0, height)
    gradient.setColorAt(0.0, QColor("#1a1a2e"))
    gradient.setColorAt(1.0, QColor("#16213e"))
    painter.setPen(Qt.NoPen)
    painter.setBrush(gradient)
    painter.drawRoundedRect(0, 0, width, height, 16, 16)

    # ---- 图标区域（圆形底） ----
    circle_cx, circle_cy = width // 2, 58
    painter.setBrush(QColor("#7C7CFF"))
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(circle_cx - 22, circle_cy - 22, 44, 44)

    # 图标文字
    font_icon = QFont("Segoe UI Emoji", 22)
    font_icon.setStyleStrategy(QFont.PreferDefault)
    painter.setFont(font_icon)
    painter.setPen(QColor("#ffffff"))
    painter.drawText(QRect(circle_cx - 20, circle_cy - 18, 40, 40), Qt.AlignCenter, "🎬")

    # ---- 应用名 ----
    font_title = QFont("PingFang SC", 18, QFont.Bold)
    font_title.setStyleStrategy(QFont.PreferDefault)
    painter.setFont(font_title)
    painter.setPen(QColor("#ffffff"))
    painter.drawText(QRect(0, 95, width, 30), Qt.AlignCenter, APP_NAME)

    # ---- 版本号 ----
    font_ver = QFont("SF Mono", 11)
    font_ver.setStyleStrategy(QFont.PreferDefault)
    painter.setFont(font_ver)
    painter.setPen(QColor("#8888aa"))
    painter.drawText(QRect(0, 125, width, 20), Qt.AlignCenter, VERSION)

    # ---- 分隔线 ----
    painter.setPen(QPen(QColor("#333355"), 1))
    painter.drawLine(60, 158, width - 60, 158)

    # ---- 状态文字（由 showMessage 覆盖，此处为默认值） ----
    font_status = QFont("PingFang SC", 10)
    font_status.setStyleStrategy(QFont.PreferDefault)
    painter.setFont(font_status)
    painter.setPen(QColor("#7777aa"))
    painter.drawText(QRect(0, 168, width, 22), Qt.AlignCenter, "正在启动…")

    # ---- 底部彩色横条 ----
    accent_gradient = QLinearGradient(80, 0, width - 80, 0)
    accent_gradient.setColorAt(0.0, QColor("#7C7CFF"))
    accent_gradient.setColorAt(0.5, QColor("#FF6D00"))
    accent_gradient.setColorAt(1.0, QColor("#00D2FF"))
    painter.setBrush(accent_gradient)
    painter.setPen(Qt.NoPen)
    painter.drawRoundedRect(80, height - 6, width - 160, 3, 1, 1)

    painter.end()
    return pm


class SplashScreen(QSplashScreen):
    """应用启动画面。

    在 MainWindow 构造前显示，构造完成后自动淡出过渡到主窗口。
    用法:
        splash = SplashScreen()
        splash.show()
        app.processEvents()
        # ... 初始化耗时组件 ...
        splash.finish(main_window)
    """

    def __init__(self):
        pixmap = _build_pixmap()
        super().__init__(pixmap)
        self.setWindowFlags(
            Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.SplashScreen
        )
        # 居中
        screen_geo = self.screen().availableGeometry()
        x = (screen_geo.width() - pixmap.width()) // 2
        y = (screen_geo.height() - pixmap.height()) // 2
        self.setGeometry(x, y, pixmap.width(), pixmap.height())

    def set_status(self, text: str):
        """更新状态文字（e.g. "正在加载 AI 模型…"）。"""
        self.showMessage(
            text,
            Qt.AlignHCenter | Qt.AlignBottom,
            QColor("#ccccdd"),
        )
