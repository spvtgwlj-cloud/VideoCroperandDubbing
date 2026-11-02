"""智能检索核心逻辑 — 零 Qt 依赖，可独立单测。

注意：检索只使用 Whisper 返回的**未压缩** segments，
禁止调用 _compress_silence()，禁止复用 subtitles_timeline。
"""

import re

from .search_types import Hit, MatchContext, SearchIndex

# ----------------------------------------------------------------
# 阈值常量（设计文档 8.4 / 12）
# ----------------------------------------------------------------
PREFILTER_THRESHOLD = 0.12
PREFILTER_MIN_CANDIDATES = 20
PREFILTER_MIN_RATIO = 0.05
LLM_CONFIDENCE_HIT = 0.5
LLM_CONFIDENCE_MAYBE = 0.35
KEYWORD_HIT_SCORE = 0.3
LLM_TIMEOUT_SECONDS = 30
LLM_MAX_CONSECUTIVE_FAILURES = 2
DEFAULT_BATCH_SIZE = 10

_LATIN_RE = re.compile(r"[a-z0-9]+")
_CJK_RE = re.compile(r"[一-鿿]+")


def tokenize(text: str) -> list[str]:
    """把文本切成拉丁词与 CJK 2-gram（小写，允许重复）。"""
    if not text:
        return []
    lowered = text.lower()
    tokens = _LATIN_RE.findall(lowered)
    for run in _CJK_RE.findall(lowered):
        if len(run) == 1:
            tokens.append(run)
        else:
            tokens.extend(run[i:i + 2] for i in range(len(run) - 1))
    return tokens


def _context_tokens(context: MatchContext) -> set[str]:
    """query 与所有角度的标题/关键词 token 并集。"""
    tokens = set(tokenize(context.query))
    for angle in context.angles:
        tokens.update(tokenize(angle.title))
        for keyword in angle.keywords:
            tokens.update(tokenize(keyword))
    return tokens


def build_index(segments: list[dict], source_file: str,
                filekey8: str, duration: float) -> SearchIndex:
    """由未压缩转写段落构造索引。"""
    return SearchIndex(
        source_file=source_file,
        filekey8=filekey8,
        duration=duration,
        segments=segments,
    )


def keyword_match(context: MatchContext, index: SearchIndex) -> list[Hit]:
    """关键词/2-gram 覆盖打分，作为 LLM 不可用时的兜底。"""
    context_tokens = _context_tokens(context)
    if not context_tokens:
        return []

    hits: list[Hit] = []
    for i, segment in enumerate(index.segments):
        segment_tokens = set(tokenize(segment.get("text", "")))
        matched = segment_tokens & context_tokens
        score = len(matched) / max(1, len(context_tokens))
        if score < KEYWORD_HIT_SCORE:
            continue

        angle_titles: list[str] = []
        for angle in context.angles:
            angle_tokens = set(tokenize(angle.title))
            for keyword in angle.keywords:
                angle_tokens.update(tokenize(keyword))
            if angle_tokens & segment_tokens:
                angle_titles.append(angle.title)

        hits.append(Hit(
            index=i,
            score=score,
            reason=f"关键词命中: {', '.join(sorted(matched))}",
            angles=angle_titles,
        ))

    hits.sort(key=lambda hit: hit.score, reverse=True)
    return hits


def prefilter(context: MatchContext, index: SearchIndex,
              threshold: float = PREFILTER_THRESHOLD) -> list[int]:
    """本地预筛候选句；候选过少或跨语言无交集时回退全量。"""
    total = len(index.segments)
    context_tokens = _context_tokens(context)
    if not context_tokens:
        return list(range(total))

    candidates: list[int] = []
    for i, segment in enumerate(index.segments):
        segment_tokens = set(tokenize(segment.get("text", "")))
        matched = segment_tokens & context_tokens
        score = len(matched) / max(1, len(context_tokens))
        if score >= threshold:
            candidates.append(i)

    min_candidates = max(
        PREFILTER_MIN_CANDIDATES,
        int(total * PREFILTER_MIN_RATIO),
    )
    if not candidates or len(candidates) < min_candidates:
        return list(range(total))
    return candidates
