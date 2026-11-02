"""智能检索核心逻辑单测。"""

import os

import pytest

import core.smart_search as smart_search
from core.search_types import Hit, MatchContext, SearchIndex, TrendAngle
from core.smart_search import (
    keyword_match, load_cached_transcript, merge_hits, prefilter,
    save_cached_transcript, tokenize, transcript_cache_key,
    transcript_cache_path,
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
