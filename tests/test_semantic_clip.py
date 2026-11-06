"""智能切片纯逻辑单测。"""

import json

import pytest

from core.search_types import TrendAngle
from core.semantic_clip import (
    CutPlan, build_cut_prompt, merge_cut_plans, parse_cut_response,
    render_social_copy, slice_transcript,
)

SEGMENTS = [
    {"start": 0.0, "end": 5.0, "text": "开场问候"},
    {"start": 5.0, "end": 45.0, "text": "第一个完整话题"},
    {"start": 45.0, "end": 95.0, "text": "第二个完整话题"},
    {"start": 95.0, "end": 150.0, "text": "第三个完整话题"},
]

ANGLES = [
    TrendAngle(
        "AI 热点", ["AI", "模型"], "高热", heat=0.9,
        heat_raw=100, heat_source="hn",
    ),
    TrendAngle("系统翻车", ["Ubuntu"], "中热", heat=0.4),
]


def _cut(start, end, theme, **overrides):
    payload = {
        "start_time": start,
        "end_time": end,
        "theme": theme,
        "angle_index": -1,
        "hot_reason": "",
        "reason": "",
        "confidence": 0.7,
        "viral_title_zh": f"{theme}中文标题",
        "viral_title_en": f"{theme} English title",
        "social_desc_zh": f"{theme}中文描述",
        "social_desc_en": f"{theme} English description",
        "hashtags_zh": "#中文标签",
        "hashtags_en": "#EnglishTag",
    }
    payload.update(overrides)
    return payload


def _raw(cuts):
    return json.dumps({"cuts": cuts}, ensure_ascii=False)


def test_build_cut_prompt_includes_segments_angles_and_schema():
    prompt = build_cut_prompt(
        SEGMENTS, ANGLES, query="AI 与农业", min_dur=40, max_dur=180,
    )
    assert "第一个完整话题" in prompt
    assert "AI 热点" in prompt
    assert "AI 与农业" in prompt
    assert '"cuts"' in prompt
    assert "angle_index" in prompt


def test_parse_maps_angle_and_keeps_bilingual_copy():
    raw = _raw([
        _cut(
            5, 45, "话题一", angle_index=0, confidence=0.9,
            hot_reason="AI 热点相关",
        ),
    ])
    cuts = parse_cut_response(
        raw, duration=150.0, min_dur=40, max_dur=180,
        max_cuts=3, angles=ANGLES,
    )
    assert len(cuts) == 1
    cut = cuts[0]
    assert cut.angle_title == "AI 热点"
    assert cut.heat == pytest.approx(0.9)
    assert cut.hot_reason == "AI 热点相关"
    assert cut.viral_title_zh == "话题一中文标题"
    assert cut.viral_title_en == "话题一 English title"
    assert cut.hashtags_zh == "#中文标签"


def test_parse_allows_no_hot_angle():
    raw = _raw([_cut(5, 45, "话题一", angle_index=-1)])
    cuts = parse_cut_response(
        raw, duration=150.0, min_dur=40, max_dur=180,
        max_cuts=3, angles=ANGLES,
    )
    assert cuts[0].angle_index == -1
    assert cuts[0].angle_title == ""
    assert cuts[0].heat == 0.0


def test_parse_clamps_out_of_range_times():
    raw = _raw([_cut(-10, 500, "越界")])
    cuts = parse_cut_response(
        raw, duration=150.0, min_dur=40, max_dur=180,
        max_cuts=3, angles=ANGLES,
    )
    assert cuts[0].start == 0.0
    assert cuts[0].end == 150.0


def test_parse_truncates_overlong_cut():
    raw = _raw([_cut(5, 500, "过长")])
    cuts = parse_cut_response(
        raw, duration=500.0, min_dur=40, max_dur=180,
        max_cuts=3, angles=ANGLES,
    )
    assert cuts[0].duration == pytest.approx(180.0)


def test_parse_drops_too_short_and_duplicate_overlap():
    raw = _raw([
        _cut(5, 20, "太短", confidence=0.9),
        _cut(5, 45, "长版本", confidence=0.6),
        _cut(10, 50, "重叠版本", confidence=0.8),
        _cut(45, 95, "第二个", confidence=0.7),
    ])
    cuts = parse_cut_response(
        raw, duration=150.0, min_dur=40, max_dur=180,
        max_cuts=3, angles=ANGLES,
    )
    themes = [cut.theme for cut in cuts]
    assert "太短" not in themes
    assert themes.count("重叠版本") + themes.count("长版本") == 1
    assert "重叠版本" in themes  # 更高 confidence 的重叠片段保留


def test_parse_caps_at_max_cuts_and_ranks_by_score():
    raw = _raw([
        _cut(0, 45, "低分", confidence=0.5, angle_index=-1),
        _cut(45, 90, "高分带热点", confidence=0.9, angle_index=0),
        _cut(90, 140, "中分", confidence=0.7, angle_index=-1),
        _cut(140, 190, "第四", confidence=0.6, angle_index=-1),
    ])
    cuts = parse_cut_response(
        raw, duration=200.0, min_dur=40, max_dur=180,
        max_cuts=3, angles=ANGLES,
    )
    assert len(cuts) == 3
    assert cuts[0].theme == "高分带热点"


def test_merge_cut_plans_dedupes_and_caps():
    first = [CutPlan(5, 45, "A", confidence=0.7)]
    second = [
        CutPlan(10, 50, "A-overlap", confidence=0.9),
        CutPlan(60, 100, "B", confidence=0.6),
    ]
    merged = merge_cut_plans(first, second, max_cuts=2)
    assert len(merged) == 2
    assert merged[0].theme == "A-overlap"


def test_slice_transcript_shifts_times():
    sliced = slice_transcript(SEGMENTS, 40.0, 90.0)
    assert len(sliced) == 2
    assert sliced[0]["start"] == pytest.approx(0.0)
    assert sliced[0]["end"] == pytest.approx(5.0)
    assert sliced[1]["start"] == pytest.approx(5.0)
    assert sliced[1]["text"] == "第二个完整话题"


def test_render_social_copy_contains_bilingual_fields_and_hot_angle():
    cut = CutPlan(
        5, 45, "话题一", angle_title="AI 热点", heat=0.9,
        viral_title_zh="中文标题", viral_title_en="English Title",
        social_desc_zh="中文描述", social_desc_en="English description",
        hashtags_zh="#中文", hashtags_en="#English",
    )
    text = render_social_copy(cut)
    assert "中文标题" in text
    assert "English Title" in text
    assert "AI 热点" in text
    assert "00:00:05" in text
    assert "00:00:45" in text


def test_parse_rejects_empty_cuts():
    with pytest.raises(ValueError):
        parse_cut_response(
            _raw([]), duration=150.0, min_dur=40, max_dur=180,
            max_cuts=3, angles=ANGLES,
        )
