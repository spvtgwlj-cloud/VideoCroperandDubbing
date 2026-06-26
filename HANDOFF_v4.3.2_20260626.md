# HANDOFF — AI Video Dubbing Pro v4.3.2

## 项目概述

短视频 AI 配音 + 翻译 + 竖屏裁切一体化工具。v4.3.2 核心突破：多平台 AI 管线复用、H.265 兼容性修复。

**目标用户**：短视频运营工程师 / 跨境营销 / 自媒体创作者

---

## v4.3.2 核心变更（2026-06-26）

### 多平台 AI 管线复用

| 变更 | 涉及文件 |
|------|----------|
| `run()` 双层循环加入 `cached_ai` 缓存，首平台执行完整管线后缓存结果 | `process_thread.py` |
| 新增 `_render_and_merge()`（从 `_process_single` 后半段提取：帧渲染+合成） | `video_processor.py` |
| 多平台模式 `merge_audio_video` 不删 `final_audio` | `video_processor.py` |
| 多平台模式 trim 临时文件保留供后续复用 | `video_processor.py` |
| 缓存包含 `input_source`（trimmed 路径），后续平台跳过裁剪 | `process_thread.py` |

**效果**：3 平台从 3× 耗时降至 ~1.6×（Whisper/翻译/TTS 仅执行一次）。

### H.265 兼容性修复

| 变更 | 涉及文件 |
|------|----------|
| `-tag:v hvc1 -movflags +faststart` 从编码器参数区移至 `-map` 后（mp4 muxer 参数区） | `video_processor.py` |
| `_prepend_highlight` Step 1/2 均补充 `-tag:v hvc1`（之前爆点打开时 tag 丢失） | `video_processor.py` |

### UI 修复

| 变更 | 涉及文件 |
|------|----------|
| `load_config` 移除重复的 `multi_platforms` 旧 key 恢复（覆盖了正确的 `platforms`） | `ui_main.py` |
| 竖屏标题下半字高间隙 | `subtitle_renderer.py` |

---

## 架构（v4.3.2）

```
entry.py
ui/ui_main.py                         — MainWindow（~1300 行）
core/
├── config.py                         — 常量/API KEY/预设
├── process_thread.py                 — QThread + 多平台缓存（~175 行）
├── audio_pipeline.py                 — AI 管线（~670 行）
├── video_processor.py                — 视频处理 + 爆点 + _render_and_merge（~520 行）
├── subtitle_renderer.py              — 字幕+Overlay+章节（~520 行）
└── voice_cloner.py                   — 音色克隆（~61 行）
tests/                                — 65 个测试
AI视频配音Pro.spec / build.sh         — 打包
```

---

## 多平台处理流

```
Platform 1: trim → run_ai_pipeline → 缓存 → render → merge (保留 audio+trim)
Platform 2: ♻️ 复用缓存 → render → merge
Platform 3: ♻️ 复用缓存 → render → merge
```

---

## 测试

```bash
python3 -m pytest tests/ -v    # 65 tests
```

## 打包

```bash
bash build.sh mac     # → dist/AI视频配音Pro.app (~1.1GB)
```

## 版本历史

| 版本 | 日期 | 关键变更 |
|------|------|---------|
| v4.2.6 | 06-23 | 双 Overlay + 音唇同步 + 性能优化 |
| v4.3.0 | 06-23 | 面板互换 + 视频爆点 + 码率可配 |
| v4.3.1 | 06-25 | 章节进度条 + 多平台输出 + UI 方形统一 + 打包 |
| **v4.3.2** | **06-26** | **AI 管线复用 + H.265 tag 修复 + 配置保存修复** |
