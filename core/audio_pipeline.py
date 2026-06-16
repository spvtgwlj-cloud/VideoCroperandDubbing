"""AI 音频管线模块 — 作为 Mixin 混入 VideoProcessThread

包含 run_ai_pipeline 核心逻辑（~490 行）及其子步骤。
"""

import os
import re
import time
import base64
import subprocess

import requests
import whisper
import torchaudio
import numpy as np
from openai import OpenAI
from pydub import AudioSegment
from pydub import silence
from sklearn.cluster import AgglomerativeClustering
from sklearn.preprocessing import normalize
from speechbrain.inference.speaker import EncoderClassifier

from .config import DASHSCOPE_API_KEY, AI_BASE_URL, EDGE_TTS_DEFAULT
from .voice_cloner import create_cloned_voice as _create_cloned_voice


class AudioPipelineMixin:
    """AI 音频管线 Mixin — 混入 VideoProcessThread 后共享 self.* 属性"""

    # -------- 声音克隆（代理到 voice_cloner 模块） --------

    def create_cloned_voice(self, audio_path, prompt_text, spk_id):
        """代理到 voice_cloner 模块"""
        return _create_cloned_voice(
            audio_path, prompt_text, spk_id,
            self.dashscope_api_key, self.cosy_model, self.log_msg.emit,
        )

    # -------- 静音段压缩 --------

    @staticmethod
    def _compress_silence(segments, max_gap=1.5, target_gap=0.5):
        """将段落间超过 max_gap 秒的静音压缩至 target_gap 秒"""
        if len(segments) < 2:
            return segments
        compressed = [dict(segments[0])]
        time_offset = 0.0
        for i in range(1, len(segments)):
            curr = dict(segments[i])
            # 使用原始段落位置计算 gap，避免 time_offset 复合叠加
            original_gap = segments[i]["start"] - segments[i - 1]["end"]
            if original_gap > max_gap:
                reduction = original_gap - target_gap
                time_offset += reduction
            curr["start"] = max(0.0, curr["start"] - time_offset)
            curr["end"] = max(0.0, curr["end"] - time_offset)
            compressed.append(curr)
        return compressed

    # -------- 外部 SRT + 声纹映射 --------

    @staticmethod
    def _assign_speakers_by_overlap(srt_entries, whisper_segments):
        """按时间重叠度将 SRT 条目映射到 Whisper 段落的 speaker_id。

        纯函数：不依赖 self 状态，不产生副作用（除修改传入的 srt_entries 字典）。
        无重叠的条目默认分配 speaker_id=0。
        """
        for entry in srt_entries:
            best_overlap = 0.0
            best_spk = 0
            s_start, s_end = entry["start"], entry["end"]
            for seg in whisper_segments:
                overlap = max(0.0, min(s_end, seg["end"]) - max(s_start, seg["start"]))
                if overlap > best_overlap:
                    best_overlap = overlap
                    best_spk = seg.get("speaker_id", 0)
            entry["speaker_id"] = best_spk
        return srt_entries

    # -------- TTS 子方法（支持策略排序） --------

    def _run_cosyvoice_tts(self, seg, temp_tts_file, voice_id):
        """尝试 CosyVoice TTS（3 次重试），返回 (success, error_msg)"""
        TTS_URL = "https://dashscope.aliyuncs.com/api/v1/services/audio/tts/SpeechSynthesizer"
        for attempt in range(3):
            try:
                safe_text = "，" + seg["text"] if "中文" in self.target_lang else ", " + seg["text"]
                payload = {
                    "model": self.cosy_model,
                    "input": {"text": safe_text, "voice": voice_id},
                    "parameters": {"sample_rate": 16000, "format": "wav"},
                }
                resp = requests.post(
                    TTS_URL, json=payload,
                    headers={"Authorization": f"Bearer {self.dashscope_api_key}",
                             "Content-Type": "application/json"},
                    timeout=30,
                )
                if resp.status_code != 200:
                    raise Exception(f"HTTP {resp.status_code}: {resp.text}")
                output_audio = resp.json().get("output", {}).get("audio", {})
                if output_audio.get("data"):
                    audio_data = base64.b64decode(output_audio["data"])
                elif output_audio.get("url"):
                    audio_data = requests.get(output_audio["url"], timeout=30).content
                else:
                    raise Exception("无音频数据")
                with open(temp_tts_file, "wb") as f:
                    f.write(audio_data)
                return True, ""
            except Exception as e:
                last_error = str(e)
                if attempt < 2:
                    time.sleep(2)
        return False, last_error

    def _run_edge_tts(self, seg, temp_tts_file, voice_name, seg_index):
        """尝试 Edge-TTS 合成，返回 (success, error_msg)"""
        try:
            clean_text = seg["text"].replace("\n", " ").replace('"', "").replace("'", "")
            if not clean_text.strip():
                raise Exception("文本清理后为空")
            text_file = os.path.join(self.output_dir, f"tts_text_{seg_index}.txt")
            with open(text_file, "w", encoding="utf-8") as f:
                f.write(clean_text)
            result = subprocess.run(
                ["edge-tts", "--voice", voice_name.strip(), "-f", text_file, "--write-media", temp_tts_file],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            if os.path.exists(text_file):
                os.remove(text_file)
            if result.returncode == 0 and os.path.exists(temp_tts_file):
                return True, ""
            real_error = result.stderr.strip() if result.stderr else "未知 CLI 错误"
            raise Exception(f"Edge-TTS 命令失败: {real_error}")
        except Exception as e:
            return False, str(e)

    # -------- AI 管线主逻辑 --------

    def run_ai_pipeline(self, srt_timeline=None):
        """AI 核心管线。srt_timeline 不为 None 时跳过 LLM 翻译，
        直接用 SRT 条目的文本和时间戳驱动 TTS 生成。"""
        # 视频裁剪已在 _process_single 预处理中完成
        input_to_use = self.input_source

        # 更新原始音频路径（裁剪后音频也相应变化）
        trimmed_orig_audio = os.path.join(self.output_dir, "orig_audio_trimmed.wav")

        self.progress_changed.emit(5)
        self.log_msg.emit("【1/5】正在提取原视频音频...")
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-i", input_to_use, "-vn", "-acodec", "pcm_s16le", "-ar", "48000", "-ac", "1",
                 trimmed_orig_audio],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
            )
        except subprocess.CalledProcessError:
            self.log_msg.emit("❌ 音频提取失败！")
            return False

        # ---- BGM 音源分离 ----
        if self.enable_bgm_preserve:
            try:
                subprocess.run(["spleeter", "--version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
                spleeter_ok = True
            except (subprocess.CalledProcessError, FileNotFoundError):
                spleeter_ok = False

            if spleeter_ok:
                self.log_msg.emit("🎵 正在分离人声与背景音乐 (spleeter)...")
                try:
                    subprocess.run(
                        ["spleeter", "separate", "-o", self.output_dir, trimmed_orig_audio],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, timeout=300,
                    )
                    audio_name = os.path.splitext(os.path.basename(trimmed_orig_audio))[0]
                    vocals_path = os.path.join(self.output_dir, audio_name, "vocals.wav")
                    accomp_path = os.path.join(self.output_dir, audio_name, "accompaniment.wav")
                    if os.path.exists(vocals_path) and os.path.exists(accomp_path):
                        trimmed_orig_audio = vocals_path  # 人声走后续管线
                        self.accompaniment_path = accomp_path
                        self.log_msg.emit("✅ BGM 分离成功：人声 → 管线处理，伴奏 → 最后叠加")
                    else:
                        self.log_msg.emit("⚠️ BGM 分离输出文件未找到，跳过")
                        self.enable_bgm_preserve = False
                except Exception as e:
                    self.log_msg.emit(f"⚠️ BGM 分离失败 ({e})，按原始音频继续处理")
                    self.enable_bgm_preserve = False
            else:
                self.log_msg.emit("⚠️ 未检测到 spleeter，请运行: pip install spleeter")
                self.log_msg.emit("   BGM 保留功能已跳过，使用原始音频继续处理")
                self.enable_bgm_preserve = False

        self.progress_changed.emit(10)
        self.log_msg.emit("【2/5】正在加载 Whisper 模型进行语音识别...")
        import warnings
        warnings.filterwarnings("ignore")
        model = whisper.load_model("turbo")
        result = model.transcribe(trimmed_orig_audio)
        segments = result["segments"]
        if not segments:
            self.log_msg.emit("❌ 未检测到语音！")
            return False
        self.log_msg.emit(f"识别完成，共提取 {len(segments)} 句台词。")

        # ---- 静音段压缩 ----
        # 保留原始时间轴（未压缩）供保留原声分支使用
        uncompressed_segments = segments
        segments = self._compress_silence(segments)
        self.log_msg.emit(f"📏 静音段压缩后共 {len(segments)} 句。")

        self.progress_changed.emit(20)

        # ---- 保留原声分支 ----
        if not self.enable_voice_clone:
            self.log_msg.emit("ℹ️ 用户选择【保留原声】，仅进行翻译字幕生成...")
            translated_segments = []
            total = len(uncompressed_segments)
            for i, seg in enumerate(uncompressed_segments):
                if not self.running:
                    return False
                progress = 20 + int((i / total) * 35) if total > 0 else 20
                self.progress_changed.emit(progress)

                original_text = seg["text"].strip()
                prompt = (
                    f"Translate the following text to {self.target_lang}. "
                    f"Keep the translation strictly concise to match the original speaking duration. "
                    f"Only output the translated text, nothing else. Text: '{original_text}'"
                )
                try:
                    response = self.llm_client.chat.completions.create(
                        model="qwen-max", messages=[{"role": "user", "content": prompt}], temperature=0.3
                    )
                    trans_text = response.choices[0].message.content.strip()
                    if not trans_text:
                        raise ValueError("大模型返回内容为空")
                    translated_segments.append({"start": seg["start"], "end": seg["end"], "text": trans_text, "original_text": original_text})
                    self.log_msg.emit(f"字幕翻译 [{i + 1}/{total}]: {trans_text}")
                except Exception as e:
                    self.log_msg.emit(f"⚠️ 第 {i + 1} 句翻译失败 ({e})，保留原台词: {original_text}")
                    translated_segments.append({"start": seg["start"], "end": seg["end"], "text": original_text, "original_text": original_text})

            self.subtitles_timeline = translated_segments
            self.log_msg.emit("正在将原声转换为立体声双声道...")
            try:
                mono_audio = AudioSegment.from_wav(trimmed_orig_audio)
                stereo_audio = mono_audio.set_channels(2)
                stereo_audio.export(self.final_audio, format="wav")
            except Exception as e:
                self.log_msg.emit(f"⚠️ 音频转换失败 ({e})，尝试直接复制...")
                try:
                    subprocess.run(
                        ["ffmpeg", "-y", "-i", trimmed_orig_audio, "-ac", "2", self.final_audio],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
                    )
                except Exception as e2:
                    self.log_msg.emit(f"❌ 音频复制也失败: {e2}")
                    return False

            self.progress_changed.emit(70)
            # 字幕时间轴整体偏移
            if self.subtitle_offset_ms != 0:
                offset_sec = self.subtitle_offset_ms / 1000.0
                for sub in self.subtitles_timeline:
                    sub["start"] = max(0.0, sub["start"] + offset_sec)
                    sub["end"] = max(0.0, sub["end"] + offset_sec)
                self.log_msg.emit(f"⏱️ 字幕时间轴整体偏移 {self.subtitle_offset_ms:+.0f}ms")
            return True

        # ---- 声纹分离 ----
        self.progress_changed.emit(20)
        self.log_msg.emit("【3/5】正在进行高精度声纹分离与聚类分析 (智能降噪版)...")
        valid_segments = []
        orig_audio_segment = AudioSegment.from_wav(trimmed_orig_audio)
        classifier = EncoderClassifier.from_hparams(
            source="speechbrain/spkrec-ecapa-voxceleb",
            savedir="pretrained_models/spkrec-ecapa-voxceleb",
            run_opts={"device": "cpu"},
        )
        embeddings = []
        total_audio_ms = len(orig_audio_segment)
        temp_slice_path = os.path.join(self.output_dir, "temp_slice.wav")

        total_embed = len(segments)
        for idx, seg in enumerate(segments):
            if not self.running:
                return False
            progress = 20 + int((idx / total_embed) * 15) if total_embed > 0 else 20
            self.progress_changed.emit(progress)

            start_ms, end_ms = int(seg["start"] * 1000), int(seg["end"] * 1000)
            duration_ms = end_ms - start_ms
            if duration_ms < 1000 or start_ms >= total_audio_ms:
                continue

            raw_slice = orig_audio_segment[start_ms : min(end_ms, total_audio_ms)]
            try:
                non_silent_chunks = silence.split_on_silence(
                    raw_slice, min_silence_len=300,
                    silence_thresh=raw_slice.dBFS - 16, keep_silence=100,
                )
                if non_silent_chunks:
                    clean_slice = non_silent_chunks[0]
                    for chunk in non_silent_chunks[1:]:
                        clean_slice += chunk
                else:
                    clean_slice = raw_slice
            except Exception:
                clean_slice = raw_slice

            clean_duration = len(clean_slice)
            if clean_duration < 500:
                continue
            if clean_duration > 3000:
                center = clean_duration // 2
                final_slice = clean_slice[center - 1500 : center + 1500]
            else:
                final_slice = clean_slice

            final_slice.export(temp_slice_path, format="wav")
            try:
                if os.path.exists(temp_slice_path) and os.path.getsize(temp_slice_path) > 100:
                    signal, fs = torchaudio.load(temp_slice_path)
                    if signal.shape[0] > 1:
                        signal = signal[0:1, :]
                    embeddings.append(classifier.encode_batch(signal).flatten().numpy())
                    valid_segments.append(seg)
            except Exception:
                continue

        if os.path.exists(temp_slice_path):
            os.remove(temp_slice_path)

        self.progress_changed.emit(35)
        num_speakers = 2 if len(embeddings) >= 2 else 1
        if num_speakers > 1:
            clustering = AgglomerativeClustering(n_clusters=num_speakers, metric="cosine", linkage="complete")
            labels = clustering.fit_predict(normalize(np.array(embeddings), norm="l2"))
        else:
            labels = [0] * len(embeddings)

        for i, seg in enumerate(valid_segments):
            seg["speaker_id"] = labels[i]

        ref_prompts = {}
        for spk_id in range(num_speakers):
            spk_segs = [s for s in valid_segments if s["speaker_id"] == spk_id]
            if spk_segs:
                best_seg = max(spk_segs, key=lambda s: s["end"] - s["start"])
                ref_path = os.path.join(self.output_dir, f"ref_prompt_spk{spk_id}.wav")
                start_ms = int(best_seg["start"] * 1000)
                end_ms = int(best_seg["end"] * 1000)
                duration_ms = end_ms - start_ms
                if duration_ms > 4500:
                    center_ms = start_ms + (duration_ms // 2)
                    start_ms = center_ms - 2250
                    end_ms = center_ms + 2250
                ref_audio = orig_audio_segment[start_ms:end_ms].fade_in(350).fade_out(250)
                ref_audio.export(ref_path, format="wav")
                ref_prompts[spk_id] = {"text": best_seg["text"].strip(), "audio_path": ref_path}
                self.log_msg.emit(f"🎙️ 成功提取原视频角色 {spk_id} 的纯净声纹作为底座 (已控制安全时长)。")

        # ---- 本地上传映射 ----
        if self.clone_mode == 1 and self.upload_configs:
            self.log_msg.emit("【3.5/5】正在加载并映射用户上传的参考音频...")
            for config in self.upload_configs:
                up_path = config["path"]
                up_spk_id = config["spk_id"]
                if up_spk_id not in ref_prompts:
                    self.log_msg.emit(f"⚠️ 视频中未检测到 角色 {up_spk_id}，已忽略对应的上传音频。")
                    continue
                proc_audio = os.path.join(self.output_dir, f"processed_upload_spk{up_spk_id}.wav")
                try:
                    subprocess.run(
                        ["ffmpeg", "-y", "-i", up_path, "-t", "10", "-ar", "16000", "-ac", "1", "-acodec", "pcm_s16le",
                         proc_audio],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
                    )
                    ref_prompts[up_spk_id] = {"text": "User Uploaded Voice", "audio_path": proc_audio}
                    self.log_msg.emit(f"✅ 角色 {up_spk_id} 成功绑定本地上传音频！")
                except Exception as e:
                    self.log_msg.emit(f"❌ 处理上传音频失败: {e}，该角色将回退使用视频提取原声。")

        # ---- 翻译（或 SRT 驱动模式） ----
        if srt_timeline:
            if not valid_segments:
                self.log_msg.emit(
                    "⚠️ 所有语音段落均未通过声纹质量检查，缺少参考声纹。"
                    "外部 SRT 模式将使用 Edge-TTS / 原声兜底合成语音（无法进行声音克隆）。"
                )
            self.progress_changed.emit(40)
            self.log_msg.emit("【4/5】外部 SRT 模式：跳过 LLM 翻译，将 SRT 条目映射到声纹...")
            self.subtitles_timeline = self._assign_speakers_by_overlap(
                srt_timeline, valid_segments
            )
            self.log_msg.emit(
                f"声纹映射完成，共 {len(self.subtitles_timeline)} 条外部字幕已关联说话人。"
            )
        else:
            # ---- 声纹过滤后无有效段落：回退到原始 Whisper 段落翻译 ----
            if not valid_segments:
                self.log_msg.emit(
                    "⚠️ 所有语音段落均未通过声纹质量检查，"
                    "回退使用 Whisper 原始段落进行翻译（不区分说话人）"
                )
                fallback_segments = uncompressed_segments if uncompressed_segments else segments
                self.subtitles_timeline = []
                total_fb = len(fallback_segments)
                for i, seg in enumerate(fallback_segments):
                    if not self.running:
                        return False
                    progress = 40 + int((i / total_fb) * 15) if total_fb > 0 else 40
                    self.progress_changed.emit(progress)
                    original_text = seg["text"].strip()
                    try:
                        response = self.llm_client.chat.completions.create(
                            model="qwen-max",
                            messages=[{"role": "user", "content": (
                                f"Translate the following text to {self.target_lang}. "
                                f"Keep the translation strictly concise. "
                                f"Only output the translated text, nothing else. "
                                f"Text: '{original_text}'"
                            )}], temperature=0.3,
                        )
                        trans_text = response.choices[0].message.content.strip()
                        if not trans_text:
                            raise ValueError("大模型返回内容为空")
                        self.subtitles_timeline.append({
                            "start": seg["start"], "end": seg["end"],
                            "text": trans_text, "original_text": original_text,
                            "speaker_id": 0,
                        })
                        self.log_msg.emit(f"字幕翻译 [{i + 1}/{total_fb}]: {trans_text}")
                    except Exception as e:
                        self.log_msg.emit(f"⚠️ 第 {i + 1} 句翻译失败 ({e})，保留原台词: {original_text}")
                        self.subtitles_timeline.append({
                            "start": seg["start"], "end": seg["end"],
                            "text": original_text, "original_text": original_text,
                            "speaker_id": 0,
                        })
                self.log_msg.emit(
                    f"回退翻译完成，共 {len(self.subtitles_timeline)} 句（单说话人模式）。"
                )
            else:
                self.progress_changed.emit(40)
                self.log_msg.emit("【4/5】正在调用通义千问进行逐句翻译 (启用动态字数与语速约束)...")
                translated_segments = []
                total_translate = len(valid_segments)
                for i, seg in enumerate(valid_segments):
                    if not self.running:
                        return False
                    progress = 40 + int((i / total_translate) * 15) if total_translate > 0 else 40
                    self.progress_changed.emit(progress)

                    original_text = seg["text"].strip()
                    duration_sec = seg["end"] - seg["start"]
                    if "中文" in self.target_lang:
                        max_len = max(int(duration_sec * 4.5), 2)
                        constraint = f"MUST be highly summarized, STRICTLY UNDER {max_len} Chinese characters."
                    else:
                        max_len = max(int(duration_sec * 2.8), 2)
                        constraint = f"MUST be highly summarized, STRICTLY UNDER {max_len} English words."

                    prompt = (
                        f"Translate the following text to {self.target_lang} for video dubbing. "
                        f"The audio slot is exactly {duration_sec:.1f} seconds. {constraint} "
                        f"You are allowed to paraphrase, condense, or omit non-essential words to fit the timeframe. "
                        f"Output ONLY the final translation, NO quotes, NO markdown, NO explanations. "
                        f"Original text: '{original_text}'"
                    )
                    try:
                        response = self.llm_client.chat.completions.create(
                            model="qwen-max", messages=[{"role": "user", "content": prompt}], temperature=0.3
                        )
                        trans_text = response.choices[0].message.content.strip()
                        if not trans_text:
                            raise ValueError("大模型返回内容为空")
                        trans_text = re.sub(r"\[.*?\]|\(.*?\)|【.*?】|（.*?）", "", trans_text)
                        trans_text = trans_text.replace("...", ",").replace("。。。", "，")
                        trans_text = trans_text.strip()
                        translated_segments.append(
                            {"start": seg["start"], "end": seg["end"], "text": trans_text, "original_text": original_text, "speaker_id": seg["speaker_id"]}
                        )
                        self.log_msg.emit(f"角色{seg['speaker_id']} 翻译 [{i + 1}/{total_translate}] (限{max_len}单位): {trans_text}")
                    except Exception as e:
                        self.log_msg.emit(f"⚠️ 第 {i + 1} 句翻译失败 ({e})，将保留原声原台词: {original_text}")
                        translated_segments.append(
                            {"start": seg["start"], "end": seg["end"], "text": original_text, "original_text": original_text, "speaker_id": seg["speaker_id"]}
                        )

                self.subtitles_timeline = translated_segments

        # ---- 快速预览：截断时间轴 ----
        if self.quick_preview_sec > 0:
            preview_end = self.quick_preview_sec
            self.subtitles_timeline = [s for s in self.subtitles_timeline if s["start"] < preview_end]
            self.log_msg.emit(f"👁️ 快速预览模式: 只保留前 {preview_end} 秒的配音")

        # ---- TTS ----
        self.progress_changed.emit(55)
        self.log_msg.emit("【5/5】正在生成 AI 克隆配音 (支持 Edge-TTS 与 原声兜底)...")

        final_audio_canvas = AudioSegment.silent(duration=len(orig_audio_segment))
        final_audio_canvas = final_audio_canvas.set_frame_rate(48000).set_channels(2).set_sample_width(2)

        speaker_voices = {}

        for spk_id, ref in ref_prompts.items():
            try:
                speaker_voices[spk_id] = self.create_cloned_voice(ref["audio_path"], ref["text"], spk_id)
            except Exception as e:
                self.log_msg.emit(f"❌ 角色 {spk_id} 创建音色失败: {e} (将使用兜底方案)")

        total_tts = len(self.subtitles_timeline)
        for i, seg in enumerate(self.subtitles_timeline):
            if not self.running:
                return False
            progress = 55 + int((i / total_tts) * 15) if total_tts > 0 else 55
            self.progress_changed.emit(progress)

            temp_tts_file = os.path.join(self.output_dir, f"temp_tts_{i}.wav")
            spk_id = seg.get("speaker_id", 0)
            voice_id = speaker_voices.get(spk_id)

            # 确定该角色的 Edge-TTS 音色（优先用户指定，回退到语言默认）
            seg_edge_voice = EDGE_TTS_DEFAULT.get(
                "zh" if "中文" in self.target_lang else "en", "en-US-GuyNeural"
            )
            if self.enable_edge_tts_first and self.edge_tts_voices:
                user_voice = self.edge_tts_voices.get(spk_id)
                if user_voice:
                    seg_edge_voice = user_voice

            success = False
            last_error = "未知错误"

            if self.enable_edge_tts_first:
                # 方案 A：Edge-TTS（优先）
                self.log_msg.emit(f"🔊 第 {i + 1} 句使用 Edge-TTS ({seg_edge_voice})...")
                success, last_error = self._run_edge_tts(seg, temp_tts_file, seg_edge_voice, i)

                # 方案 B：CosyVoice（回退）
                if not success and voice_id:
                    self.log_msg.emit(f"⚠️ 第 {i + 1} 句 Edge-TTS 失败 ({last_error})，回退至 CosyVoice...")
                    success, last_error = self._run_cosyvoice_tts(seg, temp_tts_file, voice_id)
            else:
                # 方案 A：CosyVoice（优先）
                if voice_id:
                    success, last_error = self._run_cosyvoice_tts(seg, temp_tts_file, voice_id)
                # 方案 B：Edge-TTS（回退）
                if not success:
                    if last_error:
                        self.log_msg.emit(f"⚠️ 第 {i + 1} 句克隆失败 ({last_error})，回退至 Edge-TTS...")
                    success, last_error = self._run_edge_tts(seg, temp_tts_file, seg_edge_voice, i)

            # 方案 C：原声兜底
            if not success:
                self.log_msg.emit(f"❌ 第 {i + 1} 句全部 TTS 方案失败 ({last_error})，强制保留视频原声...")
                try:
                    start_ms = int(seg["start"] * 1000)
                    end_ms = int(seg["end"] * 1000)
                    orig_audio_segment[start_ms:end_ms].export(temp_tts_file, format="wav")
                    success = True
                except Exception as e:
                    self.log_msg.emit(f"❌ 严重错误: 第 {i + 1} 句原声提取失败 ({e})")

            # 统一处理
            if success and os.path.exists(temp_tts_file):
                target_duration_ms = int((seg["end"] - seg["start"]) * 1000)
                if target_duration_ms <= 0:
                    self.log_msg.emit(f"⚠️ 第 {i + 1} 句时长为零，跳过变速对齐")
                    tts_segment = AudioSegment.from_file(temp_tts_file)
                    insert_position = int(seg["start"] * 1000)
                    tts_segment = tts_segment.fade_in(30).fade_out(50)
                    final_audio_canvas = final_audio_canvas.overlay(tts_segment, position=insert_position)
                    try:
                        os.remove(temp_tts_file)
                    except OSError:
                        pass
                    continue
                tts_segment = AudioSegment.from_file(temp_tts_file)
                if len(tts_segment) > 300:
                    tts_segment = tts_segment[150:]
                actual_duration_ms = len(tts_segment)
                speed_factor = actual_duration_ms / target_duration_ms
                if abs(speed_factor - 1.0) > 0.1:
                    clamped_speed = max(0.75, min(speed_factor, 1.35))
                    self.log_msg.emit(
                        f"⚡ 语音变速对齐: 目标 {target_duration_ms}ms, 实际 {actual_duration_ms}ms, 变速率: x{clamped_speed:.2f}"
                    )
                    temp_speed_file = os.path.join(self.output_dir, f"temp_speed_{i}.wav")
                    try:
                        subprocess.run(
                            ["ffmpeg", "-y", "-i", temp_tts_file, "-filter:a", f"atempo={clamped_speed}", temp_speed_file],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
                        )
                    except subprocess.CalledProcessError as e:
                        self.log_msg.emit(f"⚠️ 第 {i + 1} 句变速失败 ({e})，使用原速音频")
                        tts_segment = AudioSegment.from_file(temp_tts_file)
                        insert_position = int(seg["start"] * 1000)
                        # 跳过变速分支的剩余逻辑，直接跳到叠加
                        tts_segment = tts_segment.fade_in(30).fade_out(50)
                        final_audio_canvas = final_audio_canvas.overlay(tts_segment, position=insert_position)
                        try:
                            os.remove(temp_tts_file)
                        except OSError:
                            pass
                        continue
                    tts_segment = AudioSegment.from_file(temp_speed_file)
                    os.remove(temp_speed_file)
                    final_actual_ms = len(tts_segment)
                    if final_actual_ms < target_duration_ms:
                        insert_position = int(seg["start"] * 1000) + (target_duration_ms - final_actual_ms) // 2
                    else:
                        insert_position = int(seg["start"] * 1000)
                else:
                    insert_position = int(seg["start"] * 1000)

                tts_segment = tts_segment.fade_in(30).fade_out(50)
                final_audio_canvas = final_audio_canvas.overlay(tts_segment, position=insert_position)
                try:
                    os.remove(temp_tts_file)
                except OSError:
                    pass

        # ---- 叠加 BGM 伴奏 ----
        if self.enable_bgm_preserve and self.accompaniment_path and os.path.exists(self.accompaniment_path):
            try:
                bgm = AudioSegment.from_file(self.accompaniment_path)
                bgm = bgm.set_frame_rate(48000).set_channels(2).set_sample_width(2)
                canvas_ms = len(final_audio_canvas)
                if len(bgm) < canvas_ms:
                    repeats = (canvas_ms // len(bgm)) + 1
                    bgm = bgm * repeats
                bgm = bgm[:canvas_ms]
                bgm = bgm - 9  # -9dB ≈ 35% 音量
                final_audio_canvas = final_audio_canvas.overlay(bgm)
                self.log_msg.emit("🎵 BGM 伴奏已叠加到最终音频")
            except Exception as e:
                self.log_msg.emit(f"⚠️ BGM 叠加失败: {e}")

        final_audio_canvas.export(self.final_audio, format="wav")
        self.log_msg.emit("🎉 AI 配音对齐全部完成！")
        self.progress_changed.emit(70)  # AI 管线约占整体 70%，后续还有渲染和合成

        # 字幕时间轴整体偏移
        if self.subtitle_offset_ms != 0:
            offset_sec = self.subtitle_offset_ms / 1000.0
            for sub in self.subtitles_timeline:
                sub["start"] = max(0.0, sub["start"] + offset_sec)
                sub["end"] = max(0.0, sub["end"] + offset_sec)
            self.log_msg.emit(f"⏱️ 字幕时间轴整体偏移 {self.subtitle_offset_ms:+.0f}ms")
        return True
