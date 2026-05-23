"""Shared text helpers for card rendering.

Moved from ``utils/card.py`` and ``video_creation/final_video.py``.
"""

from __future__ import annotations

import re
from typing import List, Tuple

from PIL import Image, ImageDraw, ImageFont


def _strip_emojis(text: str) -> str:
    """Remove emoji characters from *text*."""
    return re.sub(
        r"[\U0001F600-\U0001F64F"  # emoticons
        r"\U0001F300-\U0001F5FF"   # symbols & pictographs
        r"\U0001F680-\U0001F6FF"   # transport & map
        r"\U0001F1E0-\U0001F1FF"   # flags
        r"\U00002702-\U000027B0"   # dingbats
        r"\U000024C2-\U0001F251"   # misc
        r"\U0001F900-\U0001F9FF"   # supplemental
        r"\U0001FA00-\U0001FA6F"   # chess symbols
        r"\U0001FA70-\U0001FAFF"   # symbols extended
        r"\U00002600-\U000026FF"   # misc symbols
        r"\U0000FE00-\U0000FE0F"   # variation selectors
        r"\U0000200D"              # zero width joiner
        r"]+", "", text
    ).strip()


def _text_size(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
) -> Tuple[int, int]:
    """Return ``(width, height)`` of *text* rendered in *font*."""
    bb = draw.textbbox((0, 0), text, font=font)
    return bb[2] - bb[0], bb[3] - bb[1]


def _wrap(text: str, font: ImageFont.FreeTypeFont, max_px: int) -> List[str]:
    """Word-wrap *text* so each line fits within *max_px* pixels."""
    words = text.split()
    if not words:
        return [""]
    dummy = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    lines: List[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        w, _ = _text_size(dummy, candidate, font)
        if w <= max_px:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [""]


def _format_count(n: int) -> str:
    """Format a large integer as a human-readable string (e.g. ``1.2k``)."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)
