"""Font path constants and font-loading helper.

Moved from ``utils/card.py``.
"""

from __future__ import annotations

import os

from PIL import ImageFont

# ---------------------------------------------------------------------------
# Font path constants
# ---------------------------------------------------------------------------

FONT_BOLD   = os.path.join("fonts", "Montserrat-ExtraBold.ttf")
FONT_MEDIUM = os.path.join("fonts", "Roboto-Medium.ttf")
FONT_BLACK  = os.path.join("fonts", "Roboto-Black.ttf")
FONT_NORMAL = os.path.join("fonts", "Roboto-Regular.ttf")
FONT_EMOJI  = os.path.join("fonts", "NotoColorEmoji.ttf")

# Noto Color Emoji only has bitmap strikes at exactly 109 px — any other size
# raises "invalid pixel size".  We always render at 109 and scale the result.
EMOJI_NATIVE_SIZE = 109


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

def _load_font(path: str, size: int) -> ImageFont.FreeTypeFont:
    """Load a TrueType font, falling back to the default if the file is missing."""
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()
