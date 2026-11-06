"""竖屏成片渲染集成测试。"""

import subprocess

import cv2

from core.clip_renderer import render_clip


def _make_video(path):
    subprocess.run([
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "color=c=blue:s=320x240:d=2",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", str(path),
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)


def test_render_clip_vertical_with_bilingual_subtitles(tmp_path):
    source = tmp_path / "in.mp4"
    _make_video(source)
    output = tmp_path / "out.mp4"

    result = render_clip(
        str(source),
        [{
            "start": 0.0,
            "end": 2.0,
            "text": "中文主字幕",
            "original_text": "English secondary",
        }],
        str(output),
        output_w=360,
        output_h=640,
        bitrate_mbps=1,
        vt_available=False,
    )

    assert result == str(output)
    assert output.exists() and output.stat().st_size > 0

    cap = cv2.VideoCapture(str(output))
    assert int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) == 360
    assert int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) == 640
    assert int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) > 0
    cap.release()
