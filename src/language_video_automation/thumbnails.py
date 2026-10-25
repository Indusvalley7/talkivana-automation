from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ThumbnailError(RuntimeError):
    pass


DESIGN_VERSION = "talkivana-thumbnail-v1"
MAX_HEADLINE_WORDS = 6

PALETTES = (
    ("teal-gold", "#073B4C", "#0B6E69", "#FFD166", "#FFFFFF"),
    ("berry-gold", "#32103D", "#982F62", "#FFD166", "#FFFFFF"),
    ("cobalt-coral", "#102A56", "#2367C9", "#FF7A66", "#FFFFFF"),
    ("forest-amber", "#123D35", "#2A7A5D", "#FFC857", "#FFFFFF"),
    ("violet-lemon", "#30145C", "#7353BA", "#FFE45E", "#FFFFFF"),
    ("navy-orange", "#0B2447", "#1D4E89", "#FF9F1C", "#FFFFFF"),
)

TOPIC_RULES = (
    (("doctor", "appointment", "arzt", "termin"), "BOOK A DOCTOR", "APPOINTMENT WORDS", "calendar"),
    (("weather", "clothing", "wetter"), "TALK ABOUT WEATHER", "WEATHER WORDS", "weather"),
    (("direction", "way", "weg"), "ASK FOR DIRECTIONS", "DIRECTION WORDS", "map"),
    (("transport", "train", "bus", "station", "ticket"), "TRAVEL IN GERMAN", "TRAVEL WORDS", "train"),
    (("café", "cafe", "coffee", "kaffee"), "ORDER AT A CAFÉ", "CAFÉ WORDS", "cup"),
    (("restaurant", "food", "essen"), "ORDER FOOD", "RESTAURANT WORDS", "plate"),
    (("grocery", "shopping", "shop", "supermarket"), "SHOP IN GERMAN", "SHOPPING WORDS", "bag"),
    (("neighbour", "neighbor", "community"), "MEET YOUR NEIGHBOUR", "NEIGHBOUR WORDS", "home"),
    (("introduction", "greeting", "meet"), "MEET IN GERMAN", "GREETING WORDS", "chat"),
    (("workplace", "office", "work"), "GERMAN AT WORK", "WORKPLACE WORDS", "briefcase"),
    (("school", "study", "class"), "GERMAN FOR CLASS", "STUDY WORDS", "book"),
    (("routine", "home", "daily"), "EVERYDAY GERMAN", "DAILY WORDS", "home"),
)


@dataclass(frozen=True)
class ThumbnailPlan:
    headline: str
    focal_text: str
    palette_name: str
    background_top: str
    background_bottom: str
    accent: str
    foreground: str
    visual_key: str
    kind: str


def load_design_skill(*, root: Path) -> str:
    path = root / "skills" / "youtube-thumbnail-design" / "SKILL.md"
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ThumbnailError(f"Required thumbnail skill is missing: {path}") from exc
    required_markers = (
        "name: youtube-thumbnail-design",
        "1280 × 720",
        "1080 × 1920",
        "six words",
        "below 2 MB",
    )
    missing = [marker for marker in required_markers if marker not in text]
    if missing:
        raise ThumbnailError("Thumbnail skill profile is incomplete: " + ", ".join(missing))
    return text


def build_thumbnail_plan(
    *, asset: dict[str, Any], kind: str, pack_id: str
) -> ThumbnailPlan:
    if kind not in {"short", "long"}:
        raise ThumbnailError(f"Unsupported thumbnail kind: {kind}")
    title = str(asset.get("title", "")).strip()
    context = " ".join(
        str(asset.get(key, "")) for key in ("title", "topic", "scenario", "description")
    ).casefold()
    long_copy = "REAL GERMAN TALK"
    short_copy = "3 GERMAN WORDS"
    visual_key = "chat"
    matched = False
    for needles, candidate_long, candidate_short, candidate_visual in TOPIC_RULES:
        if any(needle in context for needle in needles):
            long_copy = candidate_long
            short_copy = candidate_short
            visual_key = candidate_visual
            matched = True
            break
    headline = short_copy if kind == "short" else long_copy
    if not matched:
        headline = _fallback_headline(title, kind=kind)

    vocabulary = asset.get("vocabulary") if kind == "short" else asset.get("focus_vocabulary")
    focal_text = "DEUTSCH"
    if isinstance(vocabulary, list) and vocabulary:
        focal_text = str(vocabulary[0].get("german", "DEUTSCH")).strip() or "DEUTSCH"

    pack_digest = hashlib.sha256(pack_id.encode("utf-8")).digest()
    asset_positions = {"short-1": 0, "short-2": 1, "long-1": 2, "long-2": 3}
    asset_position = asset_positions.get(str(asset.get("asset_id", "")), 0)
    palette = PALETTES[(pack_digest[0] + asset_position) % len(PALETTES)]
    if len(headline.split()) > MAX_HEADLINE_WORDS:
        raise ThumbnailError(f"Thumbnail headline exceeds {MAX_HEADLINE_WORDS} words: {headline}")
    return ThumbnailPlan(
        headline=headline,
        focal_text=focal_text,
        palette_name=palette[0],
        background_top=palette[1],
        background_bottom=palette[2],
        accent=palette[3],
        foreground=palette[4],
        visual_key=visual_key,
        kind=kind,
    )


def render_youtube_thumbnail(
    *,
    asset: dict[str, Any],
    kind: str,
    pack_id: str,
    output_path: Path,
    root: Path,
    max_file_size_bytes: int = 2 * 1024 * 1024,
) -> ThumbnailPlan:
    load_design_skill(root=root)
    plan = build_thumbnail_plan(asset=asset, kind=kind, pack_id=pack_id)
    from PIL import Image, ImageDraw

    width, height = (1280, 720) if kind == "long" else (1080, 1920)
    top = _hex(plan.background_top)
    bottom = _hex(plan.background_bottom)
    accent = _hex(plan.accent)
    foreground = _hex(plan.foreground)
    image = Image.new("RGB", (width, height), top)
    draw = ImageDraw.Draw(image)
    for y in range(height):
        ratio = y / max(1, height - 1)
        colour = tuple(int(top[i] * (1 - ratio) + bottom[i] * ratio) for i in range(3))
        draw.line((0, y, width, y), fill=colour)

    # Large geometric layers make the image energetic without adding visual clutter.
    draw.ellipse((-int(width * 0.20), -int(height * 0.30), int(width * 0.48), int(height * 0.55)), fill=_mix(top, accent, 0.16))
    draw.ellipse((int(width * 0.72), int(height * 0.62), int(width * 1.18), int(height * 1.12)), fill=_mix(bottom, accent, 0.22))
    draw.polygon(
        ((int(width * 0.50), 0), (width, 0), (width, int(height * 0.52)), (int(width * 0.68), int(height * 0.68))),
        fill=_mix(bottom, foreground, 0.08),
    )

    margin = int(width * 0.055)
    brand_font = _font(max(38, int(height * (0.045 if kind == "long" else 0.025))), bold=True)
    badge_font = _font(max(30, int(height * (0.035 if kind == "long" else 0.021))), bold=True)
    _draw_brand(draw, margin, int(height * 0.065), brand_font, accent)
    badge = "A1 GERMAN"
    badge_box = draw.textbbox((0, 0), badge, font=badge_font)
    badge_w = badge_box[2] - badge_box[0]
    badge_h = badge_box[3] - badge_box[1]
    badge_x = width - margin - badge_w - int(width * 0.035)
    badge_y = int(height * 0.055)
    draw.rounded_rectangle(
        (badge_x - int(width * 0.018), badge_y - int(height * 0.012),
         width - margin, badge_y + badge_h + int(height * 0.018)),
        radius=max(18, int(height * 0.025)), fill=accent,
    )
    draw.text((badge_x, badge_y), badge, font=badge_font, fill=_hex("#17233C"))

    if kind == "long":
        _render_long_layout(draw, plan, width=width, height=height, accent=accent, foreground=foreground)
    else:
        _render_short_layout(draw, plan, width=width, height=height, accent=accent, foreground=foreground)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    quality = 90
    while quality >= 68:
        image.save(output_path, format="JPEG", quality=quality, optimize=True, progressive=True)
        if output_path.stat().st_size <= max_file_size_bytes:
            break
        quality -= 6
    if output_path.stat().st_size > max_file_size_bytes:
        raise ThumbnailError(f"Thumbnail exceeds {max_file_size_bytes} bytes: {output_path}")
    with Image.open(output_path) as verified:
        if verified.size != (width, height) or verified.format != "JPEG":
            raise ThumbnailError(f"Thumbnail technical QA failed: {output_path}")
        verified.resize((120, max(1, round(120 * height / width))))
    return plan


def _fallback_headline(title: str, *, kind: str) -> str:
    words = re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ0-9]+", title.upper())
    stop = {"A", "AN", "THE", "YOUR", "FIRST", "IN", "AT", "OF", "AND", "WITH", "GERMAN"}
    useful = [word for word in words if word not in stop]
    if kind == "short":
        useful = ["3", *(useful[:3] or ["GERMAN", "WORDS"])]
    else:
        useful = useful[:4] or ["REAL", "GERMAN", "TALK"]
    return " ".join(useful[:MAX_HEADLINE_WORDS])


def _render_long_layout(draw, plan: ThumbnailPlan, *, width: int, height: int, accent, foreground) -> None:
    icon_center = (int(width * 0.25), int(height * 0.52))
    radius = int(height * 0.23)
    shadow = _hex("#081B24")
    draw.ellipse((icon_center[0] - radius + 14, icon_center[1] - radius + 18,
                  icon_center[0] + radius + 14, icon_center[1] + radius + 18), fill=shadow)
    draw.ellipse((icon_center[0] - radius, icon_center[1] - radius,
                  icon_center[0] + radius, icon_center[1] + radius), fill=_mix(accent, foreground, 0.12), outline=accent, width=8)
    _draw_topic_icon(draw, plan.visual_key, center=icon_center, size=int(radius * 1.18), colour=_hex("#17233C"), accent=accent)

    x = int(width * 0.47)
    kicker = "REAL CONVERSATIONS"
    kicker_font = _font(33, bold=True)
    kicker_width = draw.textbbox((0, 0), kicker, font=kicker_font)[2]
    kicker_top = int(height * 0.245)
    draw.rounded_rectangle(
        (x, kicker_top, x + kicker_width + 48, kicker_top + 64),
        radius=22,
        fill=accent,
    )
    draw.text((x + 24, kicker_top + 11), kicker, font=kicker_font, fill=_hex("#17233C"))

    headline_font, lines = _fit_text(
        draw, plan.headline, max_width=int(width * 0.47), max_lines=3,
        start=108, minimum=68, bold=True,
    )
    y = int(height * 0.36)
    _draw_left_lines(draw, lines, headline_font, x=x, y=y, fill=foreground, spacing=5, stroke_width=7, stroke_fill=_hex("#10212A"))


def _render_short_layout(draw, plan: ThumbnailPlan, *, width: int, height: int, accent, foreground) -> None:
    card_left = int(width * 0.10)
    card_right = int(width * 0.90)
    card_top = int(height * 0.25)
    card_bottom = int(height * 0.55)
    shadow = _hex("#081B24")
    draw.rounded_rectangle((card_left + 18, card_top + 24, card_right + 18, card_bottom + 24), radius=56, fill=shadow)
    draw.rounded_rectangle((card_left, card_top, card_right, card_bottom), radius=56, fill=foreground, outline=accent, width=12)
    focal_font, focal_lines = _fit_text(
        draw, plan.focal_text, max_width=card_right - card_left - 90, max_lines=2,
        start=180, minimum=86, bold=True,
    )
    _draw_centered_lines(draw, focal_lines, focal_font, center_x=width // 2, center_y=(card_top + card_bottom) // 2, fill=_hex("#17233C"), spacing=12, stroke_width=0, stroke_fill=None)

    headline_font, lines = _fit_text(
        draw, plan.headline, max_width=int(width * 0.84), max_lines=3,
        start=150, minimum=82, bold=True,
    )
    _draw_centered_lines(draw, lines, headline_font, center_x=width // 2, center_y=int(height * 0.72), fill=foreground, spacing=12, stroke_width=8, stroke_fill=_hex("#10212A"))
    cue_font = _font(54, bold=True)
    cue = "LISTEN • REPEAT • REMEMBER"
    cue_width = draw.textbbox((0, 0), cue, font=cue_font)[2]
    draw.text((width // 2 - cue_width // 2, int(height * 0.88)), cue, font=cue_font, fill=accent)


def _draw_brand(draw, x: int, y: int, font, accent) -> None:
    bubble = max(34, int(getattr(font, "size", 42) * 0.85))
    draw.ellipse((x, y, x + bubble, y + bubble), fill=accent)
    draw.ellipse((x + int(bubble * 0.42), y + int(bubble * 0.12), x + int(bubble * 1.15), y + int(bubble * 0.85)), outline=accent, width=max(3, bubble // 10))
    draw.text((x + int(bubble * 1.45), y - 4), "TALKIVANA", font=font, fill=accent)


def _draw_topic_icon(draw, key: str, *, center: tuple[int, int], size: int, colour, accent) -> None:
    x, y = center
    half = size // 2
    line = max(8, size // 18)
    if key == "calendar":
        draw.rounded_rectangle((x - half, y - half * 3 // 4, x + half, y + half * 3 // 4), radius=line * 2, outline=colour, width=line)
        draw.line((x - half, y - half // 3, x + half, y - half // 3), fill=colour, width=line)
        draw.ellipse((x - line * 2, y - line * 2, x + line * 2, y + line * 2), fill=accent)
    elif key == "weather":
        draw.ellipse((x - half // 2, y - half // 2, x + half // 2, y + half // 2), fill=accent, outline=colour, width=line)
        for angle in range(0, 360, 45):
            import math
            ax = math.cos(math.radians(angle)); ay = math.sin(math.radians(angle))
            draw.line((x + int(ax * half * 0.65), y + int(ay * half * 0.65), x + int(ax * half), y + int(ay * half)), fill=colour, width=line)
    elif key == "map":
        draw.polygon(((x - half, y - half * 3 // 4), (x - half // 3, y - half), (x + half // 3, y - half * 3 // 4), (x + half, y - half), (x + half, y + half * 3 // 4), (x + half // 3, y + half), (x - half // 3, y + half * 3 // 4), (x - half, y + half)), outline=colour, fill=accent)
        draw.ellipse((x - line * 2, y - line * 2, x + line * 2, y + line * 2), fill=colour)
    elif key == "cup":
        draw.rounded_rectangle((x - half, y - half // 2, x + half // 2, y + half // 2), radius=line * 2, fill=accent, outline=colour, width=line)
        draw.arc((x + half // 4, y - half // 3, x + half, y + half // 2), 270, 90, fill=colour, width=line)
        for offset in (-half // 3, 0, half // 3):
            draw.arc((x + offset - line, y - half, x + offset + line * 2, y - half // 3), 150, 390, fill=colour, width=max(3, line // 2))
    elif key == "train":
        draw.rounded_rectangle((x - half * 3 // 4, y - half, x + half * 3 // 4, y + half * 3 // 4), radius=line * 2, fill=accent, outline=colour, width=line)
        draw.rectangle((x - half // 2, y - half * 3 // 4, x + half // 2, y - half // 5), fill=colour)
        draw.ellipse((x - half // 2, y + half // 2, x - half // 4, y + half * 3 // 4), fill=colour)
        draw.ellipse((x + half // 4, y + half // 2, x + half // 2, y + half * 3 // 4), fill=colour)
    elif key == "plate":
        draw.ellipse((x - half, y - half, x + half, y + half), outline=colour, width=line)
        draw.ellipse((x - half // 2, y - half // 2, x + half // 2, y + half // 2), fill=accent, outline=colour, width=line)
    elif key in {"home", "bag", "briefcase", "book"}:
        draw.rectangle((x - half * 3 // 4, y - half // 3, x + half * 3 // 4, y + half * 3 // 4), fill=accent, outline=colour, width=line)
        if key == "home":
            draw.polygon(((x - half, y - half // 3), (x, y - half), (x + half, y - half // 3)), fill=accent, outline=colour)
        elif key == "bag":
            draw.arc((x - half // 2, y - half * 3 // 4, x + half // 2, y), 180, 360, fill=colour, width=line)
        elif key == "briefcase":
            draw.rectangle((x - half // 3, y - half * 2 // 3, x + half // 3, y - half // 3), outline=colour, width=line)
        else:
            draw.line((x, y - half // 3, x, y + half * 3 // 4), fill=colour, width=line)
    else:
        draw.rounded_rectangle((x - half, y - half * 3 // 4, x + half, y + half // 2), radius=line * 3, fill=accent, outline=colour, width=line)
        draw.polygon(((x - half // 3, y + half // 2), (x - half // 2, y + half), (x, y + half // 2)), fill=accent, outline=colour)
        for offset in (-half // 2, 0, half // 2):
            draw.ellipse((x + offset - line, y - line, x + offset + line, y + line), fill=colour)


def _font(size: int, *, bold: bool):
    from PIL import ImageFont
    candidates = [
        "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
    ]
    for candidate in candidates:
        if Path(candidate).is_file():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


def _fit_text(draw, text: str, *, max_width: int, max_lines: int, start: int, minimum: int, bold: bool):
    for size in range(start, minimum - 1, -4):
        font = _font(size, bold=bold)
        lines = _wrap(draw, text, font, max_width)
        if len(lines) <= max_lines:
            return font, lines
    font = _font(minimum, bold=bold)
    return font, _wrap(draw, text, font, max_width)[:max_lines]


def _wrap(draw, text: str, font, max_width: int) -> list[str]:
    words = text.split()
    if not words:
        return [""]
    lines = [words[0]]
    for word in words[1:]:
        candidate = f"{lines[-1]} {word}"
        if draw.textbbox((0, 0), candidate, font=font)[2] <= max_width:
            lines[-1] = candidate
        else:
            lines.append(word)
    return lines


def _draw_left_lines(draw, lines, font, *, x: int, y: int, fill, spacing: int, stroke_width: int, stroke_fill) -> None:
    for line_text in lines:
        draw.text((x, y), line_text, font=font, fill=fill, stroke_width=stroke_width, stroke_fill=stroke_fill)
        box = draw.textbbox((x, y), line_text, font=font, stroke_width=stroke_width)
        y = box[3] + spacing


def _draw_centered_lines(draw, lines, font, *, center_x: int, center_y: int, fill, spacing: int, stroke_width: int, stroke_fill) -> None:
    heights = [draw.textbbox((0, 0), line or " ", font=font, stroke_width=stroke_width)[3] for line in lines]
    total = sum(heights) + spacing * max(0, len(lines) - 1)
    y = center_y - total // 2
    for line_text, line_height in zip(lines, heights):
        box = draw.textbbox((0, 0), line_text, font=font, stroke_width=stroke_width)
        x = center_x - (box[2] - box[0]) // 2
        draw.text((x, y), line_text, font=font, fill=fill, stroke_width=stroke_width, stroke_fill=stroke_fill)
        y += line_height + spacing


def _hex(value: str) -> tuple[int, int, int]:
    clean = value.lstrip("#")
    return tuple(int(clean[index:index + 2], 16) for index in (0, 2, 4))  # type: ignore[return-value]


def _mix(first: tuple[int, int, int], second: tuple[int, int, int], ratio: float) -> tuple[int, int, int]:
    return tuple(int(first[index] * (1 - ratio) + second[index] * ratio) for index in range(3))  # type: ignore[return-value]
