"""智能检索核心逻辑单测。"""

import json
import os
import sys
from types import SimpleNamespace

import pytest

import core.smart_search as smart_search
from core.search_types import Clip, Hit, MatchContext, SearchIndex, TrendAngle
from core.smart_search import (
    LLMUnavailableError, build_clip_filename, build_export_cmd, export_clip,
    export_report, extract_audio, is_already_exported, keyword_match,
    llm_match_sentences, load_cached_transcript, load_export_ledger,
    mark_exported, merge_hits, prefilter, probe_duration,
    save_cached_transcript, save_export_ledger, tokenize, transcribe_audio,
    transcript_cache_key, transcript_cache_path,
)


def _index(texts, duration=60.0):
    segments = [
        {"start": i * 3.0, "end": i * 3.0 + 2.0, "text": t}
        for i, t in enumerate(texts)
    ]
    return SearchIndex(
        source_file="demo.mp4", filekey8="abcd1234",
        duration=duration, segments=segments,
    )


def test_tokenize_cjk_bigrams():
    tokens = tokenize("价格是多少")
    assert "价格" in tokens
    assert "格是" in tokens
    assert "多少" in tokens


def test_tokenize_mixed_latin_and_cjk():
    tokens = tokenize("Hello 价格 world")
    assert "hello" in tokens
    assert "world" in tokens
    assert "价格" in tokens


def test_keyword_match_hits_relevant_sentence():
    ctx = MatchContext(query="价格", angles=[])
    hits = keyword_match(ctx, _index(["这个价格很便宜", "今天天气不错"]))
    assert len(hits) == 1
    assert hits[0].index == 0
    assert hits[0].score >= 0.3


def test_keyword_match_records_angle():
    ctx = MatchContext(
        query="",
        angles=[TrendAngle(title="成本", keywords=["价格"], why="")],
    )
    hits = keyword_match(ctx, _index(["这个价格很便宜"]))
    assert hits[0].angles == ["成本"]


def test_prefilter_falls_back_for_cross_language():
    ctx = MatchContext(query="价格", angles=[])
    idx = _index([f"english sentence number {i}" for i in range(30)])
    assert prefilter(ctx, idx) == list(range(30))


def test_prefilter_limits_candidates_when_enough_hits():
    ctx = MatchContext(query="价格", angles=[])
    texts = ["这个价格很便宜"] * 20 + [f"无关内容{i}" for i in range(80)]
    idx = _index(texts, duration=300.0)
    candidates = prefilter(ctx, idx)
    assert 0 < len(candidates) < len(idx.segments)


def test_merge_hits_merges_nearby_and_splits_on_gap():
    segments = [
        {"start": 10.0, "end": 12.0, "text": "价格一"},
        {"start": 13.0, "end": 15.0, "text": "价格二"},
        {"start": 40.0, "end": 42.0, "text": "价格三"},
    ]
    hits = [Hit(0, 0.9), Hit(1, 0.8), Hit(2, 0.7)]
    clips = merge_hits(hits, segments, duration=60.0, top_k=10)
    assert len(clips) == 2
    assert clips[0].start == 9.5 and clips[0].end == 15.5
    assert clips[0].score == pytest.approx(0.85)
    assert clips[0].matched_sentences == ["价格一", "价格二"]
    assert clips[1].start == 39.5 and clips[1].end == 42.5


def test_merge_hits_clamps_padding_and_drops_short():
    segments = [{"start": 0.5, "end": 1.5, "text": "短句"}]
    clips = merge_hits([Hit(0, 0.9)], segments, duration=10.0, min_dur=3.0)
    assert clips == []


def test_merge_hits_splits_long_clip():
    segments = [
        {"start": float(i), "end": float(i + 1), "text": f"句{i}"}
        for i in range(0, 60)
    ]
    hits = [Hit(i, 0.8) for i in range(60)]
    clips = merge_hits(hits, segments, duration=60.0, max_dur=30.0, top_k=100)
    assert len(clips) > 1
    assert all(c.end - c.start <= 30.0 for c in clips)


def test_merge_hits_top_k_and_duplicate_index():
    segments = [
        {"start": 0.0, "end": 10.0, "text": "高"},
        {"start": 20.0, "end": 30.0, "text": "低"},
    ]
    hits = [Hit(0, 0.9), Hit(0, 0.5), Hit(1, 0.4)]
    clips = merge_hits(hits, segments, duration=60.0, top_k=1)
    assert len(clips) == 1
    assert clips[0].score == pytest.approx(0.9)


def test_transcript_cache_key_changes_with_content_and_model(tmp_path):
    video = tmp_path / "a.mp4"
    video.write_bytes(b"x" * 100)
    k1 = transcript_cache_key(str(video), "turbo")
    video.write_bytes(b"x" * 101)
    k2 = transcript_cache_key(str(video), "turbo")
    k3 = transcript_cache_key(str(video), "small")
    assert k1 != k2
    assert k2 != k3
    assert len(k1) == 16


def test_transcript_cache_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(smart_search, "CACHE_ROOT", str(tmp_path / "cache"))
    data = {"duration": 12.0, "language": "en", "segments": [{"start": 0.0, "end": 1.0, "text": "hi"}]}
    save_cached_transcript("abc123", data)
    assert load_cached_transcript("abc123") == data


def test_transcript_cache_corrupt_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(smart_search, "CACHE_ROOT", str(tmp_path / "cache"))
    path = transcript_cache_path("badbad")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("{not json")
    assert load_cached_transcript("badbad") is None


def test_probe_duration_parses_ffprobe(monkeypatch):
    class _Result:
        returncode = 0
        stdout = "12.34\n"
        stderr = ""
    monkeypatch.setattr(smart_search.subprocess, "run", lambda *a, **k: _Result())
    assert probe_duration("demo.mp4") == pytest.approx(12.34)


def test_probe_duration_returns_zero_on_failure(monkeypatch):
    def _boom(*a, **k):
        raise FileNotFoundError("ffprobe")
    monkeypatch.setattr(smart_search.subprocess, "run", _boom)
    assert probe_duration("demo.mp4") == 0.0


def test_extract_audio_builds_ffmpeg_command(monkeypatch, tmp_path):
    calls = []

    def _run(cmd, **kwargs):
        calls.append(cmd)
        (tmp_path / "out.wav").write_bytes(b"wav")

    monkeypatch.setattr(smart_search.subprocess, "run", _run)
    extract_audio("demo.mp4", str(tmp_path / "out.wav"))
    cmd = calls[0]
    assert "-vn" in cmd and "pcm_s16le" in cmd
    assert cmd[cmd.index("-ar") + 1] == "48000"
    assert cmd[cmd.index("-ac") + 1] == "1"
    assert "-y" in cmd


def test_transcribe_audio_returns_uncompressed_segments(monkeypatch):
    captured = {}

    class _FakeModel:
        device = "cpu"
        def transcribe(self, path, **kwargs):
            captured["path"] = path
            captured["kwargs"] = kwargs
            return {"segments": [{"start": 0.0, "end": 1.0, "text": "hi"}], "language": "en"}

    class _FakeWhisper:
        @staticmethod
        def load_model(name):
            captured["model_name"] = name
            return _FakeModel()

    monkeypatch.setitem(sys.modules, "whisper", _FakeWhisper)
    result = transcribe_audio("a.wav", model_name="turbo")
    assert result["segments"] == [{"start": 0.0, "end": 1.0, "text": "hi"}]
    assert result["language"] == "en"
    assert captured["model_name"] == "turbo"
    assert captured["path"] == "a.wav"


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
            choices=[SimpleNamespace(message=SimpleNamespace(content=item))]
        )


class _FakeClient:
    def __init__(self, responses):
        self.chat = SimpleNamespace(completions=_FakeCompletions(responses))


def test_llm_match_parses_batch_json():
    client = _FakeClient(['[{"i":0,"relevant":true,"confidence":0.9,"reason":"提到价格","angle":"成本"}]'])
    hits = llm_match_sentences(
        MatchContext(query="价格", angles=[]), ["这个价格很便宜"], [0], client, "model",
    )
    assert len(hits) == 1
    assert hits[0].index == 0 and hits[0].score == pytest.approx(0.9)
    assert hits[0].angles == ["成本"]


def test_llm_match_strips_code_fence():
    raw = '```json\n[{"i":0,"relevant":true,"confidence":0.8,"reason":"ok"}]\n```'
    client = _FakeClient([raw])
    hits = llm_match_sentences(MatchContext(query="q", angles=[]), ["s"], [3], client, "m")
    assert hits[0].index == 3


def test_llm_match_filters_below_confidence_threshold():
    client = _FakeClient(['[{"i":0,"relevant":true,"confidence":0.4,"reason":"弱"}]'])
    hits = llm_match_sentences(MatchContext(query="q", angles=[]), ["s"], [0], client, "m")
    assert hits == []


def test_llm_match_retries_single_sentence_on_batch_failure():
    # 解析失败（JSON 不合法）才逐句重试
    client = _FakeClient([
        "not json",
        '{"relevant":true,"confidence":0.7,"reason":"单句重试"}',
    ])
    hits = llm_match_sentences(MatchContext(query="q", angles=[]), ["s"], [2], client, "m")
    assert len(hits) == 1 and hits[0].index == 2


def test_llm_match_transport_failure_skips_single_retries():
    # 网络/超时失败不应逐句重试，连续两批后直接熔断
    client = _FakeClient([RuntimeError("timeout"), RuntimeError("timeout")])
    with pytest.raises(LLMUnavailableError):
        llm_match_sentences(
            MatchContext(query="q", angles=[]),
            ["a", "b"], [0, 1], client, "m", batch_size=1,
        )
    assert len(client.chat.completions.calls) == 2


def test_llm_match_circuit_breaker():
    # 第 1 批失败计 1 次并做单句重试；第 2 批失败时计数达到 2，立即熔断
    client = _FakeClient([RuntimeError("down")] * 3)
    with pytest.raises(LLMUnavailableError):
        llm_match_sentences(
            MatchContext(query="q", angles=[]),
            ["a", "b", "c"], [0, 1, 2], client, "m", batch_size=1,
        )


def test_llm_match_passes_timeout():
    client = _FakeClient(['[{"i":0,"relevant":true,"confidence":0.9,"reason":"ok"}]'])
    llm_match_sentences(MatchContext(query="q", angles=[]), ["s"], [0], client, "m")
    assert client.chat.completions.calls[0]["timeout"] == 30


def _clip(start=10.0, end=20.0, filekey8="abcd1234", score=0.8):
    return Clip(
        source_file="/videos/a/demo.mp4", filekey8=filekey8,
        start=start, end=end, matched_sentences=["价格"],
        score=score, reason="提到价格", angles=["成本"],
    )


def test_build_clip_filename_includes_filekey():
    name = build_clip_filename("/videos/a/demo.mp4", "abcd1234", 3, 10.0, 20.5)
    assert name == "demo_abcd1234_clip03_10.0-20.5.mp4"


def test_build_export_cmd_preserves_source_frame_rate():
    cmd = build_export_cmd("in.mp4", "out.mp4", 0.0, 5.0, "H.264 (MP4)", 4, vt_available=False)
    assert "-fps_mode" not in cmd


def test_build_export_cmd_h264_software():
    cmd = build_export_cmd("in.mp4", "out.mp4", 10.0, 20.0, "H.264 (MP4)", 4, vt_available=False)
    assert cmd[:3] == ["ffmpeg", "-y", "-ss"]
    assert cmd[cmd.index("-c:v") + 1] == "libx264"
    assert cmd[cmd.index("-b:v") + 1] == "4M"
    assert cmd[cmd.index("-c:a") + 1] == "copy"
    assert "-b:a" not in cmd
    assert "-map" in cmd and "0:a:0?" in cmd
    assert "-dn" in cmd and "-sn" in cmd
    assert cmd[cmd.index("-write_tmcd") + 1] == "0"
    assert "-tag:v" not in cmd


def test_build_export_cmd_h265_videotoolbox():
    cmd = build_export_cmd("in.mp4", "out.mp4", 0.0, 5.0, "H.265 (HEVC)", 4, vt_available=True)
    assert cmd[cmd.index("-c:v") + 1] == "hevc_videotoolbox"
    assert cmd[cmd.index("-tag:v") + 1] == "hvc1"
    assert "+faststart" in cmd


def test_export_clip_rejects_missing_output(monkeypatch, tmp_path):
    monkeypatch.setattr(smart_search.subprocess, "run", lambda *a, **k: None)
    with pytest.raises(RuntimeError):
        export_clip(_clip(), "in.mp4", str(tmp_path), "H.264 (MP4)", 4)


def test_export_report_writes_json(tmp_path):
    path = export_report([_clip()], str(tmp_path), meta={"query": "价格"})
    data = json.loads(open(path, encoding="utf-8").read())
    assert data["meta"]["query"] == "价格"
    assert data["results"][0]["start"] == 10.0


def test_export_ledger_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(smart_search, "CACHE_ROOT", str(tmp_path / "cache"))
    clip = _clip()
    out = tmp_path / "clip.mp4"
    out.write_bytes(b"x")
    clip.clip_path = str(out)
    ledger = load_export_ledger()
    assert not is_already_exported(clip, ledger)
    mark_exported(clip, str(out), ledger)
    save_export_ledger(ledger)
    ledger2 = load_export_ledger()
    assert is_already_exported(clip, ledger2)


def test_feature_flag_defaults_on(monkeypatch):
    import importlib, core.config
    monkeypatch.delenv("AI_VIDEO_SMART_SEARCH", raising=False)
    importlib.reload(core.config)
    assert core.config.ENABLE_SMART_SEARCH is True


def test_feature_flag_can_be_disabled(monkeypatch):
    import importlib, core.config
    monkeypatch.setenv("AI_VIDEO_SMART_SEARCH", "0")
    importlib.reload(core.config)
    assert core.config.ENABLE_SMART_SEARCH is False
    monkeypatch.delenv("AI_VIDEO_SMART_SEARCH")
    importlib.reload(core.config)


def test_llm_match_sentences_reports_batch_progress():
    client = _FakeClient([
        '[{"i":0,"relevant":true,"confidence":0.9,"reason":"ok"}]',
        '[{"i":0,"relevant":true,"confidence":0.9,"reason":"ok"}]',
    ])
    progress = []
    hits = llm_match_sentences(
        MatchContext(query="q", angles=[]),
        ["a", "b"], [0, 1], client, "m", batch_size=1,
        progress_cb=progress.append,
    )
    assert len(hits) == 2
    assert progress == [0.5, 1.0]


def test_llm_match_sentences_stops_between_batches():
    client = _FakeClient([
        '[{"i":0,"relevant":true,"confidence":0.9,"reason":"ok"}]',
    ])
    calls = {"n": 0}

    def _should_stop():
        calls["n"] += 1
        return calls["n"] > 1

    hits = llm_match_sentences(
        MatchContext(query="q", angles=[]),
        ["a", "b"], [0, 1], client, "m", batch_size=1,
        should_stop=_should_stop,
    )
    assert len(hits) == 1
    assert len(client.chat.completions.calls) == 1


def test_keyword_match_supports_relaxed_min_score():
    ctx = MatchContext(query="谷歌 、google agent 、AI", angles=[])
    idx = _index(["With world models, AI is moving from predicting text."])
    assert keyword_match(ctx, idx) == []
    hits = keyword_match(ctx, idx, min_score=0.0)
    assert len(hits) == 1
    assert hits[0].score == pytest.approx(0.25)


def test_export_clip_cancels_running_process(monkeypatch, tmp_path):
    monkeypatch.setattr(smart_search, "detect_videotoolbox", lambda: False)
    created = []

    class _FakePopen:
        def __init__(self, *args, **kwargs):
            self.returncode = None
            self.terminated = False
            created.append(self)
        def poll(self):
            return None
        def terminate(self):
            self.terminated = True
            self.returncode = -15
        def kill(self):
            self.returncode = -9
        def wait(self, timeout=None):
            return self.returncode
        def communicate(self):
            return ("", "")

    monkeypatch.setattr(smart_search.subprocess, "Popen", _FakePopen)
    with pytest.raises(RuntimeError):
        export_clip(
            _clip(), "in.mp4", str(tmp_path), "H.264 (MP4)", 4,
            should_stop=lambda: True,
        )
    assert created and created[0].terminated


def test_transcribe_audio_tightens_to_word_boundaries(monkeypatch):
    class _FakeModel:
        device = "cpu"
        def transcribe(self, path, **kwargs):
            return {
                "segments": [{
                    "start": 0.0, "end": 7.5, "text": "The price",
                    "words": [
                        {"start": 5.0, "end": 5.4, "word": "The"},
                        {"start": 5.4, "end": 7.2, "word": "price"},
                    ],
                }],
                "language": "en",
            }

    class _FakeWhisper:
        @staticmethod
        def load_model(name):
            return _FakeModel()

    monkeypatch.setitem(sys.modules, "whisper", _FakeWhisper)
    result = transcribe_audio("a.wav", model_name="turbo")
    assert result["segments"][0]["start"] == 5.0
    assert result["segments"][0]["end"] == 7.2
    assert result["segments"][0]["text"] == "The price"
