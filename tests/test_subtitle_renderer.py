"""字幕渲染模块 — 纯函数单元测试"""

import os
import pytest
from core.subtitle_renderer import (
    _srt_time_str,
    subtitles_to_srt,
    parse_srt,
)


class TestSrtTimeStr:
    """时间格式转换"""

    def test_zero_seconds(self):
        assert _srt_time_str(0.0) == "00:00:00,000"

    def test_regular_time(self):
        assert _srt_time_str(65.123) == "00:01:05,123"

    def test_millisecond_rounding(self):
        assert _srt_time_str(1.999) == "00:00:01,999"

    def test_one_hour(self):
        assert _srt_time_str(3600.5) == "01:00:00,500"

    def test_fractional_below_ms(self):
        result = _srt_time_str(0.0004)
        assert result == "00:00:00,000"


class TestSubtitlesToSrt:
    """SRT 格式导出"""

    def test_empty_list(self):
        assert subtitles_to_srt([]) == ""

    def test_single_entry_no_original(self):
        subs = [{"start": 1.5, "end": 3.2, "text": "Hello"}]
        result = subtitles_to_srt(subs)
        lines = result.split("\n")
        assert lines[0] == "1"
        assert "00:00:01,500 --> 00:00:03,200" in lines[1]
        assert lines[2] == "Hello"

    def test_single_entry_with_original(self):
        subs = [{"start": 0.0, "end": 2.0, "text": "你好", "original_text": "Hello"}]
        result = subtitles_to_srt(subs)
        assert "##ORIG## Hello" in result

    def test_original_equals_text_skipped(self):
        """原文与译文相同时不输出 ##ORIG## 标记"""
        subs = [{"start": 0.0, "end": 1.0, "text": "Same", "original_text": "Same"}]
        result = subtitles_to_srt(subs)
        assert "##ORIG##" not in result

    def test_empty_text_fields(self):
        """空 text 字段仍输出索引和时间戳"""
        subs = [{"start": 0.0, "end": 1.0, "text": "", "original_text": ""}]
        result = subtitles_to_srt(subs)
        # 不应为空字符串（有索引和时间戳）
        assert result != ""
        assert "00:00:00,000 --> 00:00:01,000" in result

    def test_multiple_entries(self):
        subs = [
            {"start": 0.0, "end": 2.0, "text": "A", "original_text": "a"},
            {"start": 3.0, "end": 5.0, "text": "B"},
        ]
        result = subtitles_to_srt(subs)
        assert "1\n" in result
        assert "2\n" in result

    def test_missing_text_key(self):
        """text key 缺失时使用空字符串"""
        subs = [{"start": 0.0, "end": 1.0}]
        result = subtitles_to_srt(subs)
        assert "00:00:00,000 --> 00:00:01,000" in result


class TestParseSrt:
    """SRT 格式解析"""

    def test_roundtrip(self, temp_srt_file, sample_srt_entries):
        """导出 → 导入 完整性"""
        parsed = parse_srt(temp_srt_file)
        assert len(parsed) == len(sample_srt_entries)
        for i, entry in enumerate(parsed):
            assert entry["text"] == sample_srt_entries[i]["text"]
            assert entry["original_text"] == sample_srt_entries[i]["original_text"]
            assert abs(entry["start"] - sample_srt_entries[i]["start"]) < 0.001
            assert abs(entry["end"] - sample_srt_entries[i]["end"]) < 0.001

    def test_speaker_id_always_zero(self, temp_srt_file):
        """parse_srt 总是设置 speaker_id=0"""
        parsed = parse_srt(temp_srt_file)
        for entry in parsed:
            assert entry["speaker_id"] == 0

    def test_no_original_text(self):
        """无 ##ORIG## 标记时 original_text 为空"""
        srt_content = (
            "1\n"
            "00:00:01,000 --> 00:00:02,000\n"
            "Plain text\n\n"
        )
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".srt", delete=False, encoding="utf-8") as f:
            f.write(srt_content)
            path = f.name
        try:
            parsed = parse_srt(path)
            assert len(parsed) == 1
            assert parsed[0]["text"] == "Plain text"
            assert parsed[0]["original_text"] == ""
        finally:
            os.unlink(path)

    def test_multiline_text(self):
        """多行字幕文本正确合并"""
        srt_content = (
            "1\n"
            "00:00:01,000 --> 00:00:03,000\n"
            "Line one\n"
            "Line two\n\n"
        )
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".srt", delete=False, encoding="utf-8") as f:
            f.write(srt_content)
            path = f.name
        try:
            parsed = parse_srt(path)
            assert parsed[0]["text"] == "Line one Line two"
        finally:
            os.unlink(path)

    def test_comma_separator(self):
        """逗号分隔的毫秒也可解析"""
        srt_content = (
            "1\n"
            "00:00:01,500 --> 00:00:03,200\n"
            "Test\n\n"
        )
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".srt", delete=False, encoding="utf-8") as f:
            f.write(srt_content)
            path = f.name
        try:
            parsed = parse_srt(path)
            assert parsed[0]["start"] == 1.5
            assert parsed[0]["end"] == 3.2
        finally:
            os.unlink(path)

    def test_empty_file(self):
        """空 SRT 文件返回空列表"""
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".srt", delete=False, encoding="utf-8") as f:
            f.write("")
            path = f.name
        try:
            parsed = parse_srt(path)
            assert parsed == []
        finally:
            os.unlink(path)
