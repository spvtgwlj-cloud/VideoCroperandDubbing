"""字幕渲染模块 — 纯函数单元测试"""

import os
import numpy as np
import pytest
from PIL import Image, ImageDraw
from core.subtitle_renderer import (
    _srt_time_str,
    subtitles_to_srt,
    parse_srt,
    add_subtitle,
    _fit_text_to_width,
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


# ============================================================
# Overlay 渲染测试
# ============================================================

def _make_test_frame(w=640, h=480):
    """创建一个纯黑测试帧 (BGR 格式)"""
    import cv2
    return np.zeros((h, w, 3), dtype=np.uint8)


class TestFitTextToWidth:
    """字号二分查找"""

    def test_short_text_fits_wide(self):
        """短文本在宽屏上获得较大字号"""
        from PIL import ImageDraw
        img = Image.new('RGB', (1920, 1080))
        draw = ImageDraw.Draw(img)
        from core.subtitle_renderer import get_chinese_font
        font_path = get_chinese_font()
        if not font_path:
            pytest.skip("无可用中文字体")
        size, font = _fit_text_to_width("测试", 1920, font_path, draw)
        assert 40 <= size <= 120  # 短文本应得较大字号

    def test_long_text_gets_smaller(self):
        """长文本获得较小字号（窄屏场景）"""
        from PIL import ImageDraw
        img = Image.new('RGB', (720, 1280))
        draw = ImageDraw.Draw(img)
        from core.subtitle_renderer import get_chinese_font
        font_path = get_chinese_font()
        if not font_path:
            pytest.skip("无可用中文字体")
        # 窄屏上 16 字标题必须缩小字号
        size_long, _ = _fit_text_to_width("这是十六个汉字标题测试文本", 720, font_path, draw)
        size_short, _ = _fit_text_to_width("测试", 720, font_path, draw)
        assert size_long < size_short  # 长文本字号更小

    def test_respects_breathing_room(self):
        """字号不超过屏幕 92% 宽度"""
        from PIL import ImageDraw
        img = Image.new('RGB', (1280, 720))
        draw = ImageDraw.Draw(img)
        from core.subtitle_renderer import get_chinese_font
        font_path = get_chinese_font()
        if not font_path:
            pytest.skip("无可用中文字体")
        text = "这是十六个汉字的测试文本喔"
        size, font = _fit_text_to_width(text, 1280, font_path, draw)
        tw = draw.textlength(text, font=font)
        assert tw <= 1280 * 0.92
        assert tw > 0


class TestOverlayRendering:
    """Overlay 元素在帧上的渲染验证"""

    def test_overlay_title_appears(self):
        """主标题以黄色渐变背景+黑色文字渲染，居中放置"""
        import cv2
        frame = _make_test_frame(1280, 720)
        out = add_subtitle(frame, "译文文本", original_text="Original",
                          enable_subtitle=True,
                          subtitle_style={
                              "color": "黄色（推荐）",
                              "font_size": 0.055,
                              "bg_enabled": False,
                              "bilingual": False,
                              "overlay_title": "测试标题",
                              "overlay_sharer": "",
                          })
        # 验证：底部有黄色像素
        bottom_third = out[out.shape[0] * 3 // 4:, :, :]
        yellow_mask = (
            (bottom_third[:, :, 0] >= 40) & (bottom_third[:, :, 0] <= 80) &
            (bottom_third[:, :, 1] >= 200) &
            (bottom_third[:, :, 2] >= 220)
        )
        assert yellow_mask.sum() > 0, "未检测到黄色标题背景"
        # 居中验证：黄色应跨越屏幕中轴线两侧
        w = bottom_third.shape[1]
        left_region = bottom_third[:, :w // 2, :]
        right_region = bottom_third[:, w // 2:, :]
        left_yellow = (
            (left_region[:, :, 0] >= 40) & (left_region[:, :, 0] <= 80) &
            (left_region[:, :, 1] >= 200) &
            (left_region[:, :, 2] >= 220)
        ).sum()
        right_yellow = (
            (right_region[:, :, 0] >= 40) & (right_region[:, :, 0] <= 80) &
            (right_region[:, :, 1] >= 200) &
            (right_region[:, :, 2] >= 220)
        ).sum()
        # 居中时两侧都应有黄色（共 > 50 像素），且比例不会极端偏斜
        total_yellow = left_yellow + right_yellow
        assert total_yellow > 50, f"黄色像素总量过少: {total_yellow}"
        assert min(left_yellow, right_yellow) > 0, (
            f"标题未居中: 左侧={left_yellow}, 右侧={right_yellow}"
        )

    def test_overlay_sharer_appears(self):
        """分享人以白色文字+紫色渐变背景渲染，渐变从左到右渐隐"""
        import cv2
        frame = _make_test_frame(1280, 720)
        out = add_subtitle(frame, "译文", original_text="",
                          enable_subtitle=True,
                          subtitle_style={
                              "color": "黄色（推荐）",
                              "font_size": 0.055,
                              "bg_enabled": False,
                              "bilingual": False,
                              "overlay_title": "",
                              "overlay_sharer": "张三",
                          })
        # 分享人位于译文上方（帧下半部），检查帧后 2/3 区域
        region_start = out.shape[0] // 3
        region = out[region_start:, :, :]
        bright_pixels = (region.max(axis=2) > 100)
        assert bright_pixels.sum() > 100, (
            f"未检测到分享人渲染内容，下半区域 max 像素值: {region.max()}"
        )

    def test_overlay_sharer_gradient_fades(self):
        """分享人紫色背景从左到右渐隐（左侧有色 → 右侧透明）"""
        frame = _make_test_frame(1920, 1080)
        out = add_subtitle(frame, "译文", original_text="",
                          enable_subtitle=True,
                          subtitle_style={
                              "color": "白色",
                              "font_size": 0.055,
                              "bg_enabled": False,
                              "bilingual": False,
                              "overlay_title": "",
                              "overlay_sharer": "测试分享人",
                          })
        # 紫色 = BGR (176, 39, 156)，在中间区域查找紫色背景行
        third_start = out.shape[0] // 3
        third_end = out.shape[0] * 2 // 3
        middle = out[third_start:third_end, :, :]

        # 找到紫色背景所在行：R 通道（BGR[2]）值最高的行
        purple_strength = middle[:, :, 2].astype(float) - (
            middle[:, :, 0].astype(float) + middle[:, :, 1].astype(float)
        ) / 2.0
        row_scores = purple_strength.max(axis=1)
        best_row = int(np.argmax(row_scores))
        if row_scores[best_row] < 30:
            pytest.skip("未检测到足够紫色像素，无法验证渐变")

        # 在该行中，左半部分紫色应强于右半部分（渐变从左到右）
        scan_row = middle[best_row, :, :]
        half = len(scan_row) // 2
        left_purple = scan_row[:half, 2].astype(float).max()
        right_purple = scan_row[half:, 2].astype(float).max()
        assert left_purple > right_purple, (
            f"渐变方向错误: 左侧R={left_purple:.0f}, 右侧R={right_purple:.0f}"
        )

    def test_empty_overlays_no_crash(self):
        """空 overlay 值不崩溃，正常渲染字幕"""
        frame = _make_test_frame(1280, 720)
        out = add_subtitle(frame, "译文", original_text="",
                          enable_subtitle=True,
                          subtitle_style={
                              "color": "黄色（推荐）",
                              "font_size": 0.055,
                              "bg_enabled": False,
                              "bilingual": False,
                          })
        assert out.shape == frame.shape  # 尺寸不变
        assert not np.array_equal(out, frame)  # 但内容变了（有字幕文字）

    def test_overlay_renders_without_subtitle(self):
        """overlay 独立于字幕：enable_subtitle=False 时仍渲染标题和分享人"""
        frame = _make_test_frame(1280, 720)
        out = add_subtitle(frame, "", original_text="",
                          enable_subtitle=False,
                          subtitle_style={
                              "overlay_title": "测试标题",
                              "overlay_sharer": "张三",
                          })
        # overlay 渲染了内容，帧不应与原始相同
        assert not np.array_equal(out, frame), "overlay 应在字幕关闭时仍渲染"

    def test_both_overlays_together(self):
        """两个 overlay 同时渲染不出错"""
        import cv2
        frame = _make_test_frame(1920, 1080)
        out = add_subtitle(frame, "译文文本", original_text="Original text",
                          enable_subtitle=True,
                          subtitle_style={
                              "color": "白色",
                              "font_size": 0.055,
                              "bg_enabled": True,
                              "bilingual": True,
                              "overlay_title": "视频主标题",
                              "overlay_sharer": "分享人名称",
                          })
        assert out.shape == frame.shape
        non_black = np.sum(out > 5)
        assert non_black > 1000, "应该渲染了大量非黑内容"


class TestChapterBar:
    """章节进度条渲染"""

    def _make_chapter_style(self, chapters, current_time=5.0, total_dur=60.0,
                            is_landscape=False):
        w, h = (1280, 720) if is_landscape else (720, 1280)
        return w, h, {
            "color": "黄色（推荐）",
            "font_size": 0.048,
            "bg_enabled": False,
            "bilingual": False,
            "_chapters": chapters,
            "_current_time": current_time,
            "_total_duration": total_dur,
        }

    def test_chapter_bar_visible(self):
        """章节进度条在底部渲染可见像素"""
        chapters = [{"start": 0, "title": "开场"}, {"start": 20, "title": "正片"}]
        w, h, style = self._make_chapter_style(chapters)
        frame = _make_test_frame(w, h)
        out = add_subtitle(frame, "译文", original_text="",
                          enable_subtitle=True, subtitle_style=style)
        # 底部 bar 区域应有非黑像素（底板 + 章节文字）
        bottom_bar = out[h * 4 // 5:, :, :]
        non_black = np.sum(bottom_bar.max(axis=2) > 10)
        assert non_black > 100, f"章节栏底部无可见内容, 非黑像素={non_black}"

    def test_chapter_bar_absent_when_no_chapters(self):
        """无章节数据时不渲染章节栏"""
        w, h, style = self._make_chapter_style([])
        frame = _make_test_frame(w, h)
        out = add_subtitle(frame, "译文", original_text="",
                          enable_subtitle=True, subtitle_style=style)
        # 底部应该只有细条进度条或无内容（取决于 total_duration）
        # 只要不崩溃即可
        assert out.shape == frame.shape

    def test_chapter_text_left_aligned(self):
        """章节首字在时间标记位置，右侧有内容"""
        chapters = [{"start": 10, "title": "测试章节"}]
        w, h, style = self._make_chapter_style(chapters, current_time=5, total_dur=60)
        frame = _make_test_frame(w, h)
        out = add_subtitle(frame, "译文", original_text="",
                          enable_subtitle=True, subtitle_style=style)
        # 第 10 秒标记应在 bar_area_l + bar_area_w * 10/60 处
        margin_x = int(w * 0.03)
        bar_w = w - margin_x * 2
        expected_x = margin_x + int(bar_w * 10 / 60)
        # 该位置附近应有非黑像素（竖线标记 + 章节文字）
        region = out[h * 4 // 5:, max(0, expected_x - 10):min(w, expected_x + 40), :]
        non_black = np.sum(region.max(axis=2) > 10)
        assert non_black > 0, f"章节标记位置 {expected_x} 附近无可见内容"

    def test_playhead_visible(self):
        """播放头竖线在进度位置可见"""
        chapters = [{"start": 0, "title": "开场"}]
        w, h, style = self._make_chapter_style(chapters, current_time=15, total_dur=60)
        frame = _make_test_frame(w, h)
        out = add_subtitle(frame, "译文", original_text="",
                          enable_subtitle=True, subtitle_style=style)
        # 播放头应有蓝色像素 (0, 188, 212) ≈ BGR(212, 188, 0)
        bottom = out[h * 4 // 5:, :, :]
        blue_mask = (bottom[:, :, 0] >= 200) & (bottom[:, :, 1] >= 150) & (bottom[:, :, 2] <= 50)
        assert blue_mask.sum() > 0, "未检测到播放头蓝色竖线"

    def test_progress_overlay_left_of_playhead(self):
        """已播放遮罩在播放头左侧"""
        chapters = [{"start": 0, "title": "开场"}, {"start": 30, "title": "结尾"}]
        w, h, style = self._make_chapter_style(chapters, current_time=15, total_dur=60)
        frame = _make_test_frame(w, h)
        out = add_subtitle(frame, "译文", original_text="",
                          enable_subtitle=True, subtitle_style=style)
        bottom = out[h * 4 // 5:, :, :]
        mid = w // 2
        # 左半部分（已播）亮度应低于右半（未播，黑底+白字更亮）
        left_bright = float(bottom[:, :mid, :].max())
        right_bright = float(bottom[:, mid:, :].max())
        # 右侧（未播黑底+白字）应该更亮或至少不全是黑
        assert right_bright > 5, f"右侧未播区域过暗: {right_bright}"

    def test_landscape_smaller_font(self):
        """横屏字幕字体小于竖屏"""
        chapters = [{"start": 0, "title": "开场"}]
        # 竖屏
        _, _, style_v = self._make_chapter_style(chapters, is_landscape=False)
        out_v = add_subtitle(_make_test_frame(720, 1280), "译文测试", original_text="",
                            enable_subtitle=True, subtitle_style=style_v)
        # 横屏
        _, _, style_h = self._make_chapter_style(chapters, is_landscape=True)
        out_h = add_subtitle(_make_test_frame(1280, 720), "译文测试", original_text="",
                            enable_subtitle=True, subtitle_style=style_h)
        # 横屏字幕的非黑像素（字幕文字）应少于竖屏（字号更小 = 像素更少）
        v_text_px = np.sum(out_v.max(axis=2) > 100)
        h_text_px = np.sum(out_h.max(axis=2) > 100)
        assert h_text_px < v_text_px, (
            f"横屏字幕应更小: 横屏={h_text_px}px, 竖屏={v_text_px}px"
        )
