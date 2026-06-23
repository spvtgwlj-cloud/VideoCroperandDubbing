"""视频处理模块 — SRT 导入/导出守卫测试"""

import os
import tempfile
import pytest
from unittest.mock import MagicMock, patch
from core.video_processor import VideoProcessorMixin


class MockThread(VideoProcessorMixin):
    """不实例化完整 QThread，仅测试 Mixin 方法"""

    def __init__(self):
        self.subtitles_timeline = []
        self.final_output = ""
        self.log_msg = MagicMock()
        self.enable_voice_clone = False
        self.subtitle_file_path = ""
        self.export_subtitle = True

class TestExportSrt:
    """_export_srt 守卫测试"""

    @pytest.fixture
    def thread(self):
        t = MockThread()
        t.final_output = os.path.join(tempfile.gettempdir(), "test_output.mp4")
        return t

    def test_empty_timeline_skipped(self, thread):
        """空 timeline 不写文件"""
        thread.subtitles_timeline = []
        thread._export_srt()
        thread.log_msg.emit.assert_called()
        call_args = [c[0][0] for c in thread.log_msg.emit.call_args_list]
        assert any("跳过 SRT 导出" in str(a) for a in call_args)

    def test_empty_timeline_no_file_created(self, thread):
        """空 timeline 不创建文件"""
        srt_path = os.path.splitext(thread.final_output)[0] + ".srt"
        # 确保文件不存在
        if os.path.exists(srt_path):
            os.unlink(srt_path)
        thread.subtitles_timeline = []
        thread._export_srt()
        assert not os.path.exists(srt_path)

    def test_valid_timeline_creates_file(self, thread):
        """有效 timeline 创建 SRT 文件"""
        thread.subtitles_timeline = [
            {"start": 0.0, "end": 2.0, "text": "Hello", "original_text": "Hi"},
        ]
        thread._export_srt()
        srt_path = os.path.splitext(thread.final_output)[0] + ".srt"
        assert os.path.exists(srt_path)
        with open(srt_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "Hello" in content
        assert "##ORIG## Hi" in content
        os.unlink(srt_path)

    def test_valid_timeline_non_empty_srt(self, thread):
        """导出后 SRT 文件内容大于 0"""
        thread.subtitles_timeline = [
            {"start": 0.0, "end": 1.0, "text": "Test"},
        ]
        thread._export_srt()
        srt_path = os.path.splitext(thread.final_output)[0] + ".srt"
        assert os.path.getsize(srt_path) > 0
        os.unlink(srt_path)

    def test_export_logs_count(self, thread):
        """日志中显示导出条数"""
        thread.subtitles_timeline = [
            {"start": 0.0, "end": 1.0, "text": "A"},
            {"start": 1.0, "end": 2.0, "text": "B"},
        ]
        thread._export_srt()
        srt_path = os.path.splitext(thread.final_output)[0] + ".srt"
        call_args = [c[0][0] for c in thread.log_msg.emit.call_args_list]
        assert any("2 条" in str(a) for a in call_args)
        os.unlink(srt_path)


class TestLoadExternalSubtitles:
    """_load_external_subtitles 测试"""

    @pytest.fixture
    def thread(self):
        return MockThread()

    def test_nonexistent_file(self, thread):
        """文件不存在时不修改 timeline"""
        thread.subtitles_timeline = [{"start": 0, "end": 1, "text": "keep"}]
        thread._load_external_subtitles("/nonexistent/path.srt")
        assert len(thread.subtitles_timeline) == 1
        assert thread.subtitles_timeline[0]["text"] == "keep"

    def test_empty_file(self, thread):
        """空 SRT 文件不替换已有 timeline"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".srt", delete=False, encoding="utf-8") as f:
            f.write("")
            path = f.name
        try:
            thread.subtitles_timeline = [{"start": 0, "end": 1, "text": "keep"}]
            thread._load_external_subtitles(path)
            assert len(thread.subtitles_timeline) == 1
        finally:
            os.unlink(path)

    def test_valid_file_replaces_timeline(self, thread):
        """有效 SRT 替换 timeline"""
        from core.subtitle_renderer import subtitles_to_srt
        new_subs = [
            {"start": 0.0, "end": 2.0, "text": "New text", "original_text": "Orig"},
        ]
        content = subtitles_to_srt(new_subs)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".srt", delete=False, encoding="utf-8") as f:
            f.write(content)
            path = f.name
        try:
            thread.subtitles_timeline = [{"start": 0, "end": 1, "text": "old"}]
            thread._load_external_subtitles(path)
            assert len(thread.subtitles_timeline) == 1
            assert thread.subtitles_timeline[0]["text"] == "New text"
            assert thread.subtitles_timeline[0]["speaker_id"] == 0  # parse_srt 行为
        finally:
            os.unlink(path)
