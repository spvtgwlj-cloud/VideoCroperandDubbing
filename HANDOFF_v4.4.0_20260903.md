# HANDOFF — AI Video Dubbing Pro v4.4.0

## 项目概述

短视频 AI 配音 + 翻译 + 竖屏裁切一体化工具。v4.4.0 为**规划阶段**：新增「智能视频搜索」能力——通过自然语言在选定视频中定位并输出匹配片段。

**目标用户**：短视频运营工程师 / 跨境营销 / 自媒体创作者

---

## v4.4.0 核心规划（2026-09-03）

> ✅ 本版本已完成实现（2026-11-02）。完整设计见 `智能视频检索v4.4.0设计方案20261102.md`，实施计划见 `docs/superpowers/plans/2026-11-02-smart-search.md`。

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

## 实施状态（2026-11-02）

### 新增文件

| 文件 | 说明 |
|------|------|
| `core/search_types.py` | 共享 dataclass |
| `core/smart_search.py` | 检索纯逻辑（转写/缓存/打分/合并/导出/报告/台账） |
| `core/trend_sources.py` | HN/V2EX 抓取、缓存、关键词、自动归纳 |
| `core/trend_thread.py` | `TrendFetchThread` 异步抓取/归纳 |
| `core/search_thread.py` | `SmartSearchThread` 编排全流程 |
| `ui/smart_search_dialog.py` | 独立检索对话框 |
| `tests/test_smart_search.py` | 检索核心 + 功能开关测试 |
| `tests/test_trend_sources.py` | 热点 + TrendFetchThread 测试 |
| `tests/test_search_thread.py` | 编排线程测试 |

### 修改文件

- `core/config.py`：新增 `ENABLE_SMART_SEARCH`（`AI_VIDEO_SMART_SEARCH=0` 可关闭）
- `ui/ui_main.py`：「🔑 AI 大模型设置」右侧新增「🔍 智能检索」按钮 + 懒加载入口
- `AI视频配音Pro.spec`：新增 6 个 hiddenimports

### 测试

```bash
python3 -m pytest tests/ -q    # 119 passed, 1 skipped
```

新增 55 个测试，覆盖关键词匹配/预筛、片段合并、转写缓存、LLM 批量打分与熔断、导出/报告/去重台账、热点抓取/归纳、编排线程、功能开关与 UI 线程保护。

### 端到端验证

- 生成 15 秒测试视频，语音真实起点 5.0s。
- Whisper 词级时间戳收紧后转写为 4.52–7.06s；导出片段 4.02–7.56s（误差 < 0.5s）。
- 转写缓存命中、`search_results.json` 生成、H.264 片段导出均验证通过。

### 已知限制

- Whisper `transcribe` 无法中途打断；若正在转写，停止需等当前视频处理完。ffmpeg 提取/导出支持取消。
- HN 网络不稳定时热榜抓取可能失败；不影响仅用提示词检索。
- 检索窗口当前固定 H.264 / 4 Mbps，未暴露编码/码率控件。
- GUI 的完整手动点击流程建议发布前再走一遍验收。

### 分支与回退

- 基线：`abff400` / 标签 `v4.3.4-baseline`
- 开发分支：`feature/v4.4.0-smart-search`
- 运行时关闭：`AI_VIDEO_SMART_SEARCH=0`
- 代码回退：`git checkout v4.3.4-baseline`

---

## 架构（v4.4.0）

```
entry.py                                — 主入口（SplashScreen + API 配置检查）
ui/
├── splash_screen.py                    — 启动画面
├── api_config_dialog.py                — API 配置对话框
├── smart_search_dialog.py              — 独立检索对话框（新增）
└── ui_main.py                          — MainWindow（+智能检索入口）
core/
├── config.py                           — 平台预设/字幕颜色
├── llm_config.py                       — LLM 供应商配置 + 持久化
├── process_thread.py                   — QThread + 多平台缓存（主流程）
├── audio_pipeline.py                   — AI 管线（转写/翻译/TTS）
├── video_processor.py                  — 视频处理 + 爆点 + 渲染合并
├── subtitle_renderer.py                — 字幕+Overlay+章节
├── voice_cloner.py                     — 音色克隆
├── search_types.py                     — 检索共享 dataclass（新增）
├── smart_search.py                     — 检索纯逻辑（新增）
├── trend_sources.py                    — HN/V2EX 热点抓取（新增）
├── trend_thread.py                     — 热点异步抓取线程（新增）
└── search_thread.py                    — 检索后台线程（新增）
tests/                                  — 120 个测试（65 基线 + 55 新增）
AI视频配音Pro.spec / build.sh           — 打包
```

---

## 测试

```bash
python3 -m pytest tests/ -v    # 119 passed + 1 skipped（120 tests）
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
| **v4.4.0** | **11-02** | **智能视频检索 — 热点/批量/缓存/独立窗口（已实现）** |
