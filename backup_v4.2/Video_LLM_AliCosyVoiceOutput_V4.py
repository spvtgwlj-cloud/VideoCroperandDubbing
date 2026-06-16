#@20260507 相对V2版本，V3增加了可以上传2个音频样本并选择映射音频对象的能力，同时增加音色克隆失败后采用本地Edge_TTS技术输出音频及采用原声兜底的方案
# v4.1: 新增平台预设模板、批量文件夹处理、快速预览、字幕样式编辑、视频裁剪、静音段压缩、保留原声默认、拖拽输入、进度条、输出快速打开

import os
import re
import sys
import json
import cv2
import time
import base64
import whisper
import datetime
import requests
import dashscope
import subprocess
import torchaudio
import numpy as np
from openai import OpenAI
from dashscope import Files
from pydub import AudioSegment
from sklearn.cluster import AgglomerativeClustering
from sklearn.preprocessing import normalize
from PIL import Image, ImageDraw, ImageFont
from insightface.app import FaceAnalysis
from speechbrain.inference.speaker import EncoderClassifier
from PyQt5.QtGui import QImage, QPixmap, QPainter, QColor
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QHBoxLayout,
                             QVBoxLayout, QLabel, QPushButton, QComboBox,
                             QLineEdit, QTextEdit, QGroupBox, QRadioButton,
                             QSpinBox, QFileDialog, QGridLayout, QCheckBox,
                             QProgressBar, QSlider, QMessageBox)
from PyQt5.QtCore import Qt, pyqtSignal, QThread

# ==========================================
# AI 大模型配置 (阿里云通义千问) — 直接修改此处
# ==========================================
DASHSCOPE_API_KEY = "sk-bee6589163b94d20857955a69c53ef6b"
AI_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
# 环境变量可覆盖上述默认值（CI/共享机器场景）
DASHSCOPE_API_KEY = os.environ.get("DASHSCOPE_API_KEY", DASHSCOPE_API_KEY)
AI_BASE_URL = os.environ.get("DASHSCOPE_BASE_URL", AI_BASE_URL)
# ==========================================

os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

# ==========================================
# 平台预设模板
# ==========================================
PLATFORM_PRESETS = {
    "手动配置":     {"is_vertical": None, "subtitle_pos": -1,     "codec": None,           "fps": 0,   "ow": 0, "oh": 0, "desc": "使用下方自定义设置"},
    "抖音 / 视频号": {"is_vertical": True,  "subtitle_pos": 0.25, "codec": "H.264 (MP4)",  "fps": 30,  "ow": 1080, "oh": 1920, "desc": "9:16 竖屏，字幕避让底部 UI"},
    "快手":          {"is_vertical": True,  "subtitle_pos": 0.20, "codec": "H.265 (HEVC)", "fps": 30,  "ow": 1080, "oh": 1920, "desc": "9:16 竖屏，字幕略靠下"},
    "小红书":        {"is_vertical": True,  "subtitle_pos": 0.15, "codec": "H.264 (MP4)",  "fps": 30,  "ow": 1080, "oh": 1440, "desc": "3:4 竖屏，适合图文/视频笔记"},
    "B站":          {"is_vertical": False, "subtitle_pos": 0.08, "codec": "H.265 (HEVC)", "fps": 30,  "ow": 0, "oh": 0, "desc": "横屏保留原比例"},
    "YouTube":      {"is_vertical": False, "subtitle_pos": 0.08, "codec": "H.264 (MP4)",  "fps": 30,  "ow": 0, "oh": 0, "desc": "横屏，兼容性优先"},
}

# 字幕颜色预设 (RGB 三元组)
SUBTITLE_COLORS = {
    "黄色（推荐）": (255, 235, 59),
    "白色":         (255, 255, 255),
    "青色":         (0, 255, 255),
    "红色":         (255, 80, 80),
    "绿色":         (80, 255, 80),
}


class VideoProcessThread(QThread):
    update_frame = pyqtSignal(QImage)
    log_msg = pyqtSignal(str)
    finished = pyqtSignal()
    progress_changed = pyqtSignal(int)  # 0-100
    batch_finished = pyqtSignal(list)  # 批量处理完成后发送结果列表

    def __init__(self, input_source, is_vertical, target_lang, codec, fps,
                 enable_subtitle, enable_voice_clone, clone_mode, upload_configs,
                 trim_start=0, trim_end=0, quick_preview_sec=0,
                 subtitle_style=None, batch_files=None,
                 output_w=1080, output_h=1920,
                 subtitle_offset_ms=0,
                 enable_bgm_preserve=False):
        super().__init__()
        self.input_source = input_source
        self.is_vertical = is_vertical
        self.target_lang = target_lang
        self.fps = fps
        self.codec = codec
        self.enable_subtitle = enable_subtitle
        self.enable_voice_clone = enable_voice_clone
        self.clone_mode = clone_mode
        self.upload_configs = upload_configs
        self.trim_start = trim_start
        self.trim_end = trim_end
        self.quick_preview_sec = quick_preview_sec
        self.subtitle_style = subtitle_style or {}
        self.batch_files = batch_files or []
        self.output_w = output_w
        self.output_h = output_h
        self.subtitle_offset_ms = subtitle_offset_ms
        self.enable_bgm_preserve = enable_bgm_preserve
        self.accompaniment_path = None  # BGM 分离后的伴奏音轨路径
        self.running = True

        self.smooth_center_x = None
        self.damping_factor = 0.08
        self.subtitles_timeline = []

        self.log_msg.emit("正在加载 InsightFace 模型 (Mac M1 模式)...")
        self.face_app = FaceAnalysis(name='buffalo_l', providers=['CoreMLExecutionProvider', 'CPUExecutionProvider'])
        self.face_app.prepare(ctx_id=-1, det_size=(640, 640))

        self.output_dir, self.temp_video, self.orig_audio, self.final_audio, self.final_output = self.prepare_output_env()
        self.video_writer = None
        self.llm_client = OpenAI(api_key=DASHSCOPE_API_KEY, base_url=AI_BASE_URL)

        self.cosy_model = "cosyvoice-v2"
        self.dashscope_api_key = DASHSCOPE_API_KEY

    def prepare_output_env(self, suffix=""):
        desktop_path = os.path.join(os.path.expanduser("~"), 'Desktop')
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M")
        folder_name = f"AI_LLMTest_{timestamp}"
        full_dir = os.path.join(desktop_path, folder_name)
        os.makedirs(full_dir, exist_ok=True)

        temp_video = os.path.join(full_dir, f"temp_silent{suffix}.mp4")
        orig_audio = os.path.join(full_dir, f"orig_audio{suffix}.wav")
        final_audio = os.path.join(full_dir, f"final_synced_audio{suffix}.wav")
        final_output = os.path.join(full_dir, f"Output{suffix}_{timestamp}.mp4")
        return full_dir, temp_video, orig_audio, final_audio, final_output

    def get_chinese_font(self):
        font_paths = ["/System/Library/Fonts/PingFang.ttc", "/System/Library/Fonts/STHeiti Light.ttc"]
        for path in font_paths:
            if os.path.exists(path): return path
        return None

    # -------- 字幕样式辅助方法 --------
    def _get_subtitle_color(self):
        color_name = self.subtitle_style.get("color", "黄色（推荐）")
        return SUBTITLE_COLORS.get(color_name, (255, 235, 59))

    def _get_subtitle_font_ratio(self):
        return self.subtitle_style.get("font_size", 0.055)

    def _get_subtitle_bg(self):
        return self.subtitle_style.get("bg_enabled", False)

    def _get_portrait_margin(self):
        return self.subtitle_style.get("portrait_margin", 0.25)

    def _get_landscape_margin(self):
        return self.subtitle_style.get("landscape_margin", 0.15)

    def _get_bilingual(self):
        return self.subtitle_style.get("bilingual", False)

    # -------- 字幕绘制 --------
    def add_subtitle(self, frame, text, original_text=""):
        if not self.enable_subtitle or not text:
            return frame

        cv2_im_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        pil_im = Image.fromarray(cv2_im_rgb)
        draw = ImageDraw.Draw(pil_im)

        img_w, img_h = pil_im.width, pil_im.height
        is_landscape = img_w > img_h
        base_dim = min(img_w, img_h)

        # ---- 双语：在上方 1/3 处绘制原文（灰色小字） ----
        if self._get_bilingual() and original_text:
            orig_font_ratio = 0.035
            orig_font_size = int(base_dim * orig_font_ratio)
            font_path = self.get_chinese_font()
            orig_font = ImageFont.truetype(font_path, orig_font_size) if font_path else ImageFont.load_default()

            # 原文自动换行
            max_width = int(img_w * 0.85)
            orig_lines = []
            cur = ""
            for char in original_text:
                if draw.textlength(cur + char, font=orig_font) <= max_width:
                    cur += char
                else:
                    last_space = cur.rfind(' ')
                    if last_space != -1 and (len(cur) - last_space) < 15:
                        orig_lines.append(cur[:last_space].strip())
                        cur = cur[last_space + 1:] + char
                    else:
                        orig_lines.append(cur)
                        cur = char
            if cur:
                orig_lines.append(cur.strip())
            orig_wrapped = "\n".join(orig_lines)

            orig_bbox = draw.textbbox((0, 0), orig_wrapped, font=orig_font, align="center")
            orig_text_h = orig_bbox[3] - orig_bbox[1]
            orig_x = (img_w - (orig_bbox[2] - orig_bbox[0])) // 2
            orig_y = max(10, img_h // 3 - orig_text_h // 2)

            gray_color = (180, 180, 180)
            orig_bold = max(1, int(orig_font_size * 0.02))
            orig_offset = max(2, int(orig_font_size * 0.04))

            if self._get_subtitle_bg():
                padding = int(orig_font_size * 0.25)
                orig_bbox_full = draw.textbbox((0, 0), orig_wrapped, font=orig_font, align="center")
                ow = orig_bbox_full[2] - orig_bbox_full[0]
                oh = orig_bbox_full[3] - orig_bbox_full[1]
                draw.rectangle([orig_x - padding, orig_y - padding, orig_x + ow + padding, orig_y + oh + padding],
                               fill=(0, 0, 0, 100))

            draw.multiline_text((orig_x, orig_y), orig_wrapped, font=orig_font, fill=gray_color,
                                stroke_width=orig_bold, stroke_fill=(0, 0, 0), align="center")

        # ---- 译文（底部，正常比例） ----
        font_ratio = self._get_subtitle_font_ratio()
        font_size = int(base_dim * font_ratio)
        font_path = self.get_chinese_font()
        font = ImageFont.truetype(font_path, font_size) if font_path else ImageFont.load_default()

        # 自动换行
        max_width = int(img_w * 0.9)
        lines = []
        current_line = ""
        for char in text:
            if draw.textlength(current_line + char, font=font) <= max_width:
                current_line += char
            else:
                last_space = current_line.rfind(' ')
                if last_space != -1 and (len(current_line) - last_space) < 15:
                    lines.append(current_line[:last_space].strip())
                    current_line = current_line[last_space + 1:] + char
                else:
                    lines.append(current_line)
                    current_line = char
        if current_line:
            lines.append(current_line.strip())
        wrapped_text = "\n".join(lines)

        text_bbox = draw.textbbox((0, 0), wrapped_text, font=font, align="center")
        text_w = text_bbox[2] - text_bbox[0]
        text_h = text_bbox[3] - text_bbox[1]
        x = (img_w - text_w) // 2

        if is_landscape:
            bottom_margin = int(img_h * self._get_landscape_margin())
        else:
            bottom_margin = int(img_h * self._get_portrait_margin())
        y = max(10, img_h - text_h - bottom_margin)

        main_color = self._get_subtitle_color()
        shadow_color = (0, 0, 0)
        bold_width = max(1, int(font_size * 0.025))
        offset = max(2, int(font_size * 0.05))

        # 可选半透明背景框
        if self._get_subtitle_bg():
            padding = int(font_size * 0.3)
            bg_box = [x - padding, y - padding, x + text_w + padding, y + text_h + padding]
            draw.rectangle(bg_box, fill=(0, 0, 0, 140))

        draw.multiline_text((x + offset, y + offset), wrapped_text, font=font, fill=shadow_color,
                            stroke_width=bold_width, stroke_fill=shadow_color, align="center")
        draw.multiline_text((x - offset, y - offset), wrapped_text, font=font, fill=shadow_color,
                            stroke_width=bold_width, stroke_fill=shadow_color, align="center")
        draw.multiline_text((x, y), wrapped_text, font=font, fill=main_color, stroke_width=bold_width,
                            stroke_fill=main_color, align="center")

        return cv2.cvtColor(np.array(pil_im), cv2.COLOR_RGB2BGR)

    # -------- 声音克隆 --------
    def create_cloned_voice(self, audio_path, prompt_text, spk_id):
        dashscope.api_key = self.dashscope_api_key
        CLONE_URL = "https://dashscope.aliyuncs.com/api/v1/services/audio/tts/customization"
        self.log_msg.emit(f"🎵 正在上传角色 {spk_id} 的参考音频...")
        try:
            upload_resp = Files.upload(file_path=audio_path, purpose="voice_clone")
            if upload_resp.status_code != 200:
                raise Exception(f"上传失败: {upload_resp.message}")
            file_id = upload_resp.output["uploaded_files"][0]["file_id"]
            file_info = Files.get(file_id)
            audio_url = file_info.output["url"]
        except Exception as e:
            raise Exception(f"音频上传阶段出错: {e}")

        payload = {
            "model": "voice-enrollment",
            "input": {"action": "create_voice", "target_model": self.cosy_model, "url": audio_url,
                      "prefix": f"spk{spk_id}"},
            "parameters": {"response_format": "wav"},
        }
        headers = {"Authorization": f"Bearer {self.dashscope_api_key}", "Content-Type": "application/json"}
        self.log_msg.emit(f"🎵 正在为角色 {spk_id} 创建克隆音色...")
        resp = requests.post(CLONE_URL, json=payload, headers=headers, timeout=30)
        if resp.status_code != 200:
            raise Exception(f"声音复刻失败: {resp.status_code} {resp.text}")
        voice_id = resp.json().get("output", {}).get("voice_id")
        if not voice_id:
            raise Exception("未获取到音色ID")
        self.log_msg.emit(f"✅ 音色创建成功，Voice ID: {voice_id}")
        return voice_id

    # -------- 静音段压缩 --------
    @staticmethod
    def _compress_silence(segments, max_gap=1.5, target_gap=0.5):
        """将段落间超过 max_gap 秒的静音压缩至 target_gap 秒"""
        if len(segments) < 2:
            return segments
        compressed = [dict(segments[0])]
        time_offset = 0.0
        for i in range(1, len(segments)):
            prev = compressed[-1]
            curr = dict(segments[i])
            gap = curr["start"] - prev["end"]
            if gap > max_gap:
                reduction = gap - target_gap
                time_offset += reduction
            curr["start"] = max(0.0, curr["start"] - time_offset)
            curr["end"] = max(0.0, curr["end"] - time_offset)
            compressed.append(curr)
        return compressed

    # -------- AI 管线 --------
    def run_ai_pipeline(self):
        # ---- 视频裁剪 ----
        input_to_use = self.input_source
        temp_trim_path = None
        if self.trim_start > 0 or self.trim_end > 0:
            self.log_msg.emit(f"✂️ 正在裁剪视频: {self.trim_start}s ~ {self.trim_end or '结尾'}s")
            temp_trim_path = os.path.join(self.output_dir, "temp_trimmed.mp4")
            cmd = ["ffmpeg", "-y"]
            if self.trim_start > 0:
                cmd.extend(["-ss", str(self.trim_start)])
            cmd.extend(["-i", self.input_source])
            if self.trim_end > 0:
                cmd.extend(["-to", str(self.trim_end)])
            cmd.extend(["-c", "copy", temp_trim_path])
            try:
                subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
                input_to_use = temp_trim_path
            except subprocess.CalledProcessError as e:
                self.log_msg.emit(f"⚠️ 视频裁剪失败，使用原始视频: {e.stderr[-200:] if e.stderr else ''}")

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
        segments = self._compress_silence(segments)
        self.log_msg.emit(f"📏 静音段压缩后共 {len(segments)} 句。")

        self.progress_changed.emit(20)

        # ---- 保留原声分支 ----
        if not self.enable_voice_clone:
            self.log_msg.emit("ℹ️ 用户选择【保留原声】，仅进行翻译字幕生成...")
            translated_segments = []
            total = len(segments)
            for i, seg in enumerate(segments):
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

            self.progress_changed.emit(100)
            # 字幕时间轴整体偏移
            if self.subtitle_offset_ms != 0:
                offset_sec = self.subtitle_offset_ms / 1000.0
                for sub in self.subtitles_timeline:
                    sub["start"] = max(0.0, sub["start"] + offset_sec)
                    sub["end"] = max(0.0, sub["end"] + offset_sec)
                self.log_msg.emit(f"⏱️ 字幕时间轴整体偏移 {self.subtitle_offset_ms:+.0f}ms")
            # 清理裁剪临时文件
            if temp_trim_path and os.path.exists(temp_trim_path):
                os.remove(temp_trim_path)
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

        from pydub import silence
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

        # ---- 翻译 ----
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
        TTS_URL = "https://dashscope.aliyuncs.com/api/v1/services/audio/tts/SpeechSynthesizer"

        final_audio_canvas = AudioSegment.silent(duration=len(orig_audio_segment))
        final_audio_canvas = final_audio_canvas.set_frame_rate(48000).set_channels(2).set_sample_width(2)

        speaker_voices = {}
        edge_voice = "zh-CN-YunjianNeural" if "中文" in self.target_lang else "en-US-GuyNeural"

        for spk_id, ref in ref_prompts.items():
            try:
                speaker_voices[spk_id] = self.create_cloned_voice(ref["audio_path"], ref["text"], spk_id)
            except Exception as e:
                self.log_msg.emit(f"❌ 角色 {spk_id} 创建音色失败: {e} (将使用兜底方案)")

        total_tts = len(self.subtitles_timeline)
        for i, seg in enumerate(self.subtitles_timeline):
            if not self.running:
                return False
            progress = 55 + int((i / total_tts) * 35) if total_tts > 0 else 55
            self.progress_changed.emit(progress)

            temp_tts_file = os.path.join(self.output_dir, f"temp_tts_{i}.wav")
            spk_id = seg.get("speaker_id", 0)
            voice_id = speaker_voices.get(spk_id)

            success = False
            last_error = "未知错误"

            # 方案 A：CosyVoice
            if voice_id:
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
                        success = True
                        break
                    except Exception as e:
                        last_error = str(e)
                        if attempt < 2:
                            time.sleep(2)

            # 方案 B：Edge-TTS
            if not success:
                self.log_msg.emit(f"⚠️ 第 {i + 1} 句克隆失败 ({last_error})，回退至 Edge-TTS...")
                try:
                    clean_text = seg["text"].replace("\n", " ").replace('"', "").replace("'", "")
                    if not clean_text.strip():
                        raise Exception("文本清理后为空")
                    # 将文本写入临时文件，避免 --text 传参时特殊字符被 edge-tts 参数解析器误读
                    text_file = os.path.join(self.output_dir, f"tts_text_{i}.txt")
                    with open(text_file, "w", encoding="utf-8") as f:
                        f.write(clean_text)
                    result = subprocess.run(
                        ["edge-tts", "--voice", edge_voice.strip(), "-f", text_file, "--write-media", temp_tts_file],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                    )
                    if os.path.exists(text_file):
                        os.remove(text_file)
                    if result.returncode == 0 and os.path.exists(temp_tts_file):
                        success = True
                    else:
                        real_error = result.stderr.strip() if result.stderr else "未知 CLI 错误"
                        raise Exception(f"Edge-TTS 命令失败: {real_error}")
                except Exception as e:
                    last_error = str(e)

            # 方案 C：原声兜底
            if not success:
                self.log_msg.emit(f"❌ 第 {i + 1} 句 Edge-TTS 也失败 ({last_error})，强制保留视频原声...")
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
                    subprocess.run(
                        ["ffmpeg", "-y", "-i", temp_tts_file, "-filter:a", f"atempo={clamped_speed}", temp_speed_file],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
                    )
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
                # 若 BGM 比画板短则循环，若长则裁切
                canvas_ms = len(final_audio_canvas)
                if len(bgm) < canvas_ms:
                    repeats = (canvas_ms // len(bgm)) + 1
                    bgm = bgm * repeats
                bgm = bgm[:canvas_ms]
                # 降低 BGM 音量至约 35% 以免盖过人声
                bgm = bgm - 9  # -9dB ≈ 35% 音量
                final_audio_canvas = final_audio_canvas.overlay(bgm)
                self.log_msg.emit("🎵 BGM 伴奏已叠加到最终音频")
            except Exception as e:
                self.log_msg.emit(f"⚠️ BGM 叠加失败: {e}")

        final_audio_canvas.export(self.final_audio, format="wav")
        self.log_msg.emit("🎉 AI 配音对齐全部完成！")
        self.progress_changed.emit(100)

        # 清理裁剪临时文件
        if temp_trim_path and os.path.exists(temp_trim_path):
            try:
                os.remove(temp_trim_path)
            except OSError:
                pass

        # 字幕时间轴整体偏移
        if self.subtitle_offset_ms != 0:
            offset_sec = self.subtitle_offset_ms / 1000.0
            for sub in self.subtitles_timeline:
                sub["start"] = max(0.0, sub["start"] + offset_sec)
                sub["end"] = max(0.0, sub["end"] + offset_sec)
            self.log_msg.emit(f"⏱️ 字幕时间轴整体偏移 {self.subtitle_offset_ms:+.0f}ms")
        return True

    # -------- 音视频合成 --------
    def merge_audio_video(self):
        self.log_msg.emit("正在合成最终的音视频文件 (应用高质量重编码)...")
        is_h265 = "H.265" in self.codec
        v_codec = "hevc_videotoolbox" if is_h265 else "h264_videotoolbox"

        cmd = [
            "ffmpeg", "-y",
            "-i", self.temp_video,
            "-i", self.final_audio,
            "-c:v", v_codec,
            "-pix_fmt", "yuv420p",
            "-b:v", "5M",
        ]
        if is_h265:
            cmd.extend(["-tag:v", "hvc1"])
        cmd.extend([
            "-c:a", "aac", "-ac", "2", "-b:a", "256k",
            "-map", "0:v:0", "-map", "1:a:0",
            "-shortest", self.final_output,
        ])

        try:
            subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
            self.log_msg.emit("✅ 音视频合成成功 (M1 硬件加速已启用)！")
            for f in [self.temp_video, self.orig_audio, self.final_audio]:
                if os.path.exists(f):
                    os.remove(f)
        except subprocess.CalledProcessError as e:
            error_details = e.stderr[-500:] if e.stderr else "未知 FFmpeg 错误"
            self.log_msg.emit(f"❌ 音视频合成失败 (错误码 {e.returncode}): {error_details}")
        except Exception as e:
            self.log_msg.emit(f"❌ 音视频合成发生异常: {e}")

    # -------- 处理单视频 --------
    def _process_single(self):
        """处理一个视频的内部逻辑"""
        try:
            if not self.run_ai_pipeline():
                return
        except Exception as e:
            self.log_msg.emit(f"AI 管线异常: {e}")
            return

        self.log_msg.emit("开始画面裁切渲染与动态字幕处理...")
        self.progress_changed.emit(80)
        cap = cv2.VideoCapture(self.input_source)
        orig_fps = cap.get(cv2.CAP_PROP_FPS)
        if orig_fps == 0 or np.isnan(orig_fps):
            orig_fps = self.fps

        frame_count, last_target_center_x = 0, None

        # 快速预览：最多处理的帧数
        max_frames = 0
        if self.quick_preview_sec > 0:
            max_frames = int(orig_fps * self.quick_preview_sec)

        while self.running:
            ret, frame = cap.read()
            if not ret:
                break

            current_time = frame_count / orig_fps
            if self.quick_preview_sec > 0 and current_time > self.quick_preview_sec:
                break

            current_text = ""
            current_orig = ""
            for sub in self.subtitles_timeline:
                if sub["start"] <= current_time <= sub["end"]:
                    current_text = sub["text"]
                    current_orig = sub.get("original_text", "")
                    break

            h, w, _ = frame.shape
            out_frame = frame

            if self.is_vertical:
                if last_target_center_x is None:
                    last_target_center_x = w // 2
                if frame_count % 4 == 0:
                    faces = self.face_app.get(frame)
                    if len(faces) > 0:
                        largest_face = max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
                        last_target_center_x = int((largest_face.bbox[0] + largest_face.bbox[2]) / 2)

                if self.smooth_center_x is None:
                    self.smooth_center_x = last_target_center_x
                else:
                    self.smooth_center_x += (last_target_center_x - self.smooth_center_x) * self.damping_factor

                target_w = min(int(h * 9 / 16), w)
                x1 = int(self.smooth_center_x - target_w / 2)
                x2 = x1 + target_w
                if x1 < 0:
                    x1, x2 = 0, target_w
                elif x2 > w:
                    x1, x2 = w - target_w, w
                out_frame = cv2.resize(frame[:, x1:x2], (self.output_w, self.output_h))

            out_frame = self.add_subtitle(out_frame, current_text, current_orig)

            if self.video_writer is None:
                self.video_writer = cv2.VideoWriter(
                    self.temp_video, cv2.VideoWriter_fourcc(*"mp4v"), orig_fps,
                    (out_frame.shape[1], out_frame.shape[0]),
                )
            self.video_writer.write(out_frame)

            if frame_count % 3 == 0:
                rgb_image = cv2.cvtColor(out_frame, cv2.COLOR_BGR2RGB)
                self.update_frame.emit(
                    QImage(rgb_image.data, rgb_image.shape[1], rgb_image.shape[0],
                           rgb_image.shape[2] * rgb_image.shape[1], QImage.Format_RGB888)
                )
            frame_count += 1

        cap.release()
        if self.video_writer:
            self.video_writer.release()

        self.progress_changed.emit(90)
        if self.running:
            self.merge_audio_video()
            self.log_msg.emit(f"🎉 全部处理完成！文件保存在: {self.final_output}")

    # -------- 入口：单文件或批量 --------
    def run(self):
        self.batch_results = []
        if self.batch_files:
            total = len(self.batch_files)
            for idx, file_path in enumerate(self.batch_files):
                file_name = os.path.basename(file_path)
                if not self.running:
                    result = {"file": file_name, "success": False, "error": "用户取消"}
                    self.batch_results.append(result)
                    break
                safe_name = os.path.splitext(file_name)[0]
                self.log_msg.emit(f"\n📁 批量处理 [{idx + 1}/{total}]: {file_name}")
                self.input_source = file_path
                self.output_dir, self.temp_video, self.orig_audio, self.final_audio, self.final_output = \
                    self.prepare_output_env(suffix=f"_{safe_name}")
                self.video_writer = None
                self.subtitles_timeline = []
                self.smooth_center_x = None

                # 记录每个文件的结果
                result = {"file": file_name, "path": file_path, "output": self.final_output,
                          "success": False, "error": None}
                try:
                    self._process_single()
                    if os.path.exists(self.final_output) and os.path.getsize(self.final_output) > 0:
                        result["success"] = True
                    else:
                        result["error"] = "处理未生成输出文件"
                except Exception as e:
                    result["error"] = str(e)
                self.batch_results.append(result)

                self.progress_changed.emit(int((idx + 1) / total * 100))

            self.batch_finished.emit(self.batch_results)
        else:
            self._process_single()
        self.finished.emit()

    def stop(self):
        self.running = False
        if not self.wait(8000):
            self.log_msg.emit("⚠️ 线程未在 8 秒内退出，强制终止...")
            self.terminate()
            self.wait()


# ==========================================
# 主 UI 界面
# ==========================================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AI Video Dubbing Pro (Mac Native)")
        self.resize(1280, 880)
        self.thread = None
        self.last_output = None
        self.batch_folder_path = ""
        self.setAcceptDrops(True)
        self.init_ui()
        self.apply_apple_style()

    # -------- 拖拽输入 --------
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path.lower().endswith((".mp4", ".mov", ".avi", ".mkv", ".wav", ".mp3", ".m4a")):
                if path.lower().endswith((".mp4", ".mov", ".avi", ".mkv")):
                    self.input_path.setText(path)
                    self.draw_waveform(path)
                else:
                    # 音频文件自动填入第一个音频槽
                    self.input_audio_1.setText(path)
                break

    # -------- UI 构建 --------
    def init_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QHBoxLayout(main_widget)
        main_layout.setContentsMargins(15, 15, 15, 15)

        # ---------- 左：预览 ----------
        self.left_panel = QWidget()
        left_layout = QVBoxLayout(self.left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self.preview_label = QLabel("视频预览区\n(处理过程中实时显示)")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setStyleSheet(
            "background-color: #1C1C1E; color: #E5E5EA; border-radius: 12px; font-size: 15px;"
        )
        left_layout.addWidget(self.preview_label)

        # 波形可视化
        self.waveform_label = QLabel("音频波形 (选择视频后自动生成)")
        self.waveform_label.setAlignment(Qt.AlignCenter)
        self.waveform_label.setFixedHeight(80)
        self.waveform_label.setStyleSheet(
            "background-color: #2C2C2E; color: #86868B; border-radius: 8px; font-size: 12px;"
        )
        left_layout.addWidget(self.waveform_label)

        # ---------- 右：配置 ----------
        self.right_panel = QWidget()
        right_layout = QVBoxLayout(self.right_panel)
        right_layout.setContentsMargins(15, 0, 0, 0)

        config_group = QGroupBox("系统配置 (Configuration)")
        config_layout = QGridLayout(config_group)
        config_layout.setSpacing(10)
        config_layout.setContentsMargins(20, 25, 20, 20)

        # ---- Row 0: 平台预设 ----
        config_layout.addWidget(QLabel("平台预设:"), 0, 0)
        self.preset_combo = QComboBox()
        preset_names = list(PLATFORM_PRESETS.keys())
        self.preset_combo.addItems(preset_names)
        self.preset_combo.setCurrentText("手动配置")
        self.preset_combo.currentTextChanged.connect(self.on_preset_changed)
        config_layout.addWidget(self.preset_combo, 0, 1, 1, 3)

        # ---- Row 1: 本地视频 ----
        config_layout.addWidget(QLabel("本地视频:"), 1, 0)
        self.input_path = QLineEdit()
        config_layout.addWidget(self.input_path, 1, 1, 1, 2)
        btn_browse = QPushButton("浏览视频")
        btn_browse.clicked.connect(self.browse_video)
        config_layout.addWidget(btn_browse, 1, 3)

        # ---- Row 2: 批量处理 ----
        config_layout.addWidget(QLabel("批量处理:"), 2, 0)
        self.chk_batch = QCheckBox("批量处理整个文件夹")
        self.chk_batch.toggled.connect(self.on_batch_toggled)
        config_layout.addWidget(self.chk_batch, 2, 1)
        self.btn_browse_folder = QPushButton("选择文件夹")
        self.btn_browse_folder.clicked.connect(self.browse_folder)
        self.btn_browse_folder.setVisible(False)
        config_layout.addWidget(self.btn_browse_folder, 2, 2)
        self.lbl_batch_count = QLabel("")
        self.lbl_batch_count.setStyleSheet("color: #86868B;")
        config_layout.addWidget(self.lbl_batch_count, 2, 3)

        # ---- Row 3: 视频裁剪 ----
        config_layout.addWidget(QLabel("视频裁剪:"), 3, 0)
        self.trim_start = QSpinBox()
        self.trim_start.setRange(0, 99999)
        self.trim_start.setSuffix(" 秒 起始")
        self.trim_start.setSpecialValueText("从开头")
        config_layout.addWidget(self.trim_start, 3, 1)
        self.trim_end = QSpinBox()
        self.trim_end.setRange(0, 99999)
        self.trim_end.setSuffix(" 秒 结束")
        self.trim_end.setSpecialValueText("到结尾")
        config_layout.addWidget(self.trim_end, 3, 2, 1, 2)

        # ---- Row 4: 目标语言 ----
        config_layout.addWidget(QLabel("目标语言:"), 4, 0)
        self.audio_lang = QComboBox()
        self.audio_lang.addItems(["中文 (Chinese) - 自动翻译生成", "英文 (English) - 自动翻译生成"])
        config_layout.addWidget(self.audio_lang, 4, 1, 1, 3)

        # ---- Row 5: 画面输出 ----
        config_layout.addWidget(QLabel("画面输出:"), 5, 0)
        self.radio_horizontal = QRadioButton("横屏 (保持原比例)")
        self.radio_vertical = QRadioButton("竖屏 (InsightFace 智能追踪)")
        self.radio_vertical.setChecked(True)
        lay_radio = QHBoxLayout()
        lay_radio.addWidget(self.radio_horizontal)
        lay_radio.addWidget(self.radio_vertical)
        lay_radio.addStretch()
        config_layout.addLayout(lay_radio, 5, 1, 1, 3)
        # ---- Row 6: 输出分辨率 ----
        config_layout.addWidget(QLabel("输出分辨率:"), 6, 0)
        self.res_w_spin = QSpinBox()
        self.res_w_spin.setRange(240, 4320)
        self.res_w_spin.setValue(1080)
        self.res_w_spin.setSuffix(" ×")
        config_layout.addWidget(self.res_w_spin, 6, 1)
        self.res_w_spin.valueChanged.connect(
            lambda v: self._update_aspect_ratio(self.res_w_spin, is_width=True))
        self.res_h_spin = QSpinBox()
        self.res_h_spin.setRange(240, 4320)
        self.res_h_spin.setValue(1920)
        self.res_h_spin.setSuffix(" px")
        config_layout.addWidget(self.res_h_spin, 6, 2)
        self.res_h_spin.valueChanged.connect(
            lambda v: self._update_aspect_ratio(self.res_h_spin, is_width=False))
        self.chk_lock_aspect = QCheckBox("锁定 9:16")
        self.chk_lock_aspect.setChecked(True)
        config_layout.addWidget(self.chk_lock_aspect, 6, 3)
        # 横屏时置灰分辨率控件
        self.radio_horizontal.toggled.connect(self._toggle_resolution_controls)
        self.radio_vertical.toggled.connect(self._toggle_resolution_controls)

        # ---- Row 7: 字幕 ----
        config_layout.addWidget(QLabel("字幕配置:"), 7, 0)
        self.chk_subtitle = QCheckBox("在画面上生成硬字幕")
        self.chk_subtitle.setChecked(True)
        config_layout.addWidget(self.chk_subtitle, 7, 1)
        self.subtitle_offset_spin = QSpinBox()
        self.subtitle_offset_spin.setRange(-2000, 2000)
        self.subtitle_offset_spin.setValue(0)
        self.subtitle_offset_spin.setSuffix(" ms")
        self.subtitle_offset_spin.setSingleStep(100)
        self.subtitle_offset_spin.setToolTip("字幕时间轴整体偏移（负值提前，正值延后）")
        config_layout.addWidget(self.subtitle_offset_spin, 7, 2, 1, 2)

        # ---- Row 8: 字幕样式 ----
        config_layout.addWidget(QLabel("字幕样式:"), 8, 0)
        self.sub_color_combo = QComboBox()
        self.sub_color_combo.addItems(list(SUBTITLE_COLORS.keys()))
        config_layout.addWidget(self.sub_color_combo, 8, 1)

        font_layout = QHBoxLayout()
        font_layout.addWidget(QLabel("字号"))
        self.sub_font_slider = QSlider(Qt.Horizontal)
        self.sub_font_slider.setRange(30, 100)
        self.sub_font_slider.setValue(55)  # 0.055 = 5.5%
        self.sub_font_slider.setTickPosition(QSlider.TicksBelow)
        self.sub_font_slider.setTickInterval(10)
        self.sub_font_label = QLabel("5.5%")
        self.sub_font_slider.valueChanged.connect(
            lambda v: self.sub_font_label.setText(f"{v / 10:.1f}%")
        )
        font_layout.addWidget(self.sub_font_slider)
        font_layout.addWidget(self.sub_font_label)
        config_layout.addLayout(font_layout, 8, 2)

        self.chk_sub_bg = QCheckBox("背景框")
        self.chk_bilingual = QCheckBox("双语字幕")
        sub_checkbox_layout = QHBoxLayout()
        sub_checkbox_layout.addWidget(self.chk_sub_bg)
        sub_checkbox_layout.addWidget(self.chk_bilingual)
        sub_checkbox_layout.addStretch()
        config_layout.addLayout(sub_checkbox_layout, 8, 3)

        # ---- Row 9: 声音 ----
        config_layout.addWidget(QLabel("声音配置:"), 9, 0)
        self.chk_voice_clone = QCheckBox("启用 AI 声音克隆配音 (取消勾选则保留原声)")
        self.chk_voice_clone.setChecked(False)  # 默认保留原声
        config_layout.addWidget(self.chk_voice_clone, 9, 1, 1, 3)

        # ---- Row 10: BGM 保留 ----
        self.chk_bgm_preserve = QCheckBox("分离并保留背景音乐 (需安装 spleeter)")
        config_layout.addWidget(self.chk_bgm_preserve, 10, 1, 1, 3)


        # ---- Row 11: 配音模式 ----
        self.lbl_clone_mode = QLabel("配音模式:")
        config_layout.addWidget(self.lbl_clone_mode, 11, 0)
        self.radio_clone_video = QRadioButton("全部提取视频原声 (自动区分角色)")
        self.radio_clone_upload = QRadioButton("指定本地音频映射 (支持多人覆盖)")
        self.radio_clone_video.setChecked(True)
        self.mode_widget = QWidget()
        mode_layout = QHBoxLayout(self.mode_widget)
        mode_layout.setContentsMargins(0, 0, 0, 0)
        mode_layout.addWidget(self.radio_clone_video)
        mode_layout.addWidget(self.radio_clone_upload)
        mode_layout.addStretch()
        config_layout.addWidget(self.mode_widget, 11, 1, 1, 3)

        # ---- Row 12: 音频上传面板 ----
        self.upload_panel = QWidget()
        upload_layout = QGridLayout(self.upload_panel)
        upload_layout.setContentsMargins(0, 0, 0, 0)
        upload_layout.setSpacing(8)

        upload_layout.addWidget(QLabel("样本一:"), 0, 0)
        self.input_audio_1 = QLineEdit()
        self.input_audio_1.setPlaceholderText("选择音频 (建议5-10秒)")
        upload_layout.addWidget(self.input_audio_1, 0, 1)
        btn_au1 = QPushButton("浏览")
        btn_au1.clicked.connect(lambda: self.browse_audio(self.input_audio_1))
        upload_layout.addWidget(btn_au1, 0, 2)
        self.combo_spk_1 = QComboBox()
        self.combo_spk_1.addItems(["映射至: 角色 0", "映射至: 角色 1"])
        self.combo_spk_1.setCurrentIndex(0)
        upload_layout.addWidget(self.combo_spk_1, 0, 3)

        upload_layout.addWidget(QLabel("样本二:"), 1, 0)
        self.input_audio_2 = QLineEdit()
        self.input_audio_2.setPlaceholderText("选择音频 (可选)")
        upload_layout.addWidget(self.input_audio_2, 1, 1)
        btn_au2 = QPushButton("浏览")
        btn_au2.clicked.connect(lambda: self.browse_audio(self.input_audio_2))
        upload_layout.addWidget(btn_au2, 1, 2)
        self.combo_spk_2 = QComboBox()
        self.combo_spk_2.addItems(["映射至: 角色 0", "映射至: 角色 1"])
        self.combo_spk_2.setCurrentIndex(1)
        upload_layout.addWidget(self.combo_spk_2, 1, 3)

        config_layout.addWidget(self.upload_panel, 12, 0, 1, 4)

        # ---- Row 13: 快速预览 + 编码/帧率 ----
        config_layout.addWidget(QLabel("快速预览:"), 13, 0)
        self.chk_quick_preview = QCheckBox("仅处理前")
        self.quick_preview_sec = QSpinBox()
        self.quick_preview_sec.setRange(5, 120)
        self.quick_preview_sec.setValue(15)
        self.quick_preview_sec.setSuffix(" 秒")
        self.quick_preview_sec.setEnabled(False)
        self.chk_quick_preview.toggled.connect(self.quick_preview_sec.setEnabled)
        preview_layout = QHBoxLayout()
        preview_layout.addWidget(self.chk_quick_preview)
        preview_layout.addWidget(self.quick_preview_sec)
        preview_layout.addStretch()
        config_layout.addLayout(preview_layout, 13, 1, 1, 3)

        config_layout.addWidget(QLabel("编码/帧率:"), 14, 0)
        self.codec_combo = QComboBox()
        self.codec_combo.addItems(["H.264 (MP4)", "H.265 (HEVC)"])
        config_layout.addWidget(self.codec_combo, 14, 1)
        self.fps_spin = QSpinBox()
        self.fps_spin.setRange(15, 120)
        self.fps_spin.setValue(30)
        self.fps_spin.setSuffix(" FPS")
        config_layout.addWidget(self.fps_spin, 14, 2, 1, 2)

        # ---- Row 15: 进度条 ----
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        config_layout.addWidget(self.progress_bar, 15, 0, 1, 4)

        # ---- Row 16: 开始按钮 + 输出操作 ----
        btn_layout = QHBoxLayout()
        self.btn_start = QPushButton("开始执行 (Start Processing)")
        self.btn_start.setFixedHeight(45)
        self.btn_start.clicked.connect(self.start_processing)
        btn_layout.addWidget(self.btn_start, 3)

        self.btn_open_folder = QPushButton("📂 打开文件夹")
        self.btn_open_folder.setFixedHeight(45)
        self.btn_open_folder.clicked.connect(self.open_output_folder)
        self.btn_open_folder.setEnabled(False)
        btn_layout.addWidget(self.btn_open_folder, 1)

        self.btn_preview = QPushButton("▶ 预览视频")
        self.btn_preview.setFixedHeight(45)
        self.btn_preview.clicked.connect(self.preview_output)
        self.btn_preview.setEnabled(False)
        btn_layout.addWidget(self.btn_preview, 1)

        config_layout.addLayout(btn_layout, 16, 0, 1, 4)

        # ---- Row 17: 配置保存/加载 ----
        config_btn_layout = QHBoxLayout()
        self.btn_save_config = QPushButton("💾 保存配置")
        self.btn_save_config.clicked.connect(self.save_config)
        self.btn_load_config = QPushButton("📂 加载配置")
        self.btn_load_config.clicked.connect(self.load_config)
        config_btn_layout.addWidget(self.btn_save_config)
        config_btn_layout.addWidget(self.btn_load_config)
        config_btn_layout.addStretch()
        config_layout.addLayout(config_btn_layout, 17, 0, 1, 4)

        right_layout.addWidget(config_group)

        # ---- 日志 ----
        log_group = QGroupBox("运行日志 (Console)")
        log_layout = QVBoxLayout(log_group)
        self.log_console = QTextEdit()
        self.log_console.setReadOnly(True)
        log_layout.addWidget(self.log_console)
        right_layout.addWidget(log_group)

        main_layout.addWidget(self.left_panel, 4)
        main_layout.addWidget(self.right_panel, 5)

        # 绑定联动
        self.chk_voice_clone.toggled.connect(self.toggle_clone_options)
        self.radio_clone_video.toggled.connect(self.toggle_clone_options)
        self.radio_clone_upload.toggled.connect(self.toggle_clone_options)
        self.toggle_clone_options()

    # -------- 预设切换 --------
    def on_preset_changed(self, preset_name):
        preset = PLATFORM_PRESETS.get(preset_name)
        if not preset or preset_name == "手动配置":
            return

        is_vertical = preset["is_vertical"]
        if is_vertical is True:
            self.radio_vertical.setChecked(True)
        elif is_vertical is False:
            self.radio_horizontal.setChecked(True)

        subtitle_pos = preset["subtitle_pos"]
        if subtitle_pos > 0:
            pass  # 字幕位置在 subtitle_style 里处理，不额外暴露

        codec = preset["codec"]
        if codec:
            idx = self.codec_combo.findText(codec)
            if idx >= 0:
                self.codec_combo.setCurrentIndex(idx)

        fps = preset["fps"]
        if fps > 0:
            self.fps_spin.setValue(fps)

        # 设置分辨率
        ow, oh = preset.get("ow", 0), preset.get("oh", 0)
        if ow > 0 and oh > 0:
            self.res_w_spin.setValue(ow)
            self.res_h_spin.setValue(oh)

        self.log(f"✅ 已应用预设: {preset_name} — {preset['desc']}")

    # -------- 批量模式 --------
    def on_batch_toggled(self, checked):
        self.btn_browse_folder.setVisible(checked)
        self.lbl_batch_count.setVisible(checked)
        if not checked:
            self.lbl_batch_count.setText("")
            self.batch_folder_path = ""

    def browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择视频文件夹")
        if folder:
            self.batch_folder_path = folder
            videos = [f for f in os.listdir(folder) if f.lower().endswith((".mp4", ".mov", ".avi", ".mkv"))]
            self.lbl_batch_count.setText(f"找到 {len(videos)} 个视频")
            self.log(f"📁 批量文件夹: {folder} ({len(videos)} 个视频)")

    # -------- 输出操作 --------
    def open_output_folder(self):
        if self.last_output and os.path.exists(os.path.dirname(self.last_output)):
            subprocess.run(["open", os.path.dirname(self.last_output)])

    def preview_output(self):
        if self.last_output and os.path.exists(self.last_output):
            subprocess.run(["open", self.last_output])

    # -------- 联动 --------
    def toggle_clone_options(self):
        is_clone = self.chk_voice_clone.isChecked()
        self.lbl_clone_mode.setVisible(is_clone)
        self.mode_widget.setVisible(is_clone)

        is_upload = is_clone and self.radio_clone_upload.isChecked()
        self.upload_panel.setVisible(is_upload)

    # -------- 分辨率联动 --------
    def _toggle_resolution_controls(self):
        """横屏时置灰分辨率控件（竖屏才可自定义分辨率）"""
        is_portrait = self.radio_vertical.isChecked()
        self.res_w_spin.setEnabled(is_portrait)
        self.res_h_spin.setEnabled(is_portrait)
        self.chk_lock_aspect.setEnabled(is_portrait)

    def _update_aspect_ratio(self, changed_spin, is_width):
        """锁定比例勾选时，修改宽/高自动按 9:16 等比变化"""
        if not self.chk_lock_aspect.isChecked():
            return
        # 阻止循环触发
        self.res_w_spin.blockSignals(True)
        self.res_h_spin.blockSignals(True)
        try:
            if is_width:
                self.res_h_spin.setValue(int(changed_spin.value() * 16 / 9))
            else:
                self.res_w_spin.setValue(int(changed_spin.value() * 9 / 16))
        finally:
            self.res_w_spin.blockSignals(False)
            self.res_h_spin.blockSignals(False)

    # -------- 样式 --------
    def apply_apple_style(self):
        self.setStyleSheet("""
        QWidget { font-family: "SF Pro Display", sans-serif; font-size: 14px; color: #1D1D1F; background-color: #F5F5F7; }
        QGroupBox { background-color: #FFFFFF; border: 1px solid #E5E5EA; border-radius: 10px; margin-top: 12px; }
        QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; padding: 0 8px; color: #86868B; font-weight: bold; }
        QLineEdit, QComboBox, QSpinBox { border: 1px solid #D2D2D7; border-radius: 6px; padding: 6px 10px; background: #FFF; }
        QPushButton { background-color: #007AFF; color: white; border-radius: 6px; padding: 8px; font-weight: bold; }
        QPushButton:hover { background-color: #0051D5; }
        QPushButton:disabled { background-color: #C7C7CC; }
        QTextEdit { background-color: #1E1E1E; color: #32D74B; font-family: "Menlo", monospace; border-radius: 8px; padding: 10px;}
        QProgressBar { border: 1px solid #D2D2D7; border-radius: 6px; text-align: center; height: 20px; background: #F5F5F7; }
        QProgressBar::chunk { background-color: #007AFF; border-radius: 5px; }
        """)

    # -------- 文件对话框 --------
    def browse_video(self):
        file_name, _ = QFileDialog.getOpenFileName(self, "选择视频文件", "", "Video Files (*.mp4 *.mov)")
        if file_name:
            self.input_path.setText(file_name)
            self.draw_waveform(file_name)

    def browse_audio(self, line_edit):
        file_name, _ = QFileDialog.getOpenFileName(self, "选择音频文件", "", "Audio Files (*.wav *.mp3 *.m4a)")
        if file_name:
            line_edit.setText(file_name)

    # -------- 日志 / 预览 --------
    def log(self, message):
        time_str = time.strftime("%H:%M:%S", time.localtime())
        self.log_console.append(f"[{time_str}] {message}")
        self.log_console.verticalScrollBar().setValue(self.log_console.verticalScrollBar().maximum())

    def update_preview(self, qt_image):
        self.preview_label.setPixmap(
            QPixmap.fromImage(qt_image).scaled(
                self.preview_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
        )

    # -------- 音频波形 --------
    def draw_waveform(self, video_path):
        """提取视频前 10 秒音频，生成波形图"""
        if not video_path or not os.path.exists(video_path):
            self.waveform_label.setText("音频波形 (选择视频后自动生成)")
            return
        if not video_path.lower().endswith((".mp4", ".mov", ".avi", ".mkv")):
            return

        temp_wav = os.path.join(self.output_dir if hasattr(self, 'output_dir') and self.output_dir
                                else os.path.dirname(video_path), "_waveform_temp.wav")
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-i", video_path, "-t", "10",
                 "-acodec", "pcm_s16le", "-ar", "22050", "-ac", "1", temp_wav],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
            )
            with open(temp_wav, "rb") as f:
                data = f.read()
            # 跳过 WAV 头 44 字节，读取 PCM S16LE 样本
            samples = np.frombuffer(data[44:], dtype=np.int16).astype(np.float32)
            if len(samples) > 0:
                self._render_waveform(samples)
        except Exception as e:
            self.log(f"⚠️ 无法生成波形图: {e}")
        finally:
            if os.path.exists(temp_wav):
                try:
                    os.remove(temp_wav)
                except OSError:
                    pass

    def _render_waveform(self, samples, width=640, height=76):
        """将 PCM 样本绘制为波形图"""
        pixmap = QPixmap(width, height)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)

        center_y = height // 2

        # 中心线
        painter.setPen(QColor(80, 80, 80, 160))
        painter.drawLine(0, center_y, width, center_y)

        # 降采样到宽度像素数
        chunk_size = max(1, len(samples) // width)
        if chunk_size > 1:
            truncated = samples[:chunk_size * width]
            display = np.abs(truncated.reshape(-1, chunk_size)).max(axis=1)
        else:
            display = np.abs(samples)

        # 归一化到波形高度
        max_val = max(1, np.max(display))
        display = display / max_val * (center_y - 4)

        # 绘制波形线条
        painter.setPen(QColor(0, 180, 255, 200))
        for x in range(min(width, len(display))):
            h = max(1, int(display[x]))
            painter.drawLine(x, center_y - h, x, center_y + h)

        painter.end()
        self.waveform_label.setPixmap(pixmap)

    # -------- 开始处理 --------
    def start_processing(self):
        # 收集输入源
        batch_files = []
        input_src = self.input_path.text().strip()

        if self.chk_batch.isChecked() and hasattr(self, "batch_folder_path") and self.batch_folder_path:
            all_files = os.listdir(self.batch_folder_path)
            batch_files = sorted([
                os.path.join(self.batch_folder_path, f)
                for f in all_files
                if f.lower().endswith((".mp4", ".mov", ".avi", ".mkv"))
            ])
            if not batch_files:
                return self.log("错误: 文件夹中没有找到视频文件！")
            input_src = batch_files[0]
        else:
            if not input_src:
                return self.log("错误: 请输入本地视频源！")
            if not os.path.exists(input_src):
                return self.log(f"错误: 视频文件不存在: {input_src}")

        # 上传音频校验
        upload_configs = []
        if self.chk_voice_clone.isChecked() and self.radio_clone_upload.isChecked():
            path1 = self.input_audio_1.text().strip()
            path2 = self.input_audio_2.text().strip()
            if path1:
                upload_configs.append({"path": path1, "spk_id": self.combo_spk_1.currentIndex()})
            if path2:
                upload_configs.append({"path": path2, "spk_id": self.combo_spk_2.currentIndex()})
            for cfg in upload_configs:
                if not os.path.exists(cfg["path"]):
                    return self.log(f"错误: 音频文件不存在: {cfg['path']}")
            if not upload_configs:
                return self.log("错误: 已选择上传覆盖模式，但未提供任何有效的音频文件！")

        # 停止已有线程
        if self.thread and self.thread.isRunning():
            self.thread.stop()
            self.btn_start.setText("开始执行 (Start Processing)")
            self.btn_start.setStyleSheet("background-color: #007AFF;")
            return

        # 字幕样式
        subtitle_style = {
            "color": self.sub_color_combo.currentText(),
            "font_size": self.sub_font_slider.value() / 1000.0,
            "bg_enabled": self.chk_sub_bg.isChecked(),
            "bilingual": self.chk_bilingual.isChecked(),
        }

        # 快速预览
        quick_preview_sec = self.quick_preview_sec.value() if self.chk_quick_preview.isChecked() else 0

        # 启动线程
        self.btn_start.setText("停止执行 (Stop)")
        self.btn_start.setStyleSheet("background-color: #FF3B30;")
        self.progress_bar.setValue(0)
        self.btn_open_folder.setEnabled(False)
        self.btn_preview.setEnabled(False)

        self.thread = VideoProcessThread(
            input_source=input_src,
            is_vertical=self.radio_vertical.isChecked(),
            target_lang=self.audio_lang.currentText(),
            codec=self.codec_combo.currentText(),
            fps=self.fps_spin.value(),
            enable_subtitle=self.chk_subtitle.isChecked(),
            enable_voice_clone=self.chk_voice_clone.isChecked(),
            clone_mode=0 if self.radio_clone_video.isChecked() else 1,
            upload_configs=upload_configs,
            trim_start=self.trim_start.value(),
            trim_end=self.trim_end.value(),
            quick_preview_sec=quick_preview_sec,
            subtitle_style=subtitle_style,
            batch_files=batch_files if len(batch_files) > 1 else [],
            output_w=self.res_w_spin.value(),
            output_h=self.res_h_spin.value(),
            subtitle_offset_ms=self.subtitle_offset_spin.value(),
            enable_bgm_preserve=self.chk_bgm_preserve.isChecked(),
        )

        self.thread.update_frame.connect(self.update_preview)
        self.thread.log_msg.connect(self.log)
        self.thread.finished.connect(self.reset_processing_state)
        self.thread.progress_changed.connect(self.progress_bar.setValue)
        self.thread.batch_finished.connect(self.show_batch_summary)
        self.thread.start()

    def reset_processing_state(self):
        if self.thread:
            self.last_output = getattr(self.thread, "final_output", None)
            if self.last_output:
                self.btn_open_folder.setEnabled(True)
                self.btn_preview.setEnabled(True)
        self.btn_start.setText("开始执行 (Start Processing)")
        self.btn_start.setStyleSheet("background-color: #007AFF;")
        self.thread = None

    # -------- 批量摘要 --------
    def show_batch_summary(self, results):
        """批量处理完成后弹出摘要对话框"""
        total = len(results)
        success_count = sum(1 for r in results if r["success"])
        fail_count = total - success_count

        summary_lines = [f"处理完成 ({success_count}/{total})", "",
                         f"✅ 成功: {success_count}", f"❌ 失败: {fail_count}", ""]
        if fail_count > 0:
            summary_lines.append("失败明细:")
            for r in results:
                if not r["success"]:
                    err_msg = r.get("error") or "未知错误"
                    summary_lines.append(f"  · {r['file']} → {err_msg}")
            summary_lines.append("")

        output_dir = ""
        if results and results[0].get("output"):
            output_dir = os.path.dirname(results[0]["output"])
            summary_lines.append(f"📁 输出文件夹: {output_dir}")

        msg = QMessageBox(self)
        msg.setWindowTitle("批量处理完成")
        msg.setText("\n".join(summary_lines))
        msg.setIcon(QMessageBox.Information)
        open_btn = msg.addButton("📂 打开文件夹", QMessageBox.ActionRole)
        msg.addButton("确定", QMessageBox.AcceptRole)
        msg.exec_()

        if msg.clickedButton() == open_btn and output_dir and os.path.exists(output_dir):
            subprocess.run(["open", output_dir])

    # -------- 配置模板保存/加载 --------
    def save_config(self):
        """将当前 UI 控件状态保存为 JSON 模板"""
        config = {
            "version": 2,
            "preset": self.preset_combo.currentText(),
            "video_path": self.input_path.text(),
            "batch_enabled": self.chk_batch.isChecked(),
            "batch_folder": getattr(self, "batch_folder_path", ""),
            "trim_start": self.trim_start.value(),
            "trim_end": self.trim_end.value(),
            "target_lang": self.audio_lang.currentText(),
            "is_vertical": self.radio_vertical.isChecked(),
            "enable_subtitle": self.chk_subtitle.isChecked(),
            "subtitle_color": self.sub_color_combo.currentText(),
            "subtitle_font_size": self.sub_font_slider.value(),
            "subtitle_bg": self.chk_sub_bg.isChecked(),
            "bilingual": self.chk_bilingual.isChecked(),
            "subtitle_offset_ms": self.subtitle_offset_spin.value(),
            "enable_voice_clone": self.chk_voice_clone.isChecked(),
            "clone_mode": 0 if self.radio_clone_video.isChecked() else 1,
            "quick_preview": self.chk_quick_preview.isChecked(),
            "quick_preview_sec": self.quick_preview_sec.value(),
            "codec": self.codec_combo.currentText(),
            "fps": self.fps_spin.value(),
            "output_w": self.res_w_spin.value(),
            "output_h": self.res_h_spin.value(),
            "lock_aspect": self.chk_lock_aspect.isChecked(),
            "bgm_preserve": self.chk_bgm_preserve.isChecked(),
        }
        file_path, _ = QFileDialog.getSaveFileName(self, "保存配置模板", "", "JSON 文件 (*.json)")
        if not file_path:
            return
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            self.log(f"💾 配置已保存: {file_path}")
        except Exception as e:
            self.log(f"❌ 保存配置失败: {e}")

    def load_config(self):
        """从 JSON 模板恢复 UI 控件状态"""
        file_path, _ = QFileDialog.getOpenFileName(self, "加载配置模板", "", "JSON 文件 (*.json)")
        if not file_path:
            return
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                config = json.load(f)
        except Exception as e:
            self.log(f"❌ 加载配置失败: {e}")
            return

        # 恢复所有 UI 控件
        def _restore_combo(widget, key):
            val = config.get(key)
            if val:
                idx = widget.findText(val)
                if idx >= 0:
                    widget.setCurrentIndex(idx)

        _restore_combo(self.preset_combo, "preset")
        self.input_path.setText(config.get("video_path", ""))
        self.chk_batch.setChecked(config.get("batch_enabled", False))
        if config.get("batch_folder"):
            self.batch_folder_path = config["batch_folder"]
            videos = [f for f in os.listdir(config["batch_folder"]) if f.lower().endswith((".mp4", ".mov", ".avi", ".mkv"))]
            self.lbl_batch_count.setText(f"找到 {len(videos)} 个视频")
        self.trim_start.setValue(config.get("trim_start", 0))
        self.trim_end.setValue(config.get("trim_end", 0))

        _restore_combo(self.audio_lang, "target_lang")

        # 画面输出：用 is_vertical 值设置
        is_vert = config.get("is_vertical", True)
        self.radio_vertical.setChecked(is_vert)
        self.radio_horizontal.setChecked(not is_vert)

        self.chk_subtitle.setChecked(config.get("enable_subtitle", True))
        _restore_combo(self.sub_color_combo, "subtitle_color")
        self.sub_font_slider.setValue(config.get("subtitle_font_size", 55))
        self.chk_sub_bg.setChecked(config.get("subtitle_bg", False))
        self.chk_bilingual.setChecked(config.get("bilingual", False))
        self.subtitle_offset_spin.setValue(config.get("subtitle_offset_ms", 0))

        self.chk_voice_clone.setChecked(config.get("enable_voice_clone", False))
        clone_mode = config.get("clone_mode", 0)
        self.radio_clone_video.setChecked(clone_mode == 0)
        self.radio_clone_upload.setChecked(clone_mode == 1)

        self.chk_quick_preview.setChecked(config.get("quick_preview", False))
        self.quick_preview_sec.setValue(config.get("quick_preview_sec", 15))
        _restore_combo(self.codec_combo, "codec")
        self.fps_spin.setValue(config.get("fps", 30))

        self.res_w_spin.setValue(config.get("output_w", 1080))
        self.res_h_spin.setValue(config.get("output_h", 1920))
        self.chk_lock_aspect.setChecked(config.get("lock_aspect", True))
        self.chk_bgm_preserve.setChecked(config.get("bgm_preserve", False))

        self.log(f"📂 配置已加载: {file_path}")

    def closeEvent(self, event):
        if self.thread:
            self.thread.stop()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
