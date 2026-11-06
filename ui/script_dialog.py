"""建议脚本结果对话框。"""

import os
import subprocess

from PyQt5.QtWidgets import (
    QApplication, QDialog, QHBoxLayout, QLabel, QPushButton, QTextEdit,
    QVBoxLayout,
)


class ScriptDialog(QDialog):
    """展示建议脚本，支持复制与打开输出目录。"""

    def __init__(self, script, markdown, json_path="", md_path="",
                 parent=None):
        super().__init__(parent)
        self.script = script
        self.json_path = json_path
        self.md_path = md_path
        self.setWindowTitle("📝 建议脚本")
        self.resize(900, 700)

        layout = QVBoxLayout(self)
        header = QLabel(f"{script.title}  ·  {script.target_duration}")
        header.setStyleSheet(
            "font-size: 16px; font-weight: bold; color: #E0E0F0;",
        )
        layout.addWidget(header)

        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setPlainText(markdown)
        layout.addWidget(self.text_edit, 1)

        row = QHBoxLayout()
        self.btn_copy = QPushButton("复制脚本")
        self.btn_copy.clicked.connect(self._copy_script)
        self.btn_open = QPushButton("打开输出文件夹")
        self.btn_open.clicked.connect(self._open_folder)
        self.btn_close = QPushButton("关闭")
        self.btn_close.clicked.connect(self.accept)
        row.addWidget(self.btn_copy)
        row.addWidget(self.btn_open)
        row.addStretch()
        row.addWidget(self.btn_close)
        layout.addLayout(row)

        self._apply_style()

    def _copy_script(self) -> None:
        QApplication.clipboard().setText(self.text_edit.toPlainText())

    def _open_folder(self) -> None:
        folder = os.path.dirname(self.md_path) if self.md_path else ""
        if folder and os.path.isdir(folder):
            subprocess.run(["open", folder])

    def _apply_style(self) -> None:
        self.setStyleSheet("""
        QDialog {
            background-color: #0A0A1A;
            color: #D0D0E8;
            font-family: "SF Pro Display", "PingFang SC", sans-serif;
            font-size: 13px;
        }
        QLabel { color: #B0B0D0; background: transparent; }
        QTextEdit {
            background-color: #101025;
            border: 1px solid #2A2A5A;
            border-radius: 8px;
            padding: 10px;
            color: #E0E0F0;
            selection-background-color: #2979FF;
        }
        QPushButton {
            background-color: #2979FF;
            color: white;
            border: none;
            border-radius: 6px;
            padding: 7px 16px;
            font-weight: bold;
        }
        QPushButton:hover { background-color: #1A6BFF; }
        """)
