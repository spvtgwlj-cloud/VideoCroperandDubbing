"""SmartSearchThread 编排单测。"""

import pytest
from core.search_types import Clip, Hit, MatchContext, TrendAngle
import core.search_thread as st


def _clip(path="a.mp4", start=1.0, end=10.0):
    return Clip(source_file=path, filekey8="abcd1234", start=start, end=end,
                matched_sentences=["价格"], score=0.9, reason="ok", angles=[])


def _patch_pipeline(monkeypatch, segments=None):
    segments = segments or [
        {"start": 0.0, "end": 5.0, "text": "这个价格很便宜"},
        {"start": 20.0, "end": 25.0, "text": "别的内容"},
    ]
    monkeypatch.setattr(st, "transcript_cache_key", lambda *a, **k: "abcd1234efgh5678")
    monkeypatch.setattr(st, "load_cached_transcript", lambda key: {
        "duration": 60.0, "language": "zh", "segments": segments,
    })
    monkeypatch.setattr(st, "save_cached_transcript", lambda *a, **k: None)
    monkeypatch.setattr(st, "prefilter", lambda ctx, idx: [0])
    monkeypatch.setattr(st, "keyword_match", lambda ctx, idx: [Hit(0, 0.9)])
    monkeypatch.setattr(st, "merge_hits", lambda hits, segs, **kw: [_clip(kw.get("source_file", "a.mp4"))])
    monkeypatch.setattr(st, "load_llm_config", lambda: {})
    monkeypatch.setattr(st, "get_translation_config", lambda cfg: {"api_key": "", "base_url": "", "model": ""})
    monkeypatch.setattr(st, "load_export_ledger", lambda: {})
    monkeypatch.setattr(st, "save_export_ledger", lambda ledger: None)
    monkeypatch.setattr(st, "is_already_exported", lambda clip, ledger: False)
    monkeypatch.setattr(st, "mark_exported", lambda clip, path, ledger: ledger.update({clip.filekey8: path}))
    monkeypatch.setattr(st, "export_clip", lambda *a, **k: "/tmp/clip.mp4")
    monkeypatch.setattr(st, "export_report", lambda *a, **k: "/tmp/report.json")


def test_thread_processes_all_files(monkeypatch):
    _patch_pipeline(monkeypatch)
    thread = st.SmartSearchThread(["a.mp4", "b.mp4"], "价格", [], "H.264 (MP4)", 4, "/tmp/out")
    results = []
    thread.results_ready.connect(results.extend)
    thread.run()
    assert len(results) == 2


def test_thread_continues_after_file_failure(monkeypatch):
    _patch_pipeline(monkeypatch)
    calls = {"n": 0}
    def _key(path, model="turbo"):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("broken video")
        return "abcd1234efgh5678"
    monkeypatch.setattr(st, "transcript_cache_key", _key)
    thread = st.SmartSearchThread(["bad.mp4", "good.mp4"], "价格", [], "H.264 (MP4)", 4, "/tmp/out")
    results = []
    logs = []
    thread.results_ready.connect(results.extend)
    thread.log_msg.connect(logs.append)
    thread.run()
    assert len(results) == 1
    assert any("broken video" in x for x in logs)


def test_thread_uses_keyword_fallback_when_llm_unavailable(monkeypatch):
    _patch_pipeline(monkeypatch)
    called = {"keyword": 0}
    monkeypatch.setattr(st, "get_translation_config",
                        lambda cfg: {"api_key": "k", "base_url": "u", "model": "m"})
    monkeypatch.setattr(st, "OpenAI", lambda **kw: object())
    monkeypatch.setattr(st, "llm_match_sentences",
                        lambda *a, **k: (_ for _ in ()).throw(st.LLMUnavailableError("down")))
    def _kw(ctx, idx):
        called["keyword"] += 1
        return [Hit(0, 0.9)]
    monkeypatch.setattr(st, "keyword_match", _kw)
    thread = st.SmartSearchThread(["a.mp4"], "价格", [], "H.264 (MP4)", 4, "/tmp/out")
    thread.run()
    assert called["keyword"] == 1


def test_thread_stop_before_first_file(monkeypatch):
    _patch_pipeline(monkeypatch)
    thread = st.SmartSearchThread(["a.mp4"], "价格", [], "H.264 (MP4)", 4, "/tmp/out")
    thread.running = False
    results = []
    thread.results_ready.connect(results.extend)
    thread.run()
    assert results == []


def test_thread_continues_after_clip_export_failure(monkeypatch):
    _patch_pipeline(monkeypatch)
    clips = [_clip("a.mp4", 1.0, 10.0), _clip("a.mp4", 20.0, 30.0)]
    monkeypatch.setattr(st, "merge_hits", lambda *a, **k: clips)

    calls = {"n": 0}
    def _export(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("disk full")
        return "/tmp/clip2.mp4"
    monkeypatch.setattr(st, "export_clip", _export)

    thread = st.SmartSearchThread(["a.mp4"], "价格", [], "H.264 (MP4)", 4, "/tmp/out")
    results = []
    logs = []
    thread.results_ready.connect(results.extend)
    thread.log_msg.connect(logs.append)
    thread.run()

    assert len(results) == 2
    assert results[0].clip_path == ""
    assert results[1].clip_path == "/tmp/clip2.mp4"
    assert any("disk full" in message for message in logs)
