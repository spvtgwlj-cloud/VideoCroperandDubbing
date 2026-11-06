# -*- mode: python ; coding: utf-8 -*-
"""
AI Video Dubbing Pro — PyInstaller 打包配置文件
支持 macOS (.app) 和 Windows (.exe)
"""

import sys
import os
from pathlib import Path

# ---- 项目根目录 ----
ROOT = Path(SPECPATH)

# ---- 平台检测 ----
IS_MAC = sys.platform == "darwin"
IS_WIN = sys.platform == "win32"

# ---- 使用 PyInstaller 工具函数 ----
from PyInstaller.utils.hooks import collect_submodules

# ---- 需要打包的数据文件 ----
datas = [
    (str(ROOT / "core"), "core"),
    (str(ROOT / "ui"), "ui"),
]

# ---- 需要隐藏导入的模块（PyInstaller 可能检测不到） ----
hidden_imports = [
    # PyQt5
    "PyQt5", "PyQt5.QtCore", "PyQt5.QtGui", "PyQt5.QtWidgets",
    "PyQt5.sip",
    # OpenCV
    "cv2", "cv2.data",
    # PIL
    "PIL", "PIL.Image", "PIL.ImageDraw", "PIL.ImageFont",
    "PIL._imaging", "PIL._imagingft",
    # AI 模型
    "whisper", "whisper.model", "whisper.tokenizer",
    "torch", "torchaudio", "torchvision",
    "speechbrain", "speechbrain.inference",
    "speechbrain.inference.speaker",
    "speechbrain.lobes",
    "insightface", "insightface.app", "insightface.model_zoo",
    "insightface.utils",
    # 音频处理
    "pydub", "pydub.audio_segment", "pydub.silence",
    # 聚类
    "sklearn", "sklearn.cluster", "sklearn.preprocessing",
    "sklearn.metrics.pairwise",
    # API 客户端
    "dashscope", "dashscope.audio",
    "openai",
    "requests",
    "edge_tts",
    # 智能检索与建议脚本（v4.4.0）
    "core.search_types", "core.smart_search", "core.trend_sources",
    "core.trend_thread", "core.search_thread", "ui.smart_search_dialog",
    "core.script_suggest", "core.script_thread", "ui.script_dialog",
    "core.search_params",
    # 其他
    "numpy", "numpy.core", "numpy.linalg",
    "scipy",
    "matplotlib", "mpl_toolkits",
    "onnxruntime",
    "audioop_lts",
]

# ---- 需要排除的模块（减小体积） ----
excluded_imports = [
    "tkinter",
    "jupyter", "IPython", "notebook",
    "pytest",
]

# SpeechBrain 子模块 + Runtime Hook（修复打包后目录扫描）
speechbrain_hidden = collect_submodules("speechbrain")
for sm in speechbrain_hidden:
    if sm not in hidden_imports:
        hidden_imports.append(sm)

# Runtime hook 在程序启动时执行（patch speechbrain.utils.importutils）
runtime_hooks = [str(ROOT / "hook-speechbrain.py")]

# ---- FFmpeg 路径（Mac 从 Homebrew，Win 需自带） ----
if IS_MAC:
    ffmpeg_paths = [
        "/opt/homebrew/bin/ffmpeg",
        "/usr/local/bin/ffmpeg",
    ]
    ffmpeg_bin = next((p for p in ffmpeg_paths if os.path.exists(p)), None)
    if ffmpeg_bin:
        binaries = [(ffmpeg_bin, ".")]
    else:
        binaries = []
        print("⚠️ 未找到 ffmpeg，请确保系统中已安装: brew install ffmpeg")
elif IS_WIN:
    ffmpeg_bin = ROOT / "ffmpeg.exe"
    if ffmpeg_bin.exists():
        binaries = [(str(ffmpeg_bin), ".")]
    else:
        binaries = []
        print("⚠️ 未找到 ffmpeg.exe，请将 ffmpeg.exe 放到项目根目录")
else:
    binaries = []

# ---- PyInstaller Analysis ----
a = Analysis(
    [str(ROOT / "entry.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=runtime_hooks,
    excludes=excluded_imports,
    noarchive=False,
)

pyz = PYZ(a.pure)

# ---- 打包方式 ----
if IS_MAC:
    # macOS: onedir 模式（所有依赖收集到目录 → 打包为 .app）
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="AI视频配音Pro",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        console=False,
        disable_windowed_traceback=False,
        target_arch="arm64" if "arm" in os.uname().machine else "x86_64",
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=True,
        upx_exclude=[],
        name="AI视频配音Pro",
    )
    app = BUNDLE(
        coll,
        name="AI视频配音Pro.app",
        icon=str(ROOT / "icon.icns") if (ROOT / "icon.icns").exists() else None,
        bundle_identifier="com.ai.videodubbingpro",
        info_plist={
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
            "CFBundleShortVersionString": "4.3.1",
            "CFBundleName": "AI视频配音Pro",
            "NSMicrophoneUsageDescription": "需要麦克风权限以录制音频",
        },
    )
else:
    # Windows/Linux: onedir 模式（目录包含 exe + 所有依赖）
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="AI视频配音Pro",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        console=False,
        disable_windowed_traceback=False,
        target_arch=None,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=True,
        upx_exclude=[],
        name="AI视频配音Pro",
    )
