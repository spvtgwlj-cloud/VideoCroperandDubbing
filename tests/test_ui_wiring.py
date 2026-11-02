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
