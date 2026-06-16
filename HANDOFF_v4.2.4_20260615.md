# HANDOFF — AI Video Dubbing Pro v4.2.4

## 项目概述

短视频 AI 配音 + 翻译 + 竖屏裁切工具。输入横屏/竖屏视频，自动识别人声、翻译、声音克隆、竖屏智能裁切，输出适配各平台的短视频。

**目标用户**：短视频运营工程师
**核心需求**：快速处理批量素材，多平台分发（抖音/快手/小红书/B站/YouTube）

---

## 当前状态：v4.2.4 ✅ Edge-TTS 优先输出 + 分角色语音选择

### v4.2.4 本回合变更摘要（2026-06-15）

| 类别 | 变更 | 涉及文件 |
|------|------|----------|
| **新功能** | Edge-TTS 优先输出：复选框 + 分角色音色选择 | `ui/ui_main.py`, `core/audio_pipeline.py`, `core/process_thread.py`, `core/config.py` |
| **Code Review 修复** | 10 项修复：Critical×2 + High×2 + Medium×3 + Low×3 | `core/audio_pipeline.py`, `core/video_processor.py`, `core/subtitle_renderer.py`, `core/process_thread.py` |
| **UI 修复** | Edge-TTS 面板显隐联动 bug（某些操作顺序不显示） | `ui/ui_main.py` |

### v4.2.4 新功能详解

#### 1. Edge-TTS 优先输出（复选框 + 策略排序）

用户在「声音配置」模块可见一个新的复选框 **「优先使用 Edge-TTS 语音合成 (分角色选音色)」**，勾选后：

**TTS 策略排序变化：**

| 模式 | 尝试顺序 |
|------|---------|
| ✅ **Edge-TTS 优先**（新） | Edge-TTS（分角色音色）→ CosyVoice（3次重试）→ 原声兜底 |
| 🔄 **原有模式** | CosyVoice（3次重试）→ Edge-TTS → 原声兜底 |

日志会明确标注每句话使用的合成方式。

#### 2. 分角色音色选择

勾选 Edge-TTS 优先后，展开 **「Edge-TTS 音色」面板**，包含两个下拉框：

- **角色 0 语音**（默认：`zh-CN-YunjianNeural` 云健，男，激情）
- **角色 1 语音**（默认：`zh-CN-XiaoxiaoNeural` 晓晓，女，温暖）

可用音色 10 种（5 中文 + 5 英文），支持男女声线差异化配置：

| 中文音色 | 英文音色 |
|---------|---------|
| 云健 (男, 激情) | Guy (Male, Passion) |
| 云希 (男, 阳光) | Christopher (Male, Authority) |
| 云扬 (男, 专业) | Jenny (Female, Friendly) |
| 晓晓 (女, 温暖) | Aria (Female, Confident) |
| 晓依 (女, 活泼) | Michelle (Female, Pleasant) |

面板显隐联动：
- 取消「声音克隆」→ Edge-TTS 面板自动隐藏
- 恢复「声音克隆」→ 若复选框仍勾选，重新显示面板
- 配置保存/加载支持 Edge-TTS 全部设置

#### 3. Code Review 修复（10 项）

| # | 级别 | 文件 | 问题 | 修复方式 |
|---|------|------|------|---------|
| 1 | 🔴 Critical | `audio_pipeline.py` | `_compress_silence` 用已偏移 end 算 gap → 段乱序 | 改用 `segments[i-1]["end"]` 原始位置 |
| 2 | 🔴 Critical | `video_processor.py` | Path A 跳过 trim 预处理 → 裁剪被静默忽略 | 裁剪前提至 `_process_single()` 顶部，所有路径共享 |
| 3 | 🟠 High | `subtitle_renderer.py` | `##ORIG##` 原文换行致 SRT 重解析损毁 | 添加 `.replace(chr(10), ' ')` 转义 |
| 4 | 🟠 High | `audio_pipeline.py` | SRT 模式 + 空 valid_segments → 无声纹警告 | 新增警告日志 |
| 5 | 🟡 Medium | `audio_pipeline.py` | seg 零时长 → ZeroDivisionError | 添加 `target_duration_ms <= 0` 守卫 |
| 6 | 🟡 Medium | `audio_pipeline.py` | ffmpeg atempo 未捕获 → 循环崩溃 | try/except 包裹，回退原速 |
| 7 | 🟡 Medium | `video_processor.py` | 提前 return 泄露 temp_trim_path | 所有 return 点添加清理 |
| 8 | 🟢 Low | `process_thread.py` | terminate() 前未清理 ffmpeg 僵尸 | 添加 `pkill -P` 子进程清理 |
| 9 | 🟢 Low | `video_processor.py` | 不可达死代码 | 布尔代数证明后移除 |
| 10 | 🟢 Low | `video_processor.py` | 字幕查找 O(n) → O(1) | 游标摊还优化 |

---

## 处理路径（v4.2.4）

```
_process_single() 入口
  │
  ├── 裁剪预处理（trim 提至最前，所有路径共享）
  │
  ├── Path A: 外部 SRT + 保留原声（跳过 AI）
  ├── Path B: 外部 SRT + 声音克隆（LSRT 驱动 TTS，分角色音色）
  └── Path C: 标准 AI 管线
        └── [声音克隆] TTS 策略排序：
              ├── Edge-TTS 优先（分角色音色） → CosyVoice → 原声
              └── 原有模式（CosyVoice → Edge-TTS → 原声）
```

---

## 架构（v4.2.4 多文件结构）

```
entry.py                              — 主入口（含 urllib3 警告过滤）
ui/
└── ui_main.py                        — MainWindow 主 UI（~920 行）
core/
├── config.py                         — 全局常量/API KEY/预设模板/Edge-TTS 音色列表（~55 行）
├── process_thread.py                 — VideoProcessThread (QThread), run+stop（~145 行）
├── audio_pipeline.py                 — AudioPipelineMixin, run_ai_pipeline（~630 行）
│   ├── _compress_silence()           — 静音压缩（原始位置算 gap）
│   ├── _assign_speakers_by_overlap() — SRT→声纹映射
│   ├── _run_cosyvoice_tts()          — CosyVoice TTS（3 次重试，v4.2.4 提取为子方法）
│   ├── _run_edge_tts()               — Edge-TTS 合成（v4.2.4 提取为子方法）
│   └── run_ai_pipeline()             — AI 核心管线（支持 TTS 策略排序）
├── video_processor.py                — VideoProcessorMixin, _process_single（~290 行）
├── subtitle_renderer.py              — 字幕渲染纯函数（~250 行）
└── voice_cloner.py                   — CosyVoice 音色克隆（~61 行）
tests/                                — 50 个测试
├── conftest.py
├── test_subtitle_renderer.py         — 13 tests
├── test_audio_pipeline.py            — 15 tests
├── test_video_processor.py           — 8 tests
└── test_e2e_pipeline.py              — 14 tests
```

---

## 已知问题

**所有 P0 问题已修复，当前无已知阻塞性 bug。**

### v4.2.4 修复补记（2026-06-15 后续会话）

| # | 级别 | 文件 | 问题 | 修复方式 |
|---|------|------|------|---------|
| 11 | 🟢 Low | `ui/ui_main.py` | `toggle_clone_options` 勾选声音克隆时不调用 `toggle_edge_tts_options` → Edge-TTS 面板在某些操作顺序下不显示 | 将 `if not is_clone` 改为：`is_clone` 时调用 `toggle_edge_tts_options()`，否则直接隐藏 |

---

## 下一阶段建议（v5.0 方向）

- 字幕样式扩展（自定义字体、描边颜色、位置微调）
- 多语言并行翻译（一次生成中/英/日/韩）
- 云端处理（阿里云函数计算）
- 智能场景检测（画面主体自动避让）
- SRT `##SPK##` 标记（保存 speaker_id，编辑后保留多人克隆映射）

---

## 测试

```bash
python3 -m pytest tests/ -v       # 全部 50 个测试
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
| v4.2.3 | 2026-06-15 | P0 修复 + Path B(外部SRT+声音克隆) + 50 测试 |
| **v4.2.4** | **2026-06-15** | **Edge-TTS 优先输出 + 分角色音色 + Code Review 10 项修复** |
