"""HN / V2EX 热点抓取与缓存单测。"""

from types import SimpleNamespace

import pytest

from core.search_types import Hotspot, TrendAngle
from core.trend_sources import (
    extract_keywords, fallback_angles, fetch_hn, fetch_v2ex, fetch_hotspots,
    load_trend_cache, save_trend_cache, summarize_hotspots,
)
import core.trend_sources as trend_sources


class _Resp:
    def __init__(self, payload=None, text="", status=200):
        self._payload = payload
        self.text = text
        self.status_code = status
    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")
    def json(self):
        return self._payload


class _Session:
    def __init__(self, responses):
        self.responses = list(responses)
    def get(self, url, **kwargs):
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


HN_PAYLOAD = {"hits": [
    {"title": "Show HN: Price tracker", "url": "https://example.com/a",
     "points": 120, "num_comments": 30, "objectID": "1"},
]}

V2EX_PAYLOAD = [
    {"title": "最近在折腾价格监控", "url": "https://v2ex.com/t/1", "replies": 12},
]

V2EX_RSS = """<?xml version="1.0"?><rss><channel><item>
<title>V2EX 热门话题</title><link>https://v2ex.com/t/2</link>
</item></channel></rss>"""


def test_fetch_hn_parses_algolia(monkeypatch):
    items = fetch_hn(limit=10, session=_Session([_Resp(HN_PAYLOAD)]))
    assert items[0].source == "hn"
    assert items[0].title == "Show HN: Price tracker"
    assert items[0].score == 120


def test_fetch_v2ex_parses_json():
    items = fetch_v2ex(limit=10, session=_Session([_Resp(V2EX_PAYLOAD)]))
    assert items[0].source == "v2ex"
    assert items[0].title == "最近在折腾价格监控"
    assert items[0].score == 12


def test_fetch_v2ex_falls_back_to_rss():
    session = _Session([RuntimeError("api down"), _Resp(text=V2EX_RSS)])
    items = fetch_v2ex(limit=10, session=session)
    assert items[0].title == "V2EX 热门话题"


def test_fetch_hotspots_survives_source_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(trend_sources, "TREND_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(trend_sources, "fetch_hn", lambda **kw: (_ for _ in ()).throw(RuntimeError("down")))
    monkeypatch.setattr(trend_sources, "fetch_v2ex", lambda **kw: [Hotspot("v2ex", "t", "u")])
    items = fetch_hotspots(force_refresh=True)
    assert len(items) == 1 and items[0].source == "v2ex"


def test_trend_cache_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(trend_sources, "TREND_CACHE_DIR", str(tmp_path))
    save_trend_cache("hn", [Hotspot("hn", "t", "u", score=1)])
    items = load_trend_cache("hn", ttl_seconds=1800)
    assert items[0].title == "t"


def test_trend_cache_expires(tmp_path, monkeypatch):
    monkeypatch.setattr(trend_sources, "TREND_CACHE_DIR", str(tmp_path))
    save_trend_cache("hn", [Hotspot("hn", "t", "u")])
    monkeypatch.setattr(trend_sources.time, "time", lambda: 10**12)
    assert load_trend_cache("hn", ttl_seconds=60) is None


class _FakeCompletions:
    def __init__(self, responses):
        self.responses = list(responses)
    def create(self, **kwargs):
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=item))]
        )


class _FakeClient:
    def __init__(self, responses):
        self.chat = SimpleNamespace(completions=_FakeCompletions(responses))


def test_extract_keywords_cjk_and_latin():
    kws = extract_keywords("价格 price monitor 价格 监控")
    assert "价格" in kws and "price" in kws
    assert len(kws) <= 6


def test_fallback_angles_one_per_item():
    items = [Hotspot("hn", "价格监控工具", "u"), Hotspot("v2ex", "AI 剪辑", "u2")]
    angles = fallback_angles(items, max_angles=8)
    assert len(angles) == 2
    assert angles[0].title == "价格监控工具"
    assert angles[0].why == "原始热点"


def test_fallback_angles_carry_hotspot_heat():
    items = [
        Hotspot("hn", "高热", "u1", score=100),
        Hotspot("hn", "低热", "u2", score=10),
    ]
    angles = fallback_angles(items, max_angles=8)
    assert [angle.heat for angle in angles] == pytest.approx([1.0, 0.0])
    assert angles[0].heat_raw == 100
    assert angles[0].heat_source == "hn"


def test_fetch_hotspots_normalizes_heat_per_source(monkeypatch, tmp_path):
    monkeypatch.setattr(trend_sources, "TREND_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(trend_sources, "fetch_hn", lambda **kw: [
        Hotspot("hn", "a", "u1", score=10),
        Hotspot("hn", "b", "u2", score=30),
    ])
    monkeypatch.setattr(trend_sources, "fetch_v2ex", lambda **kw: [
        Hotspot("v2ex", "c", "u3", score=5),
        Hotspot("v2ex", "d", "u4", score=5),
    ])
    items = fetch_hotspots(force_refresh=True)
    hn = [item for item in items if item.source == "hn"]
    v2ex = [item for item in items if item.source == "v2ex"]
    assert [item.heat for item in hn] == pytest.approx([0.0, 1.0])
    assert [item.heat for item in v2ex] == pytest.approx([1.0, 1.0])


def test_summarize_hotspots_maps_source_index_to_heat():
    items = [
        Hotspot("hn", "低热", "u1", score=10),
        Hotspot("hn", "高热", "u2", score=100),
    ]
    client = _FakeClient([
        '{"angles":[{"title":"角度","keywords":[],"why":"x","source_ids":[1]}]}',
    ])
    angles = summarize_hotspots(items, client, "m")
    assert angles[0].heat == pytest.approx(1.0)
    assert angles[0].heat_raw == 100
    assert angles[0].heat_source == "hn"


def test_summarize_hotspots_parses_json():
    client = _FakeClient(['{"angles":[{"title":"成本焦虑","keywords":["价格","省钱"],"why":"高热","source_ids":["hn:1"]}]}'])
    angles = summarize_hotspots([Hotspot("hn", "价格", "u")], client, "m")
    assert angles[0].title == "成本焦虑"
    assert angles[0].keywords == ["价格", "省钱"]


def test_summarize_hotspots_accepts_code_fence():
    client = _FakeClient(['```json\n{"angles":[{"title":"角度","keywords":[],"why":"x"}]}\n```'])
    angles = summarize_hotspots([Hotspot("hn", "价格", "u")], client, "m")
    assert angles[0].title == "角度"


def test_summarize_hotspots_falls_back_on_invalid_json():
    client = _FakeClient(["not json"])
    angles = summarize_hotspots([Hotspot("hn", "价格监控", "u")], client, "m")
    assert angles[0].title == "价格监控"


def test_summarize_hotspots_falls_back_on_llm_error():
    client = _FakeClient([RuntimeError("down")])
    angles = summarize_hotspots([Hotspot("hn", "价格监控", "u")], client, "m")
    assert angles[0].title == "价格监控"


def test_trend_thread_emits_done(monkeypatch):
    from core.trend_thread import TrendFetchThread
    monkeypatch.setattr("core.trend_thread.fetch_hotspots", lambda **kw: [Hotspot("hn", "t", "u")])
    thread = TrendFetchThread()
    received = []
    thread.done.connect(received.extend)
    thread.run()
    assert received[0].title == "t"


def test_trend_thread_emits_angles(monkeypatch):
    from core.trend_thread import TrendFetchThread
    monkeypatch.setattr("core.trend_thread.fetch_hotspots", lambda **kw: [Hotspot("hn", "t", "u")])
    monkeypatch.setattr("core.trend_thread.load_llm_config", lambda: {})
    monkeypatch.setattr("core.trend_thread.get_translation_config",
                        lambda cfg: {"api_key": "", "base_url": "", "model": ""})
    monkeypatch.setattr("core.trend_thread.fallback_angles",
                        lambda items, max_angles=8: [TrendAngle("兜底", [], "无 Key")])
    thread = TrendFetchThread(summarize=True)
    angles = []
    thread.angles_ready.connect(angles.extend)
    thread.run()
    assert angles[0].title == "兜底"


def test_trend_thread_emits_failed(monkeypatch):
    from core.trend_thread import TrendFetchThread

    def _boom(**kw):
        raise RuntimeError("network down")
    monkeypatch.setattr("core.trend_thread.fetch_hotspots", _boom)
    thread = TrendFetchThread()
    errors = []
    thread.failed.connect(errors.append)
    thread.run()
    assert errors == ["network down"]
