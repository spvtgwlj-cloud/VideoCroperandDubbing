"""主界面/对话框线程保护的单测（offscreen Qt）。"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys
import types

import pytest
from PyQt5.QtWidgets import QApplication


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


class _FakeRunningThread:
    def __init__(self):
        self.stopped = False

    def isRunning(self):
        return True

    def stop(self):
        self.stopped = True


class _FakeEvent:
    def __init__(self):
        self.ignored = False
        self.accepted = False

    def ignore(self):
        self.ignored = True

    def accept(self):
        self.accepted = True


def test_dialog_close_waits_for_trend_thread(app):
    from ui.smart_search_dialog import SmartSearchDialog

    dialog = SmartSearchDialog()
    dialog._trend_thread = _FakeRunningThread()
    event = _FakeEvent()
    dialog.closeEvent(event)

    assert event.ignored is True
    assert dialog._close_when_finished is True

    dialog._trend_thread = None
    dialog.close()


def test_start_search_shows_visible_status_when_scope_missing(app):
    from ui.smart_search_dialog import SmartSearchDialog

    dialog = SmartSearchDialog()
    dialog.input_single.clear()
    dialog.input_query.setText("price")
    dialog.start_search()

    assert "请选择有效的视频" in dialog.status_label.text()
    assert dialog.btn_start.isEnabled()
    dialog.close()


def test_dialog_prefills_scope(app, tmp_path):
    from ui.smart_search_dialog import SmartSearchDialog

    video = tmp_path / "a.mp4"
    video.write_bytes(b"x")
    folder = tmp_path / "batch"
    folder.mkdir()

    dialog = SmartSearchDialog()
    dialog.prefill_scope(str(video), str(folder), use_batch=False)
    assert dialog.input_single.text() == str(video)
    assert dialog.radio_single.isChecked()

    dialog.prefill_scope(str(video), str(folder), use_batch=True)
    assert dialog.input_batch.text() == str(folder)
    assert dialog.radio_batch.isChecked()
    dialog.close()


def test_results_list_shows_content_score_and_angles(app):
    from core.search_types import Clip
    from ui.smart_search_dialog import SmartSearchDialog

    dialog = SmartSearchDialog()
    clip = Clip(
        source_file="/videos/demo.mp4", filekey8="abcd1234",
        start=1.0, end=5.0, matched_sentences=["价格"], score=0.85,
        reason="提到价格", angles=["成本"], clip_path="/tmp/demo.mp4",
    )
    clip.content_score = 0.8
    clip.heat = 1.0
    clip.heat_raw = 120
    clip.heat_source = "hn"
    dialog._on_results([clip])
    text = dialog.results_list.item(0).text()
    assert "契合 0.80" in text
    assert "成本" in text
    assert "HN 120" in text
    dialog.close()


def test_manual_mode_toggles_hotspot_checkboxes(app):
    from PyQt5.QtCore import Qt
    from core.search_types import Hotspot
    from ui.smart_search_dialog import SmartSearchDialog

    dialog = SmartSearchDialog()
    dialog._on_trends_done([Hotspot("hn", "价格", "u", score=10)])
    item = dialog.trend_list.item(0)
    assert not (item.flags() & Qt.ItemIsUserCheckable)
    dialog.radio_manual.setChecked(True)
    assert item.flags() & Qt.ItemIsUserCheckable
    dialog.close()


def test_auto_mode_falls_back_to_raw_hotspots_when_angles_not_ready(app):
    from core.search_types import Hotspot
    from ui.smart_search_dialog import SmartSearchDialog

    dialog = SmartSearchDialog()
    dialog._on_trends_done([
        Hotspot("hn", "AI 热点", "u", score=100, heat=1.0),
    ])
    assert dialog.radio_auto.isChecked()
    assert dialog._auto_angles == []

    angles = dialog._collect_angles()
    assert len(angles) == 1
    assert angles[0].title == "AI 热点"
    assert angles[0].heat == 1.0
    dialog.close()


def test_auto_mode_prefers_summarized_angles(app):
    from core.search_types import Hotspot, TrendAngle
    from ui.smart_search_dialog import SmartSearchDialog

    dialog = SmartSearchDialog()
    dialog._on_trends_done([
        Hotspot("hn", "原始标题", "u", score=100),
    ])
    dialog._auto_angles = [TrendAngle("AI 归纳", [], "")]

    assert [angle.title for angle in dialog._collect_angles()] == ["AI 归纳"]
    dialog.close()


def test_manual_mode_still_requires_checkbox(app):
    from PyQt5.QtCore import Qt
    from core.search_types import Hotspot
    from ui.smart_search_dialog import SmartSearchDialog

    dialog = SmartSearchDialog()
    dialog.radio_manual.setChecked(True)
    dialog._on_trends_done([
        Hotspot("hn", "原始标题", "u", score=100),
    ])
    assert dialog._collect_angles() == []

    dialog.trend_list.item(0).setCheckState(Qt.Checked)
    assert [angle.title for angle in dialog._collect_angles()] == ["原始标题"]
    dialog.close()


def test_start_search_explains_running_trend_fetch(app, tmp_path):
    from ui.smart_search_dialog import SmartSearchDialog

    video = tmp_path / "a.mp4"
    video.write_bytes(b"x")
    dialog = SmartSearchDialog()
    dialog.input_single.setText(str(video))
    dialog.input_query.clear()
    dialog._trend_thread = _FakeRunningThread()

    dialog.start_search()

    assert "仍在进行" in dialog.status_label.text()
    dialog.close()


def test_script_dialog_renders_markdown(app):
    from core.script_suggest import (
        ScriptSection, SuggestedScript, render_script_markdown,
    )
    from ui.script_dialog import ScriptDialog

    script = SuggestedScript(
        title="标题", hook="钩子",
        sections=[ScriptSection("开场", "口播", [0], "0.0s-5.0s", "画面")],
        cta="CTA", why="理由",
    )
    dialog = ScriptDialog(script, render_script_markdown(script))
    text = dialog.text_edit.toPlainText()

    assert "标题" in text
    assert "口播" in text
    assert "CTA" in text
    dialog.close()


def test_script_button_exists(app):
    from ui.smart_search_dialog import SmartSearchDialog

    dialog = SmartSearchDialog()
    assert "建议脚本" in dialog.btn_script.text()
    dialog.close()


def test_suggest_script_requires_scope(app):
    from ui.smart_search_dialog import SmartSearchDialog

    dialog = SmartSearchDialog()
    dialog.input_single.clear()
    dialog.suggest_script()

    assert "请选择有效的视频" in dialog.status_label.text()
    dialog.close()


def test_empty_results_keep_detailed_status(app):
    from ui.smart_search_dialog import SmartSearchDialog

    dialog = SmartSearchDialog()
    dialog._set_status("LLM 判定无足够相关片段")
    dialog._on_results([])

    assert "LLM" in dialog.status_label.text()
    dialog.close()


def test_relaxed_fallback_checkbox_defaults_off(app):
    from ui.smart_search_dialog import SmartSearchDialog

    dialog = SmartSearchDialog()
    assert dialog.chk_relaxed.isChecked() is False
    dialog.close()


def test_settings_are_wrapped_in_scroll_area(app):
    from PyQt5.QtWidgets import QScrollArea
    from ui.smart_search_dialog import SmartSearchDialog

    dialog = SmartSearchDialog()
    assert dialog.findChild(QScrollArea) is not None
    dialog.close()


def test_output_dir_field_has_minimum_width(app):
    from ui.smart_search_dialog import SmartSearchDialog

    dialog = SmartSearchDialog()
    assert dialog.input_out_dir.minimumWidth() >= 360
    dialog.close()


def test_open_smart_search_prefills_scope_from_main_window(
    app, monkeypatch, tmp_path,
):
    from ui.ui_main import MainWindow

    video = tmp_path / "a.mp4"
    video.write_bytes(b"x")
    recorded = {}
    fake_module = types.ModuleType("ui.smart_search_dialog")

    class _FakeDialog:
        def __init__(self, parent=None):
            pass

        def prefill_scope(self, **kwargs):
            recorded.update(kwargs)

        def exec_(self):
            return 0

    fake_module.SmartSearchDialog = _FakeDialog
    monkeypatch.setitem(sys.modules, "ui.smart_search_dialog", fake_module)

    window = MainWindow()
    window.input_path.setText(str(video))
    window.open_smart_search()

    assert recorded["single_path"] == str(video)
    assert recorded["use_batch"] is False
    window.close()


def test_open_smart_search_refuses_while_dubbing(app, monkeypatch):
    from ui.ui_main import MainWindow

    opened = []
    fake_module = types.ModuleType("ui.smart_search_dialog")

    class _FakeDialog:
        def __init__(self, parent=None):
            pass

        def exec_(self):
            opened.append(True)
            return 0

    fake_module.SmartSearchDialog = _FakeDialog
    monkeypatch.setitem(sys.modules, "ui.smart_search_dialog", fake_module)

    window = MainWindow()

    class _RunningThread:
        def isRunning(self):
            return True

    window.thread = _RunningThread()
    logs = []
    window.log = logs.append
    window.open_smart_search()

    assert opened == []
    assert any("配音处理中" in message for message in logs)

    window.thread = None
    window.close()
