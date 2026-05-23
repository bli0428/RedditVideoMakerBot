"""Avatar download and circular-crop helper.

Moved from ``utils/card.py``.
"""

from __future__ import annotations

import io
from typing import Optional

import requests
from PIL import Image, ImageDraw


def _download_avatar(url: str, size: int) -> Optional[Image.Image]:
    """Fetch *url*, resize to *size*×*size*, and apply a circular mask.

    Returns ``None`` on any failure — callers must handle the missing-avatar
    case gracefully.
    """
    if not url:
        return None
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        img = Image.open(io.BytesIO(resp.content)).convert("RGBA")
        img = img.resize((size, size), Image.LANCZOS)
        mask = Image.new("L", (size, size), 0)
        ImageDraw.Draw(mask).ellipse([0, 0, size - 1, size - 1], fill=255)
        img.putalpha(mask)
        return img
    except Exception:
        return None
