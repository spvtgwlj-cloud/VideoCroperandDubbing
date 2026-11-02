"""智能检索核心逻辑单测。"""

from core.search_types import Hit, MatchContext, SearchIndex, TrendAngle
from core.smart_search import keyword_match, prefilter, tokenize


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
