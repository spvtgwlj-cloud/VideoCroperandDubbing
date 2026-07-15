# HANDOFF — AI Video Dubbing Pro v4.3.3

## 项目概述

短视频 AI 配音 + 翻译 + 竖屏裁切一体化工具。v4.3.3 新增：启动画面（Splash Screen）。

**目标用户**：短视频运营工程师 / 跨境营销 / 自媒体创作者

---

## v4.3.3 核心变更（2026-06-29）

### 启动画面（Splash Screen）

| 变更 | 涉及文件 |
|------|----------|
| 新增 `SplashScreen` 类（继承 `QSplashScreen`），纯 QPainter 代码绘制 420×240 品牌画面 | `ui/splash_screen.py`（新文件） |
| `entry.py` 启动流程加入 splash 显示 → MainWindow 构造 → finish 过渡 | `entry.py` |

**画面组成**：
- 深蓝色渐变背景（`#1a1a2e` → `#16213e`），16px 圆角
- 🎬 图标（紫色圆形底 + emoji 字体）
- 应用名「AI 视频配音 Pro」+ 版本号
- 底部彩色横条（蓝 → 橙 → 青渐变）
- 状态文字「正在启动…」，支持 `set_status()` 动态更新

**设计特点**：零外部资源依赖，所有视觉元素由 `QPainter` 实时绘制。`splash.finish(window)` 实现启动画面到主窗口的自然过渡。

---

## 架构（v4.3.3）

```
entry.py                                — 主入口（含 SplashScreen 启动流程）
ui/splash_screen.py                     — 启动画面（~110 行）
ui/ui_main.py                           — MainWindow（~1300 行）
core/
├── config.py                           — 常量/API KEY/预设
├── process_thread.py                   — QThread + 多平台缓存（~175 行）
├── audio_pipeline.py                   — AI 管线（~670 行）
├── video_processor.py                  — 视频处理 + 爆点 + _render_and_merge（~520 行）
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
| **v4.3.3** | **06-29** | **启动画面（Splash Screen）— 纯代码绘制，零资源依赖** |
