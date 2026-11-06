"""热点异步抓取/归纳线程。"""

from PyQt5.QtCore import QThread, pyqtSignal
from openai import OpenAI

from .llm_config import get_translation_config, load_llm_config
from .trend_sources import fallback_angles, fetch_hotspots, summarize_hotspots


class TrendFetchThread(QThread):
    """在后台抓取热点，并可选地用 LLM 归纳爆点角度。"""

    done = pyqtSignal(list)
    angles_ready = pyqtSignal(list)
    failed = pyqtSignal(str)

    def __init__(self, sources=("hn", "v2ex"), limit=20, force_refresh=False,
                 summarize=False, max_angles=8, parent=None):
        super().__init__(parent)
        self.sources = sources
        self.limit = limit
        self.force_refresh = force_refresh
        self.summarize = summarize
        self.max_angles = max_angles

    def run(self):
        try:
            items = fetch_hotspots(
                sources=self.sources,
                limit=self.limit,
                force_refresh=self.force_refresh,
            )
            self.done.emit(items)
            if self.summarize:
                self.angles_ready.emit(self._build_angles(items))
        except Exception as exc:
            self.failed.emit(str(exc))

    def _build_angles(self, items):
        """有可用 LLM 时归纳角度，否则退回原始标题。"""
        try:
            cfg = get_translation_config(load_llm_config())
            if cfg.get("api_key"):
                client = OpenAI(
                    api_key=cfg["api_key"],
                    base_url=cfg.get("base_url", ""),
                )
                return summarize_hotspots(
                    items, client, cfg.get("model", ""), self.max_angles,
                )
        except Exception:
            pass
        return fallback_angles(items, self.max_angles)
