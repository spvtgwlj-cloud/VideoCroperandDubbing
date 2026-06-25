#!/usr/bin/env python3
"""生成推广视频的旁白音频 + SRT 字幕"""
import os, subprocess, asyncio

OUT_DIR = os.path.dirname(os.path.abspath(__file__))

NARRATION = [
    (0, "每天几十条视频要做多平台多语言版本？人工配音翻译剪辑，半天过去了才出三条。这条视频看完，你的效率翻十倍。"),
    (0, "拖入视频，勾选目标平台，抖音竖屏、小红书三比四、YouTube横屏，一次处理同时输出三份不同规格的成品。双语字幕自动叠加，原声保留或AI翻译任你选。三十秒，三个平台，全部搞定。"),
    (0, "内置声音克隆，自动识别视频中不同说话人，男女角色各自独立音色。支持中英双语，翻译加配音一气呵成。Edge-TTS本地极速合成，CosyVoice云端高保真兜底，每句话都有双重保障。"),
    (0, "底部章节进度条，观众一眼看清视频结构。输入章节时间和标题，底部时间轴展示全部章节，蓝色播放头随进度移动。"),
    (0, "爆点片头自动截取你的高光时刻放到最前面。主标题和分享人水印，省去后期叠加的麻烦。这三个功能，让你的视频专业度直接拉满。"),
    (0, "批量处理整个文件夹，配置模板一键保存和复用。同一个配置，二十个视频，无人值守全部搞定。"),
    (0, "跨境卖家一条素材打通TikTok加YouTube。自媒体博主一次处理多平台同步发布。教育机构录播课自动加字幕留章节。AI视频配音Pro，让每条视频都能被世界听懂。"),
    (0, "支持macOS和Windows，核心功能免费使用。AI视频配音Pro，立即下载体验，让你的视频处理效率翻十倍。"),
]

def build_srt_from_wavs(wav_files):
    """从实际音频时长反推 SRT 时间轴"""
    srt = os.path.join(OUT_DIR, "promo_narration.srt")
    lines = []
    t = 0.0
    for i, (wav, (_, text)) in enumerate(zip(wav_files, NARRATION), 1):
        # 获取实际时长
        probe = subprocess.run(
            ["ffprobe","-i",wav,"-show_entries","format=duration","-v","quiet","-of","csv=p=0"],
            capture_output=True, text=True)
        dur = float(probe.stdout.strip())
        start, end = t, t + dur
        t = end
        def ts(x):
            h, r = divmod(int(x), 3600)
            m, s = divmod(r, 60)
            ms = int((x - int(x)) * 1000)
            return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
        lines.extend([str(i), f"{ts(start)} --> {ts(end)}", text, ""])
    with open(srt, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"SRT: {srt} ({len(NARRATION)} 条, 总长 {t:.1f}s)")

async def gen_audio():
    import edge_tts
    VOICE = "zh-CN-YunjianNeural"
    wavs = []
    for i, (_, text) in enumerate(NARRATION):
        wav = os.path.join(OUT_DIR, f"seg_{i:02d}.wav")
        if os.path.exists(wav) and os.path.getsize(wav) > 1000:
            print(f"  [{i}] skip")
        else:
            mp3 = os.path.join(OUT_DIR, f"seg_{i:02d}.mp3")
            print(f"  [{i}] {text[:40]}...")
            await edge_tts.Communicate(text, VOICE).save(mp3)
            subprocess.run(
                ["ffmpeg","-y","-i",mp3,"-ar","48000","-ac","1","-sample_fmt","s16",wav],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
            os.remove(mp3)
        wavs.append(wav)

    # concat filter 拼接
    inputs, filters = [], []
    for i, w in enumerate(wavs):
        inputs.extend(["-i", w])
        filters.append(f"[{i}:a]")
    filter_expr = f"{''.join(filters)}concat=n={len(wavs)}:v=0:a=1[out]"

    final = os.path.join(OUT_DIR, "promo_narration.wav")
    subprocess.run(
        ["ffmpeg","-y"] + inputs + ["-filter_complex", filter_expr, "-map", "[out]", final],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

    mp3 = os.path.join(OUT_DIR, "promo_narration.mp3")
    subprocess.run(["ffmpeg","-y","-i",final,"-b:a","192k",mp3],
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    probe = subprocess.run(
        ["ffprobe","-i",mp3,"-show_entries","format=duration","-v","quiet","-of","csv=p=0"],
        capture_output=True, text=True)
    print(f"Audio: {mp3} ({float(probe.stdout.strip()):.1f}s)")

    # 根据实际时长生成 SRT
    build_srt_from_wavs(wavs)

    for s in wavs:
        if os.path.exists(s): os.remove(s)

if __name__ == "__main__":
    asyncio.run(gen_audio())
