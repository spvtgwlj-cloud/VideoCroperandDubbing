"""视频处理模块 — 作为 Mixin 混入 VideoProcessThread

包含单视频帧渲染、人脸追踪、音视频合成。
"""

import os
import subprocess

import cv2
import numpy as np
from PyQt5.QtGui import QImage

from .subtitle_renderer import add_subtitle as _render_subtitle
from .subtitle_renderer import subtitles_to_srt, parse_srt


class VideoProcessorMixin:
    """视频处理 Mixin — 混入 VideoProcessThread 后共享 self.* 属性"""

    # -------- 字幕叠加（代理到 subtitle_renderer 模块） --------

    def add_subtitle(self, frame, text, original_text=""):
        """将字幕渲染到视频帧上"""
        return _render_subtitle(
            frame, text, original_text,
            enable_subtitle=self.enable_subtitle,
            subtitle_style=self.subtitle_style,
        )

    # -------- 编码器探测 ----------

    _vt_available = None  # 类级别缓存

    @classmethod
    def _check_videotoolbox_available(cls):
        """探测当前 ffmpeg 是否支持 VideoToolbox 硬件编码器（结果缓存）"""
        if cls._vt_available is not None:
            return cls._vt_available
        try:
            result = subprocess.run(
                ["ffmpeg", "-encoders"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            cls._vt_available = "videotoolbox" in result.stdout
        except Exception:
            cls._vt_available = False
        return cls._vt_available

    # -------- 音视频合成 --------

    def merge_audio_video(self):
        """用 FFmpeg 合成最终音视频文件（优先 VideoToolbox，不可用时回退软件编码）"""
        is_h265 = "H.265" in self.codec
        vt_ok = self._check_videotoolbox_available()

        if vt_ok:
            v_codec = "hevc_videotoolbox" if is_h265 else "h264_videotoolbox"
            accel_tag = "Hardware (VideoToolbox)"
        else:
            v_codec = "libx265" if is_h265 else "libx264"
            accel_tag = "Software (libx264/5)"

        self.log_msg.emit(f"正在合成最终的音视频文件 [{accel_tag}]...")

        cmd = [
            "ffmpeg", "-y",
            "-i", self.temp_video,
            "-i", self.final_audio,
            "-c:v", v_codec,
            "-pix_fmt", "yuv420p",
            "-b:v", f"{self.bitrate_mbps}M",
            "-c:a", "aac", "-ac", "2", "-b:a", "256k",
            "-map", "0:v:0", "-map", "1:a:0",
        ]
        # 容器级选项必须在 -map 之后（mp4 muxer 参数）
        if is_h265:
            cmd.extend(["-tag:v", "hvc1", "-movflags", "+faststart"])
        cmd.extend(["-shortest", self.final_output])

        try:
            subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
            self.log_msg.emit(f"✅ 音视频合成成功 ({accel_tag})！")
            # 多平台模式保留 final_audio 供后续平台复用
            cleanup_files = [self.temp_video, self.orig_audio]
            if not getattr(self, "multi_platforms", []):
                cleanup_files.append(self.final_audio)
            for f in cleanup_files:
                if os.path.exists(f):
                    os.remove(f)
        except subprocess.CalledProcessError as e:
            error_details = e.stderr[-500:] if e.stderr else "未知 FFmpeg 错误"
            self.log_msg.emit(f"❌ 音视频合成失败 (错误码 {e.returncode}): {error_details}")
        except Exception as e:
            self.log_msg.emit(f"❌ 音视频合成发生异常: {e}")

    # -------- 视频爆点（片头截取 + 拼接） --------

    def _prepend_highlight(self):
        """从处理后视频中截取片段，用 concat filter 拼接到视频最前面"""
        highlight_clip = os.path.join(self.output_dir, "highlight_clip.mp4")
        merged_output = os.path.join(self.output_dir, "merged_final.mp4")

        # 编码器（H.265 硬编码/H.264 硬编码优先）
        is_h265 = "H.265" in self.codec
        vt_ok = self._check_videotoolbox_available()
        v_codec = ("hevc_videotoolbox" if is_h265 else "h264_videotoolbox") if vt_ok else ("libx265" if is_h265 else "libx264")

        try:
            # Step 1: 从 final_output 截取片段
            self.log_msg.emit(
                f"🔥 视频爆点: 从第 {self.highlight_start_sec} 秒截取 {self.highlight_dur_sec} 秒片头..."
            )
            step1 = ["ffmpeg", "-y",
                     "-i", self.final_output,
                     "-ss", str(self.highlight_start_sec),
                     "-t", str(self.highlight_dur_sec),
                     "-c:v", v_codec, "-b:v", f"{self.bitrate_mbps}M",
                     "-c:a", "aac", "-b:a", "256k",
                     "-pix_fmt", "yuv420p",
                     "-map", "0:v:0", "-map", "0:a:0"]
            if is_h265:
                step1.extend(["-tag:v", "hvc1", "-movflags", "+faststart"])
            step1.append(highlight_clip)
            subprocess.run(step1, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

            # Step 2: concat filter 拼接
            step2 = ["ffmpeg", "-y",
                     "-i", highlight_clip,
                     "-i", self.final_output,
                     "-filter_complex",
                     "[0:v][0:a][1:v][1:a]concat=n=2:v=1:a=1[outv][outa]",
                     "-map", "[outv]", "-map", "[outa]",
                     "-c:v", v_codec, "-b:v", f"{self.bitrate_mbps}M",
                     "-c:a", "aac", "-b:a", "256k",
                     "-pix_fmt", "yuv420p"]
            if is_h265:
                step2.extend(["-tag:v", "hvc1", "-movflags", "+faststart"])
            step2.append(merged_output)
            subprocess.run(step2, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

            # Step 3: 替换原文件
            os.remove(self.final_output)
            os.rename(merged_output, self.final_output)
            self.log_msg.emit("✅ 视频爆点片头已添加到视频最前面")

        except subprocess.CalledProcessError as e:
            self.log_msg.emit(f"⚠️ 视频爆点处理失败: {e.stderr[-200:] if e.stderr else str(e)}")
        finally:
            if os.path.exists(highlight_clip):
                try:
                    os.remove(highlight_clip)
                except OSError:
                    pass

    # -------- 字幕导出 & 外部字幕加载 --------

    def _export_srt(self):
        """将 self.subtitles_timeline 导出为 SRT 文件到输出目录"""
        if not self.subtitles_timeline:
            self.log_msg.emit("⚠️ 字幕时间轴为空，跳过 SRT 导出（可能未检测到语音或所有段落过滤）")
            return
        srt_path = os.path.splitext(self.final_output)[0] + ".srt"
        try:
            srt_content = subtitles_to_srt(self.subtitles_timeline)
            if not srt_content.strip():
                self.log_msg.emit("⚠️ 生成的 SRT 内容为空，跳过写入")
                return
            with open(srt_path, "w", encoding="utf-8") as f:
                f.write(srt_content)
            self.log_msg.emit(f"📄 字幕已导出 ({len(self.subtitles_timeline)} 条): {os.path.basename(srt_path)}")
        except Exception as e:
            self.log_msg.emit(f"⚠️ 字幕导出失败: {e}")

    def _load_external_subtitles(self, srt_path):
        """从外部 SRT 文件加载字幕，替换 self.subtitles_timeline"""
        if not srt_path or not os.path.exists(srt_path):
            self.log_msg.emit(f"⚠️ 外部字幕文件不存在: {srt_path}")
            return
        try:
            loaded = parse_srt(srt_path)
            if not loaded:
                self.log_msg.emit("⚠️ 外部字幕文件内容为空，继续使用自动生成字幕")
                return
            count = len(loaded)
            self.subtitles_timeline = loaded
            self.log_msg.emit(f"📂 已加载外部字幕文件 ({count} 条): {os.path.basename(srt_path)}")
        except Exception as e:
            self.log_msg.emit(f"⚠️ 外部字幕文件解析失败: {e}，继续使用自动生成字幕")

    # -------- 单视频处理 --------

    def _process_single(self):
        """处理一个视频的内部逻辑（渲染 + 字幕 + 合成）"""
        # ---- 视频裁剪预处理（所有路径共享） ----
        temp_trim_path = None
        if self.trim_start > 0 or self.trim_end > 0:
            if not self.running:
                return
            self.log_msg.emit(
                f"✂️ 正在裁剪视频: 从第 {self.trim_start} 秒 → 到第 {self.trim_end or '结尾'} 秒"
            )
            temp_trim_path = os.path.join(self.output_dir, "temp_trimmed.mp4")
            cmd = ["ffmpeg", "-y"]
            if self.trim_start > 0:
                cmd.extend(["-ss", str(self.trim_start)])
            if self.trim_end > 0:
                cmd.extend(["-to", str(self.trim_end)])
            cmd.extend(["-i", self.input_source])
            cmd.extend(["-c", "copy", temp_trim_path])
            try:
                subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
                self.input_source = temp_trim_path
            except subprocess.CalledProcessError as e:
                self.log_msg.emit(f"⚠️ 视频裁剪失败，使用原始视频: {e.stderr[-200:] if e.stderr else ''}")
            # 裁剪子进程可能持续很久，检查用户是否已停止
            if not self.running:
                if temp_trim_path and os.path.exists(temp_trim_path):
                    try:
                        os.remove(temp_trim_path)
                    except OSError:
                        pass
                return

        # ---- 确定处理路径 ----
        srt_driven = self.subtitle_file_path and self.enable_voice_clone

        # Path A: 外部字幕 + 保留原声 — 跳过 AI 管线，直出渲染
        if self.subtitle_file_path and not self.enable_voice_clone:
            self._load_external_subtitles(self.subtitle_file_path)
            if not self.subtitles_timeline:
                self.log_msg.emit("❌ 外部字幕加载失败或内容为空，终止处理")
                if temp_trim_path and os.path.exists(temp_trim_path):
                    os.remove(temp_trim_path)
                return
            self.log_msg.emit("ℹ️ 已加载外部字幕，跳过 AI 管线（Whisper/翻译/TTS/声纹分离）...")
            self.log_msg.emit("正在提取原始音频...")
            try:
                subprocess.run(
                    ["ffmpeg", "-y", "-i", self.input_source, "-vn",
                     "-acodec", "pcm_s16le", "-ar", "48000", "-ac", "2",
                     self.final_audio],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
                )
            except subprocess.CalledProcessError:
                self.log_msg.emit("❌ 音频提取失败！")
                if temp_trim_path and os.path.exists(temp_trim_path):
                    os.remove(temp_trim_path)
                return
            self.progress_changed.emit(70)

        # Path B: 外部 SRT + 声音克隆 — SRT 驱动 TTS，跳过 LLM 翻译
        # Path C: 标准 AI 管线（无外部 SRT，或仅有声音克隆）
        else:
            srt_entries = None
            if srt_driven:
                self._load_external_subtitles(self.subtitle_file_path)
                if self.subtitles_timeline:
                    srt_entries = self.subtitles_timeline
                    self.log_msg.emit(
                        f"📂 外部 SRT + 声纹克隆：已加载 {len(srt_entries)} 条字幕，"
                        "将跳过 LLM 翻译，直接使用 SRT 时间戳驱动 TTS 生成"
                    )

            try:
                if not self.run_ai_pipeline(srt_timeline=srt_entries):
                    if temp_trim_path and os.path.exists(temp_trim_path):
                        os.remove(temp_trim_path)
                    return
            except Exception as e:
                self.log_msg.emit(f"AI 管线异常: {e}")
                if temp_trim_path and os.path.exists(temp_trim_path):
                    os.remove(temp_trim_path)
                return

            # 字幕导出（仅 AI 生成的才导出；SRT 驱动模式下不覆盖用户的 SRT）
            if self.export_subtitle and not srt_driven:
                self._export_srt()

        self.log_msg.emit("开始画面裁切渲染与动态字幕处理...")
        # 外部字幕路径：70→75（前进）；AI管线路径：70→75（前进）
        self.progress_changed.emit(75)
        cap = cv2.VideoCapture(self.input_source)
        orig_fps = cap.get(cv2.CAP_PROP_FPS)
        if orig_fps == 0 or np.isnan(orig_fps):
            orig_fps = self.fps

        # 获取视频总时长（用于进度条 + 章节）
        total_frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        total_duration = total_frames / orig_fps if orig_fps > 0 else 0.0

        frame_count, last_target_center_x, sub_cursor = 0, None, 0

        # 将时间和章节注入 style dict（渲染器每帧读取）
        self.subtitle_style["_total_duration"] = total_duration
        self.subtitle_style["_chapters"] = getattr(self, "chapters", [])

        # 快速预览：最多处理的帧数
        max_frames = 0
        if self.quick_preview_sec > 0:
            max_frames = int(orig_fps * self.quick_preview_sec)

        while self.running:
            ret, frame = cap.read()
            if not ret:
                break

            current_time = frame_count / orig_fps
            self.subtitle_style["_current_time"] = current_time
            if self.quick_preview_sec > 0 and current_time > self.quick_preview_sec:
                break

            # 游标推进：跳过已结束的字幕段（O(1) 摊还，替代全量扫描）
            while sub_cursor < len(self.subtitles_timeline) and current_time > self.subtitles_timeline[sub_cursor]["end"]:
                sub_cursor += 1

            current_text = ""
            current_orig = ""
            if sub_cursor < len(self.subtitles_timeline):
                sub = self.subtitles_timeline[sub_cursor]
                if sub["start"] <= current_time <= sub["end"]:
                    current_text = sub["text"]
                    current_orig = sub.get("original_text", "")

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
            # 视频爆点：截取片头 → 拼接到最前面
            if self.highlight_enabled:
                self._prepend_highlight()
            self.progress_changed.emit(100)
            self.log_msg.emit(f"🎉 全部处理完成！文件保存在: {self.final_output}")
        # 清理裁剪临时文件（多平台模式保留，后续平台复用）
        if temp_trim_path and os.path.exists(temp_trim_path) and not getattr(self, "multi_platforms", []):
            try:
                os.remove(temp_trim_path)
            except OSError:
                pass

    # -------- 画面渲染 + 合成（多平台复用：跳过 AI 管线） --------

    def _render_and_merge(self):
        """仅做画面渲染 + 音视频合成（复用已有的 subtitles_timeline + final_audio）"""
        self.log_msg.emit("开始画面裁切渲染与动态字幕处理...")
        self.progress_changed.emit(75)
        cap = cv2.VideoCapture(self.input_source)
        orig_fps = cap.get(cv2.CAP_PROP_FPS)
        if orig_fps == 0 or np.isnan(orig_fps):
            orig_fps = self.fps

        total_frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        total_duration = total_frames / orig_fps if orig_fps > 0 else 0.0

        frame_count, last_target_center_x, sub_cursor = 0, None, 0
        self.subtitle_style["_total_duration"] = total_duration
        self.subtitle_style["_chapters"] = getattr(self, "chapters", [])

        max_frames = 0
        if self.quick_preview_sec > 0:
            max_frames = int(orig_fps * self.quick_preview_sec)

        while self.running:
            ret, frame = cap.read()
            if not ret:
                break
            current_time = frame_count / orig_fps
            self.subtitle_style["_current_time"] = current_time
            if self.quick_preview_sec > 0 and current_time > self.quick_preview_sec:
                break
            while sub_cursor < len(self.subtitles_timeline) and current_time > self.subtitles_timeline[sub_cursor]["end"]:
                sub_cursor += 1
            current_text = ""
            current_orig = ""
            if sub_cursor < len(self.subtitles_timeline):
                sub = self.subtitles_timeline[sub_cursor]
                if sub["start"] <= current_time <= sub["end"]:
                    current_text = sub["text"]
                    current_orig = sub.get("original_text", "")

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
                self.update_frame.emit(QImage(rgb_image.data, rgb_image.shape[1], rgb_image.shape[0],
                                             rgb_image.shape[2] * rgb_image.shape[1], QImage.Format_RGB888))
            frame_count += 1

        cap.release()
        if self.video_writer:
            self.video_writer.release()

        self.progress_changed.emit(90)
        if self.running:
            self.merge_audio_video()
            if self.highlight_enabled:
                self._prepend_highlight()
            self.progress_changed.emit(100)
            self.log_msg.emit(f"🎉 全部处理完成！文件保存在: {self.final_output}")
