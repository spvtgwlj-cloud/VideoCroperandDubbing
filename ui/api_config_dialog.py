"""API 配置对话框 — 首次运行或按需配置 LLM 供应商和 API Key"""

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel,
    QLineEdit, QComboBox, QCheckBox, QPushButton, QDialogButtonBox,
    QFormLayout, QWidget,
)
from PyQt5.QtCore import Qt
from core.llm_config import LLM_PROVIDERS, load_llm_config, save_llm_config


class ApiConfigDialog(QDialog):
    """LLM 供应商和 API Key 配置对话框"""

    def __init__(self, current_config=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🔑 API 配置")
        self.setFixedSize(680, 620)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        if current_config is None:
            current_config = load_llm_config()
        self._config = current_config

        self._init_ui()
        self._apply_style()
        self._load_config_to_ui()

    # ----------------------------------------------------------------
    # UI 构建
    # ----------------------------------------------------------------

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(12)
        main_layout.setContentsMargins(20, 16, 28, 16)

        # --- 翻译 LLM 配置 ---
        trans_group = QGroupBox("🌐 翻译 LLM 配置（用于视频字幕翻译）")
        trans_layout = QFormLayout(trans_group)
        trans_layout.setSpacing(8)
        trans_layout.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        trans_layout.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)

        self.trans_provider = QComboBox()
        self.trans_provider.addItems(LLM_PROVIDERS.keys())
        self.trans_provider.currentTextChanged.connect(self._on_trans_provider_changed)
        trans_layout.addRow("供应商:", self.trans_provider)

        self.trans_api_key = QLineEdit()
        self.trans_api_key.setEchoMode(QLineEdit.Password)
        self.trans_api_key.setPlaceholderText("输入 API Key...")
        trans_layout.addRow("API Key:", self.trans_api_key)

        self.trans_model = QLineEdit()
        self.trans_model.setPlaceholderText("例如: qwen-max / deepseek-chat")
        trans_layout.addRow("模型名:", self.trans_model)

        self.trans_base_url = QLineEdit()
        self.trans_base_url.setPlaceholderText("https://...")
        trans_layout.addRow("Base URL:", self.trans_base_url)

        main_layout.addWidget(trans_group)

        # --- 声音克隆配置 ---
        clone_group = QGroupBox("🎙️ 声音克隆配置（CosyVoice TTS + 可选独立翻译模型）")
        clone_layout = QVBoxLayout(clone_group)
        clone_layout.setSpacing(8)

        # TTS 部分（始终可见）
        tts_form = QFormLayout()
        tts_form.setSpacing(6)
        tts_form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        tts_form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)

        self.clone_tts_api_key = QLineEdit()
        self.clone_tts_api_key.setEchoMode(QLineEdit.Password)
        self.clone_tts_api_key.setPlaceholderText("CosyVoice TTS API Key（留空则复用翻译 Key）")
        tts_form.addRow("TTS API Key:", self.clone_tts_api_key)

        self.clone_cosy_model = QLineEdit()
        self.clone_cosy_model.setPlaceholderText("cosyvoice-v2")
        tts_form.addRow("CosyVoice 模型:", self.clone_cosy_model)

        clone_layout.addLayout(tts_form)

        # 独立翻译 LLM（可选）
        self.chk_separate_llm = QCheckBox("为声音克隆使用独立的翻译 LLM（与上方翻译配置不同）")
        self.chk_separate_llm.toggled.connect(self._on_separate_llm_toggled)
        clone_layout.addWidget(self.chk_separate_llm)

        self.separate_llm_widget = QWidget()
        sep_form = QFormLayout(self.separate_llm_widget)
        sep_form.setSpacing(6)
        sep_form.setContentsMargins(12, 0, 24, 0)
        sep_form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        sep_form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)

        self.clone_llm_provider = QComboBox()
        self.clone_llm_provider.addItems(LLM_PROVIDERS.keys())
        self.clone_llm_provider.currentTextChanged.connect(self._on_clone_provider_changed)
        sep_form.addRow("供应商:", self.clone_llm_provider)

        self.clone_llm_api_key = QLineEdit()
        self.clone_llm_api_key.setEchoMode(QLineEdit.Password)
        self.clone_llm_api_key.setPlaceholderText("输入 API Key...")
        sep_form.addRow("API Key:", self.clone_llm_api_key)

        self.clone_llm_model = QLineEdit()
        self.clone_llm_model.setPlaceholderText("例如: qwen-max")
        sep_form.addRow("模型名:", self.clone_llm_model)

        self.clone_llm_base_url = QLineEdit()
        self.clone_llm_base_url.setPlaceholderText("https://...")
        sep_form.addRow("Base URL:", self.clone_llm_base_url)

        self.separate_llm_widget.setVisible(False)
        clone_layout.addWidget(self.separate_llm_widget)

        main_layout.addWidget(clone_group)

        # --- 底部按钮 ---
        btn_box = QDialogButtonBox()
        self.save_btn = QPushButton("💾 保存并继续")
        self.save_btn.setDefault(True)
        self.save_btn.clicked.connect(self.accept)
        btn_box.addButton(self.save_btn, QDialogButtonBox.AcceptRole)

        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.clicked.connect(self.reject)
        btn_box.addButton(self.cancel_btn, QDialogButtonBox.RejectRole)

        main_layout.addWidget(btn_box)

    # ----------------------------------------------------------------
    # 信号处理
    # ----------------------------------------------------------------

    def _on_trans_provider_changed(self, text):
        """翻译供应商切换 → 自动填充 base_url"""
        url = LLM_PROVIDERS.get(text, "")
        self.trans_base_url.setText(url)
        is_custom = (text == "自定义 (Custom)")
        self.trans_base_url.setReadOnly(not is_custom)
        if is_custom:
            self.trans_base_url.setStyleSheet(
                "background-color: #101025; border: 1px solid #2A2A5A; border-radius: 6px; "
                "padding: 5px 10px; color: #E0E0F0;"
            )
        else:
            self.trans_base_url.setStyleSheet(
                "background-color: #181830; border: 1px solid #2A2A5A; border-radius: 6px; "
                "padding: 5px 10px; color: #8888AA;"
            )

    def _on_clone_provider_changed(self, text):
        """声音克隆 LLM 供应商切换 → 自动填充 base_url"""
        url = LLM_PROVIDERS.get(text, "")
        self.clone_llm_base_url.setText(url)
        is_custom = (text == "自定义 (Custom)")
        self.clone_llm_base_url.setReadOnly(not is_custom)
        if is_custom:
            self.clone_llm_base_url.setStyleSheet(
                "background-color: #101025; border: 1px solid #2A2A5A; border-radius: 6px; "
                "padding: 5px 10px; color: #E0E0F0;"
            )
        else:
            self.clone_llm_base_url.setStyleSheet(
                "background-color: #181830; border: 1px solid #2A2A5A; border-radius: 6px; "
                "padding: 5px 10px; color: #8888AA;"
            )

    def _on_separate_llm_toggled(self, checked):
        """勾选/取消独立 LLM → 显示/隐藏配置区域 + 调整窗口大小"""
        self.separate_llm_widget.setVisible(checked)
        if checked:
            self.setFixedSize(680, 760)
        else:
            self.setFixedSize(680, 620)

    # ----------------------------------------------------------------
    # 数据加载/保存
    # ----------------------------------------------------------------

    def _load_config_to_ui(self):
        """从 config dict 回填 UI 控件"""
        trans = self._config.get("translation", {})
        vc = self._config.get("voice_clone", {})

        # 翻译部分
        provider = trans.get("provider", "阿里云百炼 (DashScope)")
        idx = self.trans_provider.findText(provider)
        if idx >= 0:
            self.trans_provider.setCurrentIndex(idx)
        self.trans_api_key.setText(trans.get("api_key", ""))
        self.trans_model.setText(trans.get("model", "qwen-max"))
        self.trans_base_url.setText(trans.get("base_url", ""))

        # 声音克隆部分
        self.clone_tts_api_key.setText(vc.get("tts_api_key", ""))
        self.clone_cosy_model.setText(vc.get("cosy_model", "cosyvoice-v2"))

        use_separate = vc.get("use_separate_llm", False)
        self.chk_separate_llm.setChecked(use_separate)

        clone_provider = vc.get("provider", "阿里云百炼 (DashScope)")
        idx2 = self.clone_llm_provider.findText(clone_provider)
        if idx2 >= 0:
            self.clone_llm_provider.setCurrentIndex(idx2)
        self.clone_llm_api_key.setText(vc.get("api_key", ""))
        self.clone_llm_model.setText(vc.get("model", "qwen-max"))
        self.clone_llm_base_url.setText(vc.get("base_url", ""))

    def get_config(self):
        """从 UI 控件读取完整的配置 dict"""
        return {
            "translation": {
                "provider": self.trans_provider.currentText(),
                "api_key": self.trans_api_key.text().strip(),
                "base_url": self.trans_base_url.text().strip(),
                "model": self.trans_model.text().strip() or "qwen-max",
            },
            "voice_clone": {
                "use_separate_llm": self.chk_separate_llm.isChecked(),
                "provider": self.clone_llm_provider.currentText(),
                "api_key": self.clone_llm_api_key.text().strip(),
                "base_url": self.clone_llm_base_url.text().strip(),
                "model": self.clone_llm_model.text().strip() or "qwen-max",
                "tts_api_key": self.clone_tts_api_key.text().strip(),
                "cosy_model": self.clone_cosy_model.text().strip() or "cosyvoice-v2",
            },
        }

    def accept(self):
        """保存按钮：持久化配置并关闭对话框"""
        config = self.get_config()
        save_llm_config(config)
        super().accept()

    # ----------------------------------------------------------------
    # 样式
    # ----------------------------------------------------------------

    def _apply_style(self):
        """暗色主题，匹配主窗口风格"""
        self.setStyleSheet("""
        QDialog {
            background-color: #0A0A1A;
            font-family: "SF Pro Display", "PingFang SC", sans-serif;
            font-size: 13px;
            color: #D0D0E8;
        }
        QGroupBox {
            background-color: #14142B;
            border: 1px solid #262650;
            border-radius: 10px;
            margin-top: 14px;
            padding: 16px 20px 12px 12px;
            font-weight: bold;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            subcontrol-position: top left;
            padding: 0 12px;
            color: #7C7CFF;
            font-weight: bold;
            font-size: 14px;
        }
        QLabel {
            color: #B0B0D0;
            background: transparent;
            font-size: 12px;
        }
        QLineEdit {
            background-color: #101025;
            border: 1px solid #2A2A5A;
            border-radius: 6px;
            padding: 7px 12px;
            color: #E0E0F0;
            min-height: 18px;
            selection-background-color: #2979FF;
        }
        QLineEdit:focus {
            border-color: #00BCD4;
        }
        QComboBox {
            background-color: #101025;
            border: 1px solid #2A2A5A;
            border-radius: 6px;
            padding: 6px 10px;
            color: #E0E0F0;
            min-width: 320px;
            selection-background-color: #2979FF;
        }
        QComboBox:focus {
            border-color: #00BCD4;
        }
        QComboBox QAbstractItemView {
            background-color: #14142B;
            border: 1px solid #2A2A5A;
            color: #D0D0E8;
            selection-background-color: #2979FF;
        }
        QCheckBox {
            color: #B0B0D0;
            background: transparent;
            spacing: 10px;
            padding: 4px 0;
        }
        QCheckBox::indicator {
            width: 20px;
            height: 20px;
        }
        QPushButton {
            border-radius: 6px;
            padding: 8px 18px;
            font-weight: bold;
            border: none;
            font-size: 13px;
        }
        QPushButton#save_btn {
            background-color: #2979FF;
            color: white;
        }
        QPushButton#save_btn:hover {
            background-color: #1A6BFF;
        }
        QDialogButtonBox {
            background: transparent;
        }
        """)
        self.save_btn.setObjectName("save_btn")
