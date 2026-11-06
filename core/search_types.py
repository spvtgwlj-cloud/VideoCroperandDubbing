"""智能检索共享数据类（零依赖，供 core 内多个纯逻辑模块复用）。"""

from dataclasses import dataclass, field


@dataclass
class TrendAngle:
    """一个爆点角度，用于构建检索上下文。"""

    title: str
    keywords: list[str]
    why: str
    source_ids: list[str] = field(default_factory=list)
    heat: float = 0.0        # 同来源归一化热度（0-1），仅用于排序微调
    heat_raw: int = 0        # 原始热度，用于展示
    heat_source: str = ""    # "hn" | "v2ex"


@dataclass
class Hotspot:
    """一条原始热点。"""

    source: str
    title: str
    url: str
    score: int = 0
    comments: int = 0
    keywords: list[str] = field(default_factory=list)
    heat: float = 0.0        # 同来源归一化热度（0-1）


@dataclass
class SearchIndex:
    """单个视频的转写索引。"""

    source_file: str
    filekey8: str
    duration: float
    segments: list[dict]


@dataclass
class Hit:
    """命中的一句转写。"""

    index: int
    score: float
    reason: str = ""
    angles: list[str] = field(default_factory=list)
    heat: float = 0.0
    heat_raw: int = 0
    heat_source: str = ""


@dataclass
class Clip:
    """合并后的待导出片段。"""

    source_file: str
    filekey8: str
    start: float
    end: float
    matched_sentences: list[str]
    score: float
    reason: str
    angles: list[str]
    clip_path: str = ""
    already_exported: bool = False
    content_score: float = 0.0
    heat: float = 0.0
    heat_raw: int = 0
    heat_source: str = ""


@dataclass
class MatchContext:
    """一次检索的用户意图上下文。"""

    query: str
    angles: list[TrendAngle]
