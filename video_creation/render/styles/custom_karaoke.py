"""CustomKaraokeStyle — custom header + karaoke body plugin.

Implements the custom header natively (no temp PNGs, no ``_CustomCard``
delegation) and uses ``_render_karaoke_line`` for the body, producing one
centered caption RGBA image per ``LineTiming`` entry.

``compose_frame`` reproduces the karaoke pop-in / fade-out logic from
``make_combined_frame`` (``body_style == "karaoke"``, ``card_style == "custom"``
branch) in ``video_creation/final_video.py``.

Satisfies: Requirements 4.1, 5.1, 5.2, 7.1, 7.4, 11.1, 11.2
"""

from __future__ import annotations

from typing import Any, Mapping

import numpy as np
from PIL import Image, ImageDraw

from video_creation.render.context import RenderContext
from video_creation.render.styles.base import BodyAssets, CardStylePlugin
from video_creation.render.styles.shared.animation import header_pop_zoom_scale
from video_creation.render.styles.shared.avatar import _download_avatar
from video_creation.render.styles.shared.captions import _render_karaoke_line
from video_creation.render.styles.shared.fonts import (
    FONT_BOLD,
    _load_font,
)
from video_creation.render.styles.shared.text import _text_size, _wrap
from video_creation.render.timing.models import LineTiming
from video_creation.render.styles import register_style


@register_style
class CustomKaraokeStyle(CardStylePlugin):
    """Custom header + karaoke body visual treatment.

    The header is rendered natively via PIL — no temp files, no delegation to
    ``_CustomCard`` (Req 5.1).  The body produces one RGBA ndarray per
    ``LineTiming`` chunk (Req 5.2).  ``compose_frame`` returns a single RGBA
    frame whose alpha channel doubles as the MoviePy mask (Req 4.1).

    Class-level layout constants (Req 11.1, 11.2)
    -----------------------------------------------
    All layout constants are class-level; none are shared with other plugins.
    """

    # ── Plugin identity ────────────────────────────────────────────────────
    style_id = "custom-karaoke"
    options_schema: Mapping[str, type] = {
        "theme": str,
        "karaoke_words_per_chunk": int,
    }

    # ── Header card palette (mirrors _CustomCard) ─────────────────────────
    HEADER_BG      = "#ffffff"
    HEADER_BORDER  = "#e0e0e0"
    HEADER_TEXT    = "#1a1a1a"
    HEADER_META    = "#555555"
    HEADER_RADIUS  = 20
    HEADER_BORDER_W = 2
    HEADER_INSET   = 8    # gap between canvas edge and rounded rect
    HEADER_PADDING = 40   # inner padding

    # ── Header font sizes ─────────────────────────────────────────────────
    TITLE_FONT_SIZE    = 36
    USERNAME_FONT_SIZE = 30
    AVATAR_SIZE        = 56   # pixels

    # ── Layout constants (class-level, Req 11.1, 11.2) ───────────────────
    CARD_WIDTH_PCT: float = 0.85       # header display width as fraction of W
    HEADER_Y_START: float = 0.12       # header top Y as fraction of H (at t=0)
    HEADER_Y_END: float = 0.10
    POP_DUR: float = 0.25              # seconds for the pop-in phase
    ZOOM_AMOUNT: float = 0.0   # no zoom after pop-in
    HEADER_DISMISS_DUR: float = 0.4    # seconds to fade header out once body starts
    KARAOKE_Y_PCT: float = 0.60        # vertical centre of karaoke text (fraction of H)
    FADE_OUT_DUR: float = 0.15         # seconds of fade-out before next chunk

    # ── Constructor ───────────────────────────────────────────────────────

    def __init__(self, options: Mapping[str, Any], canvas: Any) -> None:
        super().__init__(options, canvas)

    # ── render_header ─────────────────────────────────────────────────────

    def render_header(self, ctx: RenderContext) -> np.ndarray:
        """Render the custom header card natively and return an RGBA ndarray.

        Implements the same visual as ``_CustomCard._render_header()``:
        white rounded rectangle, circular avatar, username, and wrapped title.
        No temp files are written (Req 5.1).

        Returns
        -------
        numpy.ndarray
            Shape ``(H, W, 4)``, dtype ``uint8``, RGBA.
        """
        pad = self.HEADER_PADDING
        w = int(ctx.canvas.width * self.CARD_WIDTH_PCT)

        title_font    = _load_font(FONT_BOLD,   self.TITLE_FONT_SIZE)
        username_font = _load_font(FONT_BOLD,   self.USERNAME_FONT_SIZE)
        avatar_size   = self.AVATAR_SIZE

        dummy_draw = ImageDraw.Draw(Image.new("RGBA", (1, 1)))

        title_lines = _wrap(ctx.title, title_font, w - pad * 2) if ctx.title else []
        _, title_lh = _text_size(dummy_draw, "Ag", title_font)

        avatar = _download_avatar(ctx.avatar_url, avatar_size)

        # Compute card height
        content_h = avatar_size + 15
        if title_lines:
            content_h += len(title_lines) * (title_lh + 8) + 10
        h = pad + content_h + pad

        img  = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.rounded_rectangle(
            [self.HEADER_INSET, self.HEADER_INSET,
             w - self.HEADER_INSET, h - self.HEADER_INSET],
            radius=self.HEADER_RADIUS,
            fill=self.HEADER_BG,
            outline=self.HEADER_BORDER,
            width=self.HEADER_BORDER_W,
        )

        y = pad
        if avatar:
            img.paste(avatar, (pad, y), avatar)

        username_x = pad + avatar_size + 16 if avatar else pad
        _, un_h = _text_size(dummy_draw, ctx.author, username_font)
        username_y = y + (avatar_size - un_h) // 2 if avatar else y
        draw.text(
            (username_x, username_y),
            ctx.author,
            font=username_font,
            fill=self.HEADER_META,
        )

        y += avatar_size + 15
        for line in title_lines:
            draw.text((pad, y), line, font=title_font, fill=self.HEADER_TEXT)
            y += title_lh + 8

        return np.array(img.convert("RGBA"))

    # ── render_body ───────────────────────────────────────────────────────

    def render_body(
        self,
        ctx: RenderContext,
        line_timings: tuple[LineTiming, ...],
    ) -> BodyAssets:
        """Pre-render one centered caption RGBA image per ``LineTiming`` entry.

        Calls ``_render_karaoke_line`` for each entry and stores the results
        in ``BodyAssets.chunk_images``.  No temp files are written (Req 5.2).
        """
        chunk_images: list[np.ndarray] = []
        for lt in line_timings:
            pil_img = _render_karaoke_line(lt.text)
            chunk_images.append(np.array(pil_img.convert("RGBA")))
        return BodyAssets(chunk_images=tuple(chunk_images))

    # ── compose_frame ─────────────────────────────────────────────────────

    def compose_frame(
        self,
        t: float,
        ctx: RenderContext,
        header: np.ndarray,
        body: BodyAssets,
        line_timings: tuple[LineTiming, ...],
    ) -> np.ndarray:
        """Return one RGBA frame for time *t*.

        Reproduces the karaoke pop-in / fade-out logic from
        ``make_combined_frame`` (``body_style == "karaoke"``,
        ``card_style == "custom"`` branch).

        The frame is RGBA, shape ``(H, W, 4)``, dtype ``uint8`` (Req 4.1).
        """
        W = ctx.canvas.width
        H = ctx.canvas.height

        # Derive title_duration from line_timings: it's the start time of the
        # first body line timing entry (or 0 if empty).  In the plugin
        # architecture, LineTiming.start values are absolute video times, so
        # the first entry's start approximates when the body begins.
        title_duration = line_timings[0].start if line_timings else 0.0

        # Total card duration = end of last timing entry.
        if line_timings:
            total_card_dur = line_timings[-1].end
        else:
            total_card_dur = title_duration

        # ── Layout ────────────────────────────────────────────────────────
        DISPLAY_W = int(W * self.CARD_WIDTH_PCT)
        h_scale = DISPLAY_W / header.shape[1]
        HEADER_DISP_H = int(header.shape[0] * h_scale)

        HEADER_Y_START = int(H * self.HEADER_Y_START)
        HEADER_Y_END   = int(H * self.HEADER_Y_END)

        # ── RGBA canvas ───────────────────────────────────────────────────
        frame = np.zeros((H, W, 4), dtype=np.uint8)

        # ── Header with pop-in + drift up ─────────────────────────────────
        h_alpha = self._header_alpha(t, title_duration)
        if h_alpha > 0:
            scale = header_pop_zoom_scale(
                t, total_card_dur, self.POP_DUR, self.ZOOM_AMOUNT
            )
            cur_w = max(1, int(DISPLAY_W * scale))
            cur_h = max(1, int(HEADER_DISP_H * scale))
            h_pil = Image.fromarray(header).resize((cur_w, cur_h), Image.LANCZOS)
            h_arr = np.array(h_pil)

            x = (W - cur_w) // 2
            slide_progress = min(1.0, t / max(0.001, total_card_dur))
            base_y = int(HEADER_Y_START + (HEADER_Y_END - HEADER_Y_START) * slide_progress)
            base_center_y = base_y + HEADER_DISP_H // 2
            y_off = base_center_y - cur_h // 2

            # Alpha composite header onto frame.
            src_y = max(0, -y_off)
            dst_y = max(0, y_off)
            src_x = max(0, -x)
            dst_x = max(0, x)
            ph = min(cur_h - src_y, H - dst_y)
            pw = min(cur_w - src_x, W - dst_x)
            if ph > 0 and pw > 0:
                h_slice = h_arr[src_y:src_y + ph, src_x:src_x + pw]
                a = h_slice[:, :, 3:4].astype(np.float32) / 255.0 * h_alpha
                bg = frame[dst_y:dst_y + ph, dst_x:dst_x + pw, :3].astype(np.float32)
                rgb = h_slice[:, :, :3].astype(np.float32)
                blended_rgb = (rgb * a + bg * (1 - a)).astype(np.uint8)
                blended_a = np.maximum(
                    frame[dst_y:dst_y + ph, dst_x:dst_x + pw, 3],
                    (h_slice[:, :, 3].astype(np.float32) * h_alpha).astype(np.uint8),
                )
                frame[dst_y:dst_y + ph, dst_x:dst_x + pw, :3] = blended_rgb
                frame[dst_y:dst_y + ph, dst_x:dst_x + pw, 3] = blended_a

        # ── Karaoke body: one chunk at a time, centred on screen ──────────
        if t >= title_duration and line_timings:
            line_timings_list = list(line_timings)

            # Find the active chunk: last one whose absolute start <= t.
            active_idx: int | None = None
            for li, lt in enumerate(line_timings_list):
                if t >= lt.start:
                    active_idx = li

            if active_idx is not None and active_idx < len(body.chunk_images):
                lt = line_timings_list[active_idx]
                k_arr = body.chunk_images[active_idx].copy()
                kh, kw = k_arr.shape[:2]

                # Centre horizontally, place at KARAOKE_Y_PCT down the screen.
                bx = max(0, (W - kw) // 2)
                by = int(H * self.KARAOKE_Y_PCT) - kh // 2
                by = max(0, min(by, H - kh))

                a2 = k_arr[:, :, 3:4].astype(np.float32) / 255.0
                ph2 = min(kh, H - by)
                pw2 = min(kw, W - bx)
                if ph2 > 0 and pw2 > 0:
                    k_slice = k_arr[:ph2, :pw2]
                    bg2 = frame[by:by + ph2, bx:bx + pw2, :3].astype(np.float32)
                    a2_slice = a2[:ph2, :pw2]
                    blended_rgb2 = (
                        k_slice[:, :, :3].astype(np.float32) * a2_slice
                        + bg2 * (1 - a2_slice)
                    ).astype(np.uint8)
                    blended_a2 = np.maximum(
                        frame[by:by + ph2, bx:bx + pw2, 3],
                        k_slice[:, :, 3],
                    )
                    frame[by:by + ph2, bx:bx + pw2, :3] = blended_rgb2
                    frame[by:by + ph2, bx:bx + pw2, 3] = blended_a2

        return frame

    # ── Private helpers ───────────────────────────────────────────────────

    def _header_alpha(self, t: float, title_duration: float) -> float:
        """Return header opacity at time *t*.

        1.0 while the title is playing; fades to 0 over ``HEADER_DISMISS_DUR``
        once the body starts.  For the karaoke style the header is always
        shown (no ``dismiss_title_on_body`` option), so it fades naturally.
        """
        if t < title_duration:
            return 1.0
        elapsed = t - title_duration
        if elapsed >= self.HEADER_DISMISS_DUR:
            return 0.0
        return 1.0 - elapsed / self.HEADER_DISMISS_DUR
