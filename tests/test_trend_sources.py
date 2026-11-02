"""HN / V2EX 热点抓取与缓存单测。"""

from core.search_types import Hotspot, TrendAngle
from core.trend_sources import (
    fetch_hn, fetch_v2ex, fetch_hotspots,
    load_trend_cache, save_trend_cache,
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
