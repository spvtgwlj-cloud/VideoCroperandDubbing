"""建议脚本纯逻辑 — prompt、解析、素材映射、Markdown、落盘（零 Qt 依赖）。"""

import json
import os
import re
from dataclasses import asdict, dataclass, field

from .search_types import TrendAngle


@dataclass
class ScriptSection:
    """脚本中的一个分段。"""

    name: str
    narration: str
    source_segment_ids: list[int] = field(default_factory=list)
    source_time: str = ""
    visual_note: str = ""


@dataclass
class SuggestedScript:
    """一次建议脚本生成的完整结果。"""

    title: str
    hook: str
    sections: list[ScriptSection]
    cta: str = ""
    why: str = ""
    target_duration: str = "30-60秒"
    source_file: str = ""
    angles: list[str] = field(default_factory=list)


def build_script_prompt(segments: list[dict], angles: list[TrendAngle],
                        query: str = "", max_segments: int = 200) -> str:
    """构造建议脚本 prompt；只允许 LLM 引用真实转写句子编号。"""
    lines = [
        "你是短视频编导。根据视频转写和最新热点角度，"
        "写一条可以直接照着拍/剪的短视频脚本。",
        "",
        "要求：",
        "- 输出中文；引用原片台词时保留原话。",
        "- 总时长 30-60 秒，3-5 个分段。",
        "- 每个分段必须包含 name、narration（口播）、"
        "source_segment_ids（只能引用下方转写句子编号，可为空）、"
        "visual_note（用哪段画面；没有合适素材时写“需补拍：...”）。",
        "- 如果视频内容与热点关联较弱，明确说明借势角度，"
        "不要编造视频里没有的事实。",
        "- 只返回 JSON，不要代码块或解释。",
        "",
        "JSON 格式：",
        '{"title":"...","hook":"3秒钩子","target_duration":"30-60秒",'
        '"sections":[{"name":"...","narration":"...",'
        '"source_segment_ids":[0,1],"visual_note":"..."}],'
        '"cta":"...","why":"..."}',
        "",
        f"创作方向: {query or '（无，按热点角度自由发挥）'}",
        "热点角度:",
    ]
    if angles:
        for angle in angles[:8]:
            keywords = ", ".join(angle.keywords)
            lines.append(
                f"- {angle.title} | 关键词: {keywords} | 理由: {angle.why}"
            )
    else:
        lines.append("- （无热点角度，请优先依据视频内容）")

    lines.append("")
    lines.append("视频转写:")
    for index, segment in enumerate(segments[:max_segments]):
        try:
            start = float(segment.get("start", 0.0))
            end = float(segment.get("end", 0.0))
        except (TypeError, ValueError):
            start = end = 0.0
        lines.append(
            f"[{index}] {start:.1f}-{end:.1f} {segment.get('text', '')}"
        )
    if len(segments) > max_segments:
        lines.append(f"（仅显示前 {max_segments} 句）")
    return "\n".join(lines)


def _strip_code_fence(raw: str) -> str:
    text = (raw or "").strip()
    text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _coerce_int(value) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    return None


def _resolve_segment_time(ids: list[int], segments: list[dict]) -> str:
    """把句子编号映射为时间范围；越界编号已被过滤。"""
    valid = [segments[index] for index in ids if 0 <= index < len(segments)]
    if not valid:
        return ""
    try:
        start = min(float(segment.get("start", 0.0)) for segment in valid)
        end = max(float(segment.get("end", 0.0)) for segment in valid)
    except (TypeError, ValueError):
        return ""
    return f"{start:.1f}s-{end:.1f}s"


def parse_script_response(raw: str, segments: list[dict]) -> SuggestedScript:
    """解析 LLM 返回的脚本 JSON，过滤虚构的句子编号。"""
    try:
        data = json.loads(_strip_code_fence(raw))
    except ValueError as exc:
        raise ValueError(f"脚本不是合法 JSON: {exc}") from exc
    if isinstance(data, dict):
        data = data.get("script") or data.get("result") or data
    if not isinstance(data, dict):
        raise ValueError("脚本 JSON 不是对象")

    title = str(data.get("title", "")).strip()
    hook = str(data.get("hook", "")).strip()
    if not title:
        raise ValueError("脚本缺少 title")
    if not hook:
        raise ValueError("脚本缺少 hook")

    raw_sections = data.get("sections")
    if not isinstance(raw_sections, list) or not raw_sections:
        raise ValueError("脚本缺少 sections")

    sections: list[ScriptSection] = []
    for index, entry in enumerate(raw_sections):
        if not isinstance(entry, dict):
            continue
        narration = str(entry.get("narration", "")).strip()
        if not narration:
            continue

        ids: list[int] = []
        raw_ids = entry.get("source_segment_ids", [])
        if isinstance(raw_ids, list):
            for value in raw_ids:
                number = _coerce_int(value)
                if (number is not None
                        and 0 <= number < len(segments)
                        and number not in ids):
                    ids.append(number)

        name = str(entry.get("name", "")).strip() or f"分段{index + 1}"
        visual_note = str(entry.get("visual_note", "")).strip()
        if not ids and not visual_note:
            visual_note = "需补拍：需要补充与该段口播匹配的画面"
        sections.append(ScriptSection(
            name=name,
            narration=narration,
            source_segment_ids=ids,
            source_time=_resolve_segment_time(ids, segments),
            visual_note=visual_note,
        ))

    if not sections:
        raise ValueError("脚本没有有效分段")
    return SuggestedScript(
        title=title,
        hook=hook,
        sections=sections,
        cta=str(data.get("cta", "")).strip(),
        why=str(data.get("why", "")).strip(),
        target_duration=(
            str(data.get("target_duration", "")).strip() or "30-60秒"
        ),
    )


def render_script_markdown(script: SuggestedScript) -> str:
    """把脚本渲染成可直接阅读/复制的 Markdown。"""
    lines = [
        f"# {script.title}",
        "",
        f"**3 秒钩子**：{script.hook}",
        "",
        f"**目标时长**：{script.target_duration}",
        "",
    ]
    if script.angles:
        lines.append(f"**关联热点**：{'、'.join(script.angles)}")
        lines.append("")
    lines.append("## 分段脚本")
    for index, section in enumerate(script.sections, start=1):
        lines.append(f"### {index}. {section.name}")
        lines.append(f"- 口播：{section.narration}")
        lines.append(f"- 素材：{section.source_time or '需补拍'}")
        if section.visual_note:
            lines.append(f"- 画面：{section.visual_note}")
        lines.append("")
    if script.cta:
        lines.append("## CTA")
        lines.append(script.cta)
        lines.append("")
    if script.why:
        lines.append("## 选题理由")
        lines.append(script.why)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def save_script(script: SuggestedScript, out_dir: str) -> tuple[str, str]:
    """保存 suggested_script.json 与 suggested_script.md，返回两个路径。"""
    os.makedirs(out_dir, exist_ok=True)
    json_path = os.path.join(out_dir, "suggested_script.json")
    md_path = os.path.join(out_dir, "suggested_script.md")
    with open(json_path, "w", encoding="utf-8") as file:
        json.dump(asdict(script), file, ensure_ascii=False, indent=2)
    with open(md_path, "w", encoding="utf-8") as file:
        file.write(render_script_markdown(script))
    return json_path, md_path
