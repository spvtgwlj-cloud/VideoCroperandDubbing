"""智能切片纯逻辑：整段语义分段、时间校验、热点关联与双语文案。"""

import json
import re
from dataclasses import dataclass

from .search_types import TrendAngle

DEFAULT_MIN_DUR = 40.0
DEFAULT_MAX_DUR = 180.0
DEFAULT_MAX_CUTS = 3


@dataclass
class CutPlan:
    """LLM 分析出的一个完整主题切片。"""

    start: float
    end: float
    theme: str
    angle_index: int = -1
    angle_title: str = ""
    heat: float = 0.0
    hot_reason: str = ""
    reason: str = ""
    confidence: float = 0.5
    viral_title_zh: str = ""
    viral_title_en: str = ""
    social_desc_zh: str = ""
    social_desc_en: str = ""
    hashtags_zh: str = ""
    hashtags_en: str = ""
    is_fallback: bool = False
    clip_path: str = ""

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


def _score(cut: CutPlan) -> float:
    """内容置信度为主，热度只做很小的加分。"""
    return cut.confidence + 0.05 * cut.heat


def _overlap_ratio(a: CutPlan, b: CutPlan) -> float:
    intersection = max(0.0, min(a.end, b.end) - max(a.start, b.start))
    shorter = min(a.duration, b.duration)
    return intersection / shorter if shorter > 0 else 0.0


def _dedupe(cuts: list[CutPlan]) -> list[CutPlan]:
    """重叠超过 50% 的切片只保留得分更高者。"""
    kept: list[CutPlan] = []
    for cut in sorted(cuts, key=_score, reverse=True):
        if any(_overlap_ratio(cut, existing) >= 0.5 for existing in kept):
            continue
        kept.append(cut)
    return kept


def build_cut_prompt(segments: list[dict], angles: list[TrendAngle],
                     query: str = "", min_dur: float = DEFAULT_MIN_DUR,
                     max_dur: float = DEFAULT_MAX_DUR,
                     max_cuts: int = DEFAULT_MAX_CUTS,
                     max_chars: int = 15000) -> str:
    """构造整段语义切片 prompt；热点作为可选加分项。"""
    lines = [
        "你是顶级短视频编导。请通读整段视频转写，按“话题完整性”切出"
        f"最多 {max_cuts} 个适合直接发布的短视频片段。",
        "",
        "要求：",
        f"- 每个切片时长 {min_dur:.0f}-{max_dur:.0f} 秒；"
        "话题完整，不要在句子中间切断。",
        "- 起止时间必须来自下方转写时间轴，禁止编造。",
        "- 每个切片尽量关联一个热点角度；没有合适热点时 angle_index 填 -1，"
        "不要硬蹭。",
        "- 每个切片都要给出中英文标题、描述和标签。",
        "- 只返回 JSON，不要解释或代码块。",
        "",
        "JSON 格式：",
        '{"cuts":[{"start_time":0.0,"end_time":45.0,"theme":"主题",'
        '"angle_index":0,"hot_reason":"为什么关联该热点","reason":"内容概述",'
        '"confidence":0.0,"viral_title_zh":"中文爆款标题",'
        '"viral_title_en":"English viral title",'
        '"social_desc_zh":"中文发布描述","social_desc_en":"English description",'
        '"hashtags_zh":"#标签","hashtags_en":"#tags"}]}',
        "",
        f"创作方向: {query or '（无，按内容与热点自由判断）'}",
        "热点角度:",
    ]
    if angles:
        for index, angle in enumerate(angles[:8]):
            keywords = ", ".join(angle.keywords)
            lines.append(
                f"[{index}] {angle.title} | 关键词: {keywords} | "
                f"理由: {angle.why} | 热度: {angle.heat:.2f}"
            )
    else:
        lines.append("（无热点角度，可返回 angle_index=-1）")

    lines.append("")
    lines.append("视频转写:")
    transcript_lines: list[str] = []
    for segment in segments:
        try:
            start = float(segment.get("start", 0.0))
            end = float(segment.get("end", 0.0))
        except (TypeError, ValueError):
            continue
        transcript_lines.append(
            f"[{start:.1f}-{end:.1f}] {segment.get('text', '')}"
        )
    transcript = "\n".join(transcript_lines)
    if len(transcript) > max_chars:
        transcript = transcript[:max_chars] + "\n（转写过长，已截断）"
    lines.append(transcript)
    return "\n".join(lines)


def _strip_code_fence(raw: str) -> str:
    text = (raw or "").strip()
    text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _coerce_float(value) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_int(value) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return None
    return number


def _cut_from_entry(entry: dict, index: int, duration: float,
                    min_dur: float, max_dur: float,
                    angles: list[TrendAngle]) -> CutPlan | None:
    start = _coerce_float(entry.get("start_time"))
    end = _coerce_float(entry.get("end_time"))
    if start is None or end is None or duration <= 0:
        return None

    start = max(0.0, min(start, duration))
    end = max(0.0, min(end, duration))
    if end <= start:
        return None

    effective_min = min(min_dur, duration)
    if end - start < effective_min:
        return None
    if end - start > max_dur:
        end = min(duration, start + max_dur)
    if end <= start:
        return None

    angle_index = _coerce_int(entry.get("angle_index"))
    angle_title = ""
    heat = 0.0
    if angle_index is not None and 0 <= angle_index < len(angles):
        angle = angles[angle_index]
        angle_title = angle.title
        heat = angle.heat
    else:
        angle_index = -1

    confidence = _coerce_float(entry.get("confidence"))
    confidence = 0.5 if confidence is None else max(0.0, min(1.0, confidence))

    theme = str(entry.get("theme", "")).strip() or f"切片{index + 1}"
    return CutPlan(
        start=start,
        end=end,
        theme=theme,
        angle_index=angle_index,
        angle_title=angle_title,
        heat=heat,
        hot_reason=str(entry.get("hot_reason", "")).strip(),
        reason=str(entry.get("reason", "")).strip(),
        confidence=confidence,
        viral_title_zh=str(entry.get("viral_title_zh", "")).strip(),
        viral_title_en=str(entry.get("viral_title_en", "")).strip(),
        social_desc_zh=str(entry.get("social_desc_zh", "")).strip(),
        social_desc_en=str(entry.get("social_desc_en", "")).strip(),
        hashtags_zh=str(entry.get("hashtags_zh", "")).strip(),
        hashtags_en=str(entry.get("hashtags_en", "")).strip(),
    )


def parse_cut_response(raw: str, duration: float,
                       min_dur: float = DEFAULT_MIN_DUR,
                       max_dur: float = DEFAULT_MAX_DUR,
                       max_cuts: int = DEFAULT_MAX_CUTS,
                       angles: list[TrendAngle] | None = None) -> list[CutPlan]:
    """解析 LLM 切片 JSON，校验时间、去重并取 Top-N。"""
    try:
        data = json.loads(_strip_code_fence(raw))
    except ValueError as exc:
        raise ValueError(f"切片结果不是合法 JSON: {exc}") from exc
    if isinstance(data, dict):
        data = data.get("cuts")
    if not isinstance(data, list):
        raise ValueError("切片结果缺少 cuts 数组")

    cuts: list[CutPlan] = []
    for index, entry in enumerate(data):
        if not isinstance(entry, dict):
            continue
        cut = _cut_from_entry(
            entry, index, duration, min_dur, max_dur, angles or [],
        )
        if cut is not None:
            cuts.append(cut)

    cuts = _dedupe(cuts)
    if not cuts:
        raise ValueError("没有通过校验的切片")
    return cuts[:max_cuts]


def merge_cut_plans(existing: list[CutPlan], new: list[CutPlan],
                    max_cuts: int = DEFAULT_MAX_CUTS) -> list[CutPlan]:
    """合并多个转写块的切片结果，去重后取 Top-N。"""
    return _dedupe(list(existing) + list(new))[:max_cuts]


def slice_transcript(segments: list[dict], start: float,
                     end: float) -> list[dict]:
    """从全局转写切出局部字幕，时间轴平移到 0。"""
    sliced: list[dict] = []
    for segment in segments:
        try:
            seg_start = float(segment.get("start", 0.0))
            seg_end = float(segment.get("end", 0.0))
        except (TypeError, ValueError):
            continue
        local_start = max(seg_start, start) - start
        local_end = min(seg_end, end) - start
        if local_end <= local_start:
            continue
        sliced.append({
            "start": local_start,
            "end": local_end,
            "text": segment.get("text", ""),
            "text_zh": segment.get("text_zh", segment.get("text", "")),
            "text_en": segment.get("text_en", ""),
        })
    return sliced


def _format_time(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 3600:02d}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"


def render_social_copy(cut: CutPlan) -> str:
    """生成单个切片的中英文运营文案。"""
    angle_line = (
        f"{cut.angle_title}（热度 {cut.heat:.2f}）"
        if cut.angle_title else "无关联热点"
    )
    lines = [
        f"# {cut.theme}",
        "",
        f"- 时间：{_format_time(cut.start)} - {_format_time(cut.end)}"
        f"（{cut.duration:.1f}s）",
        f"- 关联热点：{angle_line}",
    ]
    if cut.hot_reason:
        lines.append(f"- 热点理由：{cut.hot_reason}")
    if cut.reason:
        lines.append(f"- 内容概述：{cut.reason}")
    lines.extend([
        "",
        "## 中文",
        f"【标题】{cut.viral_title_zh}",
        f"【描述】{cut.social_desc_zh}",
        f"【标签】{cut.hashtags_zh}",
        "",
        "## English",
        f"[Title] {cut.viral_title_en}",
        f"[Description] {cut.social_desc_en}",
        f"[Hashtags] {cut.hashtags_en}",
        "",
    ])
    return "\n".join(lines)
