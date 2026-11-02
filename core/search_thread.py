"""智能检索编排线程 — 转写、打分、合并、导出全流程。"""

import os
import tempfile

from PyQt5.QtCore import QThread, pyqtSignal
from openai import OpenAI

from .llm_config import get_translation_config, load_llm_config
from .search_types import MatchContext
from .smart_search import (
    LLMUnavailableError, build_index, export_clip, export_ledger_key,
    export_report, extract_audio, is_already_exported, keyword_match,
    llm_match_sentences, load_cached_transcript, load_export_ledger,
    mark_exported, merge_hits, prefilter, probe_duration,
    save_cached_transcript, save_export_ledger, transcribe_audio,
    transcript_cache_key,
)


class SmartSearchThread(QThread):
    """在后台完成批量视频检索；所有异常都在线程内消化。"""

    log_msg = pyqtSignal(str)
    progress_changed = pyqtSignal(int)
    results_ready = pyqtSignal(list)
    error = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, scope_files, query, angles, codec, bitrate_mbps,
                 out_dir, *, min_dur=3.0, max_dur=120.0, merge_gap=2.0,
                 top_k=10, pad_before=0.5, pad_after=0.5, deep_mode=False,
                 force_export=False, batch_size=10, parent=None):
        super().__init__(parent)
        self.scope_files = list(scope_files)
        self.query = query
        self.angles = list(angles)
        self.codec = codec
        self.bitrate_mbps = bitrate_mbps
        self.out_dir = out_dir
        self.min_dur = min_dur
        self.max_dur = max_dur
        self.merge_gap = merge_gap
        self.top_k = top_k
        self.pad_before = pad_before
        self.pad_after = pad_after
        self.deep_mode = deep_mode
        self.force_export = force_export
        self.batch_size = batch_size
        self.running = True
        self._client = None
        self._model = ""
        self._whisper_model = None

    def stop(self) -> None:
        """请求停止；当前文件转写完成后不再开始下一个文件。"""
        self.running = False

    def _get_whisper_model(self):
        if self._whisper_model is None:
            import whisper
            self._whisper_model = whisper.load_model("turbo")
        return self._whisper_model

    def _resolve_llm(self):
        try:
            cfg = get_translation_config(load_llm_config())
            if not cfg.get("api_key"):
                return None, ""
            client = OpenAI(
                api_key=cfg["api_key"],
                base_url=cfg.get("base_url", ""),
            )
            return client, cfg.get("model", "")
        except Exception:
            return None, ""

    def run(self):
        results = []
        ledger = {}
        try:
            ledger = load_export_ledger()
            self._client, self._model = self._resolve_llm()
            context = MatchContext(query=self.query, angles=self.angles)
            total_files = max(1, len(self.scope_files))

            for file_pos, video in enumerate(self.scope_files):
                if not self.running:
                    break
                try:
                    results.extend(self._process_file(video, context, ledger))
                except Exception as exc:
                    self.log_msg.emit(f"⚠️ {video} 处理失败: {exc}")
                self.progress_changed.emit(
                    int((file_pos + 1) / total_files * 100)
                )
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            try:
                save_export_ledger(ledger)
            except Exception as exc:
                self.log_msg.emit(f"⚠️ 导出台账保存失败: {exc}")
            try:
                self.results_ready.emit(results)
            except Exception:
                pass
            try:
                export_report(results, self.out_dir, meta={
                    "query": self.query,
                    "angles": [angle.title for angle in self.angles],
                    "files": self.scope_files,
                })
            except Exception as exc:
                self.log_msg.emit(f"⚠️ 报告保存失败: {exc}")
            self.finished.emit()

    def _process_file(self, video, context, ledger):
        key = transcript_cache_key(video, "turbo")
        filekey8 = key[:8]
        cached = load_cached_transcript(key)

        if cached is not None:
            segments = cached.get("segments", [])
            duration = float(cached.get("duration", 0.0) or 0.0)
            if duration <= 0:
                duration = probe_duration(video)
            self.log_msg.emit(f"♻️ 命中转写缓存: {os.path.basename(video)}")
        else:
            duration = probe_duration(video)
            with tempfile.TemporaryDirectory(prefix="smart_search_") as tmp:
                wav_path = os.path.join(tmp, "audio.wav")
                extract_audio(video, wav_path, self.log_msg.emit)
                data = transcribe_audio(
                    wav_path,
                    model=self._get_whisper_model(),
                    model_name="turbo",
                    log_cb=self.log_msg.emit,
                )
            segments = data.get("segments", [])
            save_cached_transcript(key, {
                "source_file": video,
                "language": data.get("language", ""),
                "duration": duration,
                "segments": segments,
            })
            self.log_msg.emit(
                f"🎙️ 转写完成: {os.path.basename(video)} ({len(segments)} 句)"
            )

        index = build_index(segments, video, filekey8, duration)
        if self.deep_mode:
            candidates = list(range(len(segments)))
        else:
            candidates = prefilter(context, index)
        sentences = [segments[i].get("text", "") for i in candidates]

        if self._client and sentences:
            try:
                hits = llm_match_sentences(
                    context, sentences, candidates,
                    self._client, self._model, self.batch_size,
                    log_cb=self.log_msg.emit,
                )
            except LLMUnavailableError as exc:
                self.log_msg.emit(f"⚠️ LLM 不可用，降级为关键词匹配: {exc}")
                hits = keyword_match(context, index)
        else:
            hits = keyword_match(context, index)

        clips = merge_hits(
            hits, segments,
            min_gap=self.merge_gap,
            pad_before=self.pad_before,
            pad_after=self.pad_after,
            min_dur=self.min_dur,
            max_dur=self.max_dur,
            top_k=self.top_k,
            source_file=video,
            filekey8=filekey8,
            duration=duration,
        )

        for idx, clip in enumerate(clips):
            if not self.force_export and is_already_exported(clip, ledger):
                clip.already_exported = True
                entry = ledger.get(export_ledger_key(clip), {})
                clip.clip_path = entry.get("path", "")
                continue
            clip.clip_path = export_clip(
                clip, video, self.out_dir, self.codec,
                self.bitrate_mbps, idx=idx,
            )
            mark_exported(clip, clip.clip_path, ledger)

        return clips
