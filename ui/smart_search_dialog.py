"""智能视频检索 — 独立模态对话框。"""

import datetime
import os
import subprocess

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QAbstractItemView, QAbstractScrollArea, QButtonGroup, QCheckBox, QDialog,
    QDoubleSpinBox, QFileDialog, QFormLayout, QFrame, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
    QProgressBar, QPushButton, QRadioButton, QScrollArea, QSpinBox,
    QTextEdit, QVBoxLayout, QWidget,
)

from core.script_suggest import render_script_markdown
from core.script_thread import ScriptSuggestionThread
from core.search_thread import SmartSearchThread
from core.search_types import TrendAngle
from core.smart_search import export_report
from core.trend_sources import extract_keywords
from core.trend_thread import TrendFetchThread
from ui.script_dialog import ScriptDialog

DEFAULT_CODEC = "H.264 (MP4)"
DEFAULT_BITRATE_MBPS = 4
VIDEO_EXTENSIONS = (".mp4", ".mov", ".avi", ".mkv")


class SmartSearchDialog(QDialog):
    """批量视频 + 热点 + 自然语言检索的独立窗口。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🔍 智能视频检索")
        self.resize(1100, 800)
        self.setMinimumSize(900, 600)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        self._auto_angles: list[TrendAngle] = []
        self._clips = []
        self._close_when_finished = False
        self._thread = None
        self._trend_thread = None
        self._script_thread = None

        self._init_ui()
        self._apply_style()
        self._set_default_output_dir()

    # ----------------------------------------------------------------
    # UI 构建
    # ----------------------------------------------------------------

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(18, 14, 24, 14)

        settings = QWidget()
        settings_layout = QVBoxLayout(settings)
        settings_layout.setContentsMargins(0, 0, 0, 0)
        settings_layout.setSpacing(10)
        settings_layout.addWidget(self._build_scope_group())
        settings_layout.addWidget(self._build_intent_group())
        settings_layout.addWidget(self._build_params_group())

        self.settings_scroll = QScrollArea()
        self.settings_scroll.setWidgetResizable(True)
        self.settings_scroll.setFrameShape(QFrame.NoFrame)
        self.settings_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.settings_scroll.setSizeAdjustPolicy(
            QAbstractScrollArea.AdjustToContents,
        )
        self.settings_scroll.setWidget(settings)
        main_layout.addWidget(self.settings_scroll, 2)

        main_layout.addLayout(self._build_action_row())
        self.status_label = QLabel("准备就绪")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("color: #B0B0D0;")
        main_layout.addWidget(self.status_label)
        main_layout.addWidget(self._build_results_group(), 1)
        main_layout.addWidget(self._build_log_group())

    def _build_scope_group(self):
        group = QGroupBox("① 检索范围")
        layout = QVBoxLayout(group)

        single_row = QHBoxLayout()
        self.radio_single = QRadioButton("单个视频")
        self.radio_single.setChecked(True)
        self.input_single = QLineEdit()
        self.input_single.setPlaceholderText("选择或拖入一个视频文件...")
        self.btn_browse_single = QPushButton("浏览")
        self.btn_browse_single.clicked.connect(self._browse_single)
        single_row.addWidget(self.radio_single)
        single_row.addWidget(self.input_single, 1)
        single_row.addWidget(self.btn_browse_single)
        layout.addLayout(single_row)

        batch_row = QHBoxLayout()
        self.radio_batch = QRadioButton("批量文件夹")
        self.input_batch = QLineEdit()
        self.input_batch.setPlaceholderText("选择包含视频的文件夹...")
        self.btn_browse_batch = QPushButton("浏览")
        self.btn_browse_batch.clicked.connect(self._browse_batch)
        self.chk_recursive = QCheckBox("递归子目录")
        batch_row.addWidget(self.radio_batch)
        batch_row.addWidget(self.input_batch, 1)
        batch_row.addWidget(self.btn_browse_batch)
        batch_row.addWidget(self.chk_recursive)
        layout.addLayout(batch_row)

        self.scope_group = QButtonGroup(self)
        self.scope_group.addButton(self.radio_single)
        self.scope_group.addButton(self.radio_batch)
        return group

    def _build_intent_group(self):
        group = QGroupBox("② 检索意图")
        layout = QVBoxLayout(group)

        query_row = QHBoxLayout()
        query_row.addWidget(QLabel("提示词:"))
        self.input_query = QLineEdit()
        self.input_query.setPlaceholderText(
            "例如：找到提到价格、成本、避坑的部分（留空则只用热点角度）"
        )
        query_row.addWidget(self.input_query, 1)
        layout.addLayout(query_row)

        trend_row = QHBoxLayout()
        self.chk_hn = QCheckBox("HN")
        self.chk_hn.setChecked(True)
        self.chk_v2ex = QCheckBox("V2EX")
        self.chk_v2ex.setChecked(True)
        self.spin_limit = QSpinBox()
        self.spin_limit.setRange(5, 50)
        self.spin_limit.setValue(20)
        self.spin_limit.setSuffix(" 条")
        self.btn_fetch = QPushButton("抓取热榜")
        self.btn_fetch.clicked.connect(self._on_fetch_trends)
        trend_row.addWidget(QLabel("热度来源:"))
        trend_row.addWidget(self.chk_hn)
        trend_row.addWidget(self.chk_v2ex)
        trend_row.addWidget(QLabel("数量:"))
        trend_row.addWidget(self.spin_limit)
        trend_row.addWidget(self.btn_fetch)
        trend_row.addStretch()
        layout.addLayout(trend_row)

        mode_row = QHBoxLayout()
        self.radio_auto = QRadioButton("自动归纳")
        self.radio_auto.setChecked(True)
        self.radio_manual = QRadioButton("手动勾选")
        self.mode_group = QButtonGroup(self)
        self.mode_group.addButton(self.radio_auto)
        self.mode_group.addButton(self.radio_manual)
        mode_row.addWidget(QLabel("模式:"))
        mode_row.addWidget(self.radio_auto)
        mode_row.addWidget(self.radio_manual)
        mode_row.addStretch()
        layout.addLayout(mode_row)

        self.trend_list = QListWidget()
        self.trend_list.setMaximumHeight(130)
        self.trend_list.setSelectionMode(QAbstractItemView.NoSelection)
        layout.addWidget(self.trend_list)

        self.angle_label = QLabel("自动归纳: 尚未抓取")
        self.angle_label.setWordWrap(True)
        layout.addWidget(self.angle_label)
        self.radio_manual.toggled.connect(self._on_mode_changed)
        return group

    def _build_params_group(self):
        group = QGroupBox("③ 参数")
        layout = QVBoxLayout(group)
        form = QFormLayout()
        form.setSpacing(6)

        self.spin_min_dur = QSpinBox()
        self.spin_min_dur.setRange(1, 600)
        self.spin_min_dur.setValue(3)
        self.spin_min_dur.setSuffix(" 秒")
        self.spin_max_dur = QSpinBox()
        self.spin_max_dur.setRange(5, 3600)
        self.spin_max_dur.setValue(120)
        self.spin_max_dur.setSuffix(" 秒")
        self.spin_merge_gap = QDoubleSpinBox()
        self.spin_merge_gap.setRange(0.0, 60.0)
        self.spin_merge_gap.setDecimals(1)
        self.spin_merge_gap.setSingleStep(0.5)
        self.spin_merge_gap.setValue(2.0)
        self.spin_merge_gap.setSuffix(" 秒")
        self.spin_top_k = QSpinBox()
        self.spin_top_k.setRange(1, 100)
        self.spin_top_k.setValue(10)
        self.spin_top_k.setSuffix(" 条/视频")
        self.chk_deep = QCheckBox("深度模式（全部句子送 LLM，更慢更贵）")
        self.chk_force_export = QCheckBox("强制重新导出（忽略已导出台账）")
        self.chk_relaxed = QCheckBox("无强匹配时输出弱相关片段（需人工复核）")

        form.addRow("最短片段:", self.spin_min_dur)
        form.addRow("最长片段:", self.spin_max_dur)
        form.addRow("合并间隔:", self.spin_merge_gap)
        form.addRow("每视频最多:", self.spin_top_k)

        checks_row = QHBoxLayout()
        checks_row.setSpacing(24)
        checks_row.addWidget(self.chk_deep)
        checks_row.addWidget(self.chk_force_export)
        checks_row.addStretch()
        form.addRow("", checks_row)
        form.addRow("", self.chk_relaxed)
        layout.addLayout(form)

        out_row = QHBoxLayout()
        out_row.addWidget(QLabel("输出目录:"))
        self.input_out_dir = QLineEdit()
        self.input_out_dir.setPlaceholderText("选择片段输出目录...")
        self.input_out_dir.setMinimumWidth(360)
        self.btn_browse_out = QPushButton("浏览")
        self.btn_browse_out.clicked.connect(self._browse_output)
        out_row.addWidget(self.input_out_dir, 1)
        out_row.addWidget(self.btn_browse_out)
        layout.addLayout(out_row)
        return group

    def _build_action_row(self):
        row = QHBoxLayout()
        self.btn_start = QPushButton("开始检索")
        self.btn_start.setFixedHeight(40)
        self.btn_start.clicked.connect(self.start_search)
        self.btn_stop = QPushButton("停止")
        self.btn_stop.setFixedHeight(40)
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_search)
        self.btn_script = QPushButton("📝 建议脚本")
        self.btn_script.setFixedHeight(40)
        self.btn_script.clicked.connect(self.suggest_script)
        self.progress = QProgressBar()
        self.progress.setValue(0)
        row.addWidget(self.btn_start, 1)
        row.addWidget(self.btn_stop, 1)
        row.addWidget(self.btn_script, 1)
        row.addWidget(self.progress, 3)
        return row

    def _build_results_group(self):
        group = QGroupBox("④ 检索结果")
        layout = QVBoxLayout(group)
        self.results_list = QListWidget()
        self.results_list.itemDoubleClicked.connect(self._on_result_double_clicked)
        layout.addWidget(self.results_list)

        buttons = QHBoxLayout()
        self.btn_open_out = QPushButton("打开输出文件夹")
        self.btn_open_out.clicked.connect(self._open_output_folder)
        self.btn_export_report = QPushButton("重新导出报告")
        self.btn_export_report.clicked.connect(self._export_report)
        buttons.addWidget(self.btn_open_out)
        buttons.addWidget(self.btn_export_report)
        buttons.addStretch()
        layout.addLayout(buttons)
        return group

    def _build_log_group(self):
        group = QGroupBox("运行日志")
        layout = QVBoxLayout(group)
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumHeight(110)
        layout.addWidget(self.log_view)
        return group

    # ----------------------------------------------------------------
    # 作用域与浏览
    # ----------------------------------------------------------------

    def _collect_scope(self) -> list[str]:
        if self.radio_single.isChecked():
            path = self.input_single.text().strip()
            return [path] if path and os.path.isfile(path) else []

        folder = self.input_batch.text().strip()
        if not folder or not os.path.isdir(folder):
            return []

        files: list[str] = []
        if self.chk_recursive.isChecked():
            for root, _dirs, names in os.walk(folder):
                for name in names:
                    if name.lower().endswith(VIDEO_EXTENSIONS):
                        files.append(os.path.join(root, name))
        else:
            for name in os.listdir(folder):
                path = os.path.join(folder, name)
                if os.path.isfile(path) and name.lower().endswith(VIDEO_EXTENSIONS):
                    files.append(path)
        return sorted(files)

    def _browse_single(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择视频", "", "视频文件 (*.mp4 *.mov *.avi *.mkv)",
        )
        if path:
            self.input_single.setText(path)
            self.radio_single.setChecked(True)

    def _browse_batch(self):
        path = QFileDialog.getExistingDirectory(self, "选择视频文件夹")
        if path:
            self.input_batch.setText(path)
            self.radio_batch.setChecked(True)

    def _browse_output(self):
        path = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if path:
            self.input_out_dir.setText(path)

    def _set_default_output_dir(self):
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M")
        default = os.path.join(
            os.path.expanduser("~"), "Desktop", f"AI_智能检索_{stamp}",
        )
        self.input_out_dir.setText(default)

    def prefill_scope(self, single_path="", batch_folder="", use_batch=False):
        """从主窗口带入当前选择，避免用户以为已选文件但对话框为空。"""
        if use_batch and batch_folder and os.path.isdir(batch_folder):
            self.input_batch.setText(batch_folder)
            self.radio_batch.setChecked(True)
        elif single_path and os.path.isfile(single_path):
            self.input_single.setText(single_path)
            self.radio_single.setChecked(True)

    # ----------------------------------------------------------------
    # 热点
    # ----------------------------------------------------------------

    def _on_fetch_trends(self):
        sources = []
        if self.chk_hn.isChecked():
            sources.append("hn")
        if self.chk_v2ex.isChecked():
            sources.append("v2ex")
        if not sources:
            return self._on_log("⚠️ 请至少选择一个热度来源")

        self.btn_fetch.setEnabled(False)
        self.trend_list.clear()
        self._auto_angles = []
        self.angle_label.setText("自动归纳: 抓取中...")
        self._trend_thread = TrendFetchThread(
            sources=tuple(sources),
            limit=self.spin_limit.value(),
            force_refresh=True,
            summarize=self.radio_auto.isChecked(),
            parent=self,
        )
        self._trend_thread.done.connect(self._on_trends_done)
        self._trend_thread.angles_ready.connect(self._on_angles_ready)
        self._trend_thread.failed.connect(self._on_trends_failed)
        self._trend_thread.finished.connect(self._on_trend_finished)
        self._trend_thread.start()

    def _on_trends_done(self, items):
        self.trend_list.clear()
        for hotspot in items:
            text = f"[{hotspot.source.upper()}] {hotspot.title}  🔥{hotspot.score}"
            item = QListWidgetItem(text)
            item.setCheckState(Qt.Unchecked)
            item.setData(Qt.UserRole, hotspot)
            self._set_item_checkable(item, self.radio_manual.isChecked())
            self.trend_list.addItem(item)
        self._on_log(f"✅ 已抓取 {len(items)} 条热点")

    def _on_angles_ready(self, angles):
        self._auto_angles = list(angles)
        titles = " / ".join(angle.title for angle in angles[:3])
        if titles:
            self.angle_label.setText(f"自动归纳: {titles}")
        else:
            self.angle_label.setText("自动归纳: 无（将仅使用提示词）")

    def _on_trends_failed(self, msg):
        self.btn_fetch.setEnabled(True)
        self.angle_label.setText("自动归纳: 抓取失败")
        self._on_log(f"⚠️ 热点抓取失败: {msg}")

    def _collect_angles(self) -> list[TrendAngle]:
        if self.radio_auto.isChecked():
            return list(self._auto_angles)

        angles: list[TrendAngle] = []
        for i in range(self.trend_list.count()):
            item = self.trend_list.item(i)
            if item.checkState() != Qt.Checked:
                continue
            hotspot = item.data(Qt.UserRole)
            if hotspot is None:
                continue
            angles.append(TrendAngle(
                title=hotspot.title,
                keywords=extract_keywords(hotspot.title),
                why="手动选择",
                source_ids=[f"{hotspot.source}:{hotspot.url}"],
                heat=hotspot.heat,
                heat_raw=hotspot.score,
                heat_source=hotspot.source,
            ))
        return angles

    def _set_item_checkable(self, item, enabled):
        """自动模式下隐藏热点复选框，手动模式才允许勾选。"""
        flags = item.flags()
        if enabled:
            flags |= Qt.ItemIsUserCheckable
        else:
            flags &= ~Qt.ItemIsUserCheckable
            item.setCheckState(Qt.Unchecked)
        item.setFlags(flags)

    def _on_mode_changed(self):
        manual = self.radio_manual.isChecked()
        for i in range(self.trend_list.count()):
            self._set_item_checkable(self.trend_list.item(i), manual)
        self.angle_label.setVisible(not manual)

    # ----------------------------------------------------------------
    # 检索
    # ----------------------------------------------------------------

    def start_search(self):
        if self._thread is not None and self._thread.isRunning():
            return self._on_log("⚠️ 检索仍在进行，请先停止")
        if self._script_thread is not None and self._script_thread.isRunning():
            return self._on_log("⚠️ 建议脚本仍在生成，请稍候")

        scope = self._collect_scope()
        if not scope:
            return self._on_log("⚠️ 请选择有效的视频文件或文件夹")

        query = self.input_query.text().strip()
        angles = self._collect_angles()
        if not query and not angles:
            return self._on_log("⚠️ 请输入提示词，或先抓取/勾选热点角度")

        out_dir = self.input_out_dir.text().strip()
        if not out_dir:
            return self._on_log("⚠️ 请选择输出目录")
        try:
            os.makedirs(out_dir, exist_ok=True)
        except OSError as exc:
            return self._on_log(f"⚠️ 输出目录不可写: {exc}")

        self._clips = []
        self.results_list.clear()
        self.progress.setValue(0)
        self.btn_start.setEnabled(False)
        self.btn_fetch.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.btn_script.setEnabled(False)

        self._thread = SmartSearchThread(
            scope, query, angles,
            DEFAULT_CODEC, DEFAULT_BITRATE_MBPS, out_dir,
            min_dur=self.spin_min_dur.value(),
            max_dur=self.spin_max_dur.value(),
            merge_gap=self.spin_merge_gap.value(),
            top_k=self.spin_top_k.value(),
            deep_mode=self.chk_deep.isChecked(),
            force_export=self.chk_force_export.isChecked(),
            allow_relaxed_fallback=self.chk_relaxed.isChecked(),
            parent=self,
        )
        self._thread.log_msg.connect(self._on_log)
        self._thread.progress_changed.connect(self._on_progress)
        self._thread.results_ready.connect(self._on_results)
        self._thread.error.connect(self._on_error)
        self._thread.finished.connect(self._on_finished)
        self._on_log(
            f"▶️ 开始检索 {len(scope)} 个视频（{DEFAULT_CODEC} / "
            f"{DEFAULT_BITRATE_MBPS} Mbps）"
        )
        self._thread.start()

    def stop_search(self):
        if self._thread is not None and self._thread.isRunning():
            self._thread.stop()
            self._on_log("⏹️ 正在停止（当前视频处理完后退出）...")

    def suggest_script(self):
        """针对当前选中的单个视频生成建议脚本。"""
        if self._script_thread is not None and self._script_thread.isRunning():
            return self._on_log("⚠️ 建议脚本仍在生成，请稍候")
        if self._thread is not None and self._thread.isRunning():
            return self._on_log("⚠️ 检索仍在进行，请先停止")
        if (self._trend_thread is not None
                and self._trend_thread.isRunning()):
            return self._on_log("⚠️ 热点抓取仍在进行，请稍候")

        scope = self._collect_scope()
        if not scope:
            return self._on_log("⚠️ 请选择有效的视频文件或文件夹")
        video = scope[0]
        if len(scope) > 1:
            self._on_log(
                "ℹ️ 建议脚本针对单个视频，已使用第一个: "
                f"{os.path.basename(video)}"
            )

        out_dir = self.input_out_dir.text().strip()
        if not out_dir:
            return self._on_log("⚠️ 请选择输出目录")
        try:
            os.makedirs(out_dir, exist_ok=True)
        except OSError as exc:
            return self._on_log(f"⚠️ 输出目录不可写: {exc}")

        self.progress.setValue(0)
        self.btn_start.setEnabled(False)
        self.btn_fetch.setEnabled(False)
        self.btn_script.setEnabled(False)
        self._script_thread = ScriptSuggestionThread(
            video, self._collect_angles(), self.input_query.text().strip(),
            out_dir, parent=self,
        )
        self._script_thread.log_msg.connect(self._on_log)
        self._script_thread.progress_changed.connect(self._on_progress)
        self._script_thread.script_ready.connect(self._on_script_ready)
        self._script_thread.error.connect(self._on_script_error)
        self._script_thread.finished.connect(self._on_script_finished)
        self._on_log(f"▶️ 正在生成建议脚本: {os.path.basename(video)}")
        self._script_thread.start()

    def _on_script_ready(self, script, json_path, md_path):
        markdown = render_script_markdown(script)
        self._on_log(f"✅ 建议脚本已生成: {md_path}")
        dialog = ScriptDialog(script, markdown, json_path, md_path, self)
        dialog.exec_()

    def _on_script_error(self, msg):
        self._on_log(f"❌ 建议脚本生成失败: {msg}")

    def _on_script_finished(self):
        self.btn_start.setEnabled(True)
        self.btn_fetch.setEnabled(True)
        self.btn_script.setEnabled(True)
        if self.progress.value() < 100:
            self.progress.setValue(0)
        self._maybe_finish_close()

    def _on_log(self, msg):
        self.log_view.append(msg)
        bar = self.log_view.verticalScrollBar()
        bar.setValue(bar.maximum())
        self._set_status(msg, warn=msg.startswith(("⚠️", "❌")))

    def _set_status(self, text, warn=False):
        self.status_label.setText(text)
        self.status_label.setStyleSheet(
            "color: #FF6D00;" if warn else "color: #B0B0D0;"
        )

    def _on_progress(self, value):
        self.progress.setValue(int(value))

    def _format_clip_line(self, clip) -> str:
        """结果列表单行：文件 | 时间 | 契合度 | 关联角度/热度 | 摘要。"""
        prefix = "[已导出] " if clip.already_exported else ""
        snippet = " ".join(clip.matched_sentences)[:60]
        angle_text = "、".join(clip.angles[:2]) if clip.angles else "无关联热点"
        heat_text = ""
        if clip.heat_raw:
            heat_text = f"（{clip.heat_source.upper()} {clip.heat_raw}）"
        return (
            f"{prefix}{os.path.basename(clip.source_file)} | "
            f"{clip.start:.1f}s-{clip.end:.1f}s | "
            f"契合 {clip.content_score:.2f} | {angle_text}{heat_text} | {snippet}"
        )

    def _format_clip_tooltip(self, clip) -> str:
        """悬停展示完整命中理由与命中句。"""
        return (
            f"内容契合: {clip.content_score:.2f}\n"
            f"最终排序分: {clip.score:.2f}\n"
            f"关联角度: {'、'.join(clip.angles) or '无'}\n"
            f"命中理由: {clip.reason}\n"
            f"命中句: {' / '.join(clip.matched_sentences)}"
        )

    def _on_results(self, clips):
        self._clips = list(clips)
        self.results_list.clear()
        for clip in clips:
            item = QListWidgetItem(self._format_clip_line(clip))
            item.setData(Qt.UserRole, clip.clip_path)
            item.setToolTip(self._format_clip_tooltip(clip))
            self.results_list.addItem(item)
        if clips:
            self._on_log(f"✅ 检索完成，共 {len(clips)} 个片段")
        else:
            # 保留线程给出的具体空结果原因，不用泛化提示覆盖状态栏。
            self.log_view.append("ℹ️ 检索完成：未找到匹配片段（原因见上方日志）")
            bar = self.log_view.verticalScrollBar()
            bar.setValue(bar.maximum())

    def _on_error(self, msg):
        self._on_log(f"❌ 检索失败: {msg}")

    def _on_finished(self):
        self.btn_start.setEnabled(True)
        self.btn_fetch.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.btn_script.setEnabled(True)
        self.progress.setValue(100)
        self._maybe_finish_close()

    def _on_trend_finished(self):
        self.btn_fetch.setEnabled(True)
        self._maybe_finish_close()

    def _maybe_finish_close(self):
        """检索线程与热点线程都结束后，才真正关闭窗口。"""
        if not self._close_when_finished:
            return
        if self._thread is not None and self._thread.isRunning():
            return
        if self._trend_thread is not None and self._trend_thread.isRunning():
            return
        if (self._script_thread is not None
                and self._script_thread.isRunning()):
            return
        self._close_when_finished = False
        self.accept()

    def _on_result_double_clicked(self, item):
        path = item.data(Qt.UserRole)
        if path and os.path.exists(path):
            subprocess.run(["open", path])
        elif path:
            self._on_log(f"⚠️ 片段文件不存在: {path}")

    def _open_output_folder(self):
        out_dir = self.input_out_dir.text().strip()
        if out_dir and os.path.isdir(out_dir):
            subprocess.run(["open", out_dir])
        else:
            self._on_log("⚠️ 输出目录不存在")

    def _export_report(self):
        if not self._clips:
            return self._on_log("⚠️ 暂无结果可导出")
        out_dir = self.input_out_dir.text().strip()
        path = export_report(self._clips, out_dir, meta={
            "query": self.input_query.text().strip(),
            "angles": [angle.title for angle in self._collect_angles()],
        })
        self._on_log(f"✅ 报告已保存: {path}")

    # ----------------------------------------------------------------
    # 关闭
    # ----------------------------------------------------------------

    def closeEvent(self, event):
        if self._thread is not None and self._thread.isRunning():
            event.ignore()
            self._thread.stop()
            self._close_when_finished = True
            self._on_log("⏳ 正在停止（当前转写完成后退出）...")
            return

        if self._trend_thread is not None and self._trend_thread.isRunning():
            event.ignore()
            self._close_when_finished = True
            self._on_log("⏳ 热点抓取仍在进行，完成后自动关闭...")
            return

        if (self._script_thread is not None
                and self._script_thread.isRunning()):
            event.ignore()
            self._close_when_finished = True
            self._on_log("⏳ 建议脚本生成中，完成后自动关闭...")
            return

        event.accept()

    # ----------------------------------------------------------------
    # 样式
    # ----------------------------------------------------------------

    def _apply_style(self):
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
            padding: 16px 16px 10px 12px;
            font-weight: bold;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            subcontrol-position: top left;
            padding: 0 10px;
            color: #7C7CFF;
            font-weight: bold;
        }
        QLabel { color: #B0B0D0; background: transparent; }
        QLineEdit, QSpinBox, QDoubleSpinBox, QListWidget, QTextEdit {
            background-color: #101025;
            border: 1px solid #2A2A5A;
            border-radius: 6px;
            padding: 6px 10px;
            color: #E0E0F0;
            selection-background-color: #2979FF;
        }
        QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {
            border-color: #00BCD4;
        }
        QListWidget::item { padding: 4px; }
        QListWidget::item:selected { background-color: #2979FF; }
        QListWidget::indicator {
            width: 15px;
            height: 15px;
            border: 1px solid #55558A;
            border-radius: 4px;
            background-color: #0E0E20;
        }
        QListWidget::indicator:checked {
            background-color: #2979FF;
            border-color: #2979FF;
        }
        QCheckBox, QRadioButton { color: #B0B0D0; background: transparent; spacing: 8px; }
        QPushButton {
            background-color: #2979FF;
            color: white;
            border: none;
            border-radius: 6px;
            padding: 7px 16px;
            font-weight: bold;
        }
        QPushButton:hover { background-color: #1A6BFF; }
        QPushButton:disabled { background-color: #2A2A4A; color: #7777AA; }
        QProgressBar {
            background-color: #101025;
            border: 1px solid #2A2A5A;
            border-radius: 6px;
            text-align: center;
            color: #E0E0F0;
        }
        QProgressBar::chunk { background-color: #2979FF; border-radius: 5px; }
        """)
