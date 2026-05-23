"""Emoji row and French flag rendering helpers.

Moved from ``utils/card.py``.
"""

from __future__ import annotations

from PIL import Image, ImageDraw

from video_creation.render.styles.shared.fonts import FONT_EMOJI, EMOJI_NATIVE_SIZE

# Award emojis shown as a decorative row beneath the author handle.
# These are the classic Reddit award icons rendered via Noto Color Emoji.
# The French flag is drawn separately (see _make_french_flag) because Pillow
# can't ligature-shape regional-indicator pairs (🇫🇷) into a single flag glyph.
_AWARD_ROW = "🥐🗼🍷🧀🥖🎨⚜️"


def _render_emoji_row(text: str, target_height: int) -> Image.Image:
    """Render *text* with NotoColorEmoji at native size, then scale to *target_height*.

    Returns a transparent RGBA image.  Falls back to a 1-px-wide placeholder
    if the font is missing or the text produces no glyphs.
    """
    try:
        from PIL import ImageFont
        font = ImageFont.truetype(FONT_EMOJI, EMOJI_NATIVE_SIZE)
    except OSError:
        return Image.new("RGBA", (1, target_height), (0, 0, 0, 0))

    dummy = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    bb = dummy.textbbox((0, 0), text, font=font, embedded_color=True)
    native_w = bb[2] - bb[0]
    native_h = bb[3] - bb[1]
    if native_w <= 0 or native_h <= 0:
        return Image.new("RGBA", (1, target_height), (0, 0, 0, 0))

    # Draw at native size on a transparent canvas
    canvas = Image.new("RGBA", (native_w + 4, native_h + 4), (0, 0, 0, 0))
    ImageDraw.Draw(canvas).text((-bb[0], -bb[1]), text, font=font, embedded_color=True)

    # Scale down to target_height, preserving aspect ratio
    scale    = target_height / native_h
    scaled_w = max(1, int(native_w * scale))
    return canvas.resize((scaled_w, target_height), Image.LANCZOS)


def _make_french_flag(height: int) -> Image.Image:
    """Return a French flag (blue/white/red vertical stripes) as an RGBA image.

    Standard flag aspect ratio is 3:2 (width:height).  The flag is drawn into
    a rounded rectangle so it blends visually with the emoji glyphs next to
    it, which all have rounded silhouettes.
    """
    # 3:2 aspect ratio.  Render at 4× then downsample for clean stripe edges.
    scale = 4
    h = height * scale
    w = int(h * 1.5)

    flag = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(flag)

    # Use a rounded-rect mask so corners are smooth.
    radius = max(2, h // 8)
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, w - 1, h - 1], radius=radius, fill=255)

    stripe_w = w // 3
    # Official French flag colours
    draw.rectangle([0,             0, stripe_w,     h], fill="#0055A4")  # blue
    draw.rectangle([stripe_w,      0, stripe_w * 2, h], fill="#FFFFFF")  # white
    draw.rectangle([stripe_w * 2,  0, w,            h], fill="#EF4135")  # red

    flag.putalpha(mask)
    return flag.resize((max(1, int(height * 1.5)), height), Image.LANCZOS)


def _render_award_row(target_height: int, gap: int = 8) -> Image.Image:
    """Compose the full award row: French flag followed by the emoji row.

    Returns a transparent RGBA image whose height equals *target_height*.
    """
    flag  = _make_french_flag(target_height)
    emoji = _render_emoji_row(_AWARD_ROW, target_height)

    total_w = flag.width + gap + emoji.width
    row = Image.new("RGBA", (total_w, target_height), (0, 0, 0, 0))
    row.paste(flag, (0, 0), flag)
    row.paste(emoji, (flag.width + gap, 0), emoji)
    return row
