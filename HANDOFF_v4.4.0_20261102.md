# HANDOFF — AI Video Dubbing Pro v4.4.0

## 项目概述

短视频 AI 配音 + 翻译 + 竖屏裁切一体化工具。v4.4.0 已实现「智能视频搜索」能力——通过自然语言在选定视频中定位并输出匹配片段；2026-11-03 增加热榜关联优化、空结果诊断与「建议脚本」生成。

**目标用户**：短视频运营工程师 / 跨境营销 / 自媒体创作者

---

## v4.4.0 核心规划（2026-11-02）

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
python3 -m pytest tests/ -q    # 170 passed, 1 skipped（截至 2026-11-03）
```

新增 66 个测试，覆盖关键词匹配/预筛、片段合并、转写缓存、LLM 批量打分与熔断、导出/报告/去重台账、热点抓取/归纳、编排线程、功能开关、UI 线程保护、进度反馈、空结果兜底与导出兼容性。

2026-11-03 再新增 40 个测试，覆盖多角度独立计分、热度微调、LLM `angle_index`、空结果分型、弱相关开关与建议脚本生成。

### 端到端验证

- 生成 15 秒测试视频，语音真实起点 5.0s。
- Whisper 词级时间戳收紧后转写为 4.52–7.06s；导出片段 4.02–7.56s（误差 < 0.5s）。
- 转写缓存命中、`search_results.json` 生成、H.264 片段导出均验证通过。

### 已知限制

- Whisper `transcribe` 无法中途打断；若正在转写，停止需等当前视频处理完。ffmpeg 提取/导出支持取消。
- HN 网络不稳定时热榜抓取可能失败；不影响仅用提示词检索。
- 检索窗口当前固定 H.264 / 4 Mbps，未暴露编码/码率控件。
- 搜索片段是纯截取，不做音量归一化；源片段静音/音量低时，输出同样静音/低。
- 因保留源信号，VFR 源片段在部分播放器仍可能卡顿；PCM 源音频在 MP4 中保持 PCM，个别播放器可能不支持。
- GUI 的完整手动点击流程建议发布前再走一遍验收。

### 用户反馈修复（2026-11-02）

- 开始检索校验失败时，状态栏显示红色提示，不再只有底部日志。
- 打开检索窗口时自动带入主窗口已选的单文件/批量文件夹。
- 进度按「提取音频 → 转写 → LLM 打分 → 合并 → 导出」分阶段更新；LLM 每批显示 `X/Y 句`。
- LLM 打分阶段支持停止，不必等到整批结束。
- 缓存命中时日志明确提示「跳过音频提取/Whisper 转写」，进度直接从 50% 开始打分。
- LLM 网络/超时失败不再逐句重试；连续两批失败即降级关键词，避免长时间停在 50%。
- 强匹配为 0 时自动放宽关键词兜底（`min_score=0.0`）；报告记录 `stats` 与 `relaxed_fallback_used`，日志提示需人工复核。
- 按用户要求保留源信号：不强制 CFR、保留源帧率；音频 `-c:a copy`，不重编码、不做音量归一化；仅视频为精确切帧重编码；移除数据/时间码轨（仅元数据）。

### 热点关联与建议脚本增强（2026-11-03）

#### 1. 热榜关联优化

- 本地关键词/预筛改为「query 与每个角度独立计分取最大值」，不再被角度数量稀释。
- 角度归属阈值 `ANGLE_ATTRIBUTION_MIN = 0.15`；`TrendAngle` / `Hit` / `Clip` 增加归一化热度、原始热度与来源。
- 热度按来源分别 min-max 归一化；最终分 = 内容分 + `HEAT_BONUS_MAX(0.05) × 热度`，只做同分微调。
- LLM 逐句打分要求返回 `angle_index`，并新增「只有可独立成片的明确信息才算相关」的严格约束。
- 结果列表显示契合度、关联角度与原始热度；悬停显示命中理由、命中句与最终排序分。

#### 2. 空结果诊断与弱相关开关

- `search_results.json` 新增 `stats.zero_reason`、`stats.relaxed_enabled` 与 `file_stats[]`。
- `zero_reason` 区分：`llm_no_relevant` / `llm_unavailable` / `llm_parse_error` / `llm_partial_parse_error` / `no_segments` / `keyword_no_match` / `file_error`。
- 参数区新增「无强匹配时输出弱相关片段（需人工复核）」，默认关闭；只有勾选后才执行 `min_score=0.0` 兜底。
- LLM 正常但 0 命中时，UI 状态栏与报告明确提示「调用正常、判定无相关」，不再被泛化提示覆盖。

#### 3. 建议脚本模块

- 新增 `core/script_suggest.py`、`core/script_thread.py`、`ui/script_dialog.py`。
- 入口：智能检索窗口「📝 建议脚本」按钮，针对当前选中的单个视频（批量时使用第一个并提示）。
- 流程：复用转写缓存（无缓存则 Whisper turbo 转写）→ 使用已有热点角度或自动抓取 HN/V2EX 并归纳 → LLM 生成结构化脚本 → 解析句子编号为真实时间范围 → 保存 `suggested_script.json` / `suggested_script.md`。
- 输出：标题、3 秒钩子、目标时长、分段口播、引用素材时间范围/画面说明、CTA、选题理由；无素材分段标记「需补拍」。
- LLM 超时 120 秒、`max_tokens=1800`、关闭 SDK 自动重试；日志提示约需 1–2 分钟。
- 打包：`AI视频配音Pro.spec` 增加 `core.script_suggest`、`core.script_thread`、`ui.script_dialog` 三个 hiddenimports。

#### 4. UI 修复

- 顶部设置区套 `QScrollArea`，参数区不再被压缩；窗口高度不足时滚动。
- 热点复选框补齐深色可见样式；自动模式隐藏复选框，手动模式才可勾选。
- 「深度模式」与「强制重新导出」合并到同一行；输出目录改为独立横排并设最小宽度。

#### 5. 验证

- `python3 -m pytest tests/ -q` → **170 passed, 1 skipped**。
- 真实模型验证建议脚本：耗时 99.6s，生成 4 段，引用时间范围 `4.1-22.7s` / `59.1-79.9s` / `80.7-112.4s`；借势段无对应素材，正确标记「需补拍」。

#### 6. 已知限制（本次新增）

- 建议脚本当前模型生成约 100 秒，120 秒超时余量有限；网络慢时需重试。
- 建议脚本仅支持单个视频；输出文件名固定，同一输出目录多次生成会覆盖。
- 角度是「AI 归纳」还是「原始标题兜底」尚未在 UI/报告中标记。
- 当前环境未安装 flake8/ruff，仅执行 `py_compile` 与 pytest。

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
├── script_dialog.py                    — 建议脚本展示对话框（新增）
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
├── search_thread.py                    — 检索后台线程（新增）
├── script_suggest.py                   — 建议脚本 prompt/解析/渲染（新增）
└── script_thread.py                    — 建议脚本编排线程（新增）
tests/                                  — 171 个测试（65 基线 + 106 新增；170 passed + 1 skipped）
AI视频配音Pro.spec / build.sh           — 打包
```

---

## 测试

```bash
python3 -m pytest tests/ -v    # 170 passed + 1 skipped（171 tests）
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
| **v4.4.0** | **11-02 / 11-03** | **智能视频检索 — 热点/批量/缓存/独立窗口；11-03 增加热榜关联优化、空结果诊断与建议脚本** |
| **v4.5.0** | **11-02** | **纯本地视觉内容检索（设计阶段）** |

---

## v4.5.0 规划（纯本地视觉内容检索）

> 状态：**设计阶段，代码未实现**（2026-11-02）
> 设计文档：`智能视频内容检索v4.5.0设计方案20261102.md`

- 目标：在 v4.4.0 音频语义检索基础上，新增视频画面理解：
  - 描述性查询（如「穿黄色鞋子的机器人」）
  - 胸牌号码跨视频查询（如「找到胸牌号码为 7 的机器人」）
- **纯本地执行**：不调用云端 VLM、不上传视频/帧、不做模型微调；视觉检索运行时零网络。
- 首选本地后端：**ONNX Runtime**（Chinese-CLIP、YOLO-World/OWLv2、RapidOCR）；不可用则独立 Python 3.12 sidecar；可选本地 Qwen2.5-VL-3B（MLX，M1/16GB 上限）。
- 环境与后端：Python 3.14.6 / torch 2.11.0 / onnxruntime 1.26.0；未安装 transformers/torchvision；视觉先源码 beta，是否进 `.app` 在 Phase 4 决定。
- 架构：新增 `core/visual_types.py` / `frame_sampler.py` / `visual_index.py` / `visual_models.py` / `visual_search.py` / `visual_thread.py` 与视觉检索窗口；复用 v4.4.0 片段导出、去重、进度模式；音频引擎不改。
- 下一步：Phase 0 可行性验证（ONNX/sidecar 后端可用性、胸牌 OCR 可读性、黄鞋召回、M1/16GB 测速）→ 设计评审确认 → 实施计划。
- 仍需确认：样例视频与准确率目标；同帧多机器人/胸牌可见性；是否必须进打包 `.app`。
- 主要风险：胸牌字小/模糊、CLIP 细粒度属性噪声、Python 3.14 模型栈兼容性、本地 VLM 内存、PyInstaller 冻结。
