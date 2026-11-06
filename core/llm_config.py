"""LLM 供应商预设、API 配置加载/保存、运行时访问

提供统一的 API 配置管理：
- 5 个预设供应商（阿里云百炼、DeepSeek、MiniMax、OpenAI、自定义）
- 三层优先级加载：环境变量 > 磁盘文件 > 默认值
- 自动持久化到 ~/.ai_video_dubbing_pro/api_config.json
"""

import os
import json
import copy

# ==========================================
# 供应商预设（供应商名 → 兼容 OpenAI 的 base_url）
# ==========================================
LLM_PROVIDERS = {
    #"阿里云百炼 (DashScope)": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "阿里云百炼 (DashScope)": "https://ws-dq7z8cztmjviuvje.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
    "DeepSeek": "https://api.deepseek.com/v1",
    "MiniMax": "https://api.minimax.chat/v1",
    "OpenAI": "https://api.openai.com/v1",
    "自定义 (Custom)": "",
}

# ==========================================
# 默认模型名
# ==========================================
#DEFAULT_TRANSLATION_MODEL = "qwen-max"
DEFAULT_TRANSLATION_MODEL = "qwen3.8-max-0902"
#DEFAULT_COSY_MODEL = "cosyvoice-v2"
DEFAULT_COSY_MODEL = "cosyvoice-v1"

# 默认 API Key 留空：真实密钥只允许来自
# 环境变量 DASHSCOPE_API_KEY 或 ~/.ai_video_dubbing_pro/api_config.json。
# 严禁把真实密钥写回源码，避免随 git 历史泄露。
_LEGACY_API_KEY = ""

# ==========================================
# 持久化路径
# ==========================================
CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".ai_video_dubbing_pro")
CONFIG_FILE = os.path.join(CONFIG_DIR, "api_config.json")

# ==========================================
# 默认配置骨架
# ==========================================
_DEFAULT_CONFIG = {
    "translation": {
        "provider": "阿里云百炼 (DashScope)",
        "api_key": _LEGACY_API_KEY,
        "base_url": LLM_PROVIDERS["阿里云百炼 (DashScope)"],
        "model": DEFAULT_TRANSLATION_MODEL,
    },
    "voice_clone": {
        "use_separate_llm": False,
        "provider": "阿里云百炼 (DashScope)",
        "api_key": "",
        "base_url": LLM_PROVIDERS["阿里云百炼 (DashScope)"],
        "model": DEFAULT_TRANSLATION_MODEL,
        "tts_api_key": _LEGACY_API_KEY,
        "cosy_model": DEFAULT_COSY_MODEL,
    },
}


def load_llm_config():
    """加载 LLM 配置（合并磁盘文件 + 环境变量覆盖）。

    优先级：环境变量 > 磁盘文件 > 默认值
    返回深拷贝，调用方可安全修改。
    """
    config = copy.deepcopy(_DEFAULT_CONFIG)

    # Layer 1: 磁盘文件（仅合并非空值，防止空 Key 覆盖默认值）
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            for section in ["translation", "voice_clone"]:
                if section in saved and isinstance(saved[section], dict):
                    for k, v in saved[section].items():
                        if v:  # 跳过空字符串，保留默认值
                            config[section][k] = v
    except Exception:
        pass

    # Layer 2: 环境变量覆盖（最高优先级，兼容旧版 CI/共享机器场景）
    env_key = os.environ.get("DASHSCOPE_API_KEY", "")
    if env_key:
        config["translation"]["api_key"] = env_key
        config["voice_clone"]["tts_api_key"] = env_key
    env_url = os.environ.get("DASHSCOPE_BASE_URL", "")
    if env_url:
        config["translation"]["base_url"] = env_url

    return config


def save_llm_config(config):
    """将 LLM 配置持久化到磁盘。"""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def get_translation_config(config=None):
    """提取翻译 LLM 的有效配置。"""
    if config is None:
        config = load_llm_config()
    return config["translation"]


def get_voice_clone_config(config=None):
    """提取声音克隆相关的有效配置。"""
    if config is None:
        config = load_llm_config()
    return config["voice_clone"]
