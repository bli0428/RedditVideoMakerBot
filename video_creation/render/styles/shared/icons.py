"""Icon drawing helpers for card rendering.

Moved from ``utils/card.py`` (``_RedditStyleCard`` static methods).
"""

from __future__ import annotations

from PIL import Image, ImageDraw


def _draw_heart(
    draw: ImageDraw.ImageDraw,
    cx: int,
    cy: int,
    size: int,
    color: str,
) -> None:
    """Draw a simple heart outline centred at *(cx, cy)*."""
    s = size
    # Top-left lobe
    draw.arc(
        [cx - s, cy - s // 2, cx, cy + s // 4],
        start=200, end=360,
        fill=color, width=max(2, s // 10),
    )
    # Top-right lobe
    draw.arc(
        [cx, cy - s // 2, cx + s, cy + s // 4],
        start=180, end=340,
        fill=color, width=max(2, s // 10),
    )
    # Left side down to point
    draw.line([(cx - s, cy + s // 8), (cx, cy + s)], fill=color, width=max(2, s // 10))
    # Right side down to point
    draw.line([(cx + s, cy + s // 8), (cx, cy + s)], fill=color, width=max(2, s // 10))


def _draw_bubble(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    size: int,
    color: str,
) -> None:
    """Draw a simple speech-bubble outline at top-left *(x, y)*."""
    lw = max(2, size // 12)
    r  = size // 5
    # Rounded rectangle body
    draw.rounded_rectangle(
        [x, y, x + size, y + int(size * 0.78)],
        radius=r, outline=color, width=lw,
    )
    # Tail (small triangle at bottom-left)
    tail_x = x + int(size * 0.22)
    tail_y = y + int(size * 0.78)
    draw.polygon(
        [
            (tail_x, tail_y),
            (tail_x - int(size * 0.14), tail_y + int(size * 0.22)),
            (tail_x + int(size * 0.14), tail_y),
        ],
        fill=color,
    )


def _make_checkmark(size: int) -> Image.Image:
    """Return a smooth blue verified checkmark as a *size*×*size* RGBA image.

    Rendered at 4× scale then downsampled with LANCZOS for clean edges.
    """
    scale = 4
    s = size * scale

    img  = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Blue filled circle
    draw.ellipse([0, 0, s - 1, s - 1], fill="#1D9BF0")

    # White tick — two segments meeting at a midpoint
    lw  = max(3, s // 7)
    mid = (int(s * 0.42), int(s * 0.60))
    draw.line(
        [(int(s * 0.20), int(s * 0.48)), mid],
        fill="#FFFFFF", width=lw,
    )
    draw.line(
        [mid, (int(s * 0.78), int(s * 0.26))],
        fill="#FFFFFF", width=lw,
    )

    return img.resize((size, size), Image.LANCZOS)
