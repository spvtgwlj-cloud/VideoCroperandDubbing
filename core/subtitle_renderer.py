"""字幕绘制模块 — 纯函数，无 Qt 依赖"""

import os
from functools import lru_cache

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


@lru_cache(maxsize=16)
def _fit_text_to_width_cached(text, max_width_px, font_path):
    """二分查找最大字号（缓存版，使用 font.getlength 避免依赖 draw 对象）

    Returns font_size_px (int) — 不返回 font 对象以避免缓存失效。
    """
    lo, hi = 10, 120
    best = lo
    while lo <= hi:
        mid = (lo + hi) // 2
        font = ImageFont.truetype(font_path, mid)
        tw = font.getlength(text)
        if tw <= max_width_px * 0.92:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def _fit_text_to_width(text, max_width_px, font_path, draw=None):
    """二分查找最大字号（兼容旧签名，内部调用缓存版 + 创建 font 对象）"""
    size = _fit_text_to_width_cached(text, max_width_px, font_path)
    return size, ImageFont.truetype(font_path, size)


def _draw_rounded_rect_bg(draw, x1, y1, x2, y2, radius, fill):
    """绘制圆角矩形背景"""
    draw.rounded_rectangle([x1, y1, x2, y2], radius=radius, fill=fill)


@lru_cache(maxsize=8)
def _make_gradient_bg(w, h, radius, start_color, end_color):
    """生成并缓存渐变圆角背景 RGBA 图像（逐帧复用，避免重复像素运算）"""
    from PIL import Image as PILImage, ImageDraw as PILImageDraw
    mask = PILImage.new('L', (w, h), 0)
    mask_draw = PILImageDraw.Draw(mask)
    mask_draw.rounded_rectangle([0, 0, w, h], radius=radius, fill=255)
    mask_pixels = mask.load()

    grad_img = PILImage.new('RGBA', (w, h), (0, 0, 0, 0))
    grad_pixels = grad_img.load()
    for col in range(w):
        ratio = col / max(w - 1, 1)
        r = int(start_color[0] + (end_color[0] - start_color[0]) * ratio)
        g = int(start_color[1] + (end_color[1] - start_color[1]) * ratio)
        b = int(start_color[2] + (end_color[2] - start_color[2]) * ratio)
        a_grad = int(start_color[3] + (end_color[3] - start_color[3]) * ratio)
        for row in range(h):
            a = int(a_grad * mask_pixels[col, row] / 255)
            grad_pixels[col, row] = (r, g, b, a)
    return grad_img


def _draw_gradient_rounded_bg(draw, x1, y1, x2, y2, radius, start_color, end_color):
    """绘制水平渐变圆角背景（从缓存获取预渲染图像，逐帧仅 paste）"""
    w, h = x2 - x1, y2 - y1
    if w <= 0 or h <= 0:
        return
    grad_img = _make_gradient_bg(w, h, radius, start_color, end_color)
    draw._image.paste(grad_img, (x1, y1), grad_img)


def add_subtitle(frame, text, original_text="", enable_subtitle=True, subtitle_style=None):
    """在视频帧上叠加字幕（支持双语）+ Overlay 标题/分享人 + 进度条/章节

    纯函数，不依赖外部状态。
    主标题和分享人独立于字幕，无字幕时也会渲染。
    """
    chapters = subtitle_style.get("_chapters", []) if subtitle_style else []
    current_time = subtitle_style.get("_current_time", 0.0) if subtitle_style else 0.0
    total_duration = subtitle_style.get("_total_duration", 0.0) if subtitle_style else 0.0
    style = subtitle_style or {}
    color_name = style.get("color", "黄色（推荐）")
    main_color_rgb = SUBTITLE_COLORS.get(color_name, (255, 235, 59))
    font_ratio = style.get("font_size", 0.048)  # 缩小1号（0.055→0.048）
    bg_enabled = style.get("bg_enabled", False)
    portrait_margin = style.get("portrait_margin", 0.25)
    landscape_margin = style.get("landscape_margin", 0.15)
    bilingual = style.get("bilingual", False)
    secondary_below = bool(style.get("secondary_below", False))
    overlay_title = style.get("overlay_title", "")
    overlay_sharer = style.get("overlay_sharer", "")
    GAP_FONT_LINES = 1  # 字幕行间距（用于 overlay 元素定位）

    cv2_im_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    pil_im = Image.fromarray(cv2_im_rgb)
    draw = ImageDraw.Draw(pil_im)

    img_w, img_h = pil_im.width, pil_im.height
    is_landscape = img_w > img_h
    base_dim = min(img_w, img_h)

    # 横屏时缩小 2 号字体，避免底部信息过于拥挤
    if is_landscape:
        font_ratio *= 0.78

    # ========================================================
    # 先计算原文尺寸（双语模式下），待译文定位后确定原文位置
    # ========================================================
    orig_wrapped = ""
    orig_text_h = 0
    orig_font_size = 0
    orig_y = None
    _skip_original = True
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
                if char == "\n":
                    orig_lines.append(cur.strip())
                    cur = ""
                elif draw.textlength(cur + char, font=orig_font) <= max_width:
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
        if char == "\n":
            lines.append(current_line.strip())
            current_line = ""
        elif draw.textlength(current_line + char, font=font) <= max_width:
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

    gap_px = 0
    if bilingual and orig_wrapped:
        gap_px = max(4, int(font_size * GAP_FONT_LINES))
    if bilingual and orig_wrapped and secondary_below:
        # 主字幕在上一行，小号副字幕在其下方，整块仍贴底。
        y = max(10, img_h - (text_h + gap_px + orig_text_h) - bottom_margin)
    else:
        y = max(10, img_h - text_h - bottom_margin)

    shadow_color = (0, 0, 0)
    bold_width = max(1, int(font_size * 0.025))
    offset = max(2, int(font_size * 0.05))

    # ========================================================
    # 双语原文：在译文上方间隔 2 个字体行
    # ========================================================
    if bilingual and orig_wrapped:
        orig_bbox_full = draw.textbbox((0, 0), orig_wrapped, font=orig_font, align="center")
        orig_w = orig_bbox_full[2] - orig_bbox_full[0]
        orig_x = (img_w - orig_w) // 2

        if secondary_below:
            # 副字幕放在主字幕下方；整块已经按总高度上移。
            orig_y = y + text_h + gap_px
            _skip_original = (orig_y + orig_text_h > img_h - 2)
        else:
            # 原文底部 = 译文顶部 - gap
            orig_y = max(10, y - gap_px - orig_text_h)
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

    # ===== 译文背景框 + 文字（仅当字幕启用且有文本时） =====
    if enable_subtitle and text:
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

    # ========================================================
    # 视频主标题（译文下方 1 行字高，靠左对齐，黑色字体 + 黄色圆角背景）
    # ========================================================
    title_font_size = 0
    title_font = None
    overlay_left_margin = int(img_w * 0.04)  # 4% 左侧呼吸空间
    if overlay_title:
        font_path = font_path or get_chinese_font()
        title_font_size, title_font = _fit_text_to_width(
            overlay_title, img_w, font_path or "", draw
        )
        # 限制最大字号：比字幕字体大2号（+4px），避免短标题字体过大
        max_overlay_font = font_size + 4
        if title_font_size > max_overlay_font:
            title_font_size = max_overlay_font
            title_font = ImageFont.truetype(font_path, title_font_size) if font_path else ImageFont.load_default()
        title_bbox = draw.textbbox((0, 0), overlay_title, font=title_font, align="center")
        title_w = title_bbox[2] - title_bbox[0]
        title_h = title_bbox[3] - title_bbox[1]

        # 位置：译文下方，竖屏多留半字高间隙
        title_gap = 35 if is_landscape else 25 + int(font_size * 0.5)
        title_y = y + text_h + title_gap
        title_x = (img_w - title_w) // 2

        # 黄色渐变圆角背景（左→右：透明 → #FFEB3B 86% opacity）
        pad = int(title_font_size * 0.3)
        radius = int(title_font_size * 0.4)
        _draw_gradient_rounded_bg(
            draw,
            title_x - pad, title_y - pad,
            title_x + title_w + pad, title_y + title_h + pad,
            radius=radius,
            start_color=(255, 235, 59, 60),   # 左侧淡黄（保证字体可读）
            end_color=(255, 235, 59, 220),    # 右侧不透明
        )

        # 黑色文字（居中）
        draw.multiline_text(
            (title_x, title_y), overlay_title, font=title_font,
            fill=(0, 0, 0), align="center",
        )

    # ========================================================
    # 分享人（原声字幕上方 1 行字高，靠左对齐，白色字体 + 紫色渐变圆角背景）
    # ========================================================
    if overlay_sharer:
        font_path = font_path or get_chinese_font()
        sharer_label = f"@{overlay_sharer}"
        # 字体大小同主标题（若主标题为空则独立计算）
        if title_font_size > 0:
            sharer_font_size = title_font_size
            sharer_font = title_font
        else:
            sharer_font_size, sharer_font = _fit_text_to_width(
                sharer_label, img_w, font_path or "", draw
            )
            # 限制最大字号：比字幕字体大2号（+4px）
            max_overlay_font = font_size + 4
            if sharer_font_size > max_overlay_font:
                sharer_font_size = max_overlay_font
                sharer_font = ImageFont.truetype(font_path, sharer_font_size) if font_path else ImageFont.load_default()
        sharer_bbox = draw.textbbox((0, 0), sharer_label, font=sharer_font, align="left")
        sharer_w = sharer_bbox[2] - sharer_bbox[0]
        sharer_h = sharer_bbox[3] - sharer_bbox[1]

        # 位置：原文上方 1 行字高（原文不存在时相对于译文上方），靠左对齐
        gap_px = max(4, int(font_size * GAP_FONT_LINES))
        if orig_y is not None and not _skip_original:
            sharer_y = orig_y - gap_px - sharer_h
        else:
            sharer_y = y - gap_px - sharer_h
        sharer_y = max(4, sharer_y)
        sharer_x = overlay_left_margin

        # 紫色渐变圆角背景 (#9C27B0, 70% → 0% opacity)
        pad = int(sharer_font_size * 0.3)
        radius = int(sharer_font_size * 0.4)
        _draw_gradient_rounded_bg(
            draw,
            sharer_x - pad, sharer_y - pad,
            sharer_x + sharer_w + pad, sharer_y + sharer_h + pad,
            radius=radius,
            start_color=(156, 39, 176, 180),
            end_color=(156, 39, 176, 0),
        )

        # 白色文字（带黑色描边，靠左）
        draw.multiline_text(
            (sharer_x, sharer_y), sharer_label, font=sharer_font,
            fill=(255, 255, 255), align="left",
            stroke_width=max(1, int(sharer_font_size * 0.02)),
            stroke_fill=(0, 0, 0),
        )

    # ========================================================
    # ========================================================
    # 章节进度条（底部：底板 + 章节时间轴 + 已播灰色遮罩 + 播放头）
    # ========================================================
    if chapters and total_duration > 0:
        # 竖屏/横屏分别控制字号和栏高
        if is_landscape:
            ch_font_size = max(8, int(font_size * 0.42))
            bar_h = int(base_dim * 0.024)  # 横屏：更窄 ~26px
        else:
            ch_font_size = max(10, int(font_size * 0.68))
            bar_h = None  # 竖屏：自动计算
        ch_font_path = font_path or get_chinese_font()
        ch_font = ImageFont.truetype(ch_font_path, ch_font_size) if ch_font_path else font

        max_ch_h = 0
        for ch in chapters:
            bbox = draw.textbbox((0, 0), ch["title"], font=ch_font)
            max_ch_h = max(max_ch_h, bbox[3] - bbox[1])

        text_pad = int(ch_font_size * 0.3)
        if bar_h is None:
            bar_h = max_ch_h + text_pad * 2 + 8  # 竖屏：自动计算
        bar_y = max(0, img_h - bar_h)
        margin_x = int(img_w * 0.03)

        bar_area_l = margin_x
        bar_area_r = img_w - margin_x
        bar_area_w = bar_area_r - bar_area_l

        # 1. 底板 + 章节文字（右侧未播区域：黑底 + 清晰章节文字）
        draw.rectangle([0, bar_y, img_w, img_h], fill=(0, 0, 0, 170))
        text_y = bar_y + text_pad
        prev_end_x = bar_area_l
        for i, ch in enumerate(chapters):
            ratio = max(min(ch["start"] / total_duration, 1.0), 0.0)
            ch_x = bar_area_l + int(bar_area_w * ratio)
            ch_text = ch["title"]
            ch_bbox = draw.textbbox((0, 0), ch_text, font=ch_font)
            ch_w = ch_bbox[2] - ch_bbox[0]

            # 文字左对齐于章节开始时间（仅越界时修正）
            text_start = ch_x
            if text_start + ch_w > img_w - margin_x:
                text_start = img_w - margin_x - ch_w
            if text_start < margin_x:
                text_start = margin_x
            prev_end_x = text_start + ch_w

            # 章节起始位置小竖线标记
            draw.line([(ch_x, text_y + max_ch_h + 4), (ch_x, bar_y + bar_h - 4)],
                      fill=(255, 255, 255, 60), width=1)

            draw.multiline_text(
                (text_start, text_y), ch_text, font=ch_font,
                fill=(200, 200, 210), align="left",
            )

        # 2. 已播放遮罩：RGBA 图层确保透明度正确合成
        progress = min(max(current_time / total_duration, 0.0), 1.0)
        played_x = bar_area_l + int(bar_area_w * progress)
        if played_x > bar_area_l:
            overlay_w = played_x
            overlay_h = bar_h
            overlay = Image.new('RGBA', (overlay_w, overlay_h), (0, 0, 0, 0))
            overlay_draw = ImageDraw.Draw(overlay)
            # 亮灰遮罩，与黑底形成清晰对比
            overlay_draw.rectangle([0, 0, overlay_w, overlay_h], fill=(90, 95, 110, 140))
            pil_im.paste(overlay, (0, bar_y), overlay)

        # 3. 播放头竖线
        draw = ImageDraw.Draw(pil_im)
        draw.line([(played_x, bar_y), (played_x, img_h)], fill=(0, 188, 212), width=3)
    elif total_duration > 0:
        # 无章节时：仅底部细条进度条
        progress = min(max(current_time / total_duration, 0.0), 1.0)
        bar_h = 4
        bar_y = img_h - bar_h
        played_w = int(img_w * progress)
        draw.rectangle([0, bar_y, played_w, img_h], fill=(0, 188, 212, 220))
        if played_w < img_w:
            draw.rectangle([played_w, bar_y, img_w, img_h], fill=(0, 0, 0, 100))

    return cv2.cvtColor(np.array(pil_im), cv2.COLOR_RGB2BGR)
