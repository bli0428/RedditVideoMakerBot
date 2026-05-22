"""Render a styled post card as two pieces: header card + body card."""

import io
import os
import textwrap
from typing import List, Optional, Tuple

import requests
from PIL import Image, ImageDraw, ImageFont


def _download_avatar(url: str, size: int = 64) -> Optional[Image.Image]:
    """Download and return a circular avatar image, or None on failure."""
    if not url:
        return None
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        img = Image.open(io.BytesIO(resp.content)).convert("RGBA")
        img = img.resize((size, size), Image.LANCZOS)
        mask = Image.new("L", (size, size), 0)
        draw = ImageDraw.Draw(mask)
        draw.ellipse([0, 0, size, size], fill=255)
        img.putalpha(mask)
        return img
    except Exception:
        return None


def render_post_card(
    text: str,
    output_path: str,
    title: str = "",
    author: str = "Anonymous",
    avatar_url: str = "",
    source: str = "reddit",
    subreddit: str = "",
    width: int = 900,
    bg_color: str = "#ffffff",
    text_color: str = "#1a1a1a",
    accent_color: str = "#ff4500",
    font_path: str = os.path.join("fonts", "Montserrat-ExtraBold.ttf"),
    body_font_path: str = os.path.join("fonts", "Roboto-Medium.ttf"),
) -> Tuple[str, str, List[dict]]:
    """Render a post as two card images: header and body.

    Returns:
        (header_path, body_path, line_positions)
        line_positions are relative to the body card image.
    """
    padding = 40
    body_font = ImageFont.truetype(body_font_path, 34)
    username_font = ImageFont.truetype(font_path, 30)
    title_font = ImageFont.truetype(font_path, 36)
    avatar_size = 56

    # Measure body text
    chars_per_line = max(20, int((width - padding * 2) / (34 * 0.52)))
    lines = textwrap.wrap(text, width=chars_per_line)

    dummy = Image.new("RGB", (1, 1))
    draw = ImageDraw.Draw(dummy)

    line_height = 0
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=body_font)
        h = bbox[3] - bbox[1]
        if h > line_height:
            line_height = h
    line_spacing = int(line_height * 0.6)

    # Measure title
    title_chars = max(15, int((width - padding * 2) / (36 * 0.58)))
    title_lines = textwrap.wrap(title, width=title_chars) if title else []
    title_line_h = 0
    if title_lines:
        for tl in title_lines:
            bbox = draw.textbbox((0, 0), tl, font=title_font)
            h = bbox[3] - bbox[1]
            if h > title_line_h:
                title_line_h = h

    # ── Header card (avatar + username + title) ───────────────────────
    header_content_h = avatar_size + 20
    if title_lines:
        header_content_h += len(title_lines) * (title_line_h + 8) + 10
    header_h = padding + header_content_h + padding

    header_card = Image.new("RGBA", (width, header_h), (0, 0, 0, 0))
    hd = ImageDraw.Draw(header_card)
    hd.rounded_rectangle([8, 8, width - 8, header_h - 8], radius=20, fill=bg_color, outline="#e0e0e0", width=2)

    y = padding
    avatar = _download_avatar(avatar_url, size=avatar_size)
    if avatar:
        header_card.paste(avatar, (padding, y), avatar)

    username_x = padding + avatar_size + 16 if avatar else padding
    username_bbox = hd.textbbox((0, 0), author, font=username_font)
    username_h = username_bbox[3] - username_bbox[1]
    username_y = y + (avatar_size - username_h) // 2 if avatar else y
    hd.text((username_x, username_y), author, font=username_font, fill="#555555")

    y += avatar_size + 15

    # Title
    if title_lines:
        for tl in title_lines:
            hd.text((padding, y), tl, font=title_font, fill=text_color)
            y += title_line_h + 8

    header_path = output_path.replace(".png", "_header.png")
    header_card.save(header_path)

    # ── Body cards (paginated, max LINES_PER_PAGE lines each) ─────────
    LINES_PER_PAGE = 6
    pages = []  # list of (body_path, [line_positions_for_this_page])

    for page_idx in range(0, len(lines), LINES_PER_PAGE):
        page_lines = lines[page_idx : page_idx + LINES_PER_PAGE]

        page_content_h = len(page_lines) * (line_height + line_spacing) + 30
        page_h = padding + page_content_h + padding

        page_card = Image.new("RGBA", (width, page_h), (0, 0, 0, 0))
        pd = ImageDraw.Draw(page_card)
        pd.rounded_rectangle([8, 8, width - 8, page_h - 8], radius=20, fill=bg_color, outline="#e0e0e0", width=2)

        y = padding
        page_positions = []
        for line in page_lines:
            line_y_top = y
            pd.text((padding, y), line, font=body_font, fill=text_color)
            y += line_height + line_spacing
            page_positions.append({
                "text": line,
                "y_top": line_y_top,
                "y_bottom": y,
            })

        page_path = output_path.replace(".png", f"_body_{page_idx // LINES_PER_PAGE}.png")
        page_card.save(page_path)
        pages.append((page_path, page_positions))

    return header_path, pages
    body_card.save(body_path)

    return header_path, body_path, line_positions
