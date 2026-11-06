"""智能切片编排线程：整段语义分析、双语字幕、竖屏成片导出。"""

import json
import os
import re
import subprocess
import tempfile
from dataclasses import asdict

from PyQt5.QtCore import QThread, pyqtSignal
from openai import APITimeoutError, OpenAI

from .clip_renderer import render_clip
from .llm_config import get_translation_config, load_llm_config
from .semantic_clip import (
    DEFAULT_MAX_CUTS, DEFAULT_MAX_DUR, DEFAULT_MIN_DUR, build_cut_prompt,
    parse_cut_response, render_social_copy, slice_transcript,
)
from .smart_search import (
    extract_audio, load_cached_transcript, probe_duration,
    save_cached_transcript, transcribe_audio, transcript_cache_key,
)
from .trend_sources import fetch_hotspots, summarize_hotspots

LLM_TIMEOUT_SECONDS = 120
TRANSLATE_TIMEOUT_SECONDS = 120
LLM_MAX_TOKENS = 2500
TRANSLATE_BATCH_SIZE = 5


class SemanticClipThread(QThread):
    """在后台完成整段视频语义切片并导出竖屏成片。"""

    log_msg = pyqtSignal(str)
    progress_changed = pyqtSignal(int)
    results_ready = pyqtSignal(list)
    error = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, video_path, query, angles, out_dir, *,
                 min_dur: float = DEFAULT_MIN_DUR,
                 max_dur: float = DEFAULT_MAX_DUR,
                 top_k: int = DEFAULT_MAX_CUTS,
                 output_w: int = 1080, output_h: int = 1920,
                 bitrate_mbps: int = 4, parent=None):
        super().__init__(parent)
        self.video_path = video_path
        self.query = query
        self.angles = list(angles)
        self._used_angles = list(angles)
        self.out_dir = out_dir
        self.min_dur = min_dur
        self.max_dur = max_dur
        self.top_k = top_k
        self.output_w = output_w
        self.output_h = output_h
        self.bitrate_mbps = bitrate_mbps
        self.running = True
        self._whisper_model = None
        self._face_app = None

    def stop(self) -> None:
        """请求停止；转写阶段无法中途打断。"""
        self.running = False

    def _get_whisper_model(self):
        if self._whisper_model is None:
            import whisper
            self._whisper_model = whisper.load_model("turbo")
        return self._whisper_model

    def _get_face_app(self):
        if self._face_app is None:
            from insightface.app import FaceAnalysis
            app = FaceAnalysis(
                name="buffalo_l",
                providers=[
                    "CoreMLExecutionProvider", "CPUExecutionProvider",
                ],
            )
            app.prepare(ctx_id=-1, det_size=(640, 640))
            self._face_app = app
        return self._face_app

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

    def _load_segments(self) -> tuple[list[dict], float]:
        key = transcript_cache_key(self.video_path, "turbo")
        cached = load_cached_transcript(key)
        if cached is not None:
            self.log_msg.emit(
                f"♻️ 命中转写缓存: {os.path.basename(self.video_path)}",
            )
            return (
                cached.get("segments", []),
                float(cached.get("duration", 0.0) or 0.0),
            )

        duration = probe_duration(self.video_path)
        with tempfile.TemporaryDirectory(prefix="semantic_clip_") as tmp:
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
        return segments, duration

    def _ensure_angles(self, client, model) -> list:
        if self.angles:
            return self.angles
        self.log_msg.emit("🔥 未提供热点角度，自动抓取 HN/V2EX...")
        try:
            items = fetch_hotspots(force_refresh=True)
        except Exception as exc:
            self.log_msg.emit(f"⚠️ 热点抓取失败，将仅依据视频内容: {exc}")
            return []
        if not items:
            self.log_msg.emit("⚠️ 没有抓到热点，将仅依据视频内容")
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
            temperature=0.7,
            timeout=LLM_TIMEOUT_SECONDS,
            max_tokens=LLM_MAX_TOKENS,
            stream=True,
        )
        if not hasattr(response, "__iter__"):
            return response.choices[0].message.content or ""
        parts: list[str] = []
        for chunk in response:
            choices = getattr(chunk, "choices", None)
            if not choices:
                continue
            delta = getattr(choices[0], "delta", None)
            content = getattr(delta, "content", None) if delta else None
            if isinstance(content, str) and content:
                parts.append(content)
        return "".join(parts)

    def _call_translate(self, client, model: str, prompt: str) -> str:
        """流式翻译，避免整段响应超时。"""
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            timeout=TRANSLATE_TIMEOUT_SECONDS,
            max_tokens=1200,
            stream=True,
        )
        if not hasattr(response, "__iter__"):
            return response.choices[0].message.content or ""
        parts: list[str] = []
        for chunk in response:
            choices = getattr(chunk, "choices", None)
            if not choices:
                continue
            delta = getattr(choices[0], "delta", None)
            content = getattr(delta, "content", None) if delta else None
            if isinstance(content, str) and content:
                parts.append(content)
        return "".join(parts)

    def _plan_cuts(self, client, model: str, segments: list[dict],
                   angles: list, duration: float) -> list:
        prompt = build_cut_prompt(
            segments, angles, self.query, self.min_dur, self.max_dur,
            self.top_k,
        )
        self.log_msg.emit("🧠 正在进行整段语义切片分析（可能需要 1-2 分钟）...")
        try:
            raw = self._call_llm(client, model, prompt)
        except (APITimeoutError, TimeoutError) as exc:
            short_segments = segments[: max(1, len(segments) // 2)]
            self.log_msg.emit(
                f"⚠️ 切片分析超时，改用前 {len(short_segments)} 句重试一次...",
            )
            short_prompt = build_cut_prompt(
                short_segments, angles, self.query, self.min_dur,
                self.max_dur, self.top_k,
            )
            try:
                raw = self._call_llm(client, model, short_prompt)
            except (APITimeoutError, TimeoutError) as retry_exc:
                raise RuntimeError(
                    "切片分析超时：缩短转写后仍超时，"
                    "请稍后重试或更换更快的模型。",
                ) from retry_exc
        try:
            return parse_cut_response(
                raw, duration, self.min_dur, self.max_dur,
                self.top_k, angles,
            )
        except ValueError as exc:
            self.log_msg.emit(f"⚠️ 切片 JSON 解析失败，重试一次: {exc}")
            raw = self._call_llm(
                client, model,
                prompt + "\n\n只返回 JSON，不要代码块或解释。",
            )
            return parse_cut_response(
                raw, duration, self.min_dur, self.max_dur,
                self.top_k, angles,
            )

    def _translate_bilingual(self, segments: list[dict], client,
                             model: str) -> None:
        """为每条转写补充 text_zh / text_en，原地修改。"""
        total = len(segments)
        if total == 0:
            return
        self.log_msg.emit(f"🌐 正在生成中英双语字幕（共 {total} 句）...")
        for batch_start in range(0, total, TRANSLATE_BATCH_SIZE):
            if not self.running:
                return
            batch = segments[
                batch_start:batch_start + TRANSLATE_BATCH_SIZE
            ]
            source_lines = []
            for offset, segment in enumerate(batch):
                line_id = batch_start + offset
                text = str(segment.get("text", "")).strip()
                source_lines.append(f'<line id="{line_id}">{text}</line>')
            prompt = (
                "你是严谨的翻译。请为每一行生成中文和英文，"
                "原文是中文就保留中文并翻译成英文，"
                "原文是英文就保留英文并翻译成中文。"
                "必须保留 <line id=\"数字\"> 标签，只输出：\n"
                "<line id=\"0\"><zh>中文</zh><en>English</en></line>\n\n"
                "原文：\n" + "\n".join(source_lines)
            )
            parsed: dict[int, tuple[str, str]] = {}
            for attempt in range(3):
                try:
                    raw = self._call_translate(client, model, prompt)
                    for line_id, zh, en in re.findall(
                        r'<line id="(\d+)">\s*<zh>([\s\S]*?)</zh>'
                        r'\s*<en>([\s\S]*?)</en>\s*</line>',
                        raw,
                    ):
                        parsed[int(line_id)] = (zh.strip(), en.strip())
                    if len(parsed) >= len(batch):
                        break
                except Exception as exc:
                    if attempt == 2:
                        self.log_msg.emit(f"⚠️ 双语翻译失败: {exc}")
            for offset, segment in enumerate(batch):
                line_id = batch_start + offset
                zh, en = parsed.get(
                    line_id, (segment.get("text", ""), ""),
                )
                segment["text_zh"] = zh or segment.get("text", "")
                segment["text_en"] = en
            self.log_msg.emit(
                f"🌐 双语字幕 {min(batch_start + len(batch), total)}/{total}",
            )

    def _cut_video(self, start: float, end: float, out_path: str) -> None:
        duration = max(0.1, end - start)
        cmd = [
            "ffmpeg", "-y",
            "-ss", f"{start:.3f}",
            "-t", f"{duration:.3f}",
            "-i", self.video_path,
            "-vf", "fps=30",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "192k",
            out_path,
        ]
        result = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr or "切片失败")

    @staticmethod
    def _safe_name(text: str, index: int) -> str:
        cleaned = re.sub(r'[\\/:*?"<>|\s]+', "_", text).strip("_")
        return (cleaned or f"clip_{index + 1}")[:40]

    def run(self):
        results = []
        try:
            client, model = self._resolve_llm()
            self.progress_changed.emit(5)

            self.log_msg.emit("📄 读取视频转写...")
            segments, duration = self._load_segments()
            if not segments:
                raise RuntimeError(
                    "视频未转写出可用句子；请确认视频包含清晰人声",
                )
            if duration <= 0:
                duration = probe_duration(self.video_path)
            if not self.running:
                return
            self.progress_changed.emit(15)

            angles = self._ensure_angles(client, model)
            self._used_angles = angles
            if not self.running:
                return
            self.progress_changed.emit(20)

            cuts = self._plan_cuts(client, model, segments, angles, duration)
            self.log_msg.emit(f"✂️ 分析出 {len(cuts)} 个切片")
            if not self.running:
                return
            self.progress_changed.emit(40)

            self._translate_bilingual(segments, client, model)
            if not self.running:
                return
            self.progress_changed.emit(55)

            self.log_msg.emit("🎭 加载 InsightFace 运镜模型...")
            try:
                face_app = self._get_face_app()
            except Exception as exc:
                self.log_msg.emit(
                    f"⚠️ 运镜模型加载失败，改用居中裁切: {exc}",
                )
                face_app = None
            self.progress_changed.emit(60)

            stem = os.path.splitext(os.path.basename(self.video_path))[0]
            total_cuts = max(1, len(cuts))
            for index, cut in enumerate(cuts):
                if not self.running:
                    break
                safe_theme = self._safe_name(cut.theme, index)
                self.log_msg.emit(
                    f"🎬 正在渲染切片 {index + 1}/{len(cuts)}: {cut.theme}",
                )

                temp_clip = os.path.join(
                    self.out_dir, f"_semantic_cut_{index}.mp4",
                )
                try:
                    self._cut_video(cut.start, cut.end, temp_clip)
                    local_segments = slice_transcript(
                        segments, cut.start, cut.end,
                    )
                    subtitles = [{
                        "start": item["start"],
                        "end": item["end"],
                        "text": item.get("text_zh", item.get("text", "")),
                        "original_text": item.get("text_en", ""),
                    } for item in local_segments]
                    output_path = os.path.join(
                        self.out_dir,
                        f"{stem}_{index + 1:02d}_{safe_theme}.mp4",
                    )

                    def _render_progress(local: int, base=60,
                                         span=40, count=total_cuts,
                                         pos=index):
                        self.progress_changed.emit(
                            int(base + span * (pos + local / 100) / count),
                        )

                    render_clip(
                        temp_clip, subtitles, output_path,
                        face_app=face_app,
                        output_w=self.output_w,
                        output_h=self.output_h,
                        bitrate_mbps=self.bitrate_mbps,
                        log_cb=self.log_msg.emit,
                        progress_cb=_render_progress,
                        should_stop=lambda: not self.running,
                    )
                    if not self.running:
                        break
                    cut.clip_path = output_path
                    copy_path = os.path.join(
                        self.out_dir,
                        f"{stem}_{index + 1:02d}_{safe_theme}_文案.txt",
                    )
                    with open(copy_path, "w", encoding="utf-8") as file:
                        file.write(render_social_copy(cut))
                    results.append(cut)
                finally:
                    if os.path.exists(temp_clip):
                        os.remove(temp_clip)

            self.progress_changed.emit(100)
            self.results_ready.emit(results)
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            try:
                report_path = os.path.join(
                    self.out_dir, "semantic_clips.json",
                )
                with open(report_path, "w", encoding="utf-8") as file:
                    json.dump({
                        "video": self.video_path,
                        "query": self.query,
                        "angles": [
                            angle.title for angle in self._used_angles
                        ],
                        "cuts": [asdict(cut) for cut in results],
                    }, file, ensure_ascii=False, indent=2)
            except Exception:
                pass
            self.finished.emit()
