"""建议脚本编排线程 — 转写、热点、LLM 生成、落盘。"""

import os
import tempfile

from PyQt5.QtCore import QThread, pyqtSignal
from openai import OpenAI

from .llm_config import get_translation_config, load_llm_config
from .script_suggest import (
    build_script_prompt, parse_script_response, save_script,
)
from .smart_search import (
    extract_audio, load_cached_transcript, probe_duration,
    save_cached_transcript, transcribe_audio, transcript_cache_key,
)
from .trend_sources import fetch_hotspots, summarize_hotspots

SCRIPT_LLM_TIMEOUT_SECONDS = 120
SCRIPT_LLM_MAX_TOKENS = 1800


class ScriptSuggestionThread(QThread):
    """在后台生成一条可直接照着拍/剪的短视频脚本。"""

    log_msg = pyqtSignal(str)
    progress_changed = pyqtSignal(int)
    script_ready = pyqtSignal(object, str, str)
    error = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, video_path, angles, query, out_dir, parent=None):
        super().__init__(parent)
        self.video_path = video_path
        self.angles = list(angles)
        self.query = query
        self.out_dir = out_dir
        self.running = True
        self._whisper_model = None

    def stop(self) -> None:
        """请求停止；转写阶段无法中途打断。"""
        self.running = False

    def _get_whisper_model(self):
        if self._whisper_model is None:
            import whisper
            self._whisper_model = whisper.load_model("turbo")
        return self._whisper_model

    def _resolve_llm(self):
        cfg = get_translation_config(load_llm_config())
        if not cfg.get("api_key"):
            raise RuntimeError(
                "未配置 LLM API Key，请先在『AI 大模型设置』中配置",
            )
        client = OpenAI(
            api_key=cfg["api_key"],
            base_url=cfg.get("base_url", ""),
            max_retries=0,
        )
        return client, cfg.get("model", "")

    def _load_segments(self) -> list[dict]:
        key = transcript_cache_key(self.video_path, "turbo")
        cached = load_cached_transcript(key)
        if cached is not None:
            self.log_msg.emit(
                f"♻️ 命中转写缓存: {os.path.basename(self.video_path)}",
            )
            return cached.get("segments", [])

        duration = probe_duration(self.video_path)
        with tempfile.TemporaryDirectory(prefix="script_suggest_") as tmp:
            wav_path = os.path.join(tmp, "audio.wav")
            extract_audio(
                self.video_path, wav_path, self.log_msg.emit,
                should_stop=lambda: not self.running,
            )
            self.log_msg.emit("🎙️ 正在转写（Whisper turbo，可能较慢）...")
            data = transcribe_audio(
                wav_path,
                model=self._get_whisper_model(),
                model_name="turbo",
                log_cb=self.log_msg.emit,
            )
        segments = data.get("segments", [])
        save_cached_transcript(key, {
            "source_file": self.video_path,
            "language": data.get("language", ""),
            "duration": duration,
            "segments": segments,
        })
        return segments

    def _ensure_angles(self, client, model) -> list:
        if self.angles:
            return self.angles
        self.log_msg.emit("🔥 未提供热点角度，自动抓取 HN/V2EX...")
        try:
            items = fetch_hotspots(force_refresh=True)
        except Exception as exc:
            self.log_msg.emit(
                f"⚠️ 热点抓取失败，将仅依据视频内容生成: {exc}",
            )
            return []
        if not items:
            self.log_msg.emit("⚠️ 没有抓到热点，将仅依据视频内容生成")
            return []
        angles = summarize_hotspots(items, client, model, max_angles=8)
        titles = " / ".join(angle.title for angle in angles[:3])
        if titles:
            self.log_msg.emit(f"🔥 使用热点角度: {titles}")
        return angles

    def _call_llm(self, client, model: str, prompt: str) -> str:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.6,
            timeout=SCRIPT_LLM_TIMEOUT_SECONDS,
            max_tokens=SCRIPT_LLM_MAX_TOKENS,
        )
        return response.choices[0].message.content or ""

    def run(self):
        try:
            self.progress_changed.emit(5)
            client, model = self._resolve_llm()

            self.log_msg.emit("📄 读取视频转写...")
            segments = self._load_segments()
            if not segments:
                raise RuntimeError(
                    "视频未转写出可用句子；请确认视频包含清晰人声",
                )
            if not self.running:
                return
            self.progress_changed.emit(45)

            angles = self._ensure_angles(client, model)
            if not self.running:
                return
            self.progress_changed.emit(65)

            prompt = build_script_prompt(segments, angles, self.query)
            self.log_msg.emit("🧠 正在生成建议脚本（可能需要 1-2 分钟）...")
            raw = self._call_llm(client, model, prompt)
            try:
                script = parse_script_response(raw, segments)
            except ValueError as exc:
                self.log_msg.emit(f"⚠️ 脚本 JSON 解析失败，重试一次: {exc}")
                raw = self._call_llm(
                    client, model,
                    prompt + "\n\n只返回 JSON，不要代码块或解释。",
                )
                script = parse_script_response(raw, segments)

            script.source_file = self.video_path
            script.angles = [angle.title for angle in angles]
            json_path, md_path = save_script(script, self.out_dir)
            self.log_msg.emit(f"✅ 建议脚本已保存: {md_path}")
            self.progress_changed.emit(100)
            self.script_ready.emit(script, json_path, md_path)
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            self.finished.emit()
