# HANDOFF — AI Video Dubbing Pro v4.2.3

## 项目概述

短视频 AI 配音 + 翻译 + 竖屏裁切工具。输入横屏/竖屏视频，自动识别人声、翻译、声音克隆、竖屏智能裁切，输出适配各平台的短视频。

**目标用户**：短视频运营工程师
**核心需求**：快速处理批量素材，多平台分发（抖音/快手/小红书/B站/YouTube）

---

## 当前状态：v4.2.3 ✅ P0 全部修复 + 新功能 + 测试套件

### v4.2.3 本回合变更摘要（2026-06-15）

| 类别 | 变更 | 涉及文件 |
|------|------|----------|
| **P0 修复** | 非 Mac 编码回退：`_check_videotoolbox_available()` 缓存探测 → `libx264`/`libx265` 回退 | `video_processor.py` |
| **P0 修复** | urllib3 警告：`entry.py` 启动过滤 + `audio_pipeline.py` 显式 `import requests` | `entry.py`, `audio_pipeline.py` |
| **P0 修复** | 进度条单调递增：管线内 100→70，TTS 上限 35→15；最终 emit(100) | `audio_pipeline.py`, `video_processor.py` |
| **BUG 修复** | 翻译循环缩进破坏导致 timeline 始终为空（SRT 0 字节 + 视频无字幕） | `audio_pipeline.py` |
| **BUG 修复** | `valid_segments` 为空时 fallback 到 `uncompressed_segments` 翻译 | `audio_pipeline.py` |
| **BUG 修复** | `_export_srt()` 空 timeline 守卫，防止 0 字节文件 | `video_processor.py` |
| **新功能** | **外部 SRT + 声音克隆**：SRT 文本驱动 TTS，声纹自动映射 | `audio_pipeline.py`, `video_processor.py` |
| **测试** | 50 个测试（单元 + E2E），覆盖全部 4 条处理路径 | `tests/`（新增） |

### 已实现功能清单

| 功能 | 说明 | 位置 |
|------|------|------|
| 平台预设模板 | 6 种一键预设（手动/抖音/快手/小红书/B站/YouTube） | `PLATFORM_PRESETS` + `on_preset_changed` |
| 批量文件夹处理 | 勾选后选文件夹，自动遍历所有视频 | `chk_batch` + `run()` 批量循环 |
| 快速预览模式 | 仅处理前 N 秒（默认15秒），快速看效果 | `chk_quick_preview` + `quick_preview_sec` |
| 视频入出口裁剪 | 起止秒数，前置 ffmpeg 裁剪 | `trim_start`/`trim_end` spinboxes |
| 字幕样式编辑 | 颜色（5色）、字号滑块（3%-10%）、背景框开关、双语字幕 | `subtitle_style` dict → `add_subtitle()` |
| 声音克隆 | CosyVoice（阿里云）+ Edge-TTS 兜底 + 原声兜底，三层回退 | `create_cloned_voice` + 三方案 TTS |
| 声纹分离 | SpeechBrain ECAPA + AgglomerativeClustering，双人分离 | `run_ai_pipeline` 步骤3 |
| 保留原声默认 | 打开程序默认仅加字幕不改声音 | `chk_voice_clone.setChecked(False)` |
| 静音段压缩 | >1.5s 静音压缩至 0.5s | `_compress_silence()` |
| 拖拽输入 | 视频拖到窗口自动填入 | `dragEnterEvent`/`dropEvent` |
| 进度条 | 管线分阶段 0-100%**（v4.2.3 修复单调性）** | `progress_changed` signal + QProgressBar |
| 输出快速打开 | 完成后"打开文件夹"和"预览视频"按钮 | `btn_open_folder`/`btn_preview` |
| 字幕翻译 | 通义千问 qwen-max，动态字数约束（中4.5字/秒，英2.8词/秒） | LLM prompt in `run_ai_pipeline` |
| InsightFace 智能追踪 | 竖屏模式下人脸检测 + 平滑阻尼追踪 | `_process_single` 竖屏分支 |
| Mac 硬件加速 | H.264/H.265 VideoToolbox 编码 **（v4.2.3 自动回退软件编码）** | `merge_audio_video` |
| 输出分辨率自定义 | QSpinBox 240-4320，锁定 9:16 比例，横屏自动置灰 | `_process_single` + `_toggle_resolution_controls` |
| 批量摘要报告 | 处理完成后弹出摘要对话框（成功/失败统计 + 失败明细） | `batch_finished` signal + `show_batch_summary` |
| 字幕时间轴微调 | ±2000ms，步长 100ms，两个分支统一偏移处理 | `subtitle_offset_spin` + 返回前偏移 |
| 双语字幕 | 原文灰色小字在译文上方间隔 2 字行，译文彩色正常字号在底部 | `add_subtitle` + `bilingual` flag |
| BGM 保留（音源分离） | spleeter 自动分人声/伴奏，TTS 后混音叠加，-9dB 衰减，自动循环 | `run_ai_pipeline` BGM 分离 + 混音叠加 |
| 配置模板保存/加载 | JSON 序列化 20+ UI 控件，FileDialog 选择路径 | `save_config` / `load_config` |
| 音频波形可视化 | ffmpeg 提取前 10 秒 → QPainter 绘制波形图在预览区下方 | `draw_waveform` / `_render_waveform` |
| 字幕导出 (SRT) | 自动导出 SRT 字幕文件，可手动编辑后导入，双语模式带 `##ORIG##` 原文标记 | `_export_srt` + `subtitles_to_srt()` |
| 外部字幕导入 | 支持加载外部 SRT 文件替换自动生成字幕用于渲染，识别 `##ORIG##` 标记恢复原文 | `_load_external_subtitles` + `parse_srt()` |
| **外部 SRT + 声音克隆** | **v4.2.3 新增**：导入 SRT 文本驱动 TTS + 声纹自动映射，跳过 LLM 翻译 | `_assign_speakers_by_overlap()` + `run_ai_pipeline(srt_timeline=)` |
| 外部字幕跳过 AI 管线 | 外部字幕+保留原声时跳过 Whisper/翻译/TTS/声纹，直出渲染 | `_process_single` Path A |
| UI 滚动视图 | 右侧面板使用 QScrollArea 包裹，小窗口自动滚动 | `ui_main.py` QScrollArea |

---

## 处理路径（v4.2.3 重构为三路径）

```
_process_single() 入口
  │
  ├── Path A: 外部 SRT + 保留原声
  │     │ 条件: subtitle_file_path ≠ "" AND enable_voice_clone = False
  │     │ 流程: 加载 SRT → 提取立体声音频 → 跳过 AI 管线 → 渲染
  │     └── 进度: 70 → 75 → 90 → 100
  │
  ├── Path B: 外部 SRT + 声音克隆  ← v4.2.3 新增
  │     │ 条件: subtitle_file_path ≠ "" AND enable_voice_clone = True
  │     │ 流程: 预加载 SRT → Whisper(仅取时间戳) → 声纹嵌入 → _assign_speakers_by_overlap()
  │     │       → 跳过 LLM 翻译 → TTS(SRT.text + SRT.timing + 克隆声音) → 渲染
  │     │       ★ SRT 文本、时间戳、克隆声音三者天然对齐
  │     └── 进度: 5→10→20→35→40→55→70→75→90→100
  │
  └── Path C: 标准 AI 管线
        │ 条件: 无外部 SRT（或仅有声音克隆无 SRT）
        ├── [保留原声] Whisper → LLM翻译 → 原声音频 → 渲染
        │     └── 进度: 5→10→20→55→70→75→90→100
        └── [声音克隆] Whisper → 声纹嵌入 → LLM翻译 → TTS → 渲染
              │  └── valid_segments 为空时 fallback 到 uncompressed_segments ← v4.2.3 新增
              └── 进度: 5→10→20→35→40→55→70→75→90→100
```

---

## 架构（v4.2 多文件结构）

### 文件结构

```
entry.py                              — 主入口（含 urllib3 警告过滤）
ui/
├── __init__.py
└── ui_main.py                        — MainWindow 主 UI (~850 行)
core/
├── __init__.py
├── config.py                         — 全局常量/API KEY/预设模板 (~35 行)
├── process_thread.py                 — VideoProcessThread (QThread), run+stop (~139 行)
├── audio_pipeline.py                 — AudioPipelineMixin, run_ai_pipeline (~620 行)
│   ├── _compress_silence()           — 静音压缩（静态方法）
│   ├── _assign_speakers_by_overlap() — SRT→声纹映射（v4.2.3 新增）
│   ├── run_ai_pipeline(srt_timeline=)— AI 核心管线（v4.2.3 新增参数）
│   └── 保留原声/声音克隆/SRT驱动 三条分支
├── video_processor.py                — VideoProcessorMixin, _process_single (~260 行)
│   ├── _check_videotoolbox_available()— 编码器探测（v4.2.3 新增）
│   ├── merge_audio_video()           — 音视频合成（v4.2.3 回退逻辑）
│   ├── _export_srt()                 — 字幕导出（v4.2.3 空守卫）
│   └── _process_single()             — 三路径分发（v4.2.3 重构）
├── subtitle_renderer.py              — 字幕渲染纯函数, 无 Qt 依赖 (~250 行)
└── voice_cloner.py                   — CosyVoice 音色克隆, 三层回退 (~61 行)
tests/                                — v4.2.3 新增
├── conftest.py                       — 共享 fixtures
├── test_subtitle_renderer.py         — 12 tests: SRT 格式/解析
├── test_audio_pipeline.py            — 15 tests: 静音压缩/声纹映射
├── test_video_processor.py           — 8 tests: 导入/导出守卫
└── test_e2e_pipeline.py              — 15 tests: 四条路径 E2E
```

---

## 功能迭代记录

| # | 功能 | 版本 | 关键修改 |
|---|------|------|----------|
| 1 | 输出分辨率自定义 | v4.2 | `output_w/output_h` + `_toggle_resolution_controls` + 锁定比例联动 |
| 2 | 批量摘要报告 | v4.2 | `batch_finished` + `show_batch_summary` |
| 3 | 字幕时间轴微调 | v4.2 | `subtitle_offset_ms` + 两分支返回前偏移 |
| 4 | 双语字幕 | v4.2→v4.2.1 | 原文从顶部 1/3 改为译文上方 2 字行 |
| 5 | BGM 保留 | v4.2 | spleeter 分离 + 混音 -9dB + 自动循环 |
| 6 | 配置模板保存/加载 | v4.2 | `save_config` / `load_config` 20+ 字段 JSON |
| 7 | 音频波形可视化 | v4.2 | ffmpeg + QPainter |
| 8 | 字幕导出 (SRT) | v4.2.1→v4.2.2 | `subtitles_to_srt()`/`parse_srt()` + `##ORIG##` 标记 |
| 9 | 外部字幕导入 | v4.2.1→v4.2.2 | `_load_external_subtitles()` + `##ORIG##` 恢复 |
| 10 | 压缩BUG根治 | v4.2.2 | `uncompressed_segments` 原始时间轴 |
| 11 | 外部字幕跳过AI | v4.2.2 | Path A 分支 |
| 12 | UI 滚动视图 | v4.2.2 | QScrollArea |
| 13 | 双语防重叠 | v4.2.2 | `_skip_original` 标志 |
| 14 | SRT 双语原文保留 | v4.2.2 | `##ORIG##` 标记闭环 |
| **15** | **非 Mac 编码回退** | **v4.2.3** | `_check_videotoolbox_available()` → `libx264`/`libx265` |
| **16** | **urllib3 警告修复** | **v4.2.3** | `entry.py` filterwarnings + `import requests` |
| **17** | **进度条单调性** | **v4.2.3** | emit(100)→emit(70), TTS 35→15, 最终 emit(100) |
| **18** | **翻译循环缩进修复** | **v4.2.3** | for 循环体缩进 +4 空格（根因：SRT 0 字节） |
| **19** | **空 valid_segments fallback** | **v4.2.3** | 回退到 `uncompressed_segments` 单说话人翻译 |
| **20** | **空 timeline 导出守卫** | **v4.2.3** | `_export_srt()` 检查 timeline 非空 + SRT 内容非空 |
| **21** | **外部 SRT + 声音克隆** | **v4.2.3** | `_assign_speakers_by_overlap()` + `run_ai_pipeline(srt_timeline=)` + Path B |
| **22** | **测试套件** | **v4.2.3** | 50 tests: 单元 27 + 集成 8 + E2E 15 |

---

## 已知问题

所有 P0 问题已修复，当前无已知阻塞性 bug。

---

## 下一阶段建议（v5.0 方向）

- **字幕样式扩展**：自定义字体、描边颜色、位置微调
- **多语言并行翻译**：一次生成中/英/日/韩多版本
- **云端处理**：阿里云函数计算，本地仅 UI
- **智能场景检测**：避开画面主体自动调整字幕位置
- **批量配置预设管理**：每平台多模板
- **SRT 格式扩展**：支持 `##SPK##` 标记保存 speaker_id，实现编辑后重新导入并保留多人克隆

---

## 依赖清单

| 包 | 用途 | 安装 |
|----|------|------|
| PyQt5 | GUI 框架 | `pip3 install PyQt5` |
| opencv-python | 视频帧处理 | `pip3 install opencv-python` |
| whisper | 语音识别 | `pip3 install openai-whisper` |
| torch / torchaudio | 声纹模型推理 | `pip3 install torch torchaudio` |
| speechbrain | 声纹嵌入 ECAPA | `pip3 install speechbrain` |
| insightface | 人脸检测追踪 | `pip3 install insightface` |
| pydub | 音频编辑/混音 | `pip3 install pydub` |
| dashscope | 阿里云 CosyVoice TTS / 音色克隆 | `pip3 install dashscope` |
| openai | LLM 翻译客户端 | `pip3 install openai` |
| scikit-learn | 声纹聚类 | `pip3 install scikit-learn` |
| Pillow | 字幕渲染 | `pip3 install Pillow` |
| requests | HTTP 客户端 | `pip3 install requests` |
| numpy | 数值计算 | `pip3 install numpy` |
| edge-tts | 语音合成兜底 | `pip3 install edge-tts` |
| audioop-lts | Python 3.14 兼容 | `pip3 install audioop-lts` |
| pytest | 测试框架 | `pip3 install pytest` |

### 可选依赖
| 包 | 用途 | 场景 |
|----|------|------|
| spleeter | 音源分离（人声/BGM） | P1 BGM保留功能 |

---

## 开发环境

- **Python**: 3.14 (Homebrew)
- **OS**: macOS (Darwin ARM64)
- **FFmpeg**: 需要安装（`brew install ffmpeg`）
- **API Keys**:
  - `DASHSCOPE_API_KEY` — 阿里云通义千问 + CosyVoice
  - `HF_ENDPOINT` — 已设置为 `https://hf-mirror.com`（国内镜像）

---

## 测试

```bash
python3 -m pytest tests/ -v       # 全部 50 个测试
python3 -m pytest tests/ -v -k e2e  # 仅 E2E 集成测试
```

---

## 启动方式

```bash
python entry.py
```

输出目录：`~/Desktop/AI_LLMTest_{yyyyMMdd_HHmm}/`

### 新增功能用法：外部 SRT + 声音克隆

1. 第一次运行：勾选「声音克隆」+「导出 SRT」→ 生成 SRT 文件
2. 打开 `.srt` 文件，手动修改翻译文本（不动时间戳）
3. 第二次运行：
   - ✅ 勾选「声音克隆」
   - 📂 字幕来源 → 「导入外部字幕文件」→ 选择编辑后的 SRT
   - ▶ 执行 → 编辑后的文本用克隆声音播出，音画同步
