"""E2E 集成测试 — 模拟完整视频处理管线

使用 mock 对象替换 Whisper/LLM/TTS/FFmpeg 等外部依赖，
聚焦于验证代码路径的正确性：timeline 设置、进度单调、空数据守卫。
"""

import os
import sys
import numpy as np
import pytest
from unittest.mock import MagicMock, patch, ANY


# ============================================================
# 辅助：构建可测试的管线 mock 线程
# ============================================================

def _make_mock_thread(**overrides):
    """创建一个 mock VideoProcessThread，包含所有管线需要的属性"""
    from core.audio_pipeline import AudioPipelineMixin
    from core.video_processor import VideoProcessorMixin

    # 用 type() 动态创建类，避免需要 PyQt5 QThread 依赖
    MockClass = type("MockPipeline", (AudioPipelineMixin, VideoProcessorMixin), {})

    mock = MockClass()
    # 基本属性
    mock.running = True
    mock.input_source = "/fake/video.mp4"
    mock.is_vertical = True
    mock.target_lang = "中文 (Chinese) - 自动翻译生成"
    mock.codec = "H.264 (MP4)"
    mock.fps = 30
    mock.enable_subtitle = True
    mock.enable_voice_clone = False
    mock.clone_mode = 0
    mock.upload_configs = []
    mock.trim_start = 0
    mock.trim_end = 0
    mock.quick_preview_sec = 0
    mock.subtitle_style = {}
    mock.batch_files = []
    mock.output_w = 1080
    mock.output_h = 1920
    mock.subtitle_offset_ms = 0
    mock.enable_bgm_preserve = False
    mock.export_subtitle = True
    mock.subtitle_file_path = ""
    mock.subtitles_timeline = []
    mock.accompaniment_path = None
    mock.dashscope_api_key = "test-key"
    mock.cosy_model = "cosyvoice-v2"
    mock.enable_edge_tts_first = False
    mock.edge_tts_voices = {}

    # 输出目录
    import tempfile
    import datetime
    mock.output_dir = tempfile.mkdtemp(prefix="e2e_test_")
    mock.temp_video = os.path.join(mock.output_dir, "temp_silent.mp4")
    mock.orig_audio = os.path.join(mock.output_dir, "orig_audio.wav")
    mock.final_audio = os.path.join(mock.output_dir, "final_synced_audio.wav")
    mock.final_output = os.path.join(mock.output_dir, f"Output_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}.mp4")

    # LLM client mock
    mock.llm_client = MagicMock()
    mock.llm_client.chat.completions.create.return_value.choices = [
        MagicMock(message=MagicMock(content="Mocked translation"))
    ]

    # signals
    mock.log_msg = MagicMock()
    mock.progress_changed = MagicMock()
    mock.update_frame = MagicMock()

    # 应用覆盖
    for k, v in overrides.items():
        setattr(mock, k, v)

    return mock


def _mock_whisper_transcribe(audio_path):
    """返回模拟的 Whisper 识别结果"""
    return {"segments": [
        {"start": 0.0, "end": 2.5, "text": "Hello world"},
        {"start": 3.0, "end": 5.0, "text": "This is a test"},
        {"start": 6.0, "end": 8.0, "text": "Another segment"},
        {"start": 9.0, "end": 11.5, "text": "Final words here"},
    ]}

def _mock_subprocess_success(*args, **kwargs):
    """模拟 subprocess.run 成功返回"""
    result = MagicMock()
    result.returncode = 0
    result.stdout = ""
    result.stderr = ""
    return result


def _make_audio_segment(duration_ms=30000):
    """创建一个 mock AudioSegment"""
    mock = MagicMock()
    mock.set_frame_rate.return_value = mock
    mock.set_channels.return_value = mock
    mock.set_sample_width.return_value = mock
    mock.fade_in.return_value = mock
    mock.fade_out.return_value = mock
    mock.export.return_value = None
    mock.__len__ = lambda s: duration_ms
    mock.dBFS = -20
    mock.get_array_of_samples.return_value = []
    return mock


# ============================================================
# H1: 保留原声路径 — 完整 timeline
# ============================================================

@patch("core.audio_pipeline.whisper.load_model")
@patch("core.audio_pipeline.subprocess.run")
@patch("core.audio_pipeline.AudioSegment")
@patch("core.audio_pipeline.AudioSegment.silent")
def test_keep_original_timeline_populated(
    mock_silent, mock_audioseg, mock_run, mock_whisper_load, monkeypatch,
):
    """e2e: 保留原声 → 翻译全部段落 → timeline 非空"""
    mock = _make_mock_thread(enable_voice_clone=False)

    # mock Whisper
    mock_model = MagicMock()
    mock_model.transcribe.return_value = _mock_whisper_transcribe(None)
    mock_whisper_load.return_value = mock_model

    # mock ffmpeg + audio
    mock_run.side_effect = _mock_subprocess_success
    mock_audioseg.from_wav.return_value = _make_audio_segment()
    mock_silent.return_value = _make_audio_segment()

    try:
        result = mock.run_ai_pipeline()
        assert result is True
        assert len(mock.subtitles_timeline) > 0
        for entry in mock.subtitles_timeline:
            assert "start" in entry
            assert "end" in entry
            assert "text" in entry
            assert "original_text" in entry
    finally:
        import shutil
        if os.path.exists(mock.output_dir):
            shutil.rmtree(mock.output_dir, ignore_errors=True)


# ============================================================
# H2: 声音克隆路径 — timeline 含 speaker_id
# ============================================================

@patch("core.audio_pipeline.whisper.load_model")
@patch("core.audio_pipeline.EncoderClassifier.from_hparams")
@patch("core.audio_pipeline.subprocess.run")
@patch("core.audio_pipeline.AudioSegment")
@patch("core.audio_pipeline.AudioSegment.silent")
@patch("core.audio_pipeline.silence.split_on_silence")
@patch("core.audio_pipeline.torchaudio.load")
@patch("os.path.exists")
@patch("os.path.getsize")
@patch("os.remove")
def test_voice_clone_timeline_with_speaker_ids(
    mock_remove, mock_getsize, mock_exists, mock_ta_load, mock_split, mock_silent,
    mock_audioseg, mock_run, mock_classifier, mock_whisper_load,
):
    """e2e: 声音克隆 → translation → timeline 条目含 speaker_id"""
    mock = _make_mock_thread(enable_voice_clone=True)

    # mock Whisper
    mock_model = MagicMock()
    mock_model.transcribe.return_value = _mock_whisper_transcribe(None)
    mock_whisper_load.return_value = mock_model

    # mock voice embedding: 返回 4 维 embedding
    mock_classifier.return_value.encode_batch.return_value.flatten.return_value.numpy.return_value = \
        [0.1, 0.2, 0.3, 0.4]

    # mock torchaudio.load
    mock_sig = MagicMock()
    mock_sig.shape = (1, 16000)
    mock_ta_load.return_value = (mock_sig, 16000)

    # mock silence splitting
    mock_split.return_value = [_make_audio_segment(1000)]

    # mock audio + file existence for embedding
    mock_run.side_effect = _mock_subprocess_success
    mock_audioseg.from_wav.return_value = _make_audio_segment(15000)
    mock_silent.return_value = _make_audio_segment(15000)
    mock_exists.return_value = True
    mock_getsize.return_value = 4096

    try:
        result = mock.run_ai_pipeline()
        assert result is True
        assert len(mock.subtitles_timeline) > 0
        # 每个条目应有 speaker_id
        for entry in mock.subtitles_timeline:
            assert "speaker_id" in entry
            assert isinstance(entry["speaker_id"], (int, float, np.int64, np.int32))
            assert "text" in entry
    finally:
        import shutil
        if os.path.exists(mock.output_dir):
            shutil.rmtree(mock.output_dir, ignore_errors=True)


# ============================================================
# H3: 声音克隆 + valid_segments 为空 → fallback
# ============================================================

@patch("core.audio_pipeline.whisper.load_model")
@patch("core.audio_pipeline.EncoderClassifier.from_hparams")
@patch("core.audio_pipeline.subprocess.run")
@patch("core.audio_pipeline.AudioSegment")
@patch("core.audio_pipeline.AudioSegment.silent")
@patch("core.audio_pipeline.silence.split_on_silence")
@patch("core.audio_pipeline.torchaudio.load")
def test_voice_clone_empty_valid_segments_fallback(
    mock_ta_load, mock_split, mock_silent, mock_audioseg, mock_run,
    mock_classifier, mock_whisper_load,
):
    """e2e: 声纹过滤后无有效段落 → fallback 到 uncompressed_segments 翻译"""
    mock = _make_mock_thread(enable_voice_clone=True)

    # mock Whisper（4 个段落）
    mock_model = MagicMock()
    mock_model.transcribe.return_value = _mock_whisper_transcribe(None)
    mock_whisper_load.return_value = mock_model

    # mock audio
    mock_run.side_effect = _mock_subprocess_success
    mock_audioseg.from_wav.return_value = _make_audio_segment(15000)
    mock_silent.return_value = _make_audio_segment(15000)

    # ✗ encoder 完全失败 → valid_segments 为空
    mock_classifier.return_value.encode_batch.side_effect = Exception("mock embedding failure")

    # mock torchaudio.load 也会失败（配合空 valid_segments）
    mock_ta_load.side_effect = Exception("mock load failure")

    try:
        result = mock.run_ai_pipeline()
        assert result is True
        # ≔ 应有 fallback 日志
        log_calls = [c[0][0] for c in mock.log_msg.emit.call_args_list]
        assert any("回退使用 Whisper 原始段落" in str(l) for l in log_calls)
        # ≔ timeline 非空（从 uncompressed_segments 翻译）
        assert len(mock.subtitles_timeline) > 0
        for entry in mock.subtitles_timeline:
            assert "text" in entry
            assert "speaker_id" in entry
            assert entry["speaker_id"] == 0  # fallback: 单一说话人
    finally:
        import shutil
        if os.path.exists(mock.output_dir):
            shutil.rmtree(mock.output_dir, ignore_errors=True)


# ============================================================
# H4: SRT 驱动 + 声音克隆 — speaker 映射
# ============================================================

@patch("core.audio_pipeline.whisper.load_model")
@patch("core.audio_pipeline.EncoderClassifier.from_hparams")
@patch("core.audio_pipeline.subprocess.run")
@patch("core.audio_pipeline.AudioSegment")
@patch("core.audio_pipeline.AudioSegment.silent")
@patch("core.audio_pipeline.silence.split_on_silence")
@patch("core.audio_pipeline.torchaudio.load")
@patch("os.path.exists")
@patch("os.path.getsize")
@patch("os.remove")
def test_srt_driven_speaker_mapping(
    mock_remove, mock_getsize, mock_exists, mock_ta_load, mock_split, mock_silent,
    mock_audioseg, mock_run, mock_classifier, mock_whisper_load,
):
    """e2e: 外部 SRT + 声纹克隆 → SRT 条目按重叠度获得 speaker_id"""
    mock = _make_mock_thread(enable_voice_clone=True)

    # SRT 条目（模拟外部导入）: 第一条与 speaker 0 重叠，第二条与 speaker 1 重叠
    srt_timeline = [
        {"start": 0.0, "end": 2.5, "text": "你好世界", "original_text": "Hello", "speaker_id": 0},
        {"start": 3.0, "end": 5.0, "text": "测试文本", "original_text": "Test", "speaker_id": 0},
    ]

    # mock Whisper
    mock_model = MagicMock()
    mock_model.transcribe.return_value = _mock_whisper_transcribe(None)
    mock_whisper_load.return_value = mock_model

    # mock audio + file existence
    mock_run.side_effect = _mock_subprocess_success
    mock_audioseg.from_wav.return_value = _make_audio_segment(15000)
    mock_silent.return_value = _make_audio_segment(15000)
    mock_exists.return_value = True
    mock_getsize.return_value = 4096

    # mock voice embedding: 两个不同嵌入 → 两个说话人
    call_count = [1]  # 从 1 开始避免零向量（cosine 聚类不支持）

    def mock_encode(signal):
        emb = MagicMock()
        emb.flatten.return_value.numpy.return_value = [call_count[0] * 0.5] * 192
        call_count[0] += 1
        return emb

    mock_classifier.return_value.encode_batch = mock_encode
    mock_sig = MagicMock()
    mock_sig.shape = (1, 16000)
    mock_ta_load.return_value = (mock_sig, 16000)
    mock_split.return_value = [_make_audio_segment(1000)]

    try:
        result = mock.run_ai_pipeline(srt_timeline=srt_timeline)
        assert result is True
        # ≔ timeline 应该是 SRT 条目
        assert len(mock.subtitles_timeline) == 2
        # ≔ text 来自 SRT 而非 LLM 翻译
        assert mock.subtitles_timeline[0]["text"] == "你好世界"
        assert mock.subtitles_timeline[1]["text"] == "测试文本"
        # ≔ speaker_id 已按重叠度映射
        for entry in mock.subtitles_timeline:
            assert "speaker_id" in entry
        # ≔ 日志确认跳过 LLM 翻译
        log_calls = [c[0][0] for c in mock.log_msg.emit.call_args_list]
        assert any("外部 SRT 模式" in str(l) for l in log_calls)
        assert any("跳过 LLM 翻译" in str(l) for l in log_calls)
    finally:
        import shutil
        if os.path.exists(mock.output_dir):
            shutil.rmtree(mock.output_dir, ignore_errors=True)


# ============================================================
# H5: 空 timeline 守卫 — _export_srt + rendering
# ============================================================

def test_export_srt_guard_empty_timeline():
    """空 timeline 时 _export_srt 不产生 0 字节文件"""
    mock = _make_mock_thread()
    mock.subtitles_timeline = []

    srt_path = os.path.splitext(mock.final_output)[0] + ".srt"
    if os.path.exists(srt_path):
        os.unlink(srt_path)

    mock._export_srt()

    # 文件不应被创建
    assert not os.path.exists(srt_path)

    # 日志应包含警告
    log_calls = [c[0][0] for c in mock.log_msg.emit.call_args_list]
    assert any("字幕时间轴为空" in str(l) for l in log_calls)

    import shutil
    if os.path.exists(mock.output_dir):
        shutil.rmtree(mock.output_dir, ignore_errors=True)


def test_export_srt_guard_empty_srt_content():
    """subtitles_to_srt 返回空字符串时不写入文件"""
    mock = _make_mock_thread()
    # 空列表导致空 SRT 内容
    mock.subtitles_timeline = []

    srt_path = os.path.splitext(mock.final_output)[0] + ".srt"
    if os.path.exists(srt_path):
        os.unlink(srt_path)

    mock._export_srt()
    assert not os.path.exists(srt_path)

    import shutil
    if os.path.exists(mock.output_dir):
        shutil.rmtree(mock.output_dir, ignore_errors=True)


# ============================================================
# H6: 进度单调递增 — 所有路径
# ============================================================

@patch("core.audio_pipeline.whisper.load_model")
@patch("core.audio_pipeline.subprocess.run")
@patch("core.audio_pipeline.AudioSegment")
@patch("core.audio_pipeline.AudioSegment.silent")
def test_progress_monotonic_keep_original(
    mock_silent, mock_audioseg, mock_run, mock_whisper_load,
):
    """e2e: 保留原声 → progress 信号值单调递增"""
    mock = _make_mock_thread(enable_voice_clone=False)
    mock_model = MagicMock()
    mock_model.transcribe.return_value = _mock_whisper_transcribe(None)
    mock_whisper_load.return_value = mock_model
    mock_run.side_effect = _mock_subprocess_success
    mock_audioseg.from_wav.return_value = _make_audio_segment()
    mock_silent.return_value = _make_audio_segment()

    try:
        mock.run_ai_pipeline()
        values = [c[0][0] for c in mock.progress_changed.emit.call_args_list]
        for i in range(1, len(values)):
            assert values[i] >= values[i - 1], (
                f"Progress not monotonic at index {i}: {values[i-1]} → {values[i]}"
            )
        assert values[-1] <= 70  # 管线完成后走 70→75→90→100
    finally:
        import shutil
        if os.path.exists(mock.output_dir):
            shutil.rmtree(mock.output_dir, ignore_errors=True)


@patch("core.audio_pipeline.whisper.load_model")
@patch("core.audio_pipeline.EncoderClassifier.from_hparams")
@patch("core.audio_pipeline.subprocess.run")
@patch("core.audio_pipeline.AudioSegment")
@patch("core.audio_pipeline.AudioSegment.silent")
@patch("core.audio_pipeline.silence.split_on_silence")
@patch("core.audio_pipeline.torchaudio.load")
@patch("os.path.exists")
@patch("os.path.getsize")
@patch("os.remove")
def test_progress_monotonic_voice_clone(
    mock_remove, mock_getsize, mock_exists, mock_ta_load, mock_split, mock_silent,
    mock_audioseg, mock_run, mock_classifier, mock_whisper_load,
):
    """e2e: 声音克隆 → progress 信号值单调递增"""
    mock = _make_mock_thread(enable_voice_clone=True)
    mock_model = MagicMock()
    mock_model.transcribe.return_value = _mock_whisper_transcribe(None)
    mock_whisper_load.return_value = mock_model
    mock_run.side_effect = _mock_subprocess_success
    mock_audioseg.from_wav.return_value = _make_audio_segment(15000)
    mock_silent.return_value = _make_audio_segment(15000)
    mock_exists.return_value = True
    mock_getsize.return_value = 4096

    mock_classifier.return_value.encode_batch.return_value.flatten.return_value.numpy.return_value = \
        [0.1, 0.2, 0.3, 0.4]
    mock_sig = MagicMock()
    mock_sig.shape = (1, 16000)
    mock_ta_load.return_value = (mock_sig, 16000)
    mock_split.return_value = [_make_audio_segment(1000)]

    try:
        mock.run_ai_pipeline()
        values = [c[0][0] for c in mock.progress_changed.emit.call_args_list]
        for i in range(1, len(values)):
            assert values[i] >= values[i - 1], (
                f"Progress not monotonic at index {i}: {values[i-1]} → {values[i]}"
            )
    finally:
        import shutil
        if os.path.exists(mock.output_dir):
            shutil.rmtree(mock.output_dir, ignore_errors=True)


# ============================================================
# H7: SRT + voice clone timeline 不被覆盖
# ============================================================

@patch("core.audio_pipeline.whisper.load_model")
@patch("core.audio_pipeline.EncoderClassifier.from_hparams")
@patch("core.audio_pipeline.subprocess.run")
@patch("core.audio_pipeline.AudioSegment")
@patch("core.audio_pipeline.AudioSegment.silent")
@patch("core.audio_pipeline.silence.split_on_silence")
@patch("core.audio_pipeline.torchaudio.load")
@patch("os.path.exists")
@patch("os.path.getsize")
@patch("os.remove")
def test_srt_driven_timeline_has_speaker_ids(
    mock_remove, mock_getsize, mock_exists, mock_ta_load, mock_split, mock_silent,
    mock_audioseg, mock_run, mock_classifier, mock_whisper_load,
):
    """e2e: SRT 驱动路径下 speaker_id 实现多人区分"""
    mock = _make_mock_thread(enable_voice_clone=True)

    srt_timeline = [
        {"start": 0.0, "end": 2.5, "text": "A", "original_text": "", "speaker_id": 0},
        {"start": 3.0, "end": 5.0, "text": "B", "original_text": "", "speaker_id": 0},
        {"start": 6.0, "end": 8.0, "text": "C", "original_text": "", "speaker_id": 0},
        {"start": 9.0, "end": 11.5, "text": "D", "original_text": "", "speaker_id": 0},
    ]

    mock_model = MagicMock()
    mock_model.transcribe.return_value = _mock_whisper_transcribe(None)
    mock_whisper_load.return_value = mock_model
    mock_run.side_effect = _mock_subprocess_success
    mock_audioseg.from_wav.return_value = _make_audio_segment(15000)
    mock_silent.return_value = _make_audio_segment(15000)

    # 让临时文件检查通过（避免所有段落被声纹质量过滤）
    def _path_exists(path):
        return "temp_slice" in str(path) or "orig_audio" in str(path)

    mock_exists.side_effect = _path_exists
    mock_getsize.return_value = 4096

    # 产生两个明显不同的说话人
    call_idx = [0]

    def mock_encode(signal):
        emb = MagicMock()
        # 偶数段：正向量；奇数段：负向量 → 聚类为 2 个说话人
        val = 1.0 if call_idx[0] % 2 == 0 else -1.0
        emb.flatten.return_value.numpy.return_value = [val] * 192
        call_idx[0] += 1
        return emb

    mock_classifier.return_value.encode_batch = mock_encode
    mock_sig = MagicMock()
    mock_sig.shape = (1, 16000)
    mock_ta_load.return_value = (mock_sig, 16000)
    mock_split.return_value = [_make_audio_segment(1000)]

    try:
        result = mock.run_ai_pipeline(srt_timeline=srt_timeline)
        assert result is True
        assert len(mock.subtitles_timeline) == 4
        # 至少有一个 speaker_id 不是 0（两个说话人区分开了）
        speaker_ids = {e["speaker_id"] for e in mock.subtitles_timeline}
        assert len(speaker_ids) >= 2, f"Expected ≥2 speakers, got: {speaker_ids}"
    finally:
        import shutil
        if os.path.exists(mock.output_dir):
            shutil.rmtree(mock.output_dir, ignore_errors=True)
