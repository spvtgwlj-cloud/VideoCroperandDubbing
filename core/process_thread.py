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

from .config import DASHSCOPE_API_KEY, AI_BASE_URL
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
                 chapters=None):
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
        self.llm_client = OpenAI(api_key=DASHSCOPE_API_KEY, base_url=AI_BASE_URL)

        self.cosy_model = "cosyvoice-v2"
        self.dashscope_api_key = DASHSCOPE_API_KEY

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
        """QThread 入口 — 单文件或批量处理"""
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
