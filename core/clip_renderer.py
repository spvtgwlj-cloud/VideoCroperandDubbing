"""智能切片成片渲染：竖屏人脸运镜 + 双语硬字幕 + 音视频合成。"""

import os
import subprocess

import cv2

from .smart_search import detect_videotoolbox
from .subtitle_renderer import add_subtitle

DEFAULT_SUBTITLE_STYLE = {
    "color": "黄色（推荐）",
    "font_size": 0.048,
    "bg_enabled": False,
    "bilingual": True,
    "secondary_below": True,
    "portrait_margin": 0.25,
}


def _log(callback, message: str) -> None:
    if callback:
        callback(message)


def render_clip(input_video: str, subtitles: list[dict], output_path: str,
                *, face_app=None, output_w: int = 1080,
                output_h: int = 1920, bitrate_mbps: int = 4,
                subtitle_style: dict | None = None,
                vt_available: bool | None = None,
                log_cb=None, progress_cb=None,
                should_stop=None) -> str:
    """把单个切片渲染为竖屏成片。

    subtitles 使用切片内相对时间：
    {"start": 0.0, "end": 2.0, "text": 中文, "original_text": 英文}
    """
    style = dict(DEFAULT_SUBTITLE_STYLE)
    style.update(subtitle_style or {})
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    temp_video = f"{output_path}.render.mp4"
    if os.path.exists(temp_video):
        os.remove(temp_video)

    cap = cv2.VideoCapture(input_video)
    if not cap.isOpened():
        raise RuntimeError(f"无法打开视频: {input_video}")

    fps = cap.get(cv2.CAP_PROP_FPS)
    if not fps or fps <= 0:
        fps = 30.0
    total_frames = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0

    writer = cv2.VideoWriter(
        temp_video, cv2.VideoWriter_fourcc(*"mp4v"), fps,
        (output_w, output_h),
    )
    if not writer.isOpened():
        cap.release()
        raise RuntimeError("无法创建渲染临时视频")

    frame_index = 0
    sub_cursor = 0
    target_center = None
    smooth_center = None
    stopped = False
    last_progress = -1

    try:
        while True:
            if should_stop is not None and should_stop():
                stopped = True
                break
            ret, frame = cap.read()
            if not ret:
                break

            current_time = frame_index / fps
            while (sub_cursor < len(subtitles)
                   and current_time > subtitles[sub_cursor]["end"]):
                sub_cursor += 1
            text = ""
            original_text = ""
            if sub_cursor < len(subtitles):
                subtitle = subtitles[sub_cursor]
                if subtitle["start"] <= current_time <= subtitle["end"]:
                    text = subtitle.get("text", "")
                    original_text = subtitle.get("original_text", "")

            height, width = frame.shape[:2]
            target_w = min(int(height * 9 / 16), width)
            if target_w <= 0:
                target_w = width

            if face_app is not None and frame_index % 4 == 0:
                try:
                    faces = face_app.get(frame)
                    if faces:
                        largest = max(
                            faces,
                            key=lambda face: (
                                (face.bbox[2] - face.bbox[0])
                                * (face.bbox[3] - face.bbox[1])
                            ),
                        )
                        target_center = int(
                            (largest.bbox[0] + largest.bbox[2]) / 2,
                        )
                except Exception:
                    pass
            if target_center is None:
                target_center = width // 2
            if smooth_center is None:
                smooth_center = target_center
            else:
                smooth_center += (target_center - smooth_center) * 0.08

            x1 = int(smooth_center - target_w / 2)
            x2 = x1 + target_w
            if x1 < 0:
                x1, x2 = 0, target_w
            elif x2 > width:
                x1, x2 = width - target_w, width

            crop = frame[:, x1:x2]
            out_frame = cv2.resize(crop, (output_w, output_h))
            out_frame = add_subtitle(
                out_frame, text, original_text,
                enable_subtitle=True, subtitle_style=style,
            )
            writer.write(out_frame)
            frame_index += 1

            if progress_cb is not None and total_frames > 0:
                percent = min(99, int(frame_index / total_frames * 100))
                if percent != last_progress:
                    last_progress = percent
                    progress_cb(percent)
    finally:
        cap.release()
        writer.release()

    if stopped:
        if os.path.exists(temp_video):
            os.remove(temp_video)
        return ""

    if frame_index == 0:
        if os.path.exists(temp_video):
            os.remove(temp_video)
        raise RuntimeError("切片没有可渲染的画面")

    if vt_available is None:
        vt_available = detect_videotoolbox()
    vcodec = "h264_videotoolbox" if vt_available else "libx264"
    _log(log_cb, "正在合成竖屏成片...")
    cmd = [
        "ffmpeg", "-y",
        "-i", temp_video,
        "-i", input_video,
        "-map", "0:v:0",
        "-map", "1:a:0?",
        "-c:v", vcodec,
        "-b:v", f"{bitrate_mbps}M",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        "-shortest",
        output_path,
    ]
    try:
        result = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr or "ffmpeg 合成失败")
    finally:
        if os.path.exists(temp_video):
            os.remove(temp_video)

    if progress_cb is not None:
        progress_cb(100)
    if not os.path.exists(output_path) or os.path.getsize(output_path) <= 0:
        raise RuntimeError("未生成有效的竖屏成片")
    _log(log_cb, f"✅ 成片已生成: {os.path.basename(output_path)}")
    return output_path
