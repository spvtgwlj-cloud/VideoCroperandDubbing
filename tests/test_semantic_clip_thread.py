"""智能切片编排线程单测。"""

import json
import re
from types import SimpleNamespace

import core.semantic_clip_thread as st
from core.search_types import TrendAngle

CUT_JSON = json.dumps({
    "cuts": [{
        "start_time": 5.0,
        "end_time": 45.0,
        "theme": "AI 与农业",
        "angle_index": 0,
        "hot_reason": "AI 热点相关",
        "reason": "完整话题",
        "confidence": 0.9,
        "viral_title_zh": "中文标题",
        "viral_title_en": "English title",
        "social_desc_zh": "中文描述",
        "social_desc_en": "English description",
        "hashtags_zh": "#中文",
        "hashtags_en": "#English",
    }],
}, ensure_ascii=False)

SEGMENTS = [
    {"start": 0.0, "end": 5.0, "text": "开场"},
    {"start": 5.0, "end": 45.0, "text": "第一个话题"},
    {"start": 45.0, "end": 95.0, "text": "第二个话题"},
]


class _FakeCompletions:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        prompt = kwargs["messages"][0]["content"]
        if "cuts" in prompt:
            if kwargs.get("stream"):
                return iter([
                    SimpleNamespace(choices=[SimpleNamespace(
                        delta=SimpleNamespace(content=CUT_JSON[:30]),
                    )]),
                    SimpleNamespace(choices=[SimpleNamespace(
                        delta=SimpleNamespace(content=CUT_JSON[30:]),
                    )]),
                ])
            return SimpleNamespace(choices=[SimpleNamespace(
                message=SimpleNamespace(content=CUT_JSON),
            )])
        lines = re.findall(r'<line id="(\d+)">(.*?)</line>', prompt)
        content = "\n".join(
            f'<line id="{line_id}"><zh>中{text}</zh>'
            f'<en>EN {text}</en></line>'
            for line_id, text in lines
        )
        return SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=content),
        )])


class _FakeClient:
    def __init__(self):
        self.chat = SimpleNamespace(completions=_FakeCompletions())


def test_thread_generates_clip_copy_and_report(monkeypatch, tmp_path):
    client = _FakeClient()
    monkeypatch.setattr(st, "transcript_cache_key", lambda *a, **k: "key")
    monkeypatch.setattr(
        st, "load_cached_transcript",
        lambda key: {"segments": SEGMENTS, "duration": 150.0},
    )
    monkeypatch.setattr(
        st, "get_translation_config",
        lambda cfg: {"api_key": "k", "base_url": "u", "model": "m"},
    )
    monkeypatch.setattr(st, "OpenAI", lambda **kw: client)
    monkeypatch.setattr(
        st.SemanticClipThread, "_get_face_app", lambda self: None,
    )
    monkeypatch.setattr(
        st, "render_clip",
        lambda source, subs, out, **kw: out,
    )
    monkeypatch.setattr(
        st.subprocess, "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stderr=""),
    )

    thread = st.SemanticClipThread(
        "demo.mp4", "", [TrendAngle("AI 热点", ["AI"], "高热", heat=0.9)],
        str(tmp_path),
    )
    results = []
    errors = []
    thread.results_ready.connect(results.extend)
    thread.error.connect(errors.append)
    thread.run()

    assert errors == []
    assert len(results) == 1
    cut = results[0]
    assert cut.theme == "AI 与农业"
    assert cut.angle_title == "AI 热点"
    assert cut.clip_path.endswith(".mp4")
    assert (tmp_path / "semantic_clips.json").exists()
    assert list(tmp_path.glob("*_文案.txt"))
    report = json.loads(
        (tmp_path / "semantic_clips.json").read_text(encoding="utf-8"),
    )
    assert report["cuts"][0]["theme"] == "AI 与农业"
