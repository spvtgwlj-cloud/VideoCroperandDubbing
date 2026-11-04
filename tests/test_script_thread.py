"""建议脚本编排线程单测。"""

from types import SimpleNamespace

import pytest

import core.script_thread as st
from core.script_suggest import ScriptSection, SuggestedScript
from core.search_types import Hotspot, TrendAngle

SEGMENTS = [
    {"start": 0.0, "end": 2.5, "text": "初四那天"},
    {"start": 2.5, "end": 5.0, "text": "我们接待了一位约旦记者"},
]
SCRIPT_JSON = """
{"title":"跨国办卡故事","hook":"约旦记者被银行卡卡住",
 "sections":[{"name":"冲突","narration":"办卡顺畅，最后却卡在银行卡",
 "source_segment_ids":[0,1],"visual_note":"窗口画面"}],
 "cta":"评论区聊聊","why":"跨境支付热点"}
"""


class _FakeCompletions:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=item))],
        )


class _FakeClient:
    def __init__(self, responses):
        self.chat = SimpleNamespace(completions=_FakeCompletions(responses))


def _patch_cached_transcript(monkeypatch, segments=None):
    cached_segments = SEGMENTS if segments is None else segments
    monkeypatch.setattr(st, "transcript_cache_key", lambda *a, **k: "key")
    monkeypatch.setattr(
        st, "load_cached_transcript",
        lambda key: {"segments": cached_segments, "duration": 10.0},
    )


def _patch_llm(monkeypatch, responses):
    client = _FakeClient(responses)
    monkeypatch.setattr(
        st, "get_translation_config",
        lambda cfg: {"api_key": "k", "base_url": "u", "model": "m"},
    )
    monkeypatch.setattr(st, "OpenAI", lambda **kw: client)
    return client


def _run(thread):
    scripts = []
    errors = []
    thread.script_ready.connect(
        lambda script, json_path, md_path: scripts.append(
            (script, json_path, md_path),
        ),
    )
    thread.error.connect(errors.append)
    thread.run()
    return scripts, errors


def test_thread_generates_script_from_cached_transcript(monkeypatch, tmp_path):
    _patch_cached_transcript(monkeypatch)
    _patch_llm(monkeypatch, [SCRIPT_JSON])
    saved = {}
    monkeypatch.setattr(
        st, "save_script",
        lambda script, out_dir: (
            saved.update(script=script, out_dir=out_dir) or "/tmp/s.json",
            "/tmp/s.md",
        ),
    )

    thread = st.ScriptSuggestionThread(
        "demo.mp4", [TrendAngle("跨境支付", ["银行卡"], "热点")],
        "", str(tmp_path),
    )
    scripts, errors = _run(thread)

    assert errors == []
    assert len(scripts) == 1
    script, json_path, md_path = scripts[0]
    assert script.title == "跨国办卡故事"
    assert json_path == "/tmp/s.json"
    assert md_path == "/tmp/s.md"
    assert saved["out_dir"] == str(tmp_path)


def test_thread_uses_extended_timeout_and_token_limit(monkeypatch, tmp_path):
    _patch_cached_transcript(monkeypatch)
    client = _patch_llm(monkeypatch, [SCRIPT_JSON])
    monkeypatch.setattr(
        st, "save_script",
        lambda script, out_dir: ("/tmp/s.json", "/tmp/s.md"),
    )

    thread = st.ScriptSuggestionThread(
        "demo.mp4", [TrendAngle("角度", [], "")], "", str(tmp_path),
    )
    _run(thread)

    call = client.chat.completions.calls[0]
    assert call["timeout"] == 120
    assert call["max_tokens"] == 1800


def test_thread_errors_without_api_key(monkeypatch, tmp_path):
    _patch_cached_transcript(monkeypatch)
    monkeypatch.setattr(
        st, "get_translation_config",
        lambda cfg: {"api_key": "", "base_url": "", "model": ""},
    )

    thread = st.ScriptSuggestionThread(
        "demo.mp4", [TrendAngle("角度", [], "")], "", str(tmp_path),
    )
    scripts, errors = _run(thread)

    assert scripts == []
    assert errors and "未配置" in errors[0]


def test_thread_errors_without_segments(monkeypatch, tmp_path):
    _patch_cached_transcript(monkeypatch, segments=[])
    _patch_llm(monkeypatch, [SCRIPT_JSON])

    thread = st.ScriptSuggestionThread(
        "demo.mp4", [TrendAngle("角度", [], "")], "", str(tmp_path),
    )
    scripts, errors = _run(thread)

    assert scripts == []
    assert errors and "未转写" in errors[0]


def test_thread_retries_once_then_errors_on_invalid_json(monkeypatch, tmp_path):
    _patch_cached_transcript(monkeypatch)
    client = _patch_llm(monkeypatch, ["not json", "still not json"])

    thread = st.ScriptSuggestionThread(
        "demo.mp4", [TrendAngle("角度", [], "")], "", str(tmp_path),
    )
    scripts, errors = _run(thread)

    assert scripts == []
    assert errors and "JSON" in errors[0]
    assert len(client.chat.completions.calls) == 2


def test_thread_fetches_angles_when_none_provided(monkeypatch, tmp_path):
    _patch_cached_transcript(monkeypatch)
    client = _patch_llm(monkeypatch, [SCRIPT_JSON])
    monkeypatch.setattr(
        st, "fetch_hotspots",
        lambda **kw: [Hotspot("hn", "AI 热点", "u", score=100)],
    )
    monkeypatch.setattr(
        st, "summarize_hotspots",
        lambda items, c, model, max_angles=8: [
            TrendAngle("AI 爆点", ["AI"], "高热"),
        ],
    )

    thread = st.ScriptSuggestionThread("demo.mp4", [], "", str(tmp_path))
    scripts, errors = _run(thread)

    assert errors == []
    assert len(scripts) == 1
    prompt = client.chat.completions.calls[0]["messages"][0]["content"]
    assert "AI 爆点" in prompt
