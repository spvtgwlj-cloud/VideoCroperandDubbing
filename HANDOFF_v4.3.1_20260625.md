# HANDOFF — AI Video Dubbing Pro v4.3.1

## 项目概述

短视频 AI 配音 + 翻译 + 竖屏裁切一体化工具。含字幕叠加、声音克隆、章节进度条、视频爆点片头、多平台输出。

**目标用户**：短视频运营工程师 / 跨境营销 / 自媒体创作者
**核心需求**：快速处理批量素材，多平台分发（抖音/快手/小红书/B站/YouTube）

---

## v4.3.1 全部变更（2026-06-25）

### 新功能

| 类别 | 变更 | 涉及文件 |
|------|------|----------|
| **章节进度条** | 底部时间轴展示全部章节，已播灰色遮罩+播放头竖线，首字左对齐时间标记，小竖线指示器 | `subtitle_renderer.py` |
| **章节 UI** | QGroupBox 可折叠默认关闭，动态增删行，配置保存/加载，与爆点控件垂直对齐 | `ui_main.py` |
| **多平台输出** | 同一素材一次处理输出到多个平台，平台横排 checkbox 选择，默认勾抖音/视频号，勾选自动应用预设 | `ui_main.py` `process_thread.py` |
| **平台多选 UI** | 5 平台横排展示替代原下拉，间距 3 汉字，右侧呼吸窗口 | `ui_main.py` |
| **UI 统一方形** | 画面输出/字幕来源 QRadioButton → QCheckBox + QButtonGroup 互斥，全局视觉统一 | `ui_main.py` |
| **UI 间距统一** | 画面输出/字幕来源/字幕样式间距统一 36px（3 汉字），字号滑块固定 120px 宽 | `ui_main.py` |
| **推广配音** | 2 分钟产品推广脚本 + Edge-TTS 旁白音频 + SRT 字幕 | `产品2分钟推广介绍.md` `generate_promo.py` |

### 修复

| 类别 | 变更 | 涉及文件 |
|------|------|----------|
| **横屏布局** | 章节栏高固定 base_dim×0.024，标题间隙固定 25px，字号缩小 2 号(0.048×0.78)，防止重叠 | `subtitle_renderer.py` `ui_main.py` |
| **H.265 封装** | 添加 `-movflags +faststart` 确保 B站/快手 H.265 输出可播放 | `video_processor.py` |
| **CosyVoice 上传** | 上传音频映射不依赖视频声纹检测，独立创建角色音色 | `audio_pipeline.py` |
| **CosyVoice 日志** | 增强错误日志（HTTP 状态码+API message+重试标记），TTS 阶段输出 ref_prompts 摘要 | `audio_pipeline.py` |
| **SpeechBrain** | 回退 CPU（不支持 MPS run_opts） | `audio_pipeline.py` |
| **Overlay 独立** | 主标题/分享人独立于字幕开关渲染 | `subtitle_renderer.py` |
| **主标题居中** | 从靠左改为居中 | `subtitle_renderer.py` |

### 工程质量

| 类别 | 变更 | 涉及文件 |
|------|------|----------|
| **测试** | 65 个 pytest（+6 章节进度条渲染测试） | `test_subtitle_renderer.py` |
| **打包** | PyInstaller onedir 模式 + speechbrain runtime hook，支持 Mac/Win | `AI视频配音Pro.spec` `build.sh` `hook-speechbrain.py` |
| **性能** | M1 MPS 加速 + Whisper fp16 + Overlay 逐帧缓存（字号/渐变预渲染） | `audio_pipeline.py` `subtitle_renderer.py` |
| **推广** | 2 分钟产品推广脚本 + 旁白音频生成工具 | `产品2分钟推广介绍.md` `generate_promo.py` |

---

## 关键架构决策

### 章节进度条渲染

```
底板(黑) → 全部章节文字(白,首字左对齐时间点) → 已播灰色遮罩(alpha=55) → 播放头蓝线
```

横屏字号 0.38×，竖屏 0.68×。数据流：`UI chapter_rows → _collect_chapters() → thread.chapters → subtitle_style["_chapters"]`

### 多平台处理

`run()` 重构为双层循环：文件 × 平台。每平台自动应用预设（is_vertical/codec/bitrate/output_w_h），输出到 `Output_{file}_{platform}.mp4`。

### H.265 编码

`hevc_videotoolbox`（Mac 硬编码）+ `-tag:v hvc1 -movflags +faststart` 确保播放兼容。

---

## 架构（v4.3.1）

```
entry.py                              — 主入口
ui/ui_main.py                         — MainWindow（~1300 行）
core/
├── config.py                         — 常量/API KEY/预设（~60 行）
├── process_thread.py                 — QThread + 多平台循环（~165 行）
├── audio_pipeline.py                 — AI 管线 + MPS 加速（~670 行）
├── video_processor.py                — 视频处理 + 爆点 + H.265 修复（~390 行）
├── subtitle_renderer.py              — 字幕+Overlay+章节渲染（~510 行）
└── voice_cloner.py                   — 音色克隆（~61 行）
tests/                                — 65 个测试
├── test_subtitle_renderer.py         — 27 tests（+6 章节 + 6 overlay）
├── test_audio_pipeline.py            — 15 tests
├── test_video_processor.py           — 8 tests
├── test_e2e_pipeline.py              — 14 tests
└── conftest.py
AI视频配音Pro.spec                    — PyInstaller 配置（onedir）
build.sh                              — 打包脚本
hook-speechbrain.py                   — Runtime hook
generate_promo.py                     — 旁白生成工具
```

---

## 测试

```bash
python3 -m pytest tests/ -v    # 65 tests
```

---

## 打包

```bash
bash build.sh mac     # → dist/AI视频配音Pro.app (~1.1GB)
bash build.sh win     # → dist/AI视频配音Pro/
```

---

## 版本历史

| 版本 | 日期 | 关键变更 |
|------|------|---------|
| v4.2.5 | 06-16 | UI 深色科技风 + 左侧三栏 |
| v4.2.6 | 06-23 | 双 Overlay + 音唇同步 + 视频裁剪修正 + 性能优化 |
| v4.3.0 | 06-23 | 面板互换 + 视频爆点 + 码率可配 + 主标题居中 |
| **v4.3.1** | **06-24** | **章节进度条 + 多平台输出 + UI 方形统一 + H.265 修复 + 打包 + 65 测试** |
