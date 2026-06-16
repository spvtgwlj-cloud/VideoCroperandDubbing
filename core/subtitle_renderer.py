"""字幕绘制模块 — 纯函数，无 Qt 依赖"""

import os
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .config import SUBTITLE_COLORS


def _srt_time_str(seconds: float) -> str:
    """将秒数转换为 SRT 时间格式: HH:MM:SS,mmm"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def subtitles_to_srt(subtitles: list[dict]) -> str:
    """将字幕时间线列表导出为 SRT 格式字符串

    双语模式下，在译文行后附加原文行（以 ##ORIG## 标记），导入时可恢复。
    """
    lines = []
    for idx, sub in enumerate(subtitles, 1):
        start = _srt_time_str(sub["start"])
        end = _srt_time_str(sub["end"])
        text = sub.get("text", "").strip()
        orig = sub.get("original_text", "").strip()
        lines.append(str(idx))
        lines.append(f"{start} --> {end}")
        lines.append(text)
        # 双语原文以 ##ORIG## 前缀标记（与其他 SRT 工具兼容）
        if orig and orig != text:
            lines.append(f"##ORIG## {orig.replace(chr(10), ' ').replace(chr(13), ' ')}")
        lines.append("")
    return "\n".join(lines)


def parse_srt(srt_path: str) -> list[dict]:
    """解析 SRT 文件为字幕时间线列表

    返回格式: [{"start": float, "end": float, "text": str, "original_text": "", "speaker_id": 0}, ...]
    """
    import re as _re

    subtitles = []
    _SRT_PATTERN = _re.compile(
        r"(\d+)\s*\n"                          # 序号
        r"(\d{2}:\d{2}:\d{2}[.,]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[.,]\d{3})\s*\n"  # 时间
        r"((?:(?!\n\n).)*)",                    # 字幕文本（不跨空行，含 ##ORIG## 行）
        _re.DOTALL,
    )

    def _to_sec(t: str) -> float:
        t = t.replace(",", ".")
        parts = t.split(":")
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])

    def _parse_text_block(block: str) -> tuple[str, str]:
        """解析文本块，返回 (main_text, original_text)"""
        block = block.strip().replace("\r", "")
        lines = block.split("\n")
        main_lines = []
        orig_text = ""
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("##ORIG##"):
                orig_text = stripped[len("##ORIG##"):].strip()
            else:
                main_lines.append(stripped)
        return " ".join(main_lines), orig_text

    with open(srt_path, "r", encoding="utf-8") as f:
        content = f.read()

    for match in _SRT_PATTERN.finditer(content):
        start_str = match.group(2).replace(",", ".")
        end_str = match.group(3).replace(",", ".")
        main_text, orig_text = _parse_text_block(match.group(4))
        subtitles.append({
            "start": _to_sec(start_str),
            "end": _to_sec(end_str),
            "text": main_text,
            "original_text": orig_text,
            "speaker_id": 0,
        })

    return subtitles


def get_chinese_font() -> str | None:
    """获取系统可用的中文字体路径"""
    font_paths = ["/System/Library/Fonts/PingFang.ttc", "/System/Library/Fonts/STHeiti Light.ttc"]
    for path in font_paths:
        if os.path.exists(path):
            return path
    return None


def add_subtitle(frame, text, original_text="", enable_subtitle=True, subtitle_style=None):
    """在视频帧上叠加字幕（支持双语）

    纯函数，不依赖外部状态。
    返回加了字幕的 BGR 格式帧。
    """
    if not enable_subtitle or not text:
        return frame

    style = subtitle_style or {}
    color_name = style.get("color", "黄色（推荐）")
    main_color_rgb = SUBTITLE_COLORS.get(color_name, (255, 235, 59))
    font_ratio = style.get("font_size", 0.055)
    bg_enabled = style.get("bg_enabled", False)
    portrait_margin = style.get("portrait_margin", 0.25)
    landscape_margin = style.get("landscape_margin", 0.15)
    bilingual = style.get("bilingual", False)

    cv2_im_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    pil_im = Image.fromarray(cv2_im_rgb)
    draw = ImageDraw.Draw(pil_im)

    img_w, img_h = pil_im.width, pil_im.height
    is_landscape = img_w > img_h
    base_dim = min(img_w, img_h)

    # ========================================================
    # 先计算原文尺寸（双语模式下），待译文定位后确定原文位置
    # ========================================================
    orig_wrapped = ""
    orig_text_h = 0
    orig_font_size = 0
    if bilingual:
        # original_text 为空时回退到 text（兼容外部导入 SRT 无原文标记的场景）
        _orig_display = original_text if original_text else ""
        if _orig_display:
            orig_font_ratio = 0.035
            orig_font_size = int(base_dim * orig_font_ratio)
            font_path = get_chinese_font()
            orig_font = ImageFont.truetype(font_path, orig_font_size) if font_path else ImageFont.load_default()

            # 原文自动换行
            max_width = int(img_w * 0.85)
            orig_lines = []
            cur = ""
            for char in _orig_display:
                if draw.textlength(cur + char, font=orig_font) <= max_width:
                    cur += char
                else:
                    last_space = cur.rfind(' ')
                    if last_space != -1 and (len(cur) - last_space) < 15:
                        orig_lines.append(cur[:last_space].strip())
                        cur = cur[last_space + 1:] + char
                    else:
                        orig_lines.append(cur)
                        cur = char
            if cur:
                orig_lines.append(cur.strip())
            orig_wrapped = "\n".join(orig_lines)

            orig_bbox = draw.textbbox((0, 0), orig_wrapped, font=orig_font, align="center")
            orig_text_h = orig_bbox[3] - orig_bbox[1]

    # ========================================================
    # 译文（底部，正常比例）
    # ========================================================
    font_size = int(base_dim * font_ratio)
    font_path = get_chinese_font()
    font = ImageFont.truetype(font_path, font_size) if font_path else ImageFont.load_default()

    # 自动换行
    max_width = int(img_w * 0.9)
    lines = []
    current_line = ""
    for char in text:
        if draw.textlength(current_line + char, font=font) <= max_width:
            current_line += char
        else:
            last_space = current_line.rfind(' ')
            if last_space != -1 and (len(current_line) - last_space) < 15:
                lines.append(current_line[:last_space].strip())
                current_line = current_line[last_space + 1:] + char
            else:
                lines.append(current_line)
                current_line = char
    if current_line:
        lines.append(current_line.strip())
    wrapped_text = "\n".join(lines)

    text_bbox = draw.textbbox((0, 0), wrapped_text, font=font, align="center")
    text_w = text_bbox[2] - text_bbox[0]
    text_h = text_bbox[3] - text_bbox[1]
    x = (img_w - text_w) // 2

    if is_landscape:
        bottom_margin = int(img_h * landscape_margin)
    else:
        bottom_margin = int(img_h * portrait_margin)
    y = max(10, img_h - text_h - bottom_margin)

    shadow_color = (0, 0, 0)
    bold_width = max(1, int(font_size * 0.025))
    offset = max(2, int(font_size * 0.05))

    # ========================================================
    # 双语原文：在译文上方间隔 2 个字体行
    # ========================================================
    if bilingual and orig_wrapped:
        GAP_FONT_LINES = 1                     # 间隔行数（v4.2.5 从 2 改为 1）
        gap_px = max(4, int(font_size * GAP_FONT_LINES))  # 按译文字号计算间距

        orig_bbox_full = draw.textbbox((0, 0), orig_wrapped, font=orig_font, align="center")
        orig_w = orig_bbox_full[2] - orig_bbox_full[0]
        # 原文底部 = 译文顶部 - gap
        orig_y = max(10, y - gap_px - orig_text_h)
        orig_x = (img_w - orig_w) // 2

        # ===== 防重叠：原文与译文间距不足时跳过原文渲染 =====
        MINIMUM_GAP_PX = max(4, int(font_size * 0.3))
        _skip_original = (orig_y + orig_text_h + MINIMUM_GAP_PX > y)

        gray_color = (180, 180, 180)
        orig_bold = max(1, int(orig_font_size * 0.02))
        orig_offset = max(2, int(orig_font_size * 0.04))

        if not _skip_original and bg_enabled:
            padding = int(orig_font_size * 0.25)
            draw.rectangle([orig_x - padding, orig_y - padding,
                            orig_x + orig_w + padding, orig_y + orig_text_h + padding],
                           fill=(0, 0, 0, 100))

        if not _skip_original:
            draw.multiline_text((orig_x, orig_y), orig_wrapped, font=orig_font, fill=gray_color,
                                stroke_width=orig_bold, stroke_fill=(0, 0, 0), align="center")

    # ===== 译文背景框 + 文字（始终在底部） =====
    if bg_enabled:
        padding = int(font_size * 0.3)
        bg_box = [x - padding, y - padding, x + text_w + padding, y + text_h + padding]
        draw.rectangle(bg_box, fill=(0, 0, 0, 140))

    draw.multiline_text((x + offset, y + offset), wrapped_text, font=font, fill=shadow_color,
                        stroke_width=bold_width, stroke_fill=shadow_color, align="center")
    draw.multiline_text((x - offset, y - offset), wrapped_text, font=font, fill=shadow_color,
                        stroke_width=bold_width, stroke_fill=shadow_color, align="center")
    draw.multiline_text((x, y), wrapped_text, font=font, fill=main_color_rgb, stroke_width=bold_width,
                        stroke_fill=main_color_rgb, align="center")

    return cv2.cvtColor(np.array(pil_im), cv2.COLOR_RGB2BGR)
