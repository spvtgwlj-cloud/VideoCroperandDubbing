# HANDOFF — AI Video Dubbing Pro v4.2.2

## 项目概述

短视频 AI 配音 + 翻译 + 竖屏裁切工具。输入横屏/竖屏视频，自动识别人声、翻译、声音克隆、竖屏智能裁切，输出适配各平台的短视频。

**目标用户**：短视频运营工程师  
**核心需求**：快速处理批量素材，多平台分发（抖音/快手/小红书/B站/YouTube）

---

## 当前状态：v4.2.2 ✅ P0/P1/P2 全部完成 + BUG 修复

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
| 进度条 | 管线分阶段 0-100% | `progress_changed` signal + QProgressBar |
| 输出快速打开 | 完成后"打开文件夹"和"预览视频"按钮 | `btn_open_folder`/`btn_preview` |
| 字幕翻译 | 通义千问 qwen-max，动态字数约束（中4.5字/秒，英2.8词/秒） | LLM prompt in `run_ai_pipeline` |
| InsightFace 智能追踪 | 竖屏模式下人脸检测 + 平滑阻尼追踪 | `_process_single` 竖屏分支 |
| Mac 硬件加速 | H.264/H.265 VideoToolbox 编码 | `merge_audio_video` |
| **输出分辨率自定义** | QSpinBox 240-4320，锁定 9:16 比例，横屏自动置灰 | `_process_single` + `_toggle_resolution_controls` |
| **批量摘要报告** | 处理完成后弹出摘要对话框（成功/失败统计 + 失败明细） | `batch_finished` signal + `show_batch_summary` |
| **字幕时间轴微调** | ±2000ms，步长 100ms，两个分支统一偏移处理 | `subtitle_offset_spin` + 返回前偏移 |
| **双语字幕** | 原文灰色小字在译文上方间隔 2 字行，译文彩色正常字号在底部 | `add_subtitle` + `bilingual` flag |
| **BGM 保留（音源分离）** | spleeter 自动分人声/伴奏，TTS 后混音叠加，-9dB 衰减，自动循环 | `run_ai_pipeline` BGM 分离 + 混音叠加 |
| **配置模板保存/加载** | JSON 序列化 20+ UI 控件，FileDialog 选择路径 | `save_config` / `load_config` |
| **音频波形可视化** | ffmpeg 提取前 10 秒 → QPainter 绘制波形图在预览区下方 | `draw_waveform` / `_render_waveform` |
| **字幕导出 (SRT)** | 自动导出 SRT 字幕文件，可手动编辑后导入，双语模式带 `##ORIG##` 原文标记 | `_export_srt` + `subtitles_to_srt()` |
| **外部字幕导入** | 支持加载外部 SRT 文件替换自动生成字幕用于渲染，识别 `##ORIG##` 标记恢复原文 | `_load_external_subtitles` + `parse_srt()` |
| **外部字幕跳过 AI 管线** | 外部字幕+保留原声时跳过 Whisper/翻译/TTS/声纹，直出渲染 | `_process_single` 分支逻辑 |
| **UI 滚动视图** | 右侧面板使用 QScrollArea 包裹，小窗口自动滚动 | `ui_main.py` QScrollArea |
| **静音段压缩时间轴修复** | 保留原声分支使用原始时间轴而非压缩时间轴 | `audio_pipeline.py` `uncompressed_segments` |
| **双语字幕防重叠** | 原文与译文空间不足时自动跳过原文渲染 | `subtitle_renderer.py` `_skip_original` |

---

## 架构（v4.2 多文件结构）

### 文件结构

```
entry.py                              — 主入口 (17 行)
ui/
├── __init__.py
└── ui_main.py                        — MainWindow 主 UI (~850 行)
core/
├── __init__.py
├── config.py                         — 全局常量/API KEY/预设模板 (~35 行)
├── process_thread.py                 — VideoProcessThread (QThread), run+stop (~139 行)
├── audio_pipeline.py                 — AudioPipelineMixin, run_ai_pipeline (~547 行)
├── video_processor.py                — VideoProcessorMixin, _process_single (~200 行)
├── subtitle_renderer.py              — 字幕渲染纯函数, 无 Qt 依赖 (~250 行)
└── voice_cloner.py                   — CosyVoice 音色克隆, 三层回退 (~61 行)
```

### 类继承关系

```
VideoProcessThread(QThread, AudioPipelineMixin, VideoProcessorMixin)
├── QThread                          — PyQt 线程骨架
│   ├── run()                        — 入口：批量或单文件
│   └── stop()                       — 安全停止（8秒超时）
├── AudioPipelineMixin               — → audio_pipeline.py
│   ├── run_ai_pipeline()            — AI 核心管线（音频→Whisper→声纹→翻译→TTS）
│   ├── create_cloned_voice()        — 代理到 voice_cloner 模块
│   └── _compress_silence(segments)  — 静音段压缩（静态方法）
└── VideoProcessorMixin              — → video_processor.py
    ├── _process_single()            — 单视频处理（渲染+字幕+人脸追踪）
    ├── merge_audio_video()          — 音视频合成
    └── add_subtitle()               — 代理到 subtitle_renderer 模块

MainWindow(QMainWindow)              — → ui/ui_main.py
├── init_ui()                        — 构建全部 UI 控件（21行 grid）
├── on_preset_changed()              — 平台预设切换
├── toggle_clone_options()           — 声音配置联动显隐
├── _toggle_subtitle_source()        — 字幕来源（自动/外部）切换显隐
├── start_processing()               — 收集配置→启动线程
├── reset_processing_state()         — 线程完成后恢复 UI
├── dragEnterEvent/dropEvent         — 拖拽输入
├── open_output_folder/preview_output — 输出操作
├── save_config / load_config        — 配置模板序列化
├── browse_video / browse_audio / browse_subtitle — 文件浏览
├── draw_waveform / _render_waveform — 音频波形绘制
└── closeEvent                       — 安全关闭
```

### 数据流

```
输入视频
  │
  ├── [外部字幕 + 保留原声快捷路径]
  │     │
  │     ▼ 直接加载外部 SRT → subtitles_timeline[]
  │     ▼ FFmpeg 提取原始立体声音频 (48kHz stereo)
  │     ▼ 跳过 Whisper/翻译/TTS/声纹/BGM，直出渲染
  │
  └── [标准 AI 管线]
        │
        ▼ [步骤1] FFmpeg 提取音频 (WAV 48kHz mono)
        │
        ▼ [步骤2] Whisper 语音识别 → segments[]
        │            └── _compress_silence() 压缩静音（声音克隆分支）
        │            └── uncompressed_segments（保留原声分支）
        │
        ├── [保留原声分支] 翻译音频 → 字幕 → 仅加字幕输出
        │
        └── [声音克隆分支]
              │
              ▼ [步骤3] SpeechBrain 声纹嵌入 → AgglomerativeClustering 聚类
              │          → 每个角色提取最长片段作为参考音色
              │            └── 可选：上传音频映射覆盖
              │
              ▼ [步骤4] LLM 逐句翻译（带字数约束）
              │
              ▼ [步骤5] TTS 生成（CosyVoice → Edge-TTS → 原声兜底）
              │          → 变速对齐 → 混音到画板
              │
              ▼ 最终音频 WAV
  │
  ▼ 画面渲染（人脸追踪裁切 1080×1920 / 横屏）
  │    └── 字幕叠加
  │
  ▼ FFmpeg 音视频合成（VideoToolbox H.264/H.265）
  │
  ▼ 输出 MP4 → ~/Desktop/AI_LLMTest_{timestamp}/
```

### 预设模板数据

```python
PLATFORM_PRESETS = {
    "手动配置":     {is_vertical: None, subtitle_pos: -1,     codec: None,           fps: 0},
    "抖音 / 视频号": {is_vertical: True,  subtitle_pos: 0.25, codec: "H.264 (MP4)",  fps: 30, ow: 1080, oh: 1920},
    "快手":          {is_vertical: True,  subtitle_pos: 0.20, codec: "H.265 (HEVC)", fps: 30, ow: 1080, oh: 1920},
    "小红书":        {is_vertical: True,  subtitle_pos: 0.15, codec: "H.264 (MP4)",  fps: 30, ow: 1080, oh: 1440},
    "B站":          {is_vertical: False, subtitle_pos: 0.08, codec: "H.265 (HEVC)", fps: 30, ow: 0, oh: 0},
    "YouTube":      {is_vertical: False, subtitle_pos: 0.08, codec: "H.264 (MP4)",  fps: 30, ow: 0, oh: 0},
}
```

---

## 功能迭代记录

| # | 功能 | 版本 | 关键修改 |
|---|------|------|----------|
| 1 | 输出分辨率自定义 | v4.2 | `output_w/output_h` 参数 + `_toggle_resolution_controls` + 锁定比例联动 |
| 2 | 批量摘要报告 | v4.2 | `batch_finished` 信号 + `show_batch_summary` 对话框 |
| 3 | 字幕时间轴微调 | v4.2 | `subtitle_offset_ms` 参数 + 两分支返回前偏移 |
| 4 | 双语字幕 | v4.2 → v4.2.1 | 原文从顶部 1/3 改为译文上方间隔 2 字行 |
| 5 | BGM 保留（音源分离） | v4.2 | spleeter 分离 + 混音叠加 + -9dB 衰减 + 自动循环 |
| 6 | 配置模板保存/加载 | v4.2 | `save_config` / `load_config` 20+ 字段 JSON |
| 7 | 音频波形可视化 | v4.2 | ffmpeg + QPainter 波形绘制 + browse/drop 触发 |
| 8 | 字幕导出 (SRT) | v4.2.1 → v4.2.2 | `subtitles_to_srt()` / `parse_srt()` + UI 控件；v4.2.2 添加 `##ORIG##` 原文标记 |
| 9 | 外部字幕导入 | v4.2.1 → v4.2.2 | `_load_external_subtitles()` + `_export_srt()`；v4.2.2 添加 `##ORIG##` 标记解析恢复原文 |
| 10 | 压缩BUG根治 | v4.2.2 | 保留原声分支使用 `uncompressed_segments` 原始时间轴 |
| 11 | 外部字幕跳过AI | v4.2.2 | `_process_single` 分支逻辑，跳过 Whisper/翻译/TTS/声纹直出 |
| 12 | UI 滚动视图 | v4.2.2 | QScrollArea 包裹右侧面板 |
| 13 | 双语防重叠 | v4.2.2 | `_skip_original` 标志跳过空间不足时的原文渲染 |
| 14 | SRT 双语原文保留 | v4.2.2 | 导出 SRT 时用 `##ORIG##` 标记保存原文；导入时恢复 `original_text`，SRT→外部字幕→双语渲染完整闭环 |

---

## 下一阶段建议

以下方向可作为 v5.0 的开发目标：

### P0 已修复（影响功能正确性）
- ~~**静音段压缩时间轴错位**~~ → **✅ 已修复** (v4.2.2)
- ~~**非 Mac 编码回退**~~ → **✅ 已修复** (v4.2.2: 自动探测 ffmpeg 编码器，VideoToolbox 不可用时回退 `libx264`/`libx265`)
- ~~**依赖版本警告修复**~~ → **✅ 已修复** (v4.2.2: 添加 `warnings.filterwarnings` + 显式 `import requests` 修复)

### 新功能方向
- **字幕样式扩展**：支持自定义字体上传、描边颜色、位置微调
- **多语言并行翻译**：一次处理生成多语言版本（中/英/日/韩...）
- **云端处理**：将管线移至阿里云函数计算，本地仅做 UI
- **智能场景检测**：根据画面内容自动调整字幕位置（避开画面主体）
- **批量配置预设管理**：每个平台可自定义多个配置模板

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
| requests | HTTP 客户端 | `built-in` |
| numpy | 数值计算 | `pip3 install numpy` |
| edge-tts | 语音合成兜底 | `pip3 install edge-tts` |
| audioop-lts | Python 3.14 兼容（替代移除的 audioop） | `pip3 install audioop-lts` |

### 可选依赖
| 包 | 用途 | 场景 |
|----|------|------|
| spleeter | 音源分离（人声/BGM） | P1 BGM保留功能 |
| pyqtgraph | 波形图绘制 | P2 音频可视化 |

---

## 开发环境

- **Python**: 3.14 (Homebrew)
- **OS**: macOS (Darwin ARM64)
- **FFmpeg**: 需要安装（`brew install ffmpeg`）
- **API Keys**:
  - `DASHSCOPE_API_KEY` — 阿里云通义千问 + CosyVoice（硬编码了默认值，可通过环境变量覆盖）
  - `HF_ENDPOINT` — 已设置为 `https://hf-mirror.com`（国内镜像）

---

## 已知问题

1. ~~**requests urllib3 版本警告**~~ → **✅ 已修复** (v4.2.2: entry.py 启动时过滤 + 显式 `import requests`)
2. ~~竖屏输出分辨率硬编码~~ → **✅ 已修复** (v4.2: 动态 `output_w/output_h`，默认 1080×1920)
3. ~~单文件过大~~ → **✅ 已修复** (已按方案 B 拆分为多文件结构)
4. ~~**只有 Mac VideoToolbox 编码**~~ → **✅ 已修复** (v4.2.2: 自动探测 ffmpeg 编码器，回退 `libx264`/`libx265`)
5. ~~**`_compress_silence` 导致保留原声分支下字幕后半段消失**~~ → **✅ 已修复** (v4.2.2: 保留原声分支使用 `uncompressed_segments` 原始时间轴)

---

## 启动方式

```bash
# 单人单视频
python entry.py

# 批量处理
# → 勾选"批量处理" → "选择文件夹" → 开始执行
```

输出目录：`~/Desktop/AI_LLMTest_{yyyyMMdd_HHmm}/`
