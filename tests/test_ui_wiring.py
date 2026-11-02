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
