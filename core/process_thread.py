"""视频处理线程 — VideoProcessThread

组合 AudioPipelineMixin + VideoProcessorMixin，作为后台 QThread 运行。
"""

import os
import subprocess
import datetime

from PyQt5.QtCore import pyqtSignal, QThread
from PyQt5.QtGui import QImage
from openai import OpenAI
from insightface.app import FaceAnalysis

from .config import PLATFORM_PRESETS
from .audio_pipeline import AudioPipelineMixin
from .video_processor import VideoProcessorMixin


class VideoProcessThread(QThread, AudioPipelineMixin, VideoProcessorMixin):
    """后台处理线程 — 混入音频管线 + 视频处理能力"""

    update_frame = pyqtSignal(QImage)
    log_msg = pyqtSignal(str)
    finished = pyqtSignal()
    progress_changed = pyqtSignal(int)   # 0-100
    batch_finished = pyqtSignal(list)    # 批量处理完成后发送结果列表

    def __init__(self, input_source, is_vertical, target_lang, codec, fps,
                 enable_subtitle, enable_voice_clone, clone_mode, upload_configs,
                 trim_start=0, trim_end=0, quick_preview_sec=0,
                 subtitle_style=None, batch_files=None,
                 output_w=1080, output_h=1920,
                 subtitle_offset_ms=0,
                 enable_bgm_preserve=False,
                 export_subtitle=False,
                 subtitle_file_path="",
                 enable_edge_tts_first=False,
                 edge_tts_voices=None,
                 highlight_enabled=False,
                 highlight_start_sec=0,
                 highlight_dur_sec=3,
                 bitrate_mbps=4,
                 chapters=None,
                 multi_platforms=None,
                 # ---- LLM / TTS API 配置参数 ----
                 translation_api_key="",
                 translation_base_url="",
                 translation_model="qwen-max",
                 tts_api_key="",
                 cosy_model="cosyvoice-v2",
                 voice_clone_use_separate=False,
                 voice_clone_api_key="",
                 voice_clone_base_url="",
                 voice_clone_model="qwen-max"):
        super().__init__()
        self.input_source = input_source
        self.is_vertical = is_vertical
        self.target_lang = target_lang
        self.fps = fps
        self.codec = codec
        self.bitrate_mbps = bitrate_mbps
        self.enable_subtitle = enable_subtitle
        self.enable_voice_clone = enable_voice_clone
        self.clone_mode = clone_mode
        self.highlight_enabled = highlight_enabled
        self.highlight_start_sec = highlight_start_sec
        self.highlight_dur_sec = highlight_dur_sec
        self.chapters = chapters or []
        self.multi_platforms = multi_platforms or []
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
        self.export_subtitle = export_subtitle
        self.subtitle_file_path = subtitle_file_path
        self.enable_edge_tts_first = enable_edge_tts_first
        self.edge_tts_voices = edge_tts_voices or {}
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

        # 解析有效的 LLM 配置（声音克隆可独立配置）
        if self.enable_voice_clone and voice_clone_use_separate and voice_clone_api_key:
            effective_key = voice_clone_api_key
            effective_url = voice_clone_base_url
            effective_model = voice_clone_model
        else:
            effective_key = translation_api_key
            effective_url = translation_base_url
            effective_model = translation_model

        # 回退到环境变量（兼容旧版 CI/共享机器场景）
        if not effective_key:
            effective_key = os.environ.get("DASHSCOPE_API_KEY", "")
        if not effective_url:
            effective_url = os.environ.get(
                "DASHSCOPE_BASE_URL",
                "https://dashscope.aliyuncs.com/compatible-mode/v1",
            )

        self.llm_client = OpenAI(api_key=effective_key, base_url=effective_url)
        self.llm_model = effective_model
        self.cosy_model = cosy_model
        self.dashscope_api_key = tts_api_key or effective_key

    def prepare_output_env(self, suffix=""):
        """创建输出目录并生成所有临时/最终文件的路径"""
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

    # -------- 入口：单文件或批量 --------

    def run(self):
        """QThread 入口 — 单文件/批量/多平台"""
        self.batch_results = []
        files = self.batch_files if self.batch_files else [self.input_source]
        platforms = self.multi_platforms if self.multi_platforms else [None]

        total_ops = len(files) * len(platforms)
        op_idx = 0

        for file_path in files:
            file_name = os.path.basename(file_path)
            if not self.running:
                break

            cached_ai = None
            orig_input_source = self.input_source

            for plat_name in platforms:
                if not self.running:
                    break
                op_idx += 1

                # 应用平台预设
                if plat_name:
                    preset = PLATFORM_PRESETS.get(plat_name, {})
                    self.is_vertical = preset.get("is_vertical", self.is_vertical)
                    codec = preset.get("codec")
                    if codec:
                        self.codec = codec
                    self.bitrate_mbps = preset.get("bitrate", self.bitrate_mbps)
                    ow = preset.get("ow", 0)
                    oh = preset.get("oh", 0)
                    if ow > 0 and oh > 0:
                        self.output_w = ow
                        self.output_h = oh

                # 输出路径
                safe_name = os.path.splitext(file_name)[0]
                suffix = f"_{safe_name}"
                if plat_name:
                    suffix += f"_{plat_name.replace(' ', '').replace('/', '')}"
                elif len(files) == 1:
                    suffix = ""

                self.input_source = file_path
                self.output_dir, self.temp_video, self.orig_audio, self.final_audio, self.final_output = \
                    self.prepare_output_env(suffix=suffix)
                self.video_writer = None
                self.subtitles_timeline = []
                self.smooth_center_x = None

                if plat_name:
                    self.log_msg.emit(f"\n🎯 多平台 [{op_idx}/{total_ops}]: {file_name} → {plat_name}")
                elif self.batch_files:
                    self.log_msg.emit(f"\n📁 批量处理 [{op_idx}/{total_ops}]: {file_name}")

                result = {"file": file_name, "platform": plat_name, "output": self.final_output,
                          "success": False, "error": None}
                try:
                    if plat_name and cached_ai is not None:
                        self.log_msg.emit("♻️ 复用 AI 管线结果（跳过 Whisper/翻译/TTS）...")
                        import copy
                        self.subtitles_timeline = copy.deepcopy(cached_ai["subtitles_timeline"])
                        self.final_audio = cached_ai["final_audio"]
                        self.input_source = cached_ai["input_source"]
                        self._render_and_merge()
                    else:
                        self._process_single()
                        if plat_name and cached_ai is None:
                            cached_ai = {
                                "subtitles_timeline": [dict(s) for s in self.subtitles_timeline],
                                "final_audio": self.final_audio,
                                "input_source": self.input_source,
                            }

                    if os.path.exists(self.final_output) and os.path.getsize(self.final_output) > 0:
                        result["success"] = True
                    else:
                        result["error"] = "处理未生成输出文件"
                except Exception as e:
                    result["error"] = str(e)
                self.batch_results.append(result)

                if total_ops > 1:
                    self.progress_changed.emit(int(op_idx / total_ops * 100))

        if self.batch_files or self.multi_platforms:
            self.batch_finished.emit(self.batch_results)
        self.finished.emit()

    def stop(self):
        """安全停止线程（8 秒超时后退回 terminate）"""
        self.running = False
        if not self.wait(8000):
            self.log_msg.emit("⚠️ 线程未在 8 秒内退出，正在终止子进程...")
            # 尝试清理由本进程 spawn 的 ffmpeg 子进程，避免僵尸进程
            try:
                subprocess.run(
                    ["pkill", "-P", str(os.getpid()), "-f", "ffmpeg"],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5,
                )
            except Exception:
                pass
            self.log_msg.emit("⚠️ 强制终止线程（输出文件可能不完整，请检查输出目录）")
            self.terminate()
            self.wait()
