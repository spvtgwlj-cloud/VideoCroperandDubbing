# HANDOFF — AI Video Dubbing Pro v4.3.0

## 项目概述

短视频 AI 配音 + 翻译 + 竖屏裁切工具。输入横屏/竖屏视频，自动识别人声、翻译、声音克隆、竖屏智能裁切，输出适配各平台的短视频。

**目标用户**：短视频运营工程师
**核心需求**：快速处理批量素材，多平台分发（抖音/快手/小红书/B站/YouTube）

---

## 当前状态：v4.3.0 ✅ 面板左右互换 + 视频爆点片头 + 码率可配

### v4.3.0 本回合变更摘要（2026-06-23）

| 类别 | 变更 | 涉及文件 |
|------|------|----------|
| **布局互换** | 系统配置移至左侧(stretch=6)，预览/波形/叠加/日志移至右侧(stretch=5) | `ui/ui_main.py` |
| **视频爆点** | 从处理后视频截取 1-5 秒片段作为片头（concat filter 重编码），起始时间/时长可配 | `ui/ui_main.py` `core/video_processor.py` `core/process_thread.py` |
| **码率可配** | 输出码率改为 UI 可配（1-20 Mbps SpinBox），FPS 固定 30 不展示，"编码/帧率"→"编码/码率" | `ui/ui_main.py` `core/config.py` |
| **主标题居中** | 主标题 overlay 从靠左改为居中放置 | `core/subtitle_renderer.py` |
| **Overlay 独立** | 主标题/分享人独立于字幕开关，无字幕时也会渲染 | `core/subtitle_renderer.py` |
| **字体统一** | 视频叠加信息/视频爆点字体匹配系统配置 | `ui/ui_main.py` |

### v4.2.6 变更摘要（2026-06-23）

| 类别 | 变更 | 涉及文件 |
|------|------|----------|
| **双 Overlay** | 视频主标题（黑色+黄色渐变圆角）+ 分享人（白色+紫色渐变圆角），UI 输入 GroupBox | `core/subtitle_renderer.py` `ui/ui_main.py` |
| **音唇同步修复** | 声音克隆 TTS 使用原始时间戳（uncompressed_segments），消除音频前移 | `core/audio_pipeline.py` |
| **视频裁剪修正** | `-to` 从输出选项改为输入选项（语义从时长→截止位置）；UX 去 SpecialValueText | `core/video_processor.py` `ui/ui_main.py` |
| **线程安全** | closeEvent 断开 finished 信号 + trim 子进程 running 检查 | `ui/ui_main.py` `core/video_processor.py` |
| **渐变修复** | 渐变背景 mask 乘入 alpha 通道，修复纯色 bug | `core/subtitle_renderer.py` |
| **性能优化** | `_fit_text_to_width` @lru_cache + 渐变图预渲染缓存 + M1 MPS 加速 | `core/subtitle_renderer.py` `core/audio_pipeline.py` |
| **码率调整** | 视频码率 5→4 Mbps | `core/video_processor.py` |
| **字号上限** | Overlay 标题/分享人最大字号 clamp（比字幕大 2 号） | `core/subtitle_renderer.py` |

---

## v4.3.0 新功能详解

### 1. 面板左右互换

```
┌──────────────────────────┬──────────────────────────────────┐
│ 📦 系统配置 (左侧)        │ 🔥视频爆点  │ 🎬 视频预览         │
│   平台预设  本地视频       │ ☑ 起始:[0]秒│                   │
│   批量处理  视频裁剪       │ 时长:[3]秒   │                   │
│   语言  输出  分辨率       │              │                   │
│   字幕配置  字幕样式       │  🎵 音频波形（前60秒）           │
│   导出  声音克隆           │  🏷️ 视频叠加信息               │
│   编码/码率  [4 Mbps]     │  📋 运行日志                    │
│   进度条  按钮区           │                                 │
└──────────────────────────┴──────────────────────────────────┘
```

### 2. 视频爆点

- 从处理后的完整视频中截取指定片段作为片头
- 起始时间 + 时长（1-5 秒）可配，默认 3 秒
- 使用 concat filter 重编码拼接，确保可靠性
- 编码器和码率与主视频一致

### 3. 码率可配

- FPS 固定 30 不再展示
- 原 FPS 位置改为码率 SpinBox（1-20 Mbps，默认 4）
- 传递给 merge_audio_video 和 _prepend_highlight 的 `-b:v` 参数

### 4. 主标题居中 + Overlay 独立性

- 主标题从靠左改为居中
- 主标题和分享人独立于「启用字幕」开关
- 无字幕时仍正常渲染 overlay

---

## 架构（v4.3.0 多文件结构）

```
entry.py                              — 主入口（23 行）
ui/
└── ui_main.py                        — MainWindow 主 UI（~1170 行）
core/
├── config.py                         — 全局常量/API KEY/预设模板/Edge-TTS 音色列表（~58 行）
├── process_thread.py                 — VideoProcessThread (QThread), run+stop（~163 行）
├── audio_pipeline.py                 — AudioPipelineMixin, run_ai_pipeline（~660 行）
├── video_processor.py                — VideoProcessorMixin（~370 行）
│   ├── merge_audio_video()           — 音视频合成（编码器自动回退）
│   └── _prepend_highlight()          — 视频爆点截取+拼接（concat filter）
├── subtitle_renderer.py              — 字幕+Overlay 渲染纯函数（~395 行）
│   ├── _fit_text_to_width()          — 字号二分查找（@lru_cache 缓存）
│   ├── _make_gradient_bg()           — 渐变背景预渲染（@lru_cache 缓存）
│   └── add_subtitle()                — 字幕 + 标题 + 分享人叠加
└── voice_cloner.py                   — CosyVoice 音色克隆（~61 行）
tests/                                — 59 个测试
├── conftest.py
├── test_subtitle_renderer.py         — 22 tests
├── test_audio_pipeline.py            — 15 tests
├── test_video_processor.py           — 8 tests
└── test_e2e_pipeline.py              — 14 tests
```

---

## 类继承关系

```
VideoProcessThread(QThread, AudioPipelineMixin, VideoProcessorMixin)
├── QThread                      — PyQt5 线程骨架
├── AudioPipelineMixin           — core/audio_pipeline.py
│   ├── run_ai_pipeline()        — AI 核心管线（MPS 加速 + TTS 双策略）
│   ├── _compress_silence()      — 静音段压缩
│   ├── _assign_speakers_by_overlap() — SRT→声纹映射
│   ├── _run_cosyvoice_tts()     — CosyVoice TTS
│   └── _run_edge_tts()          — Edge-TTS 合成
└── VideoProcessorMixin          — core/video_processor.py
    ├── _process_single()        — 单视频处理（裁剪→管线→渲染→合成→爆点）
    ├── merge_audio_video()      — 音视频合成（码率可配）
    ├── _prepend_highlight()     — 视频爆点（concat filter）
    ├── _export_srt()            — 字幕导出
    └── _load_external_subtitles() — 外部字幕加载

MainWindow(QMainWindow)          — ui/ui_main.py
```

---

## 处理路径（v4.3.0）

```
_process_single() 入口
  │
  ├── 裁剪预处理（trim，所有路径共享）
  │
  ├── Path A: 外部 SRT + 保留原声（跳过 AI）
  ├── Path B: 外部 SRT + 声音克隆（LSRT 驱动 TTS）
  └── Path C: 标准 AI 管线
        └── [声音克隆] TTS 策略排序：
              ├── Edge-TTS 优先（分角色音色） → CosyVoice → 原声
              └── 原有模式（CosyVoice → Edge-TTS → 原声）
  │
  ├── 画面裁切渲染 + 字幕叠加 + Overlay 渲染
  ├── merge_audio_video()（码率可配）
  └── _prepend_highlight()（可选，视频爆点片头）
```

---

## 已知问题

**当前无已知阻塞性 bug。**

### v4.3.0 修复记录

| # | 问题 | 修复方式 |
|---|------|---------|
| 1 | concat demuxer `-c copy` 导致爆点片头丢失 | 改用 concat filter 重编码 |
| 2 | 爆点截取首帧黑场 | `-ss` 从 input seek 改为 output seek |
| 3 | Overlay 依赖字幕开关 | 移除 early return，overlay 始终渲染 |

---

## 测试

```bash
python3 -m pytest tests/ -v       # 全部 59 个测试
```

---

## 启动方式

```bash
python entry.py
```

---

## 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| v4.0 | - | 基础管线 |
| v4.2.3 | 2026-06-15 | P0 修复 + Path B + 50 测试 |
| v4.2.4 | 2026-06-15 | Edge-TTS 优先 + 分角色音色 + Code Review 10 项 |
| v4.2.5 | 2026-06-16 | UI 深色科技风 + 左侧三栏 + 双语间隔 + Row 7/8 优化 |
| v4.2.6 | 2026-06-23 | 双 Overlay + 音唇同步 + 视频裁剪修正 + 线程安全 + 性能优化 |
| **v4.3.0** | **2026-06-23** | **面板左右互换 + 视频爆点 + 码率可配 + 主标题居中 + Overlay 独立** |
