"""Post card rendering for video overlays.

Two card styles are supported:

    "custom"  — original split header/body card: clean, minimal, rounded corners.
    "reddit"  — Twitter/X-style white card popular in Reddit video content:
                circular OP avatar (or omitted if unavailable), bold @u/author
                handle, blue verified checkmark, large bold title, and drawn
                heart/comment icons with counts.

Public API
----------
    render_card(style, text, output_path, **kwargs) -> CardResult

Both styles return:
    CardResult = (header_path: str, body_pages: list[tuple[str, list[dict]]])

Each body-page tuple is (image_path, line_positions) where each line_position
dict has keys: "text", "y_top", "y_bottom".
"""

from __future__ import annotations

import io
import os
import textwrap
from abc import ABC, abstractmethod
from typing import List, Optional, Tuple

import requests
from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------------------
# Public type aliases
# ---------------------------------------------------------------------------
LinePosDict = dict          # {"text": str, "y_top": int, "y_bottom": int}
BodyPage    = Tuple[str, List[LinePosDict]]
CardResult  = Tuple[str, List[BodyPage]]

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------
LINES_PER_PAGE = 6

_FONT_BOLD   = os.path.join("fonts", "Montserrat-ExtraBold.ttf")
_FONT_MEDIUM = os.path.join("fonts", "Roboto-Medium.ttf")
_FONT_BLACK  = os.path.join("fonts", "Roboto-Black.ttf")
_FONT_EMOJI  = os.path.join("fonts", "NotoColorEmoji.ttf")

# Award emojis shown as a decorative row beneath the author handle.
# These are the classic Reddit award icons rendered via Noto Color Emoji.
# The French flag is drawn separately (see _make_french_flag) because Pillow
# can't ligature-shape regional-indicator pairs (🇫🇷) into a single flag glyph.
_AWARD_ROW = "🥐🗼🍷🧀🥖🎨⚜️"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _load_font(path: str, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


# Noto Color Emoji only has bitmap strikes at exactly 109 px — any other size
# raises "invalid pixel size".  We always render at 109 and scale the result.
_EMOJI_NATIVE_SIZE = 109


def _render_emoji_row(text: str, target_height: int) -> Image.Image:
    """Render *text* with NotoColorEmoji at native size, then scale to *target_height*.

    Returns a transparent RGBA image.  Falls back to a 1-px-wide placeholder
    if the font is missing or the text produces no glyphs.
    """
    try:
        font = ImageFont.truetype(_FONT_EMOJI, _EMOJI_NATIVE_SIZE)
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


def _download_avatar(url: str, size: int) -> Optional[Image.Image]:
    """Fetch *url*, resize to *size*×*size*, and apply a circular mask.
    Returns None on any failure — callers must handle the missing-avatar case.
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


def _text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> Tuple[int, int]:
    """Return (width, height) of *text* rendered in *font*."""
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
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------

class _BaseCard(ABC):
    """Abstract base for card renderers.

    Subclasses implement ``_render_header`` and ``_render_body_page``.
    ``render()`` orchestrates pagination and returns the CardResult.
    """

    def __init__(
        self,
        text: str,
        output_path: str,
        title: str,
        author: str,
        avatar_url: str,
        subreddit: str,
        upvotes: int,
        num_comments: int,
        width: int,
    ) -> None:
        self.text         = text
        self.output_path  = output_path
        self.title        = title
        self.author       = author
        self.avatar_url   = avatar_url
        self.subreddit    = subreddit
        self.upvotes      = upvotes
        self.num_comments = num_comments
        self.width        = width

    # -- subclass contract ---------------------------------------------------

    @abstractmethod
    def _render_header(self) -> str:
        """Draw the header card and return its file path."""

    @abstractmethod
    def _render_body_page(
        self,
        page_lines: List[str],
        page_index: int,
    ) -> Tuple[Image.Image, List[LinePosDict]]:
        """Draw one body page and return (image, line_positions)."""

    @abstractmethod
    def _body_font(self) -> ImageFont.FreeTypeFont:
        """Font used for body text (needed for pixel-accurate wrapping)."""

    # -- orchestration -------------------------------------------------------

    def render(self) -> CardResult:
        header_path = self._render_header()

        body_lines = _wrap(self.text, self._body_font(), self.width - self._padding * 2)

        body_pages: List[BodyPage] = []
        for page_idx in range(0, max(1, len(body_lines)), LINES_PER_PAGE):
            chunk = body_lines[page_idx : page_idx + LINES_PER_PAGE]
            img, positions = self._render_body_page(chunk, page_idx // LINES_PER_PAGE)
            page_path = self.output_path.replace(
                ".png", f"_body_{page_idx // LINES_PER_PAGE}.png"
            )
            img.save(page_path)
            body_pages.append((page_path, positions))

        return header_path, body_pages

    @property
    def _padding(self) -> int:
        return 40


# ---------------------------------------------------------------------------
# Custom card  (original style)
# ---------------------------------------------------------------------------

class _CustomCard(_BaseCard):
    """Clean minimal card: white rounded rectangle, avatar + username, title."""

    # palette
    BG      = "#ffffff"
    BORDER  = "#e0e0e0"
    TEXT    = "#1a1a1a"
    META    = "#555555"
    RADIUS  = 20
    BORDER_W = 2
    INSET   = 8   # gap between canvas edge and rounded rect

    def _body_font(self) -> ImageFont.FreeTypeFont:
        return _load_font(_FONT_MEDIUM, 34)

    def _render_header(self) -> str:
        pad = self._padding
        w   = self.width

        title_font    = _load_font(_FONT_BOLD,   36)
        username_font = _load_font(_FONT_BOLD,   30)
        body_font     = self._body_font()
        avatar_size   = 56

        dummy_draw = ImageDraw.Draw(Image.new("RGBA", (1, 1)))

        title_lines = _wrap(self.title, title_font, w - pad * 2) if self.title else []
        _, title_lh = _text_size(dummy_draw, "Ag", title_font)

        avatar = _download_avatar(self.avatar_url, avatar_size)

        # Height
        content_h = avatar_size + 15
        if title_lines:
            content_h += len(title_lines) * (title_lh + 8) + 10
        h = pad + content_h + pad

        img  = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.rounded_rectangle(
            [self.INSET, self.INSET, w - self.INSET, h - self.INSET],
            radius=self.RADIUS, fill=self.BG,
            outline=self.BORDER, width=self.BORDER_W,
        )

        y = pad
        if avatar:
            img.paste(avatar, (pad, y), avatar)

        username_x = pad + avatar_size + 16 if avatar else pad
        _, un_h = _text_size(dummy_draw, self.author, username_font)
        username_y = y + (avatar_size - un_h) // 2 if avatar else y
        draw.text((username_x, username_y), self.author, font=username_font, fill=self.META)

        y += avatar_size + 15
        for line in title_lines:
            draw.text((pad, y), line, font=title_font, fill=self.TEXT)
            y += title_lh + 8

        path = self.output_path.replace(".png", "_header.png")
        img.save(path)
        return path

    def _render_body_page(
        self,
        page_lines: List[str],
        page_index: int,
    ) -> Tuple[Image.Image, List[LinePosDict]]:
        pad  = self._padding
        w    = self.width
        font = self._body_font()

        dummy_draw = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
        _, lh = _text_size(dummy_draw, "Ag", font)
        spacing = int(lh * 0.6)

        content_h = len(page_lines) * (lh + spacing) + 30
        h = pad + content_h + pad

        img  = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.rounded_rectangle(
            [self.INSET, self.INSET, w - self.INSET, h - self.INSET],
            radius=self.RADIUS, fill=self.BG,
            outline=self.BORDER, width=self.BORDER_W,
        )

        y = pad
        positions: List[LinePosDict] = []
        for line in page_lines:
            draw.text((pad, y), line, font=font, fill=self.TEXT)
            positions.append({"text": line, "y_top": y, "y_bottom": y + lh + spacing})
            y += lh + spacing

        return img, positions


# ---------------------------------------------------------------------------
# Reddit-style card  (Twitter/X aesthetic)
# ---------------------------------------------------------------------------

class _RedditStyleCard(_BaseCard):
    """White rounded card matching the popular Reddit-video Twitter/X style.

    Layout (header, top → bottom):
        [avatar circle]  @u/author  [verified checkmark]
        ─────────────────────────────────────────────────
        Large bold post title (word-wrapped)
        ─────────────────────────────────────────────────
        [heart shape] count   [speech bubble] count
    """

    # palette
    BG          = "#FFFFFF"
    BORDER      = "#CFD9DE"
    TEXT        = "#0F1419"
    META        = "#536471"
    VERIFIED    = "#1D9BF0"
    RADIUS      = 24
    BORDER_W    = 2
    INSET       = 6

    @property
    def _padding(self) -> int:
        return 44

    def _body_font(self) -> ImageFont.FreeTypeFont:
        return _load_font(_FONT_MEDIUM, 36)

    # -- icon drawing --------------------------------------------------------

    @staticmethod
    def _draw_heart(draw: ImageDraw.ImageDraw, cx: int, cy: int, size: int, color: str) -> None:
        """Draw a simple heart outline centred at (cx, cy)."""
        # Two arcs + a V shape approximated with a polygon
        s = size
        # Top-left lobe
        draw.arc([cx - s, cy - s // 2, cx, cy + s // 4], start=200, end=360, fill=color, width=max(2, s // 10))
        # Top-right lobe
        draw.arc([cx, cy - s // 2, cx + s, cy + s // 4], start=180, end=340, fill=color, width=max(2, s // 10))
        # Left side down to point
        draw.line([(cx - s, cy + s // 8), (cx, cy + s)], fill=color, width=max(2, s // 10))
        # Right side down to point
        draw.line([(cx + s, cy + s // 8), (cx, cy + s)], fill=color, width=max(2, s // 10))

    @staticmethod
    def _draw_bubble(draw: ImageDraw.ImageDraw, x: int, y: int, size: int, color: str) -> None:
        """Draw a simple speech-bubble outline at top-left (x, y)."""
        lw = max(2, size // 12)
        r  = size // 5
        # Rounded rectangle body
        draw.rounded_rectangle([x, y, x + size, y + int(size * 0.78)], radius=r, outline=color, width=lw)
        # Tail (small triangle at bottom-left)
        tail_x = x + int(size * 0.22)
        tail_y = y + int(size * 0.78)
        draw.polygon(
            [(tail_x, tail_y), (tail_x - int(size * 0.14), tail_y + int(size * 0.22)), (tail_x + int(size * 0.14), tail_y)],
            fill=color,
        )

    @staticmethod
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
        draw.line([(int(s * 0.20), int(s * 0.48)), mid],
                  fill="#FFFFFF", width=lw)
        draw.line([mid, (int(s * 0.78), int(s * 0.26))],
                  fill="#FFFFFF", width=lw)

        return img.resize((size, size), Image.LANCZOS)

    # -- card rendering ------------------------------------------------------

    def _render_header(self) -> str:
        pad = self._padding
        w   = self.width

        handle_font  = _load_font(_FONT_BLACK,  32)
        title_font   = _load_font(_FONT_BLACK,  54)
        count_font   = _load_font(_FONT_MEDIUM, 28)

        avatar_size  = 88
        check_size   = 26
        icon_size    = 28
        gap          = 22   # vertical gap between rows

        dummy_draw = ImageDraw.Draw(Image.new("RGBA", (1, 1)))

        # Avatar (may be None)
        avatar = _download_avatar(self.avatar_url, avatar_size)

        # Handle text
        handle_text = f"@u/{self.author}"
        handle_w, handle_h = _text_size(dummy_draw, handle_text, handle_font)

        # Title lines — wrap to pixel width
        title_lines = _wrap(self.title, title_font, w - pad * 2) if self.title else []
        _, title_lh = _text_size(dummy_draw, "Ag", title_font)
        title_block_h = len(title_lines) * (title_lh + 6) if title_lines else 0

        # Row heights
        row_a_h = avatar_size if avatar else handle_h + 8   # avatar / handle row
        row_awards_h = 40                                    # emoji award row
        row_b_h = title_block_h
        row_c_h = icon_size + 8                              # counts row

        content_h = row_a_h + gap + row_awards_h + gap + row_b_h + gap + row_c_h
        card_h    = pad + content_h + pad

        # Canvas with a little room for the border
        img  = Image.new("RGBA", (w, card_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        draw.rounded_rectangle(
            [self.INSET, self.INSET, w - self.INSET, card_h - self.INSET],
            radius=self.RADIUS, fill=self.BG,
            outline=self.BORDER, width=self.BORDER_W,
        )

        # ── Row A: avatar + handle + checkmark ────────────────────────────
        y = pad
        x = pad

        if avatar:
            img.paste(avatar, (x, y), avatar)
            text_x = x + avatar_size + 18
        else:
            text_x = x

        # Vertically centre handle against avatar (or just place it)
        handle_y = y + (avatar_size - handle_h) // 2 if avatar else y
        draw.text((text_x, handle_y), handle_text, font=handle_font, fill=self.TEXT)

        # Checkmark immediately after handle text
        check_x = text_x + handle_w + 8
        check_y = handle_y + (handle_h - check_size) // 2
        checkmark = self._make_checkmark(check_size)
        img.paste(checkmark, (check_x, check_y), checkmark)

        y += row_a_h + gap

        # ── Award emoji row ───────────────────────────────────────────────
        # French flag is drawn as a small image (Pillow can't ligature-shape
        # the regional-indicator pair), then concatenated with the emoji row.
        award_img = _render_award_row(row_awards_h)
        img.paste(award_img, (pad, y), award_img)
        y += row_awards_h + gap

        # ── Row B: title ──────────────────────────────────────────────────
        for line in title_lines:
            draw.text((pad, y), line, font=title_font, fill=self.TEXT)
            y += title_lh + 6

        y += gap

        # ── Row C: heart count + bubble count ─────────────────────────────
        heart_label   = _format_count(self.upvotes)   if self.upvotes   else "99+"
        comment_label = _format_count(self.num_comments) if self.num_comments else "99+"

        # Heart icon
        self._draw_heart(draw, x + icon_size // 2, y + icon_size // 4, icon_size // 2, self.META)
        count_x = x + icon_size + 8
        _, count_h = _text_size(dummy_draw, heart_label, count_font)
        count_y = y + (icon_size - count_h) // 2
        draw.text((count_x, count_y), heart_label, font=count_font, fill=self.META)

        count_w, _ = _text_size(dummy_draw, heart_label, count_font)
        bubble_x = count_x + count_w + 36

        # Speech bubble icon
        self._draw_bubble(draw, bubble_x, y, icon_size, self.META)
        draw.text((bubble_x + icon_size + 8, count_y), comment_label, font=count_font, fill=self.META)

        path = self.output_path.replace(".png", "_header.png")
        img.save(path)
        return path

    def _render_body_page(
        self,
        page_lines: List[str],
        page_index: int,
    ) -> Tuple[Image.Image, List[LinePosDict]]:
        pad  = self._padding
        w    = self.width
        font = self._body_font()

        dummy_draw = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
        _, lh = _text_size(dummy_draw, "Ag", font)
        spacing = int(lh * 0.5)

        content_h = len(page_lines) * (lh + spacing)
        h = pad + content_h + pad

        img  = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.rounded_rectangle(
            [self.INSET, self.INSET, w - self.INSET, h - self.INSET],
            radius=self.RADIUS, fill=self.BG,
            outline=self.BORDER, width=self.BORDER_W,
        )

        y = pad
        positions: List[LinePosDict] = []
        for line in page_lines:
            draw.text((pad, y), line, font=font, fill=self.TEXT)
            positions.append({"text": line, "y_top": y, "y_bottom": y + lh + spacing})
            y += lh + spacing

        return img, positions


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def render_card(
    style: str,
    text: str,
    output_path: str,
    *,
    title: str = "",
    author: str = "Anonymous",
    avatar_url: str = "",
    subreddit: str = "",
    upvotes: int = 0,
    num_comments: int = 0,
    width: int = 900,
    # custom-card-only kwargs
    bg_color: str = "#ffffff",
    text_color: str = "#1a1a1a",
    accent_color: str = "#ff4500",
    theme: str = "light",
) -> CardResult:
    """Render a post card and return (header_path, body_pages).

    Args:
        style:        "custom" or "reddit".
        text:         Post body text.
        output_path:  Base .png path; page files are derived from it.
        title:        Post title (shown in header).
        author:       Reddit username (no u/ prefix).
        avatar_url:   URL to the author's avatar image.
        subreddit:    Subreddit name (no r/ prefix).
        upvotes:      Upvote / like count.
        num_comments: Comment count.
        width:        Card width in pixels.

    Returns:
        (header_path, body_pages) where body_pages is a list of
        (page_image_path, line_positions) tuples.
    """
    common = dict(
        text=text,
        output_path=output_path,
        title=title,
        author=author,
        avatar_url=avatar_url,
        subreddit=subreddit,
        upvotes=upvotes,
        num_comments=num_comments,
        width=width,
    )

    if style == "reddit":
        card = _RedditStyleCard(**common)
    else:
        card = _CustomCard(**common)

    return card.render()


# ---------------------------------------------------------------------------
# Legacy shim — keeps any direct callers of render_post_card working
# ---------------------------------------------------------------------------

def render_post_card(
    text: str,
    output_path: str,
    title: str = "",
    author: str = "Anonymous",
    avatar_url: str = "",
    source: str = "reddit",
    subreddit: str = "",
    width: int = 900,
    **_kwargs,
) -> CardResult:
    """Deprecated: use render_card(style='custom', ...) instead."""
    return render_card(
        style="custom",
        text=text,
        output_path=output_path,
        title=title,
        author=author,
        avatar_url=avatar_url,
        subreddit=subreddit,
        width=width,
    )
