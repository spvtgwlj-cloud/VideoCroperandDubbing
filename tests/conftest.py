"""共享 fixtures 和测试工具"""

import os
import sys
import tempfile
import pytest

# 确保项目根目录在 path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ============================================================
# 基础测试数据
# ============================================================

@pytest.fixture
def sample_whisper_segments():
    """模拟 Whisper 识别的原始段落（带静音间隔）"""
    return [
        {"start": 0.0, "end": 2.5, "text": "Hello world"},
        {"start": 5.0, "end": 7.0, "text": "This is a test"},
        {"start": 7.2, "end": 9.5, "text": "Third segment here"},
        {"start": 12.0, "end": 14.0, "text": "Final words"},
    ]


@pytest.fixture
def sample_valid_segments():
    """模拟通过声纹检查的有效段落（含 speaker_id）"""
    return [
        {"start": 0.0, "end": 2.5, "text": "Hello world", "speaker_id": 0},
        {"start": 3.0, "end": 5.0, "text": "I am speaker one", "speaker_id": 0},
        {"start": 5.5, "end": 7.0, "text": "I am speaker two", "speaker_id": 1},
        {"start": 7.5, "end": 9.5, "text": "Back to speaker one", "speaker_id": 0},
    ]


@pytest.fixture
def sample_srt_entries():
    """模拟外部 SRT 导入的条目（文本已人工修改）"""
    return [
        {"start": 0.0, "end": 2.5, "text": "你好世界", "original_text": "Hello world", "speaker_id": 0},
        {"start": 3.0, "end": 5.0, "text": "我是第一位说话者", "original_text": "I am speaker one", "speaker_id": 0},
        {"start": 5.5, "end": 7.0, "text": "我是第二位说话者", "original_text": "I am speaker two", "speaker_id": 0},
        {"start": 7.5, "end": 9.5, "text": "回到第一位", "original_text": "Back to speaker one", "speaker_id": 0},
    ]


@pytest.fixture
def temp_srt_file(sample_srt_entries):
    """创建一个临时 SRT 文件用于测试 parse_srt"""
    from core.subtitle_renderer import subtitles_to_srt
    content = subtitles_to_srt(sample_srt_entries)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".srt", delete=False, encoding="utf-8") as f:
        f.write(content)
        path = f.name
    yield path
    os.unlink(path)


@pytest.fixture
def mock_thread():
    """创建一个 mock VideoProcessThread 用于测试静态方法"""
    from unittest.mock import MagicMock
    mock = MagicMock()
    mock.running = True
    mock.enable_voice_clone = False
    mock.subtitle_file_path = ""
    mock.export_subtitle = True
    mock.subtitles_timeline = []
    mock.subtitle_offset_ms = 0
    mock.quick_preview_sec = 0
    mock.codec = "H.264 (MP4)"
    mock.enable_bgm_preserve = False
    mock.clone_mode = 0
    mock.upload_configs = []
    mock.target_lang = "中文 (Chinese) - 自动翻译生成"
    mock.dashscope_api_key = "test-key"
    mock.cosy_model = "cosyvoice-v2"
    mock.log_msg = MagicMock()
    mock.progress_changed = MagicMock()
    mock.update_frame = MagicMock()
    return mock
