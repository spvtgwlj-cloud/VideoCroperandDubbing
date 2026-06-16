"""全局配置、平台预设、字幕颜色常量"""

import os

# ==========================================
# AI 大模型配置 (阿里云通义千问) — 直接修改此处
# ==========================================
DASHSCOPE_API_KEY = "sk-bee6589163b94d20857955a69c53ef6b"
AI_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
# 环境变量可覆盖上述默认值（CI/共享机器场景）
DASHSCOPE_API_KEY = os.environ.get("DASHSCOPE_API_KEY", DASHSCOPE_API_KEY)
AI_BASE_URL = os.environ.get("DASHSCOPE_BASE_URL", AI_BASE_URL)

os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

# ==========================================
# 平台预设模板
# ==========================================
PLATFORM_PRESETS = {
    "手动配置":     {"is_vertical": None, "subtitle_pos": -1,     "codec": None,           "fps": 0,   "ow": 0, "oh": 0, "desc": "使用下方自定义设置"},
    "抖音 / 视频号": {"is_vertical": True,  "subtitle_pos": 0.25, "codec": "H.264 (MP4)",  "fps": 30,  "ow": 1080, "oh": 1920, "desc": "9:16 竖屏，字幕避让底部 UI"},
    "快手":          {"is_vertical": True,  "subtitle_pos": 0.20, "codec": "H.265 (HEVC)", "fps": 30,  "ow": 1080, "oh": 1920, "desc": "9:16 竖屏，字幕略靠下"},
    "小红书":        {"is_vertical": True,  "subtitle_pos": 0.15, "codec": "H.264 (MP4)",  "fps": 30,  "ow": 1080, "oh": 1440, "desc": "3:4 竖屏，适合图文/视频笔记"},
    "B站":          {"is_vertical": False, "subtitle_pos": 0.08, "codec": "H.265 (HEVC)", "fps": 30,  "ow": 0, "oh": 0, "desc": "横屏保留原比例"},
    "YouTube":      {"is_vertical": False, "subtitle_pos": 0.08, "codec": "H.264 (MP4)",  "fps": 30,  "ow": 0, "oh": 0, "desc": "横屏，兼容性优先"},
}

# 字幕颜色预设 (RGB 三元组)
SUBTITLE_COLORS = {
    "黄色（推荐）": (255, 235, 59),
    "白色":         (255, 255, 255),
    "青色":         (0, 255, 255),
    "红色":         (255, 80, 80),
    "绿色":         (80, 255, 80),
}

# ==========================================
# Edge-TTS 音色列表
# ==========================================
# voice_id → 显示名称
EDGE_TTS_VOICES = {
    "zh-CN-YunjianNeural": "云健 (男, 激情)",
    "zh-CN-YunxiNeural": "云希 (男, 阳光)",
    "zh-CN-YunyangNeural": "云扬 (男, 专业)",
    "zh-CN-XiaoxiaoNeural": "晓晓 (女, 温暖)",
    "zh-CN-XiaoyiNeural": "晓依 (女, 活泼)",
    "en-US-GuyNeural": "Guy (Male, Passion)",
    "en-US-ChristopherNeural": "Christopher (Male, Authority)",
    "en-US-JennyNeural": "Jenny (Female, Friendly)",
    "en-US-AriaNeural": "Aria (Female, Confident)",
    "en-US-MichelleNeural": "Michelle (Female, Pleasant)",
}

# 默认音色（按目标语言）
EDGE_TTS_DEFAULT = {
    "zh": "zh-CN-YunjianNeural",  # 中文默认男声
    "en": "en-US-GuyNeural",      # 英文默认男声
}
