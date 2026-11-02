"""HN / V2EX 热点抓取、解析与缓存（零 Qt 依赖）。"""

import json
import os
import time
import xml.etree.ElementTree as ET
from dataclasses import asdict
from typing import Any

import requests

from .search_types import Hotspot

TREND_CACHE_DIR = os.path.join(
    os.path.expanduser("~"), ".ai_video_dubbing_pro", "smart_search"
)
TREND_CONFIG_FILE = os.path.join(TREND_CACHE_DIR, "trend_config.json")

HN_URL = "https://hn.algolia.com/api/v1/search?tags=front_page&hitsPerPage={limit}"
V2EX_API_URL = "https://www.v2ex.com/api/topics/hot.json"
V2EX_API_V2_URL = "https://www.v2ex.com/api/v2/topics/hot"
V2EX_RSS_URL = "https://www.v2ex.com/index.xml"


def _get(session: Any, url: str, timeout: float,
         headers: dict | None = None) -> Any:
    """用注入的 session（便于测试）或 requests 发起 GET。"""
    client = session or requests
    response = client.get(url, timeout=timeout, headers=headers or {})
    response.raise_for_status()
    return response


def fetch_hn(limit: int = 20, timeout: float = 8.0,
             session: Any = None) -> list[Hotspot]:
    """抓取 HN 首页热点（Algolia 一次请求）。"""
    response = _get(session, HN_URL.format(limit=limit), timeout)
    payload = response.json() or {}
    items: list[Hotspot] = []
    for hit in payload.get("hits", [])[:limit]:
        object_id = hit.get("objectID", "")
        url = hit.get("url") or f"https://news.ycombinator.com/item?id={object_id}"
        items.append(Hotspot(
            source="hn",
            title=hit.get("title", ""),
            url=url,
            score=int(hit.get("points") or 0),
            comments=int(hit.get("num_comments") or 0),
        ))
    return items


def fetch_v2ex(limit: int = 20, timeout: float = 8.0,
               token: str | None = None,
               session: Any = None) -> list[Hotspot]:
    """抓取 V2EX 热门；JSON 失败时退回 RSS。"""
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    url = V2EX_API_V2_URL if token else V2EX_API_URL
    try:
        response = _get(session, url, timeout, headers)
        payload = response.json() or []
        if isinstance(payload, dict):
            payload = payload.get("result", payload.get("data", []))
        items: list[Hotspot] = []
        for topic in payload[:limit]:
            replies = int(topic.get("replies") or 0)
            items.append(Hotspot(
                source="v2ex",
                title=topic.get("title", ""),
                url=topic.get("url", ""),
                score=replies,
                comments=replies,
            ))
        if items:
            return items
    except Exception:
        pass

    # 兜底：RSS
    response = _get(session, V2EX_RSS_URL, timeout)
    root = ET.fromstring(response.text)
    items = []
    for item in root.findall(".//item")[:limit]:
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        if title:
            items.append(Hotspot(source="v2ex", title=title, url=link))
    return items


def fetch_hotspots(sources=("hn", "v2ex"), limit: int = 20,
                   timeout: float = 8.0,
                   force_refresh: bool = False) -> list[Hotspot]:
    """按来源抓取热点；单个来源失败不影响其他来源。"""
    fetchers = {"hn": fetch_hn, "v2ex": fetch_v2ex}
    items: list[Hotspot] = []
    for source in sources:
        if not force_refresh:
            cached = load_trend_cache(source)
            if cached is not None:
                items.extend(cached)
                continue
        fetcher = fetchers.get(source)
        if fetcher is None:
            continue
        try:
            fetched = fetcher(limit=limit, timeout=timeout)
        except Exception:
            continue
        if fetched:
            save_trend_cache(source, fetched)
            items.extend(fetched)
    return items


def _trend_cache_path(source: str) -> str:
    return os.path.join(TREND_CACHE_DIR, f"trends_{source}.json")


def load_trend_cache(source: str,
                     ttl_seconds: int = 1800) -> list[Hotspot] | None:
    """读取未过期的热点缓存；不存在/损坏/过期返回 None。"""
    path = _trend_cache_path(source)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        fetched_at = float(data.get("fetched_at", 0))
        if time.time() - fetched_at > ttl_seconds:
            return None
        return [Hotspot(**item) for item in data.get("items", [])]
    except (OSError, ValueError, TypeError):
        return None


def save_trend_cache(source: str, items: list[Hotspot]) -> None:
    """写入热点缓存。"""
    os.makedirs(TREND_CACHE_DIR, exist_ok=True)
    path = _trend_cache_path(source)
    payload = {
        "fetched_at": time.time(),
        "items": [asdict(item) for item in items],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
