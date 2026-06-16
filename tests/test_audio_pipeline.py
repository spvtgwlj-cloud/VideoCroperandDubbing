"""音频管线静态方法 — 单元测试"""

import pytest
from core.audio_pipeline import AudioPipelineMixin


class TestCompressSilence:
    """静音段压缩"""

    def test_empty_list(self):
        assert AudioPipelineMixin._compress_silence([]) == []

    def test_single_segment(self):
        segs = [{"start": 0.0, "end": 2.0, "text": "Hi"}]
        result = AudioPipelineMixin._compress_silence(segs)
        assert len(result) == 1
        assert result[0]["start"] == 0.0
        assert result[0]["end"] == 2.0

    def test_no_large_gaps(self):
        """间隔小于 max_gap 不压缩"""
        segs = [
            {"start": 0.0, "end": 2.0},
            {"start": 2.5, "end": 4.0},  # gap = 0.5s < 1.5s
        ]
        result = AudioPipelineMixin._compress_silence(segs)
        assert result[1]["start"] == 2.5
        assert result[1]["end"] == 4.0

    def test_large_gap_compressed(self):
        """间隔 > 1.5s 时压缩至 0.5s"""
        segs = [
            {"start": 0.0, "end": 2.0},
            {"start": 5.0, "end": 7.0},  # gap = 3.0s > 1.5s
        ]
        result = AudioPipelineMixin._compress_silence(segs)
        # reduction = 3.0 - 0.5 = 2.5
        # second segment shifts: 5.0 - 2.5 = 2.5, 7.0 - 2.5 = 4.5
        assert result[1]["start"] == pytest.approx(2.5)
        assert result[1]["end"] == pytest.approx(4.5)

    def test_multiple_gaps_cumulative(self):
        """多次压缩累积偏移（使用原始段落位置计算 gap，避免复合叠加）"""
        segs = [
            {"start": 0.0, "end": 1.0},
            {"start": 4.0, "end": 5.0},   # original_gap=3.0 → reduction=2.5
            {"start": 8.0, "end": 9.0},   # original_gap=3.0 → reduction=2.5
        ]
        result = AudioPipelineMixin._compress_silence(segs)
        # First: original_gap = 8.0 - 5.0 = 3.0, reduction = 3.0 - 0.5 = 2.5
        # cumulative offset = 2.5 + 2.5 = 5.0
        # seg[2]: 8.0 - 5.0 = 3.0, 9.0 - 5.0 = 4.0
        assert result[2]["start"] == pytest.approx(3.0)
        assert result[2]["end"] == pytest.approx(4.0)

    def test_start_not_below_zero(self):
        """压缩后 start 不低于 0"""
        segs = [
            {"start": 0.0, "end": 0.5},
            {"start": 3.0, "end": 3.5},
        ]
        result = AudioPipelineMixin._compress_silence(segs)
        # reduction = 2.5 - 0.5 = 2.0, offset = 2.0
        # seg[1]: 3.0-2.0=1.0
        assert result[1]["start"] >= 0.0

    def test_custom_parameters(self):
        """自定义 max_gap 和 target_gap"""
        segs = [
            {"start": 0.0, "end": 1.0},
            {"start": 3.0, "end": 4.0},
        ]
        result = AudioPipelineMixin._compress_silence(segs, max_gap=1.0, target_gap=0.2)
        # gap=2.0 > 1.0 → reduction = 2.0 - 0.2 = 1.8
        # seg[1]: 3.0-1.8=1.2, 4.0-1.8=2.2
        assert result[1]["start"] == pytest.approx(1.2)
        assert result[1]["end"] == pytest.approx(2.2)

    def test_original_unchanged(self):
        """原列表不被修改"""
        segs = [
            {"start": 0.0, "end": 2.0},
            {"start": 5.0, "end": 7.0},
        ]
        original_first_end = segs[0]["end"]
        AudioPipelineMixin._compress_silence(segs)
        assert segs[0]["end"] == original_first_end


class TestAssignSpeakersByOverlap:
    """SRT 条目到 Whisper 段落的 speaker_id 映射"""

    def test_empty_srt(self):
        result = AudioPipelineMixin._assign_speakers_by_overlap([], [])
        assert result == []

    def test_direct_overlap(self):
        """完全重叠时直接继承 speaker_id"""
        srt = [{"start": 0.0, "end": 2.5, "text": "Hello", "speaker_id": 0}]
        valid = [{"start": 0.0, "end": 2.5, "text": "Hello world", "speaker_id": 1}]
        result = AudioPipelineMixin._assign_speakers_by_overlap(srt, valid)
        assert result[0]["speaker_id"] == 1  # 继承 Whisper 的 speaker_id=1

    def test_partial_overlap(self):
        """部分重叠取最大的 speaker_id"""
        srt = [{"start": 0.0, "end": 3.0, "text": "Hello", "speaker_id": 0}]
        valid = [
            {"start": 0.0, "end": 1.0, "text": "Hi", "speaker_id": 0},   # overlap=1.0
            {"start": 1.5, "end": 4.0, "text": "there", "speaker_id": 1},  # overlap=1.5 → wins
        ]
        result = AudioPipelineMixin._assign_speakers_by_overlap(srt, valid)
        assert result[0]["speaker_id"] == 1

    def test_no_overlap_defaults_to_zero(self):
        """无重叠默认 speaker_id=0"""
        srt = [{"start": 10.0, "end": 12.0, "text": "Late", "speaker_id": 0}]
        valid = [{"start": 0.0, "end": 2.0, "text": "Early", "speaker_id": 1}]
        result = AudioPipelineMixin._assign_speakers_by_overlap(srt, valid)
        assert result[0]["speaker_id"] == 0

    def test_empty_valid_segments(self):
        """valid_segments 为空时全部分配 speaker_id=0"""
        srt = [
            {"start": 0.0, "end": 2.0, "text": "A", "speaker_id": 0},
            {"start": 3.0, "end": 5.0, "text": "B", "speaker_id": 0},
        ]
        result = AudioPipelineMixin._assign_speakers_by_overlap(srt, [])
        for entry in result:
            assert entry["speaker_id"] == 0

    def test_multiple_srt_entries(self):
        """多个 SRT 条目各自正确映射"""
        srt = [
            {"start": 0.0, "end": 2.0, "text": "Speaker0 area", "speaker_id": 0},
            {"start": 5.0, "end": 7.0, "text": "Speaker1 area", "speaker_id": 0},
            {"start": 9.0, "end": 11.0, "text": "Speaker0 again", "speaker_id": 0},
        ]
        valid = [
            {"start": 0.0, "end": 2.5, "text": "I am zero", "speaker_id": 0},
            {"start": 3.0, "end": 7.5, "text": "I am one", "speaker_id": 1},
            {"start": 8.0, "end": 12.0, "text": "Zero back", "speaker_id": 0},
        ]
        result = AudioPipelineMixin._assign_speakers_by_overlap(srt, valid)
        assert result[0]["speaker_id"] == 0
        assert result[1]["speaker_id"] == 1
        assert result[2]["speaker_id"] == 0

    def test_original_speaker_id_overwritten(self):
        """SRT 原 speaker_id (始终为 0) 被覆盖为 Whisper 的值"""
        srt = [{"start": 0.0, "end": 2.0, "text": "Hi", "speaker_id": 0}]
        valid = [{"start": 0.0, "end": 2.0, "text": "Hi", "speaker_id": 3}]
        result = AudioPipelineMixin._assign_speakers_by_overlap(srt, valid)
        assert result[0]["speaker_id"] == 3
