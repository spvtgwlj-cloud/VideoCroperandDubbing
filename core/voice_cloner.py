"""声音克隆模块 — CosyVoice 音色克隆（阿里云）

提供三层回退：CosyVoice → Edge-TTS → 原声（在 audio_pipeline 中处理）
"""

import os
import requests
import dashscope
from dashscope import Files as DashScopeFiles


def create_cloned_voice(audio_path, prompt_text, spk_id, api_key, cosy_model, log_fn):
    """通过阿里云 CosyVoice 创建克隆音色

    Args:
        audio_path: 参考音频文件路径
        prompt_text: 参考音频对应的文本
        spk_id: 说话人 ID（用于标识）
        api_key: DASHSCOPE_API_KEY
        cosy_model: 模型名称（如 cosyvoice-v2）
        log_fn: 日志回调函数

    Returns:
        voice_id: 创建的语音 ID

    Raises:
        Exception: 创建失败时抛出
    """
    dashscope.api_key = api_key
    CLONE_URL = "https://dashscope.aliyuncs.com/api/v1/services/audio/tts/customization"
    log_fn(f"🎵 正在上传角色 {spk_id} 的参考音频...")
    try:
        upload_resp = DashScopeFiles.upload(file_path=audio_path, purpose="voice_clone")
        if upload_resp.status_code != 200:
            raise Exception(f"上传失败: {upload_resp.message}")
        file_id = upload_resp.output["uploaded_files"][0]["file_id"]
        file_info = DashScopeFiles.get(file_id)
        audio_url = file_info.output["url"]
    except Exception as e:
        raise Exception(f"音频上传阶段出错: {e}")

    payload = {
        "model": "voice-enrollment",
        "input": {
            "action": "create_voice",
            "target_model": cosy_model,
            "url": audio_url,
            "prefix": f"spk{spk_id}",
        },
        "parameters": {"response_format": "wav"},
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    log_fn(f"🎵 正在为角色 {spk_id} 创建克隆音色...")
    resp = requests.post(CLONE_URL, json=payload, headers=headers, timeout=30)
    if resp.status_code != 200:
        raise Exception(f"声音复刻失败: {resp.status_code} {resp.text}")
    voice_id = resp.json().get("output", {}).get("voice_id")
    if not voice_id:
        raise Exception("未获取到音色ID")
    log_fn(f"✅ 音色创建成功，Voice ID: {voice_id}")
    return voice_id
