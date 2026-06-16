"""主 UI 界面 — MainWindow"""

import os
import json
import time
import subprocess

import numpy as np
from PyQt5.QtGui import QPainter, QColor, QPixmap
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QLabel, QPushButton, QComboBox, QLineEdit, QTextEdit,
    QGroupBox, QRadioButton, QSpinBox, QFileDialog, QGridLayout,
    QCheckBox, QProgressBar, QSlider, QMessageBox, QScrollArea,
)
from PyQt5.QtCore import Qt

from core.config import PLATFORM_PRESETS, SUBTITLE_COLORS, EDGE_TTS_VOICES
from core.process_thread import VideoProcessThread


class MainWindow(QMainWindow):
    """AI Video Dubbing Pro 主窗口"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("AI Video Dubbing Pro (Mac Native)")
        self.resize(1280, 880)
        self.thread = None
        self.last_output = None
        self.batch_folder_path = ""
        self.output_dir = None  # 给 draw_waveform 备用
        self.setAcceptDrops(True)
        self.init_ui()
        self.apply_apple_style()

    # -------- 拖拽输入 --------
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path.lower().endswith((".mp4", ".mov", ".avi", ".mkv", ".wav", ".mp3", ".m4a")):
                if path.lower().endswith((".mp4", ".mov", ".avi", ".mkv")):
                    self.input_path.setText(path)
                    self.draw_waveform(path)
                else:
                    # 音频文件自动填入第一个音频槽
                    self.input_audio_1.setText(path)
                break

    # -------- UI 构建 --------
    def init_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QHBoxLayout(main_widget)
        main_layout.setContentsMargins(15, 15, 15, 15)

        # ---------- 左：预览 + 波形 + 日志 ----------
        self.left_panel = QWidget()
        left_layout = QVBoxLayout(self.left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)

        self.preview_label = QLabel("🎬 视频预览")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumHeight(120)
        self.preview_label.setStyleSheet(
            "background-color: #0D0D20; color: #5A5A9A; border: 1px solid #2A2A55;"
            " border-radius: 10px; font-size: 14px;"
        )
        left_layout.addWidget(self.preview_label, 2)

        # 波形可视化（缩小高度）
        self.waveform_label = QLabel("🎵 音频波形 (选择视频后自动生成)")
        self.waveform_label.setAlignment(Qt.AlignCenter)
        self.waveform_label.setFixedHeight(54)
        self.waveform_label.setStyleSheet(
            "background-color: #0D0D20; color: #5A5A9A; border: 1px solid #2A2A55;"
            " border-radius: 8px; font-size: 11px;"
        )
        left_layout.addWidget(self.waveform_label, 0)

        # ---- 日志面板（移至左侧，放大） ----
        log_group = QGroupBox("📋 运行日志 (Console)")
        log_layout = QVBoxLayout(log_group)
        log_layout.setContentsMargins(6, 20, 6, 6)
        self.log_console = QTextEdit()
        self.log_console.setReadOnly(True)
        log_layout.addWidget(self.log_console)
        left_layout.addWidget(log_group, 5)

        # ---------- 右：配置（带滚动） ----------
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setFrameShape(QScrollArea.NoFrame)
        right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        right_scroll_container = QWidget()
        right_layout = QVBoxLayout(right_scroll_container)
        right_layout.setContentsMargins(15, 0, 0, 0)

        config_group = QGroupBox("系统配置 (Configuration)")
        config_layout = QGridLayout(config_group)
        config_layout.setSpacing(10)
        config_layout.setContentsMargins(20, 25, 20, 20)

        # ---- Row 0: 平台预设 ----
        config_layout.addWidget(QLabel("平台预设:"), 0, 0)
        self.preset_combo = QComboBox()
        preset_names = list(PLATFORM_PRESETS.keys())
        self.preset_combo.addItems(preset_names)
        self.preset_combo.setCurrentText("手动配置")
        self.preset_combo.currentTextChanged.connect(self.on_preset_changed)
        config_layout.addWidget(self.preset_combo, 0, 1, 1, 3)

        # ---- Row 1: 本地视频 ----
        config_layout.addWidget(QLabel("本地视频:"), 1, 0)
        self.input_path = QLineEdit()
        config_layout.addWidget(self.input_path, 1, 1, 1, 2)
        btn_browse = QPushButton("浏览视频")
        btn_browse.clicked.connect(self.browse_video)
        config_layout.addWidget(btn_browse, 1, 3)

        # ---- Row 2: 批量处理 ----
        config_layout.addWidget(QLabel("批量处理:"), 2, 0)
        self.chk_batch = QCheckBox("批量处理整个文件夹")
        self.chk_batch.toggled.connect(self.on_batch_toggled)
        config_layout.addWidget(self.chk_batch, 2, 1)
        self.btn_browse_folder = QPushButton("选择文件夹")
        self.btn_browse_folder.clicked.connect(self.browse_folder)
        self.btn_browse_folder.setVisible(False)
        config_layout.addWidget(self.btn_browse_folder, 2, 2)
        self.lbl_batch_count = QLabel("")
        self.lbl_batch_count.setStyleSheet("color: #86868B;")
        config_layout.addWidget(self.lbl_batch_count, 2, 3)

        # ---- Row 3: 视频裁剪 ----
        config_layout.addWidget(QLabel("视频裁剪:"), 3, 0)
        self.trim_start = QSpinBox()
        self.trim_start.setRange(0, 99999)
        self.trim_start.setSuffix(" 秒 起始")
        self.trim_start.setSpecialValueText("从开头")
        config_layout.addWidget(self.trim_start, 3, 1)
        self.trim_end = QSpinBox()
        self.trim_end.setRange(0, 99999)
        self.trim_end.setSuffix(" 秒 结束")
        self.trim_end.setSpecialValueText("到结尾")
        config_layout.addWidget(self.trim_end, 3, 2, 1, 2)

        # ---- Row 4: 目标语言 ----
        config_layout.addWidget(QLabel("目标语言:"), 4, 0)
        self.audio_lang = QComboBox()
        self.audio_lang.addItems(["中文 (Chinese) - 自动翻译生成", "英文 (English) - 自动翻译生成"])
        config_layout.addWidget(self.audio_lang, 4, 1, 1, 3)

        # ---- Row 5: 画面输出 ----
        config_layout.addWidget(QLabel("画面输出:"), 5, 0)
        self.radio_horizontal = QRadioButton("横屏 (保持原比例)")
        self.radio_vertical = QRadioButton("竖屏 (InsightFace 智能追踪)")
        self.radio_vertical.setChecked(True)
        lay_radio = QHBoxLayout()
        lay_radio.addWidget(self.radio_horizontal)
        lay_radio.addWidget(self.radio_vertical)
        lay_radio.addStretch()
        config_layout.addLayout(lay_radio, 5, 1, 1, 3)

        # ---- Row 6: 输出分辨率 ----
        config_layout.addWidget(QLabel("输出分辨率:"), 6, 0)
        self.res_w_spin = QSpinBox()
        self.res_w_spin.setRange(240, 4320)
        self.res_w_spin.setValue(1080)
        self.res_w_spin.setSuffix(" ×")
        config_layout.addWidget(self.res_w_spin, 6, 1)
        self.res_w_spin.valueChanged.connect(
            lambda v: self._update_aspect_ratio(self.res_w_spin, is_width=True))
        self.res_h_spin = QSpinBox()
        self.res_h_spin.setRange(240, 4320)
        self.res_h_spin.setValue(1920)
        self.res_h_spin.setSuffix(" px")
        config_layout.addWidget(self.res_h_spin, 6, 2)
        self.res_h_spin.valueChanged.connect(
            lambda v: self._update_aspect_ratio(self.res_h_spin, is_width=False))
        self.chk_lock_aspect = QCheckBox("锁定 9:16")
        self.chk_lock_aspect.setChecked(True)
        config_layout.addWidget(self.chk_lock_aspect, 6, 3)
        # 横屏时置灰分辨率控件
        self.radio_horizontal.toggled.connect(self._toggle_resolution_controls)
        self.radio_vertical.toggled.connect(self._toggle_resolution_controls)

        # ---- Row 7: 字幕 ----
        config_layout.addWidget(QLabel("字幕配置:"), 7, 0)
        self.chk_subtitle = QCheckBox("在画面上生成硬字幕")
        self.chk_subtitle.setChecked(True)
        config_layout.addWidget(self.chk_subtitle, 7, 1)
        self.subtitle_offset_spin = QSpinBox()
        self.subtitle_offset_spin.setRange(-2000, 2000)
        self.subtitle_offset_spin.setValue(0)
        self.subtitle_offset_spin.setSuffix(" ms")
        self.subtitle_offset_spin.setSingleStep(100)
        self.subtitle_offset_spin.setToolTip("字幕时间轴整体偏移（负值提前，正值延后）")
        config_layout.addWidget(self.subtitle_offset_spin, 7, 2, 1, 2)

        # ---- Row 8: 字幕样式 ----
        config_layout.addWidget(QLabel("字幕样式:"), 8, 0)
        self.sub_color_combo = QComboBox()
        self.sub_color_combo.addItems(list(SUBTITLE_COLORS.keys()))
        config_layout.addWidget(self.sub_color_combo, 8, 1)

        font_layout = QHBoxLayout()
        font_layout.addWidget(QLabel("字号"))
        self.sub_font_slider = QSlider(Qt.Horizontal)
        self.sub_font_slider.setRange(30, 100)
        self.sub_font_slider.setValue(55)  # 0.055 = 5.5%
        self.sub_font_slider.setTickPosition(QSlider.TicksBelow)
        self.sub_font_slider.setTickInterval(10)
        self.sub_font_label = QLabel("5.5%")
        self.sub_font_slider.valueChanged.connect(
            lambda v: self.sub_font_label.setText(f"{v / 10:.1f}%")
        )
        font_layout.addWidget(self.sub_font_slider)
        font_layout.addWidget(self.sub_font_label)
        config_layout.addLayout(font_layout, 8, 2)

        self.chk_sub_bg = QCheckBox("背景框")
        self.chk_bilingual = QCheckBox("双语字幕")
        sub_checkbox_layout = QHBoxLayout()
        sub_checkbox_layout.addWidget(self.chk_sub_bg)
        sub_checkbox_layout.addWidget(self.chk_bilingual)
        sub_checkbox_layout.addStretch()
        config_layout.addLayout(sub_checkbox_layout, 8, 3)

        # ---- Row 9: 字幕导出 ----
        config_layout.addWidget(QLabel("字幕导出:"), 9, 0)
        self.chk_export_subtitle = QCheckBox("导出 SRT 字幕文件（可手动编辑后导入）")
        self.chk_export_subtitle.setChecked(True)
        config_layout.addWidget(self.chk_export_subtitle, 9, 1, 1, 3)

        # ---- Row 10: 字幕文件源 ----
        config_layout.addWidget(QLabel("字幕来源:"), 10, 0)
        self.radio_sub_auto = QRadioButton("系统自动生成")
        self.radio_sub_auto.setChecked(True)
        self.radio_sub_manual = QRadioButton("导入外部字幕文件")
        self.radio_sub_auto.toggled.connect(self._toggle_subtitle_source)
        self.radio_sub_manual.toggled.connect(self._toggle_subtitle_source)
        sub_src_layout = QHBoxLayout()
        sub_src_layout.addWidget(self.radio_sub_auto)
        sub_src_layout.addWidget(self.radio_sub_manual)
        sub_src_layout.addStretch()
        config_layout.addLayout(sub_src_layout, 10, 1, 1, 3)

        # ---- Row 11: 外部字幕文件路径 ----
        self.subtitle_file_panel = QWidget()
        sub_file_layout = QHBoxLayout(self.subtitle_file_panel)
        sub_file_layout.setContentsMargins(0, 0, 0, 0)
        self.subtitle_file_path = QLineEdit()
        self.subtitle_file_path.setPlaceholderText("选择 .srt 字幕文件...")
        sub_file_layout.addWidget(self.subtitle_file_path)
        btn_browse_sub = QPushButton("浏览")
        btn_browse_sub.clicked.connect(self.browse_subtitle)
        sub_file_layout.addWidget(btn_browse_sub)
        config_layout.addWidget(self.subtitle_file_panel, 11, 1, 1, 3)
        self.subtitle_file_panel.setVisible(False)

        # ---- Row 12: 声音 ----
        config_layout.addWidget(QLabel("声音配置:"), 12, 0)
        self.chk_voice_clone = QCheckBox("启用 AI 声音克隆配音 (取消勾选则保留原声)")
        self.chk_voice_clone.setChecked(False)  # 默认保留原声
        config_layout.addWidget(self.chk_voice_clone, 12, 1, 1, 3)

        # ---- Row 13: BGM 保留 + Edge-TTS 优先 ----
        row13_widget = QWidget()
        row13_layout = QHBoxLayout(row13_widget)
        row13_layout.setContentsMargins(0, 0, 0, 0)
        self.chk_bgm_preserve = QCheckBox("分离并保留背景音乐 (需安装 spleeter)")
        self.chk_edge_tts_first = QCheckBox("优先使用 Edge-TTS 语音合成 (分角色选音色)")
        row13_layout.addWidget(self.chk_bgm_preserve)
        row13_layout.addSpacing(16)
        row13_layout.addWidget(self.chk_edge_tts_first)
        row13_layout.addStretch()
        config_layout.addWidget(row13_widget, 13, 1, 1, 3)

        # ---- Row 14: 配音模式 ----
        self.lbl_clone_mode = QLabel("配音模式:")
        config_layout.addWidget(self.lbl_clone_mode, 14, 0)
        self.radio_clone_video = QRadioButton("全部提取视频原声 (自动区分角色)")
        self.radio_clone_upload = QRadioButton("指定本地音频映射 (支持多人覆盖)")
        self.radio_clone_video.setChecked(True)
        self.mode_widget = QWidget()
        mode_layout = QHBoxLayout(self.mode_widget)
        mode_layout.setContentsMargins(0, 0, 0, 0)
        mode_layout.addWidget(self.radio_clone_video)
        mode_layout.addWidget(self.radio_clone_upload)
        mode_layout.addStretch()
        config_layout.addWidget(self.mode_widget, 14, 1, 1, 3)

        # ---- Row 15: 音频上传面板 ----
        self.upload_panel = QWidget()
        upload_layout = QGridLayout(self.upload_panel)
        upload_layout.setContentsMargins(0, 0, 0, 0)
        upload_layout.setSpacing(8)

        upload_layout.addWidget(QLabel("样本一:"), 0, 0)
        self.input_audio_1 = QLineEdit()
        self.input_audio_1.setPlaceholderText("选择音频 (建议5-10秒)")
        upload_layout.addWidget(self.input_audio_1, 0, 1)
        btn_au1 = QPushButton("浏览")
        btn_au1.clicked.connect(lambda: self.browse_audio(self.input_audio_1))
        upload_layout.addWidget(btn_au1, 0, 2)
        self.combo_spk_1 = QComboBox()
        self.combo_spk_1.addItems(["映射至: 角色 0", "映射至: 角色 1"])
        self.combo_spk_1.setCurrentIndex(0)
        upload_layout.addWidget(self.combo_spk_1, 0, 3)

        upload_layout.addWidget(QLabel("样本二:"), 1, 0)
        self.input_audio_2 = QLineEdit()
        self.input_audio_2.setPlaceholderText("选择音频 (可选)")
        upload_layout.addWidget(self.input_audio_2, 1, 1)
        btn_au2 = QPushButton("浏览")
        btn_au2.clicked.connect(lambda: self.browse_audio(self.input_audio_2))
        upload_layout.addWidget(btn_au2, 1, 2)
        self.combo_spk_2 = QComboBox()
        self.combo_spk_2.addItems(["映射至: 角色 0", "映射至: 角色 1"])
        self.combo_spk_2.setCurrentIndex(1)
        upload_layout.addWidget(self.combo_spk_2, 1, 3)

        config_layout.addWidget(self.upload_panel, 15, 0, 1, 4)

        # ---- Row 16: Edge-TTS 音色选择面板 ----
        self.edge_tts_panel = QWidget()
        edge_tts_layout = QGridLayout(self.edge_tts_panel)
        edge_tts_layout.setContentsMargins(0, 0, 0, 0)
        edge_tts_layout.setSpacing(8)
        edge_tts_layout.setHorizontalSpacing(8)

        edge_tts_layout.addWidget(QLabel("Edge-TTS 音色:"), 0, 0)

        edge_tts_layout.addWidget(QLabel("角色 0:"), 0, 1)
        self.combo_edge_spk0 = QComboBox()
        for voice_id, display_name in EDGE_TTS_VOICES.items():
            self.combo_edge_spk0.addItem(display_name, voice_id)
        self.combo_edge_spk0.setCurrentIndex(0)  # 默认男声
        edge_tts_layout.addWidget(self.combo_edge_spk0, 0, 2)

        edge_tts_layout.addWidget(QLabel("角色 1:"), 1, 1)
        self.combo_edge_spk1 = QComboBox()
        for voice_id, display_name in EDGE_TTS_VOICES.items():
            self.combo_edge_spk1.addItem(display_name, voice_id)
        # 角色 1 默认选女声（晓晓）
        xiaoxiao_idx = self.combo_edge_spk1.findData("zh-CN-XiaoxiaoNeural")
        if xiaoxiao_idx >= 0:
            self.combo_edge_spk1.setCurrentIndex(xiaoxiao_idx)
        edge_tts_layout.addWidget(self.combo_edge_spk1, 1, 2)
        edge_tts_layout.setColumnStretch(3, 1)
        self.edge_tts_panel.setVisible(False)  # 默认隐藏

        config_layout.addWidget(self.edge_tts_panel, 16, 0, 1, 4)

        # ---- Row 17: 快速预览 + 编码/帧率 ----
        config_layout.addWidget(QLabel("快速预览:"), 17, 0)
        self.chk_quick_preview = QCheckBox("仅处理前")
        self.quick_preview_sec = QSpinBox()
        self.quick_preview_sec.setRange(5, 120)
        self.quick_preview_sec.setValue(15)
        self.quick_preview_sec.setSuffix(" 秒")
        self.quick_preview_sec.setEnabled(False)
        self.chk_quick_preview.toggled.connect(self.quick_preview_sec.setEnabled)
        preview_layout = QHBoxLayout()
        preview_layout.addWidget(self.chk_quick_preview)
        preview_layout.addWidget(self.quick_preview_sec)
        preview_layout.addStretch()
        config_layout.addLayout(preview_layout, 17, 1, 1, 3)

        config_layout.addWidget(QLabel("编码/帧率:"), 18, 0)
        self.codec_combo = QComboBox()
        self.codec_combo.addItems(["H.264 (MP4)", "H.265 (HEVC)"])
        config_layout.addWidget(self.codec_combo, 18, 1)
        self.fps_spin = QSpinBox()
        self.fps_spin.setRange(15, 120)
        self.fps_spin.setValue(30)
        self.fps_spin.setSuffix(" FPS")
        config_layout.addWidget(self.fps_spin, 18, 2, 1, 2)

        # ---- Row 19: 进度条 ----
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        config_layout.addWidget(self.progress_bar, 19, 0, 1, 4)

        # ---- Row 20: 开始按钮 + 输出操作 ----
        btn_layout = QHBoxLayout()
        self.btn_start = QPushButton("开始执行 (Start Processing)")
        self.btn_start.setFixedHeight(45)
        self.btn_start.clicked.connect(self.start_processing)
        btn_layout.addWidget(self.btn_start, 3)

        self.btn_open_folder = QPushButton("📂 打开文件夹")
        self.btn_open_folder.setFixedHeight(45)
        self.btn_open_folder.clicked.connect(self.open_output_folder)
        self.btn_open_folder.setEnabled(False)
        btn_layout.addWidget(self.btn_open_folder, 1)

        self.btn_preview = QPushButton("▶ 预览视频")
        self.btn_preview.setFixedHeight(45)
        self.btn_preview.clicked.connect(self.preview_output)
        self.btn_preview.setEnabled(False)
        btn_layout.addWidget(self.btn_preview, 1)

        config_layout.addLayout(btn_layout, 20, 0, 1, 4)

        # ---- Row 21: 配置保存/加载 ----
        config_btn_layout = QHBoxLayout()
        self.btn_save_config = QPushButton("💾 保存配置")
        self.btn_save_config.clicked.connect(self.save_config)
        self.btn_load_config = QPushButton("📂 加载配置")
        self.btn_load_config.clicked.connect(self.load_config)
        config_btn_layout.addWidget(self.btn_save_config)
        config_btn_layout.addWidget(self.btn_load_config)
        config_btn_layout.addStretch()
        config_layout.addLayout(config_btn_layout, 21, 0, 1, 4)

        right_layout.addWidget(config_group)

        main_layout.addWidget(self.left_panel, 5)

        right_scroll.setWidget(right_scroll_container)
        main_layout.addWidget(right_scroll, 6)

        # 绑定联动
        self.chk_voice_clone.toggled.connect(self.toggle_clone_options)
        self.radio_clone_video.toggled.connect(self.toggle_clone_options)
        self.radio_clone_upload.toggled.connect(self.toggle_clone_options)
        self.chk_edge_tts_first.toggled.connect(self.toggle_edge_tts_options)
        self.toggle_clone_options()
        self.toggle_edge_tts_options()

    # -------- 预设切换 --------
    def on_preset_changed(self, preset_name):
        preset = PLATFORM_PRESETS.get(preset_name)
        if not preset or preset_name == "手动配置":
            return

        is_vertical = preset["is_vertical"]
        if is_vertical is True:
            self.radio_vertical.setChecked(True)
        elif is_vertical is False:
            self.radio_horizontal.setChecked(True)

        codec = preset["codec"]
        if codec:
            idx = self.codec_combo.findText(codec)
            if idx >= 0:
                self.codec_combo.setCurrentIndex(idx)

        fps = preset["fps"]
        if fps > 0:
            self.fps_spin.setValue(fps)

        ow, oh = preset.get("ow", 0), preset.get("oh", 0)
        if ow > 0 and oh > 0:
            self.res_w_spin.setValue(ow)
            self.res_h_spin.setValue(oh)

        self.log(f"✅ 已应用预设: {preset_name} — {preset['desc']}")

    # -------- 批量模式 --------
    def on_batch_toggled(self, checked):
        self.btn_browse_folder.setVisible(checked)
        self.lbl_batch_count.setVisible(checked)
        if not checked:
            self.lbl_batch_count.setText("")
            self.batch_folder_path = ""

    def browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择视频文件夹")
        if folder:
            self.batch_folder_path = folder
            videos = [f for f in os.listdir(folder) if f.lower().endswith((".mp4", ".mov", ".avi", ".mkv"))]
            self.lbl_batch_count.setText(f"找到 {len(videos)} 个视频")
            self.log(f"📁 批量文件夹: {folder} ({len(videos)} 个视频)")

    # -------- 输出操作 --------
    def open_output_folder(self):
        if self.last_output and os.path.exists(os.path.dirname(self.last_output)):
            subprocess.run(["open", os.path.dirname(self.last_output)])

    def preview_output(self):
        if self.last_output and os.path.exists(self.last_output):
            subprocess.run(["open", self.last_output])

    # -------- 联动 --------
    def toggle_clone_options(self):
        is_clone = self.chk_voice_clone.isChecked()
        self.lbl_clone_mode.setVisible(is_clone)
        self.mode_widget.setVisible(is_clone)

        is_upload = is_clone and self.radio_clone_upload.isChecked()
        self.upload_panel.setVisible(is_upload)

        # 声音克隆开关变化时同步更新 Edge-TTS 面板显隐
        if is_clone:
            self.toggle_edge_tts_options()
        else:
            self.edge_tts_panel.setVisible(False)

    def toggle_edge_tts_options(self):
        """显示/隐藏 Edge-TTS 音色选择面板"""
        visible = self.chk_voice_clone.isChecked() and self.chk_edge_tts_first.isChecked()
        self.edge_tts_panel.setVisible(visible)

    # -------- 分辨率联动 --------
    def _toggle_resolution_controls(self):
        """横屏时置灰分辨率控件（竖屏才可自定义分辨率）"""
        is_portrait = self.radio_vertical.isChecked()
        self.res_w_spin.setEnabled(is_portrait)
        self.res_h_spin.setEnabled(is_portrait)
        self.chk_lock_aspect.setEnabled(is_portrait)

    def _update_aspect_ratio(self, changed_spin, is_width):
        """锁定比例勾选时，修改宽/高自动按 9:16 等比变化"""
        if not self.chk_lock_aspect.isChecked():
            return
        # 阻止循环触发
        self.res_w_spin.blockSignals(True)
        self.res_h_spin.blockSignals(True)
        try:
            if is_width:
                self.res_h_spin.setValue(int(changed_spin.value() * 16 / 9))
            else:
                self.res_w_spin.setValue(int(changed_spin.value() * 9 / 16))
        finally:
            self.res_w_spin.blockSignals(False)
            self.res_h_spin.blockSignals(False)

    # -------- 样式：深空科技风 --------
    def apply_apple_style(self):
        self.setStyleSheet("""
        QMainWindow { background-color: #0A0A1A; }
        QWidget {
            font-family: "SF Pro Display", "PingFang SC", sans-serif;
            font-size: 13px; color: #D0D0E8;
            background-color: #0A0A1A;
        }
        QGroupBox {
            background-color: #14142B; border: 1px solid #262650;
            border-radius: 10px; margin-top: 14px; padding: 12px 0 8px;
        }
        QGroupBox::title {
            subcontrol-origin: margin; subcontrol-position: top left;
            padding: 0 12px; color: #7C7CFF; font-weight: bold; font-size: 14px;
        }
        QLineEdit, QComboBox, QSpinBox {
            background-color: #101025; border: 1px solid #2A2A5A;
            border-radius: 6px; padding: 5px 10px; color: #E0E0F0;
            selection-background-color: #2979FF;
        }
        QLineEdit:focus, QComboBox:focus, QSpinBox:focus {
            border-color: #00BCD4;
        }
        QPushButton {
            background-color: #2979FF; color: white; border-radius: 6px;
            padding: 7px 14px; font-weight: bold; border: none;
        }
        QPushButton:hover { background-color: #1A6BFF; }
        QPushButton:pressed { background-color: #0050D0; }
        QPushButton:disabled { background-color: #252540; color: #5A5A7A; }
        QTextEdit {
            background-color: #080818; color: #00E676;
            font-family: "Menlo", "JetBrains Mono", monospace;
            border: 1px solid #1E1E40; border-radius: 6px; padding: 8px;
        }
        QProgressBar {
            border: 1px solid #2A2A5A; border-radius: 6px; text-align: center;
            background: #101025; color: #D0D0E8; height: 20px;
        }
        QProgressBar::chunk {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #00BCD4, stop:1 #2979FF);
            border-radius: 5px;
        }
        QCheckBox { spacing: 8px; color: #C0C0E0; }
        QCheckBox::indicator {
            width: 16px; height: 16px; border-radius: 4px;
            border: 2px solid #3A3A6A; background: #101025;
        }
        QCheckBox::indicator:checked {
            background-color: #2979FF; border-color: #2979FF;
        }
        QRadioButton { spacing: 8px; color: #C0C0E0; }
        QRadioButton::indicator {
            width: 16px; height: 16px; border-radius: 8px;
            border: 2px solid #3A3A6A; background: #101025;
        }
        QRadioButton::indicator:checked {
            background-color: #2979FF; border-color: #2979FF;
        }
        QSlider::groove:horizontal {
            height: 6px; background: #202045; border-radius: 3px;
        }
        QSlider::handle:horizontal {
            background: #00BCD4; width: 14px; height: 14px;
            margin: -4px 0; border-radius: 7px;
        }
        QScrollBar:vertical {
            background: #0A0A1A; width: 8px; border: none;
        }
        QScrollBar::handle:vertical {
            background: #2A2A5A; border-radius: 4px; min-height: 30px;
        }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }
        QComboBox QAbstractItemView {
            background-color: #14142B; border: 1px solid #2A2A5A;
            selection-background-color: #2979FF; color: #E0E0F0;
        }
        QComboBox::drop-down {
            border: none; background: #2A2A5A; border-radius: 0 4px 4px 0;
        }
        QLabel { color: #D0D0E8; background: transparent; }
        """)

    # -------- 字幕源联动 --------
    def _toggle_subtitle_source(self):
        """根据字幕来源选择显示/隐藏外部文件导入面板"""
        is_manual = self.radio_sub_manual.isChecked()
        self.subtitle_file_panel.setVisible(is_manual)

    # -------- 文件对话框 --------
    def browse_video(self):
        file_name, _ = QFileDialog.getOpenFileName(self, "选择视频文件", "", "Video Files (*.mp4 *.mov)")
        if file_name:
            self.input_path.setText(file_name)
            self.draw_waveform(file_name)

    def browse_audio(self, line_edit):
        file_name, _ = QFileDialog.getOpenFileName(self, "选择音频文件", "", "Audio Files (*.wav *.mp3 *.m4a)")
        if file_name:
            line_edit.setText(file_name)

    def browse_subtitle(self):
        """浏览外部 SRT 字幕文件"""
        file_name, _ = QFileDialog.getOpenFileName(self, "选择字幕文件", "", "Subtitle Files (*.srt);;All Files (*)")
        if file_name:
            self.subtitle_file_path.setText(file_name)
            self.log(f"📂 已选择外部字幕文件: {file_name}")

    # -------- 日志 / 预览 --------
    def log(self, message):
        time_str = time.strftime("%H:%M:%S", time.localtime())
        self.log_console.append(f"[{time_str}] {message}")
        self.log_console.verticalScrollBar().setValue(self.log_console.verticalScrollBar().maximum())

    def update_preview(self, qt_image):
        self.preview_label.setPixmap(
            QPixmap.fromImage(qt_image).scaled(
                self.preview_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
        )

    # -------- 音频波形 --------
    def draw_waveform(self, video_path):
        """提取视频前 10 秒音频，生成波形图"""
        if not video_path or not os.path.exists(video_path):
            self.waveform_label.setText("音频波形 (选择视频后自动生成)")
            return
        if not video_path.lower().endswith((".mp4", ".mov", ".avi", ".mkv")):
            return

        temp_wav = os.path.join(self.output_dir if hasattr(self, 'output_dir') and self.output_dir
                                else os.path.dirname(video_path), "_waveform_temp.wav")
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-i", video_path, "-t", "10",
                 "-acodec", "pcm_s16le", "-ar", "22050", "-ac", "1", temp_wav],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
            )
            with open(temp_wav, "rb") as f:
                data = f.read()
            # 跳过 WAV 头 44 字节，读取 PCM S16LE 样本
            samples = np.frombuffer(data[44:], dtype=np.int16).astype(np.float32)
            if len(samples) > 0:
                self._render_waveform(samples)
        except Exception as e:
            self.log(f"⚠️ 无法生成波形图: {e}")
        finally:
            if os.path.exists(temp_wav):
                try:
                    os.remove(temp_wav)
                except OSError:
                    pass

    def _render_waveform(self, samples, width=640, height=76):
        """将 PCM 样本绘制为波形图"""
        pixmap = QPixmap(width, height)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)

        center_y = height // 2

        # 中心线
        painter.setPen(QColor(80, 80, 80, 160))
        painter.drawLine(0, center_y, width, center_y)

        # 降采样到宽度像素数
        chunk_size = max(1, len(samples) // width)
        if chunk_size > 1:
            truncated = samples[:chunk_size * width]
            display = np.abs(truncated.reshape(-1, chunk_size)).max(axis=1)
        else:
            display = np.abs(samples)

        # 归一化到波形高度
        max_val = max(1, np.max(display))
        display = display / max_val * (center_y - 4)

        # 绘制波形线条
        painter.setPen(QColor(0, 180, 255, 200))
        for x in range(min(width, len(display))):
            h = max(1, int(display[x]))
            painter.drawLine(x, center_y - h, x, center_y + h)

        painter.end()
        self.waveform_label.setPixmap(pixmap)

    # -------- 开始处理 --------
    def start_processing(self):
        # 收集输入源
        batch_files = []
        input_src = self.input_path.text().strip()

        if self.chk_batch.isChecked() and hasattr(self, "batch_folder_path") and self.batch_folder_path:
            all_files = os.listdir(self.batch_folder_path)
            batch_files = sorted([
                os.path.join(self.batch_folder_path, f)
                for f in all_files
                if f.lower().endswith((".mp4", ".mov", ".avi", ".mkv"))
            ])
            if not batch_files:
                return self.log("错误: 文件夹中没有找到视频文件！")
            input_src = batch_files[0]
        else:
            if not input_src:
                return self.log("错误: 请输入本地视频源！")
            if not os.path.exists(input_src):
                return self.log(f"错误: 视频文件不存在: {input_src}")

        # 上传音频校验
        upload_configs = []
        if self.chk_voice_clone.isChecked() and self.radio_clone_upload.isChecked():
            path1 = self.input_audio_1.text().strip()
            path2 = self.input_audio_2.text().strip()
            if path1:
                upload_configs.append({"path": path1, "spk_id": self.combo_spk_1.currentIndex()})
            if path2:
                upload_configs.append({"path": path2, "spk_id": self.combo_spk_2.currentIndex()})
            for cfg in upload_configs:
                if not os.path.exists(cfg["path"]):
                    return self.log(f"错误: 音频文件不存在: {cfg['path']}")
            if not upload_configs:
                return self.log("错误: 已选择上传覆盖模式，但未提供任何有效的音频文件！")

        # 停止已有线程
        if self.thread and self.thread.isRunning():
            self.thread.stop()
            self.btn_start.setText("开始执行 (Start Processing)")
            self.btn_start.setStyleSheet("background-color: #007AFF;")
            return

        # 字幕样式
        subtitle_style = {
            "color": self.sub_color_combo.currentText(),
            "font_size": self.sub_font_slider.value() / 1000.0,
            "bg_enabled": self.chk_sub_bg.isChecked(),
            "bilingual": self.chk_bilingual.isChecked(),
        }

        # 快速预览
        quick_preview_sec = self.quick_preview_sec.value() if self.chk_quick_preview.isChecked() else 0

        # 启动线程
        self.btn_start.setText("停止执行 (Stop)")
        self.btn_start.setStyleSheet("background-color: #FF3B30;")
        self.progress_bar.setValue(0)
        self.btn_open_folder.setEnabled(False)
        self.btn_preview.setEnabled(False)

        # 字幕导出与外部字幕
        export_subtitle = self.chk_export_subtitle.isChecked()
        subtitle_file_path = ""
        if self.radio_sub_manual.isChecked():
            subtitle_file_path = self.subtitle_file_path.text().strip()

        self.thread = VideoProcessThread(
            input_source=input_src,
            is_vertical=self.radio_vertical.isChecked(),
            target_lang=self.audio_lang.currentText(),
            codec=self.codec_combo.currentText(),
            fps=self.fps_spin.value(),
            enable_subtitle=self.chk_subtitle.isChecked(),
            enable_voice_clone=self.chk_voice_clone.isChecked(),
            clone_mode=0 if self.radio_clone_video.isChecked() else 1,
            upload_configs=upload_configs,
            trim_start=self.trim_start.value(),
            trim_end=self.trim_end.value(),
            quick_preview_sec=quick_preview_sec,
            subtitle_style=subtitle_style,
            batch_files=batch_files if len(batch_files) > 1 else [],
            output_w=self.res_w_spin.value(),
            output_h=self.res_h_spin.value(),
            subtitle_offset_ms=self.subtitle_offset_spin.value(),
            enable_bgm_preserve=self.chk_bgm_preserve.isChecked(),
            export_subtitle=export_subtitle,
            subtitle_file_path=subtitle_file_path,
            enable_edge_tts_first=self.chk_voice_clone.isChecked() and self.chk_edge_tts_first.isChecked(),
            edge_tts_voices={
                0: self.combo_edge_spk0.currentData(),
                1: self.combo_edge_spk1.currentData(),
            },
        )

        self.thread.update_frame.connect(self.update_preview)
        self.thread.log_msg.connect(self.log)
        self.thread.finished.connect(self.reset_processing_state)
        self.thread.progress_changed.connect(self.progress_bar.setValue)
        self.thread.batch_finished.connect(self.show_batch_summary)
        self.thread.start()

    def reset_processing_state(self):
        if self.thread:
            self.last_output = getattr(self.thread, "final_output", None)
            if self.last_output:
                self.btn_open_folder.setEnabled(True)
                self.btn_preview.setEnabled(True)
        self.btn_start.setText("开始执行 (Start Processing)")
        self.btn_start.setStyleSheet("background-color: #007AFF;")
        self.thread = None

    # -------- 批量摘要 --------
    def show_batch_summary(self, results):
        """批量处理完成后弹出摘要对话框"""
        total = len(results)
        success_count = sum(1 for r in results if r["success"])
        fail_count = total - success_count

        summary_lines = [f"处理完成 ({success_count}/{total})", "",
                         f"✅ 成功: {success_count}", f"❌ 失败: {fail_count}", ""]
        if fail_count > 0:
            summary_lines.append("失败明细:")
            for r in results:
                if not r["success"]:
                    err_msg = r.get("error") or "未知错误"
                    summary_lines.append(f"  · {r['file']} → {err_msg}")
            summary_lines.append("")

        output_dir = ""
        if results and results[0].get("output"):
            output_dir = os.path.dirname(results[0]["output"])
            summary_lines.append(f"📁 输出文件夹: {output_dir}")

        msg = QMessageBox(self)
        msg.setWindowTitle("批量处理完成")
        msg.setText("\n".join(summary_lines))
        msg.setIcon(QMessageBox.Information)
        open_btn = msg.addButton("📂 打开文件夹", QMessageBox.ActionRole)
        msg.addButton("确定", QMessageBox.AcceptRole)
        msg.exec_()

        if msg.clickedButton() == open_btn and output_dir and os.path.exists(output_dir):
            subprocess.run(["open", output_dir])

    # -------- 配置模板保存/加载 --------
    def save_config(self):
        """将当前 UI 控件状态保存为 JSON 模板"""
        config = {
            "version": 2,
            "preset": self.preset_combo.currentText(),
            "video_path": self.input_path.text(),
            "batch_enabled": self.chk_batch.isChecked(),
            "batch_folder": getattr(self, "batch_folder_path", ""),
            "trim_start": self.trim_start.value(),
            "trim_end": self.trim_end.value(),
            "target_lang": self.audio_lang.currentText(),
            "is_vertical": self.radio_vertical.isChecked(),
            "enable_subtitle": self.chk_subtitle.isChecked(),
            "subtitle_color": self.sub_color_combo.currentText(),
            "subtitle_font_size": self.sub_font_slider.value(),
            "subtitle_bg": self.chk_sub_bg.isChecked(),
            "bilingual": self.chk_bilingual.isChecked(),
            "subtitle_offset_ms": self.subtitle_offset_spin.value(),
            "enable_voice_clone": self.chk_voice_clone.isChecked(),
            "clone_mode": 0 if self.radio_clone_video.isChecked() else 1,
            "quick_preview": self.chk_quick_preview.isChecked(),
            "quick_preview_sec": self.quick_preview_sec.value(),
            "codec": self.codec_combo.currentText(),
            "fps": self.fps_spin.value(),
            "output_w": self.res_w_spin.value(),
            "output_h": self.res_h_spin.value(),
            "lock_aspect": self.chk_lock_aspect.isChecked(),
            "bgm_preserve": self.chk_bgm_preserve.isChecked(),
            "export_subtitle": self.chk_export_subtitle.isChecked(),
            "subtitle_source": "manual" if self.radio_sub_manual.isChecked() else "auto",
            "subtitle_file_path": self.subtitle_file_path.text().strip(),
            "enable_edge_tts_first": self.chk_edge_tts_first.isChecked(),
            "edge_tts_voice_0": self.combo_edge_spk0.currentData(),
            "edge_tts_voice_1": self.combo_edge_spk1.currentData(),
        }
        file_path, _ = QFileDialog.getSaveFileName(self, "保存配置模板", "", "JSON 文件 (*.json)")
        if not file_path:
            return
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            self.log(f"💾 配置已保存: {file_path}")
        except Exception as e:
            self.log(f"❌ 保存配置失败: {e}")

    def load_config(self):
        """从 JSON 模板恢复 UI 控件状态"""
        file_path, _ = QFileDialog.getOpenFileName(self, "加载配置模板", "", "JSON 文件 (*.json)")
        if not file_path:
            return
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                config = json.load(f)
        except Exception as e:
            self.log(f"❌ 加载配置失败: {e}")
            return

        # 恢复所有 UI 控件
        def _restore_combo(widget, key):
            val = config.get(key)
            if val:
                idx = widget.findText(val)
                if idx >= 0:
                    widget.setCurrentIndex(idx)

        _restore_combo(self.preset_combo, "preset")
        self.input_path.setText(config.get("video_path", ""))
        self.chk_batch.setChecked(config.get("batch_enabled", False))
        if config.get("batch_folder"):
            self.batch_folder_path = config["batch_folder"]
            videos = [f for f in os.listdir(config["batch_folder"]) if f.lower().endswith((".mp4", ".mov", ".avi", ".mkv"))]
            self.lbl_batch_count.setText(f"找到 {len(videos)} 个视频")
        self.trim_start.setValue(config.get("trim_start", 0))
        self.trim_end.setValue(config.get("trim_end", 0))

        _restore_combo(self.audio_lang, "target_lang")

        is_vert = config.get("is_vertical", True)
        self.radio_vertical.setChecked(is_vert)
        self.radio_horizontal.setChecked(not is_vert)

        self.chk_subtitle.setChecked(config.get("enable_subtitle", True))
        _restore_combo(self.sub_color_combo, "subtitle_color")
        self.sub_font_slider.setValue(config.get("subtitle_font_size", 55))
        self.chk_sub_bg.setChecked(config.get("subtitle_bg", False))
        self.chk_bilingual.setChecked(config.get("bilingual", False))
        self.subtitle_offset_spin.setValue(config.get("subtitle_offset_ms", 0))

        self.chk_voice_clone.setChecked(config.get("enable_voice_clone", False))
        clone_mode = config.get("clone_mode", 0)
        self.radio_clone_video.setChecked(clone_mode == 0)
        self.radio_clone_upload.setChecked(clone_mode == 1)

        # Edge-TTS 优先
        self.chk_edge_tts_first.setChecked(config.get("enable_edge_tts_first", False))
        voice0 = config.get("edge_tts_voice_0", "")
        idx0 = self.combo_edge_spk0.findData(voice0)
        if idx0 >= 0:
            self.combo_edge_spk0.setCurrentIndex(idx0)
        voice1 = config.get("edge_tts_voice_1", "")
        idx1 = self.combo_edge_spk1.findData(voice1)
        if idx1 >= 0:
            self.combo_edge_spk1.setCurrentIndex(idx1)

        self.chk_quick_preview.setChecked(config.get("quick_preview", False))
        self.quick_preview_sec.setValue(config.get("quick_preview_sec", 15))
        _restore_combo(self.codec_combo, "codec")
        self.fps_spin.setValue(config.get("fps", 30))

        self.res_w_spin.setValue(config.get("output_w", 1080))
        self.res_h_spin.setValue(config.get("output_h", 1920))
        self.chk_lock_aspect.setChecked(config.get("lock_aspect", True))
        self.chk_bgm_preserve.setChecked(config.get("bgm_preserve", False))

        self.chk_export_subtitle.setChecked(config.get("export_subtitle", True))
        sub_source = config.get("subtitle_source", "auto")
        if sub_source == "manual":
            self.radio_sub_manual.setChecked(True)
        else:
            self.radio_sub_auto.setChecked(True)
        self.subtitle_file_path.setText(config.get("subtitle_file_path", ""))

        self.log(f"📂 配置已加载: {file_path}")

    def closeEvent(self, event):
        if self.thread:
            self.thread.stop()
        event.accept()
