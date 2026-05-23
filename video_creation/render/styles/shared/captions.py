"""Caption and karaoke line rendering helpers.

Moved from ``video_creation/final_video.py``.
"""

from __future__ import annotations

import re
import textwrap

from PIL import Image, ImageDraw

from video_creation.render.styles.shared.fonts import FONT_BOLD, _load_font
from video_creation.render.styles.shared.text import _strip_emojis

# ---------------------------------------------------------------------------
# Caption style constants (match final_video.py defaults)
# ---------------------------------------------------------------------------

CAPTION_FONT_SIZE    = 100
CAPTION_COLOR        = "white"
CAPTION_STROKE_COLOR = "black"
CAPTION_STROKE_WIDTH = 12


def _render_caption_image(text: str, max_width: int, W: int) -> Image.Image:
    """Render a caption as an RGBA ``PIL.Image`` with text wrapping and stroke outline.

    Uses Pillow for full control over styling.  The returned image is
    transparent outside the text area.

    Args:
        text:      Caption text (emojis are stripped automatically).
        max_width: Maximum pixel width for the text block.
        W:         Full frame width (used only for context; wrapping is
                   controlled by *max_width*).

    Returns:
        An RGBA ``PIL.Image``.
    """
    text = _strip_emojis(text)
    if not text:
        text = " "
    # Strip leading/trailing punctuation for cleaner captions.
    text = re.sub(r'^[\s,.\-;:!?\'\"]+|[\s,.\-;:!?\'\"]+$', '', text)
    if not text:
        text = " "

    font = _load_font(FONT_BOLD, CAPTION_FONT_SIZE)

    # Wrap text to fit within max_width.
    chars_per_line = max(10, int(max_width / (CAPTION_FONT_SIZE * 0.55)))
    lines = textwrap.wrap(text, width=chars_per_line)
    if not lines:
        lines = [" "]

    # Measure total size.
    dummy = Image.new("RGBA", (1, 1))
    draw  = ImageDraw.Draw(dummy)
    line_heights: list[int] = []
    line_widths:  list[int] = []
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        line_widths.append(bbox[2] - bbox[0])
        line_heights.append(bbox[3] - bbox[1])

    padding = 20
    stroke  = CAPTION_STROKE_WIDTH
    img_w   = max(line_widths) + padding * 2 + stroke * 2
    img_h   = sum(line_heights) + (len(lines) - 1) * 10 + padding * 2 + stroke * 2

    # Draw.
    img  = Image.new("RGBA", (int(img_w), int(img_h)), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    y    = padding
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        lw   = bbox[2] - bbox[0]
        x    = (img_w - lw) / 2
        # Stroke pass
        draw.text(
            (x, y), line, font=font,
            fill=CAPTION_STROKE_COLOR,
            stroke_width=stroke, stroke_fill=CAPTION_STROKE_COLOR,
        )
        # Fill pass
        draw.text((x, y), line, font=font, fill=CAPTION_COLOR)
        y += bbox[3] - bbox[1] + 10

    return img


def _render_karaoke_line(text: str) -> Image.Image:
    """Render a single body chunk as a large bold pop-up text image (RGBA).

    Styled identically to captions: white fill, thick black stroke, centred.
    Text is word-wrapped if it would exceed the screen width at the caption
    font size, so long full-line chunks never overflow off-screen.

    Args:
        text: The chunk text to render (emojis are stripped automatically).

    Returns:
        An RGBA ``PIL.Image``.
    """
    text = _strip_emojis(text).strip()
    if not text:
        text = " "

    font   = _load_font(FONT_BOLD, CAPTION_FONT_SIZE)
    stroke = CAPTION_STROKE_WIDTH
    pad    = 20
    # Leave generous side margins so text never touches the screen edge.
    max_text_w = 1080 - pad * 4

    dummy = Image.new("RGBA", (1, 1))
    draw  = ImageDraw.Draw(dummy)

    # Word-wrap at the caption font size.
    words_in = text.split()
    wrapped_lines: list[str] = []
    current = ""
    for word in words_in:
        candidate = (current + " " + word).strip()
        bb = draw.textbbox((0, 0), candidate, font=font)
        if bb[2] - bb[0] <= max_text_w:
            current = candidate
        else:
            if current:
                wrapped_lines.append(current)
            current = word
    if current:
        wrapped_lines.append(current)
    if not wrapped_lines:
        wrapped_lines = [" "]

    line_spacing = 8
    line_bbs     = [draw.textbbox((0, 0), l, font=font) for l in wrapped_lines]
    line_widths  = [bb[2] - bb[0] for bb in line_bbs]
    line_heights = [bb[3] - bb[1] for bb in line_bbs]

    img_w = max(line_widths) + pad * 2 + stroke * 2
    img_h = (
        sum(line_heights)
        + line_spacing * (len(wrapped_lines) - 1)
        + pad * 2
        + stroke * 2
    )
    img = Image.new("RGBA", (int(img_w), int(img_h)), (0, 0, 0, 0))
    d   = ImageDraw.Draw(img)

    y = pad + stroke
    for line, bb in zip(wrapped_lines, line_bbs):
        lw = bb[2] - bb[0]
        x  = (img_w - lw) / 2 - bb[0]
        d.text(
            (x, y - bb[1]), line, font=font,
            fill=CAPTION_STROKE_COLOR,
            stroke_width=stroke, stroke_fill=CAPTION_STROKE_COLOR,
        )
        d.text((x, y - bb[1]), line, font=font, fill=CAPTION_COLOR)
        y += bb[3] - bb[1] + line_spacing

    return img
