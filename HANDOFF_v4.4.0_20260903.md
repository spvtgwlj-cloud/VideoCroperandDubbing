# HANDOFF — AI Video Dubbing Pro v4.4.0

## 项目概述

短视频 AI 配音 + 翻译 + 竖屏裁切一体化工具。v4.4.0 为**规划阶段**：新增「智能视频搜索」能力——通过自然语言在选定视频中定位并输出匹配片段。

**目标用户**：短视频运营工程师 / 跨境营销 / 自媒体创作者

---

## v4.4.0 核心规划（2026-09-03）

> ⚠️ 本版本为**设计规划**，代码尚未实现。完整设计见 `基于原配音程序上的智能视频搜索产品功能实施设计20260903.md`。

### 1. 智能视频搜索（新增功能）

用户输入一句话需求（如"找到提到价格的部分"），程序在选定视频中智能定位并输出匹配片段（独立 mp4）。

| 决策点 | 结论 |
|--------|------|
| 片段输出形式 | 纯截取原片（重编码精确切帧） |
| 语义匹配策略 | LLM 逐句打分（主）+ 关键词本地兜底 |
| 触发方式 | 独立「智能检索」按钮 + 独立后台线程 |

### 2. 涉及文件（规划）

| 变更 | 文件 |
|------|------|
| 新增检索纯逻辑（音频提取/转写/索引/逐句打分/合并/导出） | `core/smart_search.py`（新文件，~300-400 行） |
| 新增检索后台线程 | `core/search_thread.py`（新文件，~200 行） |
| 新增搜索 UI + 接线 | `ui/ui_main.py`（+150~200 行） |
| 新增测试 | `tests/test_smart_search.py`（~200 行） |

### 3. 关键约束（实现时必须遵守）

- **检索只用未压缩 Whisper `result["segments"]`**，绝不复用配音管线的 `subtitles_timeline`（`_compress_silence` 会平移时间戳、`text` 是译文）。
- **检索线程不能继承 `VideoProcessThread`**（其 `__init__` 会加载 InsightFace）。
- 复用 `_prepend_highlight` 的单段 `-ss X -t Y` 重编码写法 + `_check_videotoolbox_available` 编码器探测。

---

## 架构（v4.4.0 规划）

```
entry.py                                — 主入口（SplashScreen + API 配置检查）
ui/
├── splash_screen.py                    — 启动画面
├── api_config_dialog.py                — API 配置对话框
└── ui_main.py                          — MainWindow（+智能检索 UI）
core/
├── config.py                           — 平台预设/字幕颜色
├── llm_config.py                       — LLM 供应商配置 + 持久化
├── process_thread.py                   — QThread + 多平台缓存（主流程）
├── audio_pipeline.py                   — AI 管线（转写/翻译/TTS）
├── video_processor.py                  — 视频处理 + 爆点 + 渲染合并
├── subtitle_renderer.py                — 字幕+Overlay+章节
├── voice_cloner.py                     — 音色克隆
├── smart_search.py                     — 检索纯逻辑（规划中，新增）
└── search_thread.py                    — 检索后台线程（规划中，新增）
tests/                                  — 65 个测试（+test_smart_search）
AI视频配音Pro.spec / build.sh           — 打包
```

---

## 测试

```bash
python3 -m pytest tests/ -v    # 65 tests（+智能检索测试）
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
| v4.3.2 | 06-26 | AI 管线复用 + H.265 tag 修复 + 配置保存修复 |
| v4.3.3 | 06-29 | 启动画面（Splash Screen）— 纯代码绘制，零资源依赖 |
| v4.3.4 | 07-16 | LLM API 供应商配置化 + 平台「自定义」+ UI 修复 |
| **v4.4.0** | **09-03** | **智能视频搜索（规划中）— 自然语言检索 + 片段导出** |
