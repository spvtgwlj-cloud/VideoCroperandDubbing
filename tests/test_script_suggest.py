"""建议脚本纯逻辑单测。"""

import json
import os

import pytest

from core.script_suggest import (
    ScriptSection, SuggestedScript, build_script_prompt,
    parse_script_response, render_script_markdown, save_script,
)
from core.search_types import TrendAngle

SEGMENTS = [
    {"start": 0.0, "end": 2.5, "text": "初四那天"},
    {"start": 2.5, "end": 5.0, "text": "我们接待了一位约旦记者"},
    {"start": 5.0, "end": 8.0, "text": "他的银行卡出了问题"},
]

ANGLES = [
    TrendAngle("跨境支付痛点", ["银行卡", "支付"], "贴近生活", heat=0.8),
]


def _raw_script(**overrides):
    payload = {
        "title": "一张银行卡的跨国故事",
        "hook": "约旦记者办卡，最后却被银行卡卡住",
        "target_duration": "30-60秒",
        "sections": [{
            "name": "冲突",
            "narration": "办卡很顺，最后却因为银行卡卡住。",
            "source_segment_ids": [0, 2],
            "visual_note": "窗口办理画面",
        }],
        "cta": "评论区聊聊你遇到的跨境支付问题",
        "why": "跨境支付是当前热点",
    }
    payload.update(overrides)
    return json.dumps(payload, ensure_ascii=False)


def test_build_script_prompt_includes_segments_and_angles():
    prompt = build_script_prompt(SEGMENTS, ANGLES, query="跨境支付")
    assert "[0]" in prompt
    assert "初四那天" in prompt
    assert "跨境支付痛点" in prompt
    assert "跨境支付" in prompt
    assert '"sections"' in prompt


def test_parse_script_response_resolves_segment_times():
    script = parse_script_response(_raw_script(), SEGMENTS)
    assert script.title == "一张银行卡的跨国故事"
    assert script.hook.startswith("约旦记者")
    assert len(script.sections) == 1
    assert script.sections[0].name == "冲突"
    assert script.sections[0].source_time == "0.0s-8.0s"
    assert script.cta.startswith("评论区")


def test_parse_script_response_drops_invalid_segment_ids():
    raw = _raw_script(sections=[{
        "name": "开场",
        "narration": "口播",
        "source_segment_ids": [1, 99],
        "visual_note": "画面",
    }])
    script = parse_script_response(raw, SEGMENTS)
    assert script.sections[0].source_segment_ids == [1]
    assert script.sections[0].source_time == "2.5s-5.0s"


def test_parse_script_response_marks_missing_footage():
    raw = _raw_script(sections=[{
        "name": "补拍",
        "narration": "需要补拍的说明",
        "source_segment_ids": [],
        "visual_note": "",
    }])
    script = parse_script_response(raw, SEGMENTS)
    assert script.sections[0].source_time == ""
    assert "需补拍" in script.sections[0].visual_note


def test_parse_script_response_accepts_code_fence():
    raw = f"```json\n{_raw_script()}\n```"
    script = parse_script_response(raw, SEGMENTS)
    assert script.title == "一张银行卡的跨国故事"


def test_parse_script_response_rejects_empty_sections():
    with pytest.raises(ValueError):
        parse_script_response(_raw_script(sections=[]), SEGMENTS)


def test_render_script_markdown_contains_sections():
    script = parse_script_response(_raw_script(), SEGMENTS)
    text = render_script_markdown(script)
    assert "# 一张银行卡的跨国故事" in text
    assert "3 秒钩子" in text
    assert "办卡很顺" in text
    assert "0.0s-8.0s" in text
    assert "评论区聊聊" in text


def test_save_script_writes_json_and_markdown(tmp_path):
    script = parse_script_response(_raw_script(), SEGMENTS)
    json_path, md_path = save_script(script, str(tmp_path))

    assert os.path.exists(json_path)
    assert os.path.exists(md_path)
    data = json.loads(open(json_path, encoding="utf-8").read())
    assert data["title"] == "一张银行卡的跨国故事"
    assert data["sections"][0]["source_time"] == "0.0s-8.0s"
