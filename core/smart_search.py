"""智能检索核心逻辑 — 零 Qt 依赖，可独立单测。

注意：检索只使用 Whisper 返回的**未压缩** segments，
禁止调用 _compress_silence()，禁止复用 subtitles_timeline。
"""

import hashlib
import json
import os
import re
import subprocess
from typing import Any, Callable

from .search_types import Clip, Hit, MatchContext, SearchIndex

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

CACHE_ROOT = os.path.join(
    os.path.expanduser("~"), ".ai_video_dubbing_pro", "smart_search"
)

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


def _split_group(group: list[Hit], segments: list[dict],
                 max_span: float) -> list[list[Hit]]:
    """把一组连续命中按 max_span 贪心切成多块。"""
    chunks: list[list[Hit]] = []
    current = [group[0]]
    for hit in group[1:]:
        block_start = segments[current[0].index]["start"]
        if segments[hit.index]["end"] - block_start > max_span:
            chunks.append(current)
            current = [hit]
        else:
            current.append(hit)
    chunks.append(current)
    return chunks


def _overlaps(a: Clip, b: Clip) -> bool:
    """两个片段交集占较短片段时长 >= 50% 视为重叠。"""
    intersection = max(0.0, min(a.end, b.end) - max(a.start, b.start))
    shorter = min(a.end - a.start, b.end - b.start)
    return shorter > 0 and intersection / shorter >= 0.5


def merge_hits(
    hits: list[Hit],
    segments: list[dict],
    *,
    min_gap: float = 2.0,
    pad_before: float = 0.5,
    pad_after: float = 0.5,
    min_dur: float = 3.0,
    max_dur: float = 120.0,
    top_k: int = 10,
    source_file: str = "",
    filekey8: str = "",
    duration: float | None = None,
) -> list[Clip]:
    """合并相邻命中句、加 padding、按句边界切分过长片段并取 Top-K。"""
    # 1. 丢弃越界 hit，同一 index 只保留最高分
    best: dict[int, Hit] = {}
    for hit in hits:
        if not 0 <= hit.index < len(segments):
            continue
        previous = best.get(hit.index)
        if previous is None or hit.score > previous.score:
            best[hit.index] = hit
    if not best:
        return []

    # 2. 按 segment start 升序
    ordered = sorted(best.values(), key=lambda h: segments[h.index]["start"])

    # 3. 相邻命中分组
    groups: list[list[Hit]] = []
    current = [ordered[0]]
    for hit in ordered[1:]:
        previous_seg = segments[current[-1].index]
        current_seg = segments[hit.index]
        if current_seg["start"] - previous_seg["end"] <= min_gap:
            current.append(hit)
        else:
            groups.append(current)
            current = [hit]
    groups.append(current)

    # 4-6. 每组按句边界切块，应用 padding 与时长过滤
    max_span = max(0.0, max_dur - pad_before - pad_after)
    clips: list[Clip] = []
    for group in groups:
        for chunk in _split_group(group, segments, max_span):
            first_seg = segments[chunk[0].index]
            last_seg = segments[chunk[-1].index]
            start = max(0.0, first_seg["start"] - pad_before)
            end = last_seg["end"] + pad_after
            if duration is not None:
                end = min(duration, end)
            if end - start < min_dur:
                continue
            reasons: list[str] = []
            for hit in chunk:
                if hit.reason and hit.reason not in reasons:
                    reasons.append(hit.reason)
            angles: list[str] = []
            for hit in chunk:
                for angle in hit.angles:
                    if angle not in angles:
                        angles.append(angle)
            clips.append(Clip(
                source_file=source_file,
                filekey8=filekey8,
                start=start,
                end=end,
                matched_sentences=[
                    segments[hit.index].get("text", "") for hit in chunk
                ],
                score=sum(hit.score for hit in chunk) / len(chunk),
                reason="；".join(reasons)[:200],
                angles=angles,
            ))

    # 7. 重叠去重：保留 score 更高者
    clips.sort(key=lambda clip: clip.score, reverse=True)
    kept: list[Clip] = []
    for clip in clips:
        if any(_overlaps(clip, existing) for existing in kept):
            continue
        kept.append(clip)

    # 8. Top-K
    return kept[:top_k]


def transcript_cache_key(video_path: str, model_name: str = "turbo") -> str:
    """按文件大小、mtime、首尾 1MB 与模型名生成 16 位缓存 key。"""
    try:
        stat = os.stat(video_path)
        with open(video_path, "rb") as f:
            head = f.read(1024 * 1024)
            f.seek(max(0, stat.st_size - 1024 * 1024))
            tail = f.read(1024 * 1024)
    except OSError:
        return ""

    digest = hashlib.sha256()
    digest.update(str(stat.st_size).encode("utf-8"))
    digest.update(str(stat.st_mtime).encode("utf-8"))
    digest.update(head)
    digest.update(tail)
    digest.update(model_name.encode("utf-8"))
    return digest.hexdigest()[:16]


def transcript_cache_path(key: str) -> str:
    """转写缓存文件路径。"""
    return os.path.join(CACHE_ROOT, "transcripts", f"{key}.json")


def load_cached_transcript(key: str) -> dict | None:
    """读取缓存；不存在或损坏返回 None。"""
    if not key:
        return None
    path = transcript_cache_path(key)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def save_cached_transcript(key: str, data: dict) -> None:
    """写入缓存。"""
    if not key:
        return
    path = transcript_cache_path(key)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def probe_duration(video_path: str) -> float:
    """用 ffprobe 读取视频时长（秒）；失败返回 0.0。"""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=nw=1:nk=1",
                video_path,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
        )
        return float(result.stdout.strip())
    except Exception:
        return 0.0


def extract_audio(video_path: str, out_wav: str,
                  log_cb: Callable[[str], None] | None = None) -> None:
    """用 ffmpeg 提取单声道 48kHz PCM 音频。"""
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vn", "-acodec", "pcm_s16le", "-ar", "48000", "-ac", "1",
        out_wav,
    ]
    if log_cb:
        log_cb(f"提取音频: {os.path.basename(video_path)}")
    try:
        subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(exc.stderr or "ffmpeg 提取音频失败") from exc
    except OSError as exc:
        raise RuntimeError(str(exc)) from exc
    if not os.path.exists(out_wav) or os.path.getsize(out_wav) <= 0:
        raise RuntimeError("ffmpeg 未生成有效音频文件")


def transcribe_audio(audio_path: str, model: Any = None,
                     model_name: str = "turbo",
                     log_cb: Callable[[str], None] | None = None) -> dict:
    """用 Whisper 转写，返回未压缩 segments。

    这里只返回 Whisper 的原始 result["segments"]。
    禁止调用 _compress_silence()，禁止复用配音管线的 subtitles_timeline
    （其时间戳已平移、文本已是译文）。
    """
    if model is None:
        import whisper
        model = whisper.load_model(model_name)
    fp16 = getattr(model, "device", None) == "mps"
    result = model.transcribe(audio_path, fp16=fp16)
    return {
        "segments": result.get("segments", []),
        "language": result.get("language", ""),
    }


class LLMUnavailableError(RuntimeError):
    """LLM 连续失败，本次运行应整体降级为关键词匹配。"""


def _strip_code_fence(raw: str) -> str:
    text = (raw or "").strip()
    text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def build_match_prompt(context: MatchContext, sentences: list[str]) -> str:
    """构造批量打分 prompt；句子编号从 0 开始。"""
    lines = [
        "你是视频内容分析助手。根据用户需求与热点角度，判断每句转写是否相关。",
        "要求：跨语言语义匹配；只返回 JSON 数组；每项格式：",
        '{"i": 句子编号, "relevant": true/false, "confidence": 0-1, '
        '"reason": "简短中文理由", "angle": "关联角度标题或空字符串"}',
        "",
        f"用户需求: {context.query or '（无，仅按热点角度匹配）'}",
    ]
    if context.angles:
        lines.append("热点角度:")
        for idx, angle in enumerate(context.angles):
            lines.append(
                f"- [{idx}] {angle.title} | 关键词: {', '.join(angle.keywords)} "
                f"| 理由: {angle.why}"
            )
    lines.append("待判断句子:")
    for i, sentence in enumerate(sentences):
        lines.append(f"{i}. {sentence}")
    return "\n".join(lines)


def parse_match_response(raw: str, expected_count: int) -> list[dict]:
    """解析 LLM 返回的 JSON 数组，容忍 ```json 围栏。"""
    text = _strip_code_fence(raw)
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise ValueError(f"LLM 返回不是合法 JSON: {exc}") from exc
    if isinstance(data, dict):
        data = data.get("results", data.get("items"))
    if not isinstance(data, list):
        raise ValueError("LLM 返回不是 JSON 数组")
    return [item for item in data if isinstance(item, dict)]


def _hit_from_item(item: dict, segment_index: int) -> Hit | None:
    if not item.get("relevant"):
        return None
    try:
        confidence = float(item.get("confidence", 0))
    except (TypeError, ValueError):
        return None
    if confidence < LLM_CONFIDENCE_HIT:
        return None

    raw_angle = item.get("angle")
    if isinstance(raw_angle, list):
        angles = [str(angle) for angle in raw_angle if angle]
    elif raw_angle:
        angles = [str(raw_angle)]
    else:
        angles = []

    return Hit(
        index=segment_index,
        score=confidence,
        reason=str(item.get("reason", "")),
        angles=angles,
    )


def _call_llm(client: Any, model: str, prompt: str) -> str:
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        timeout=LLM_TIMEOUT_SECONDS,
    )
    return response.choices[0].message.content


def llm_match_sentence(context: MatchContext, sentence: str, segment_index: int,
                       client: Any, model: str,
                       log_cb: Callable[[str], None] | None = None) -> Hit | None:
    """单句打分（批量失败时回退）。"""
    prompt = build_match_prompt(context, [sentence])
    raw = _call_llm(client, model, prompt)
    data = json.loads(_strip_code_fence(raw))
    if isinstance(data, list):
        data = data[0] if data else {}
    if not isinstance(data, dict):
        return None
    return _hit_from_item(data, segment_index)


def llm_match_sentences(
    context: MatchContext,
    sentences: list[str],
    segment_indexes: list[int],
    client: Any,
    model: str,
    batch_size: int = DEFAULT_BATCH_SIZE,
    log_cb: Callable[[str], None] | None = None,
) -> list[Hit]:
    """批量 LLM 打分；连续两批失败时抛 LLMUnavailableError。"""
    hits: list[Hit] = []
    consecutive_failures = 0

    for start in range(0, len(sentences), batch_size):
        batch = sentences[start:start + batch_size]
        batch_indexes = segment_indexes[start:start + batch_size]
        prompt = build_match_prompt(context, batch)

        try:
            raw = _call_llm(client, model, prompt)
            items = parse_match_response(raw, len(batch))
            consecutive_failures = 0
        except Exception as exc:
            consecutive_failures += 1
            if consecutive_failures >= LLM_MAX_CONSECUTIVE_FAILURES:
                raise LLMUnavailableError(str(exc)) from exc
            if log_cb:
                log_cb(f"LLM 批次失败，改单句重试: {exc}")
            for sentence, segment_index in zip(batch, batch_indexes):
                try:
                    hit = llm_match_sentence(
                        context, sentence, segment_index, client, model, log_cb,
                    )
                    if hit is not None:
                        hits.append(hit)
                except Exception:
                    pass
            continue

        for position, item in enumerate(items):
            local_index = item.get("i", position)
            if not isinstance(local_index, int) or not 0 <= local_index < len(batch_indexes):
                local_index = position
            hit = _hit_from_item(item, batch_indexes[local_index])
            if hit is not None:
                hits.append(hit)

    return hits
