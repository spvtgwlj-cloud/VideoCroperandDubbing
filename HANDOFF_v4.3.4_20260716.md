# HANDOFF — AI Video Dubbing Pro v4.3.4

## 项目概述

短视频 AI 配音 + 翻译 + 竖屏裁切一体化工具。v4.3.4 核心变更：LLM API 供应商配置化 + 平台「自定义」模式。

**目标用户**：短视频运营工程师 / 跨境营销 / 自媒体创作者

---

## v4.3.4 核心变更（2026-07-16）

### 1. LLM API 供应商配置化

**移除所有硬编码 API Key / 模型名**，替换为可配置的多供应商方案。

| 变更 | 涉及文件 |
|------|----------|
| 新增 `core/llm_config.py` — 5 个供应商预设 + 三层优先级加载 + 持久化 | `core/llm_config.py`（新文件） |
| 新增 `ui/api_config_dialog.py` — QDialog 配置界面，翻译 + 声音克隆可分别配置 | `ui/api_config_dialog.py`（新文件） |
| `core/config.py` 删除硬编码 `DASHSCOPE_API_KEY` / `AI_BASE_URL`，改为从 `llm_config` 导入 | `core/config.py` |
| `entry.py` 启动时检查配置，首次运行无配置时弹出对话框（默认预填旧 Key） | `entry.py` |
| `core/process_thread.py` 构造函数新增 9 个 API 参数，运行时动态解析 LLM client | `core/process_thread.py` |
| `core/audio_pipeline.py` 3 处 `model="qwen-max"` → `self.llm_model` | `core/audio_pipeline.py` |
| `ui/ui_main.py` 新增「🔑 AI 大模型设置」按钮，`start_processing()` 传入 API 配置 | `ui/ui_main.py` |

**供应商预设**：阿里云百炼 (DashScope) / DeepSeek / MiniMax / OpenAI / 自定义

**配置持久化**：`~/.ai_video_dubbing_pro/api_config.json`，优先级：环境变量 > 磁盘文件 > 默认值

**合并逻辑**：磁盘文件中空字符串不覆盖默认值（防止空 Key 把旧 Key 冲掉）

### 2. 平台「自定义」选项

| 变更 | 涉及文件 |
|------|----------|
| 平台多选栏 YouTube 右侧新增「自定义」复选框 | `ui/ui_main.py` |
| 勾选后解锁分辨率控件（横屏/竖屏均可自由调整），不强制覆盖任何预设值 | `ui/ui_main.py` |

「自定义」不来自 `PLATFORM_PRESETS`，不参与多平台批量导出，仅解锁 UI 控件。

### 3. UI 布局修复

| 问题 | 修复 |
|------|------|
| API 配置对话框太小 | 对话框 600×650，展开声音克隆独立 LLM 时自动扩至 600×750 |
| 左侧预览面板内容被右侧挤压 | `left_layout` 边距 + 间距优化，`main_layout` 增加面板间距 |
| 「字幕来源」复选框与其他行未对齐 | `sub_src_layout` 显式设置 `setContentsMargins(0,0,0,0)` |
| CheckBox 勾选框太小 | 指示器从 16×16 → 20×20 |
| 视频裁剪标签过长 | 「(0=不裁剪)」从标签移到 `trim_end` 后缀 |

### 4. Bug 修复

| 问题 | 修复 |
|------|------|
| 磁盘空值覆盖默认 API Key → 启动依旧弹对话框 | `load_llm_config()` 合并时跳过空字符串 |
| 声纹模型缓存被清 → 报 HuggingFace 错误 | 重新下载并重建 `pretrained_models/` 软链接 |

---

## 架构（v4.3.4）

```
entry.py                                — 主入口（SplashScreen + API 配置检查）
ui/
├── splash_screen.py                    — 启动画面（~110 行）
├── api_config_dialog.py                — API 配置对话框（~320 行，新增）
└── ui_main.py                          — MainWindow（~1380 行）
core/
├── config.py                           — 平台预设/字幕颜色（已移除硬编码 Key）
├── llm_config.py                       — LLM 供应商配置 + 持久化（~105 行，新增）
├── process_thread.py                   — QThread + 多平台缓存 + API 参数解析（~200 行）
├── audio_pipeline.py                   — AI 管线（~670 行）
├── video_processor.py                  — 视频处理 + 爆点 + 渲染合并（~520 行）
├── subtitle_renderer.py                — 字幕+Overlay+章节（~520 行）
└── voice_cloner.py                     — 音色克隆（~61 行）
tests/                                  — 65 个测试
AI视频配音Pro.spec / build.sh           — 打包
```

---

## 测试

```bash
python3 -m pytest tests/ -v    # 65 tests
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
| **v4.3.4** | **07-16** | **LLM API 供应商配置化 + 平台「自定义」+ UI 修复** |
