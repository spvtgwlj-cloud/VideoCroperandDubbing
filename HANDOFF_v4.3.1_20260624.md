# HANDOFF — AI Video Dubbing Pro v4.3.1

## 项目概述

短视频 AI 配音 + 翻译 + 竖屏裁切工具。含字幕叠加、声音克隆、章节进度条、视频爆点片头。

**目标用户**：短视频运营工程师
**核心需求**：快速处理批量素材，多平台分发（抖音/快手/小红书/B站/YouTube）

---

## 当前状态：v4.3.1 ✅ 章节进度条 + 布局优化 + 打包支持

### v4.3.1 本回合变更摘要（2026-06-24）

| 类别 | 变更 | 涉及文件 |
|------|------|----------|
| **章节进度条** | 底部时间轴展示全部章节，已播灰色遮罩 + 播放头竖线，首字左对齐时间标记 | `core/subtitle_renderer.py` |
| **章节 UI** | QGroupBox 可折叠，默认关闭，动态增删行，配置保存/加载 | `ui/ui_main.py` |
| **横屏布局** | 章节栏高度压缩至 base_dim×0.028，标题间隙固定 25px，字号缩小 1 号(0.055→0.048) | `core/subtitle_renderer.py` `ui/ui_main.py` |
| **CosyVoice 上传** | 上传音频映射不依赖视频声纹检测，独立创建角色音色 | `core/audio_pipeline.py` |
| **CosyVoice 日志** | 增强错误日志（HTTP 状态码 + API message + 3 次重试标记），TTS 阶段输出 ref_prompts 摘要 | `core/audio_pipeline.py` |
| **SpeechBrain** | EncoderClassifier 回退 CPU（不支持 MPS run_opts） | `core/audio_pipeline.py` |
| **Overlay 独立** | 主标题/分享人独立于字幕开关渲染 | `core/subtitle_renderer.py` |
| **主标题居中** | 主标题从靠左改为居中 | `core/subtitle_renderer.py` |
| **应用打包** | PyInstaller onedir 模式 + speechbrain runtime hook，支持 Mac (.app)/Windows | `AI视频配音Pro.spec` `build.sh` `hook-speechbrain.py` |

---

## 章节进度条详解

### 渲染效果

```
┌──────────────────────────────────────────────┐
│                 视频内容                      │
├──────────────────────────────────────────────┤
│ ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓│  核心内容  │  结尾          │
│ ← 已播灰遮罩     │  未播：黑底+清晰白字      │
│                  │                          │
│  开场    产品展示 │                          │
│  ▏               ▏             ▏            │  ← 小竖线标记
└──────────────────┴──────────────────────────┘
           ↑ 播放头蓝色竖线
```

- 全部章节一次性展示在时间轴上
- 首字严格左对齐章节开始时间标记
- 已播区域覆盖半透明灰色遮罩（alpha=55），隐约透出文字
- 未播区域黑底+清晰章节文字
- 蓝色播放头竖线标记当前位置

### 横屏特殊处理

| 参数 | 竖屏 | 横屏 |
|------|:--:|:--:|
| 章节字号 | 0.68×字幕 | 0.38×字幕 |
| 栏高 | 自动 | 固定 base_dim×0.028 |
| 标题间隙 | 25px | 25px |
| 字幕字号 | 0.048(4.8%) | 0.048(4.8%) |

---

## 架构（v4.3.1）

```
entry.py                              — 主入口（23 行）
ui/ui_main.py                         — MainWindow（~1290 行）
core/
├── config.py                         — 常量/API KEY/预设（~58 行）
├── process_thread.py                 — QThread（~165 行）
├── audio_pipeline.py                 — AI 管线（~670 行）
├── video_processor.py                — 视频处理（~380 行）
├── subtitle_renderer.py              — 字幕+Overlay+章节渲染（~500 行）
└── voice_cloner.py                   — 音色克隆（~61 行）
tests/                                — 59 个测试
AI视频配音Pro.spec                    — PyInstaller 打包配置
build.sh                              — 打包脚本
hook-speechbrain.py                   — Runtime hook
```

---

## 测试

```bash
python3 -m pytest tests/ -v       # 全部 59 个测试
```

---

## 打包

```bash
# Mac → dist/AI视频配音Pro.app (~1.1GB)
bash build.sh mac

# Windows → dist/AI视频配音Pro/
bash build.sh win
```

首次运行需：
- FFmpeg（Mac: `brew install ffmpeg`，Win: `ffmpeg.exe` 放根目录）
- Whisper/SpeechBrain/InsightFace 模型首次自动下载（~3GB）

---

## 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| v4.2.5 | 2026-06-16 | UI 深色科技风 + 左侧三栏 |
| v4.2.6 | 2026-06-23 | 双 Overlay + 音唇同步 + 视频裁剪修正 + 线程安全 + 性能优化 |
| v4.3.0 | 2026-06-23 | 面板左右互换 + 视频爆点 + 码率可配 + 主标题居中 + Overlay 独立 |
| **v4.3.1** | **2026-06-24** | **章节进度条 + 横屏布局优化 + CosyVoice 上传修复 + 打包支持** |
