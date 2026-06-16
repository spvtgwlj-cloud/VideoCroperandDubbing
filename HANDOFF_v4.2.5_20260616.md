# HANDOFF — AI Video Dubbing Pro v4.2.5

## 项目概述

短视频 AI 配音 + 翻译 + 竖屏裁切工具。输入横屏/竖屏视频，自动识别人声、翻译、声音克隆、竖屏智能裁切，输出适配各平台的短视频。

**目标用户**：短视频运营工程师
**核心需求**：快速处理批量素材，多平台分发（抖音/快手/小红书/B站/YouTube）

---

## 当前状态：v4.2.5 ✅ UI 深色科技风重构 + 布局优化

### v4.2.5 本回合变更摘要（2026-06-16）

| 类别 | 变更 | 涉及文件 |
|------|------|----------|
| **布局重构** | 左侧三栏布局：预览缩小(stretch=2) + 波形缩至54px + 日志移至左侧放大(stretch=5)，左右比 5:6 | `ui/ui_main.py` |
| **深色科技风** | 完整暗色主题：#0A0A1A 背景 + #00BCD4/#2979FF 霓虹蓝主调 + 终端绿色日志 + 暗色输入框/按钮/滑块/滚动条 | `ui/ui_main.py` |
| **字幕间隔** | 双语字幕原文/译文从 2 字行改为 1 字行，更紧凑 | `core/subtitle_renderer.py` |
| **音唇同步** | 字幕配置行增加「音唇同步（+ms延后/-ms提前）」说明标签 + 详细 tooltip | `ui/ui_main.py` |
| **Row 7/8 优化** | 字幕配置行右侧合并为 HBoxLayout；字幕样式行左侧颜色+选项组合、右侧滑块 span 2 列 | `ui/ui_main.py` |
| **分辨率紧凑** | 宽/高 spinbox 统一 90px 等宽，HBoxLayout 紧挨排列(间距4px) | `ui/ui_main.py` |
| **SpinBox 边框修复** | 右上下按钮背景 #181840 与边框 #2A2A5A 区分，margin-right:1px，右边框可见 | `ui/ui_main.py` |
| **启动修复** | 补全 `window.show()` 和 `app.exec_()` — UI 窗口正常显示 | `entry.py` |

### v4.2.5 新功能详解

#### 1. UI 布局重构：左侧三栏

```
┌──────────────────────┬──────────────────────────────────┐
│ 🎬 视频预览          │  系统配置 (Configuration)         │
│   （stretch=2）      │   平台预设  本地视频  批量处理    │
│                      │   视频裁剪  目标语言  画面输出    │
│ 🎵 音频波形          │   分辨率  字幕配置  字幕样式     │
│   （固定 54px）      │   导出  声音克隆  Edge-TTS      │
│                      │   预览  编码/帧率                │
│ 📋 运行日志           │   进度条                         │
│   （stretch=5）      │   [开始执行] [📂] [▶]           │
│   控制台移至左侧      │   💾保存配置  📂加载配置         │
├──────────────────────┴──────────────────────────────────┤
│      深空蓝紫科技风 · 霓虹蓝 + 电光蓝主色调              │
└─────────────────────────────────────────────────────────┘
```

#### 2. 深色科技风配色

| 元素 | 颜色 | 说明 |
|------|------|------|
| 页面背景 | `#0A0A1A` | 深空蓝紫 |
| 卡片/分组 | `#14142B` | 浅紫底 |
| 主色调 | `#00BCD4` / `#2979FF` | 霓虹蓝 / 电光蓝 |
| 日志字体 | `#00E676` | 终端绿色 |
| 输入框 | `#101025` + `#2A2A5A` 边框 | 暗色聚焦蓝色边框 |
| 按钮 (正常) | `#2979FF` | 电光蓝 |
| 按钮 (停止) | `#FF3B30` | 红色 |
| 进度条 | 渐变 `#00BCD4` → `#2979FF` | 霓虹→电光 |
| 复选框/单选框 | `#2979FF` 勾选 | 蓝色勾选态 |
| 滑块 | `#00BCD4` 手柄 | 霓虹蓝 |
| 滚动条 | `#2A2A5A` 手柄 | 暗色匹配 |

#### 3. 字幕配置行优化

**Row 7 — 字幕配置：**
```
改前: [✓ 在画面上生成硬字幕]  音唇同步（+ms音频延后/-ms提前）  [ 0 ms ]
                                                   ↑ 文字太长挤到 spinbox

改后: [✓ 在画面上生成硬字幕]  音唇同步（+ms延后/-ms提前）    [0 ms]
                              ← 合并为一个 HBoxLayout 紧凑对齐 →
```

**Row 8 — 字幕样式：**
```
改前: [颜色下拉]  字号 |━━━━━●━━━━━━━| 5.5%   [背景框] [双语字幕]
                   ↑ 滑块挤占                   ↑ 复选框被挤压

改后: [颜色下拉]  [背景框]  [双语字幕]        字号 |━━━━━━●━━━━━━━━| 5.5%
       ← 左侧 3 件等距分布 →                    ← 右侧滑块 span 2 列更宽 →
```

#### 4. 输出分辨率紧凑排列

- 宽/高 spinbox 统一 90px 等宽
- HBoxLayout 携带两个框 + 锁定复选框，间距 4px
- 不再占用两列网格，自然排列在一行内

#### 5. SpinBox 右边框修复

QSpinBox 的 up/down 按钮默认背景与边框同色（#2A2A5A），覆盖了右边框。

修复方式：
- QSpinBox 从 `QLineEdit, QComboBox, QSpinBox` 联合选择器中分离
- 新增独立 QSpinBox 样式，右侧 padding 20px
- up/down 按钮背景改为 `#181840`，`margin-right: 1px`，区别于边框色

---

## 处理路径（v4.2.5）

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

## 架构（v4.2.5 多文件结构）

```
entry.py                              — 主入口（含 urllib3 警告过滤，23 行）
ui/
└── ui_main.py                        — MainWindow 主 UI（~1046 行）
core/
├── config.py                         — 全局常量/API KEY/预设模板/Edge-TTS 音色列表（~58 行）
├── process_thread.py                 — VideoProcessThread (QThread), run+stop（~152 行）
├── audio_pipeline.py                 — AudioPipelineMixin, run_ai_pipeline（~656 行）
│   ├── _compress_silence()           — 静音压缩（原始位置算 gap）
│   ├── _assign_speakers_by_overlap() — SRT→声纹映射
│   ├── _run_cosyvoice_tts()          — CosyVoice TTS（3 次重试）
│   ├── _run_edge_tts()               — Edge-TTS 合成
│   └── run_ai_pipeline()             — AI 核心管线（支持 TTS 策略排序）
├── video_processor.py                — VideoProcessorMixin, _process_single（~298 行）
├── subtitle_renderer.py              — 字幕渲染纯函数，无 Qt 依赖（~250 行）
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

### v4.2.5 修复记录

| # | 级别 | 文件 | 问题 | 修复方式 |
|---|------|------|------|---------|
| 1 | 🟢 Low | `entry.py` | 缺少 `window.show()` 和 `app.exec_()` → UI 不显示 | 补全两行启动代码 |
| 2 | 🟢 Low | `ui/ui_main.py` | SpinBox 右边框被 up/down 按钮背景覆盖 | 拆分 QSpinBox 独立样式，按钮背景色区分 + margin-right |
| 3 | 🟢 Low | `core/subtitle_renderer.py` | 双语字幕间距 2 字行偏大 | GAP_FONT_LINES: 2 → 1 |

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
| v4.2.4 | 2026-06-15 | Edge-TTS 优先输出 + 分角色音色 + Code Review 10 项修复 |
| **v4.2.5** | **2026-06-16** | **UI 深色科技风全主题重构 + 左侧三栏布局 + 双语字幕间隔 2→1 行 + 音唇同步说明 + Row 7/8 均匀化 + 分辨率等宽紧凑 + SpinBox 右边框修复** |
