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
                 out_dir, *, min_dur=30.0, max_dur=120.0, merge_gap=2.0,
                 top_k=3, pad_before=0.5, pad_after=0.5, deep_mode=False,
                 force_export=False, allow_relaxed_fallback=False,
                 batch_size=10, parent=None):
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
        self.allow_relaxed_fallback = allow_relaxed_fallback
        self.batch_size = batch_size
        self.running = True
        self._client = None
        self._model = ""
        self._whisper_model = None
        self._llm_enabled = False
        self._hit_count = 0
        self._relaxed_fallback_used = False
        self._file_stats: list[dict] = []
        self._zero_reason = ""

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

    def _file_progress(self, file_pos: int, total_files: int):
        base = file_pos / max(1, total_files) * 100.0
        span = 100.0 / max(1, total_files)

        def emit(local: float) -> None:
            local = max(0.0, min(1.0, local))
            self.progress_changed.emit(int(base + span * local))

        return emit

    def run(self):
        results = []
        ledger = {}
        self._file_stats = []
        self._zero_reason = ""
        try:
            ledger = load_export_ledger()
            self._client, self._model = self._resolve_llm()
            self._llm_enabled = self._client is not None
            context = MatchContext(query=self.query, angles=self.angles)
            total_files = max(1, len(self.scope_files))

            for file_pos, video in enumerate(self.scope_files):
                if not self.running:
                    break
                emit_progress = self._file_progress(file_pos, total_files)
                try:
                    clips, file_stat = self._process_file(
                        video, context, ledger, emit_progress,
                    )
                    self._file_stats.append(file_stat)
                    results.extend(clips)
                except Exception as exc:
                    self._file_stats.append({
                        "file": video,
                        "error": str(exc),
                        "clips": 0,
                        "llm_hits": 0,
                        "zero_reason": "file_error",
                    })
                    if not self.running:
                        self.log_msg.emit(
                            f"⏹️ 已停止: {os.path.basename(video)}"
                        )
                    else:
                        self.log_msg.emit(f"⚠️ {video} 处理失败: {exc}")
                emit_progress(1.0)
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
                    "deep_mode": self.deep_mode,
                    "llm_enabled": self._llm_enabled,
                    "stats": {
                        "hits": self._hit_count,
                        "clips": len(results),
                        "relaxed_fallback_used": self._relaxed_fallback_used,
                        "relaxed_enabled": self.allow_relaxed_fallback,
                        "zero_reason": "" if results else self._zero_reason,
                    },
                    "file_stats": self._file_stats,
                    "message": "" if results else self._build_empty_message(),
                })
            except Exception as exc:
                self.log_msg.emit(f"⚠️ 报告保存失败: {exc}")
            self.finished.emit()

    def _build_empty_message(self) -> str:
        """根据每个文件的诊断结果给出可执行的空结果说明。"""
        reasons = {
            stat.get("zero_reason")
            for stat in self._file_stats
            if stat.get("zero_reason")
        }
        if "llm_unavailable" in reasons:
            return (
                "LLM 调用失败，已降级关键词匹配；请检查 API 配置/网络，"
                "或勾选『无强匹配时输出弱相关片段』后重试。"
            )
        if "llm_parse_error" in reasons:
            return "LLM 返回格式异常，未能解析出有效结果；请重试或更换模型。"
        if "llm_partial_parse_error" in reasons:
            return "LLM 部分批次返回格式异常，未能完成全部评估；请重试或更换模型。"
        if "llm_no_relevant" in reasons:
            return (
                "LLM 已完整评估转写句子，判定无足够相关片段；"
                "可调整提示词/热点角度，或勾选"
                "『无强匹配时输出弱相关片段』后重试。"
            )
        if "no_segments" in reasons:
            return "视频未转写出可用句子；请确认视频包含清晰人声。"
        if "keyword_no_match" in reasons:
            return (
                "关键词匹配未命中；可调整提示词，"
                "或勾选『无强匹配时输出弱相关片段』后重试。"
            )
        if "file_error" in reasons:
            return "部分视频处理失败；请查看日志中的具体错误。"
        return "未找到匹配片段。"

    def _process_file(self, video, context, ledger, progress_cb):
        file_stat = {
            "file": video,
            "segments": 0,
            "candidates": 0,
            "llm_attempted": False,
            "llm_ok": False,
            "llm_hits": 0,
            "llm_transport_errors": 0,
            "llm_parse_errors": 0,
            "keyword_strict_hits": 0,
            "keyword_relaxed_hits": 0,
            "clips": 0,
            "zero_reason": "",
        }
        progress_cb(0.02)
        key = transcript_cache_key(video, "turbo")
        filekey8 = key[:8]
        cached = load_cached_transcript(key)

        if cached is not None:
            segments = cached.get("segments", [])
            duration = float(cached.get("duration", 0.0) or 0.0)
            if duration <= 0:
                duration = probe_duration(video)
            self.log_msg.emit(
                f"♻️ 命中转写缓存（跳过音频提取/Whisper 转写）: "
                f"{os.path.basename(video)}"
            )
            progress_cb(0.15)
        else:
            duration = probe_duration(video)
            progress_cb(0.05)
            with tempfile.TemporaryDirectory(prefix="smart_search_") as tmp:
                wav_path = os.path.join(tmp, "audio.wav")
                extract_audio(
                    video, wav_path, self.log_msg.emit,
                    should_stop=lambda: not self.running,
                )
                progress_cb(0.15)
                self.log_msg.emit(
                    f"🎙️ 正在转写（Whisper turbo，可能较慢）: "
                    f"{os.path.basename(video)}"
                )
                progress_cb(0.20)
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
            progress_cb(0.45)

        file_stat["segments"] = len(segments)
        if not segments:
            file_stat["zero_reason"] = "no_segments"
            self.log_msg.emit("⚠️ 视频未转写出可用句子，跳过")
            return [], file_stat
        if not self.running:
            return [], file_stat

        index = build_index(segments, video, filekey8, duration)
        if self.deep_mode:
            candidates = list(range(len(segments)))
        else:
            candidates = prefilter(context, index)
        file_stat["candidates"] = len(candidates)
        sentences = [segments[i].get("text", "") for i in candidates]
        progress_cb(0.50)

        llm_diagnostics = {
            "transport_errors": 0, "parse_errors": 0, "batches_ok": 0,
        }
        llm_attempted = bool(self._client and sentences)
        used_llm = llm_attempted
        llm_ok = False
        file_stat["llm_attempted"] = llm_attempted
        if used_llm:
            self.log_msg.emit(
                f"🧠 LLM 打分 {len(sentences)} 句"
                f"{'（深度模式）' if self.deep_mode else ''}..."
            )
            try:
                hits = llm_match_sentences(
                    context, sentences, candidates,
                    self._client, self._model, self.batch_size,
                    log_cb=self.log_msg.emit,
                    progress_cb=lambda fraction: progress_cb(
                        0.50 + 0.35 * fraction
                    ),
                    should_stop=lambda: not self.running,
                    diagnostics=llm_diagnostics,
                )
                llm_ok = True
            except LLMUnavailableError as exc:
                self.log_msg.emit(f"⚠️ LLM 不可用，降级为关键词匹配: {exc}")
                used_llm = False
                hits = keyword_match(context, index)
                file_stat["keyword_strict_hits"] = len(hits)
        else:
            self.log_msg.emit("🧠 使用关键词匹配...")
            hits = keyword_match(context, index)
            file_stat["keyword_strict_hits"] = len(hits)

        file_stat["llm_ok"] = llm_ok
        file_stat["llm_hits"] = len(hits) if llm_ok else 0
        file_stat["llm_transport_errors"] = llm_diagnostics["transport_errors"]
        file_stat["llm_parse_errors"] = llm_diagnostics["parse_errors"]
        if llm_attempted and llm_ok:
            self.log_msg.emit(
                f"🧠 LLM 完成：评估 {len(sentences)} 句，"
                f"命中 {file_stat['llm_hits']} 句"
            )
            if llm_diagnostics["parse_errors"]:
                self.log_msg.emit(
                    f"⚠️ LLM 有 {llm_diagnostics['parse_errors']} 批"
                    "返回格式异常"
                )

        # 弱相关兜底必须由用户显式开启，默认不输出噪声片段。
        if not hits and self.allow_relaxed_fallback:
            relaxed_hits = keyword_match(context, index, min_score=0.0)
            file_stat["keyword_relaxed_hits"] = len(relaxed_hits)
            if relaxed_hits:
                hits = relaxed_hits
                self._relaxed_fallback_used = True
                self.log_msg.emit(
                    "⚠️ 未找到强匹配，已输出弱相关片段"
                    "（可能包含较弱片段，请人工复核）"
                )

        if not hits:
            if llm_attempted and not llm_ok:
                zero_reason = "llm_unavailable"
            elif llm_attempted and llm_ok and llm_diagnostics["parse_errors"]:
                zero_reason = (
                    "llm_parse_error"
                    if not llm_diagnostics["batches_ok"]
                    else "llm_partial_parse_error"
                )
            elif llm_attempted and llm_ok:
                zero_reason = "llm_no_relevant"
            else:
                zero_reason = "keyword_no_match"
            file_stat["zero_reason"] = zero_reason
            self._zero_reason = self._zero_reason or zero_reason
            if zero_reason == "llm_no_relevant":
                self.log_msg.emit(
                    f"ℹ️ LLM 已评估 {len(sentences)} 句，"
                    "判定无足够相关片段（调用正常）；"
                    "如需弱相关片段请勾选『无强匹配时输出弱相关片段』"
                )
            elif zero_reason == "llm_parse_error":
                self.log_msg.emit(
                    "⚠️ LLM 返回格式异常，未能解析出有效结果"
                )
            elif zero_reason == "llm_partial_parse_error":
                self.log_msg.emit(
                    "⚠️ LLM 部分批次返回格式异常，未能完成全部评估"
                )
            elif zero_reason == "llm_unavailable":
                self.log_msg.emit(
                    "⚠️ LLM 调用失败，关键词匹配也未命中"
                )
            elif zero_reason == "keyword_no_match":
                self.log_msg.emit(
                    "ℹ️ 关键词匹配未命中；"
                    "如需弱相关片段请勾选『无强匹配时输出弱相关片段』"
                )
            if self.allow_relaxed_fallback:
                self.log_msg.emit(
                    "⚠️ 已启用弱相关兜底，但仍未命中任何关键词"
                )

        self._hit_count += len(hits)
        progress_cb(0.85)
        if not self.running:
            return [], file_stat

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
        file_stat["clips"] = len(clips)
        progress_cb(0.88)

        total_clips = max(1, len(clips))
        for idx, clip in enumerate(clips):
            if not self.running:
                break
            self.log_msg.emit(f"📦 导出片段 {idx + 1}/{total_clips}...")
            progress_cb(0.90 + 0.10 * idx / total_clips)
            if not self.force_export and is_already_exported(clip, ledger):
                clip.already_exported = True
                entry = ledger.get(export_ledger_key(clip), {})
                clip.clip_path = entry.get("path", "")
                continue
            try:
                clip.clip_path = export_clip(
                    clip, video, self.out_dir, self.codec,
                    self.bitrate_mbps, idx=idx,
                    should_stop=lambda: not self.running,
                )
                mark_exported(clip, clip.clip_path, ledger)
            except Exception as exc:
                clip.clip_path = ""
                self.log_msg.emit(
                    f"⚠️ 片段导出失败 "
                    f"{clip.start:.1f}-{clip.end:.1f}s: {exc}"
                )

        progress_cb(1.0)
        return clips, file_stat
