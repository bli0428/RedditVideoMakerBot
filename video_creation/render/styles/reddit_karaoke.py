"""RedditKaraokeStyle — reddit header + karaoke body plugin.

Implements the Reddit-style header natively (no ``_RedditStyleCard`` delegation
or temp-file round-trips) and uses ``styles.shared.captions._render_karaoke_line``
for the karaoke body.

The ``compose_frame`` method implements the ``_header_alpha`` dismiss logic:
when ``dismiss_title_on_body=True``, the header fades from 1.0 to 0.0 over
``HEADER_DISMISS_DUR`` seconds after ``title_duration``.

Satisfies: Requirements 4.1, 5.1, 5.2, 7.1, 7.4, 7.6, 11.1, 11.2
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
from video_creation.render.styles.shared.emoji_row import _render_award_row
from video_creation.render.styles.shared.fonts import (
    FONT_BLACK,
    FONT_MEDIUM,
    _load_font,
)
from video_creation.render.styles.shared.icons import (
    _draw_bubble,
    _draw_heart,
    _make_checkmark,
)
from video_creation.render.styles.shared.text import (
    _format_count,
    _text_size,
    _wrap,
)
from video_creation.render.styles import register_style
from video_creation.render.timing.models import LineTiming


@register_style
class RedditKaraokeStyle(CardStylePlugin):
    """Reddit-style header with karaoke (one-chunk-at-a-time) body.

    The header is rendered natively with PIL — no temp files, no delegation
    to ``_RedditStyleCard`` (Req 5.1).  The body produces one RGBA ndarray
    per ``LineTiming`` entry via ``_render_karaoke_line`` (Req 5.2).

    Layout constants are class-level (Req 11.1, 11.2).
    No module-level constants are shared with other plugins (Req 12.2).
    No cross-plugin imports (Req 12.3).
    """

    style_id = "reddit-karaoke"
    options_schema: Mapping[str, type] = {
        "theme": str,
        "karaoke_words_per_chunk": int,
        "dismiss_title_on_body": bool,
    }

    # ── Layout constants (class-level, Req 11.1) ─────────────────────────
    # Card display width as a fraction of the canvas width.
    CARD_WIDTH_PCT: float = 0.85

    # Header vertical positions (fraction of canvas height).
    HEADER_Y_START: float = 0.12   # starting y (fraction)
    HEADER_Y_END: float = 0.11

    # Pop-in animation duration (seconds).
    POP_DUR: float = 0.25

    # Fractional zoom applied to the header after the pop-in.
    ZOOM_AMOUNT: float = 0.0   # no zoom after pop-in

    # Duration (seconds) over which the header fades out once the body starts.
    HEADER_DISMISS_DUR: float = 0.4

    # Vertical centre of the karaoke caption as a fraction of canvas height.
    KARAOKE_Y_PCT: float = 0.60

    # Duration (seconds) of the fade-out at the end of each karaoke chunk.
    FADE_OUT_DUR: float = 0.15

    # ── Reddit-style header palette (mirrors _RedditStyleCard) ────────────
    _HEADER_BG      = "#FFFFFF"
    _HEADER_BORDER  = "#CFD9DE"
    _HEADER_TEXT    = "#0F1419"
    _HEADER_META    = "#536471"
    _HEADER_RADIUS  = 24
    _HEADER_BORDER_W = 2
    _HEADER_INSET   = 6
    _HEADER_PAD     = 44

    # ── Constructor ───────────────────────────────────────────────────────

    def __init__(self, options: Mapping[str, Any], canvas: Any) -> None:
        super().__init__(options, canvas)

    # ── Header ────────────────────────────────────────────────────────────

    def render_header(self, ctx: RenderContext) -> np.ndarray:
        """Render the Reddit-style header card natively and return an RGBA ndarray.

        Implements the same layout as ``_RedditStyleCard._render_header()``:
        circular avatar, @u/author handle, verified checkmark, award emoji row,
        bold post title, heart/comment counts.  No temp files are written
        (Req 5.1).

        Args:
            ctx: Frozen render context with post metadata and canvas spec.

        Returns:
            numpy.ndarray of shape ``(H, W, 4)``, dtype ``uint8``, RGBA.
        """
        W = ctx.canvas.width
        # Determine display width based on content length (mirrors final_video logic)
        title_len = len(ctx.title)
        text_len = len(ctx.body_text)
        total_content_len = title_len + text_len
        if total_content_len < 300:
            card_width_pct = 0.90
        elif total_content_len < 600:
            card_width_pct = 0.85
        elif total_content_len < 900:
            card_width_pct = 0.78
        else:
            card_width_pct = 0.72
        card_w = int(W * card_width_pct)

        img = self._render_reddit_header_pil(
            title=ctx.title,
            author=ctx.author,
            avatar_url=ctx.avatar_url,
            upvotes=ctx.upvotes,
            num_comments=ctx.num_comments,
            width=card_w,
        )
        return np.array(img.convert("RGBA"))

    @classmethod
    def _render_reddit_header_pil(
        cls,
        title: str,
        author: str,
        avatar_url: str,
        upvotes: int,
        num_comments: int,
        width: int,
    ) -> Image.Image:
        """Draw the Reddit-style header card and return a PIL RGBA Image.

        This is a class method so it can be called without a plugin instance
        (e.g., from tests).  The layout mirrors ``_RedditStyleCard._render_header``
        exactly: avatar circle, @u/author, verified checkmark, award emoji row,
        bold title, heart/comment counts.

        Args:
            title:        Post title text.
            author:       Reddit username (no u/ prefix).
            avatar_url:   URL to the author's avatar image.
            upvotes:      Upvote / like count.
            num_comments: Comment count.
            width:        Card width in pixels.

        Returns:
            RGBA ``PIL.Image``.
        """
        pad = cls._HEADER_PAD
        w = width

        handle_font = _load_font(FONT_BLACK, 32)
        title_font  = _load_font(FONT_BLACK, 54)
        count_font  = _load_font(FONT_MEDIUM, 28)

        avatar_size = 88
        check_size  = 26
        icon_size   = 28
        gap         = 22   # vertical gap between rows

        dummy_draw = ImageDraw.Draw(Image.new("RGBA", (1, 1)))

        # Avatar (may be None)
        avatar = _download_avatar(avatar_url, avatar_size)

        # Handle text
        handle_text = f"@u/{author}"
        handle_w, handle_h = _text_size(dummy_draw, handle_text, handle_font)

        # Title lines — wrap to pixel width
        title_lines = _wrap(title, title_font, w - pad * 2) if title else []
        _, title_lh = _text_size(dummy_draw, "Ag", title_font)
        title_block_h = len(title_lines) * (title_lh + 6) if title_lines else 0

        # Row heights
        row_a_h = avatar_size if avatar else handle_h + 8   # avatar / handle row
        row_awards_h = 40                                    # emoji award row
        row_b_h = title_block_h
        row_c_h = icon_size + 8                              # counts row

        content_h = row_a_h + gap + row_awards_h + gap + row_b_h + gap + row_c_h
        card_h    = pad + content_h + pad

        # Canvas
        img  = Image.new("RGBA", (w, card_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        draw.rounded_rectangle(
            [cls._HEADER_INSET, cls._HEADER_INSET,
             w - cls._HEADER_INSET, card_h - cls._HEADER_INSET],
            radius=cls._HEADER_RADIUS,
            fill=cls._HEADER_BG,
            outline=cls._HEADER_BORDER,
            width=cls._HEADER_BORDER_W,
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
        draw.text((text_x, handle_y), handle_text, font=handle_font, fill=cls._HEADER_TEXT)

        # Checkmark immediately after handle text
        check_x = text_x + handle_w + 8
        check_y = handle_y + (handle_h - check_size) // 2
        checkmark = _make_checkmark(check_size)
        img.paste(checkmark, (check_x, check_y), checkmark)

        y += row_a_h + gap

        # ── Award emoji row ───────────────────────────────────────────────
        award_img = _render_award_row(row_awards_h)
        img.paste(award_img, (pad, y), award_img)
        y += row_awards_h + gap

        # ── Row B: title ──────────────────────────────────────────────────
        for line in title_lines:
            draw.text((pad, y), line, font=title_font, fill=cls._HEADER_TEXT)
            y += title_lh + 6

        y += gap

        # ── Row C: heart count + bubble count ─────────────────────────────
        heart_label   = _format_count(upvotes)   if upvotes   else "99+"
        comment_label = _format_count(num_comments) if num_comments else "99+"

        # Heart icon
        _draw_heart(draw, x + icon_size // 2, y + icon_size // 4, icon_size // 2, cls._HEADER_META)
        count_x = x + icon_size + 8
        _, count_h = _text_size(dummy_draw, heart_label, count_font)
        count_y = y + (icon_size - count_h) // 2
        draw.text((count_x, count_y), heart_label, font=count_font, fill=cls._HEADER_META)

        count_w, _ = _text_size(dummy_draw, heart_label, count_font)
        bubble_x = count_x + count_w + 36

        # Speech bubble icon
        _draw_bubble(draw, bubble_x, y, icon_size, cls._HEADER_META)
        draw.text(
            (bubble_x + icon_size + 8, count_y),
            comment_label,
            font=count_font,
            fill=cls._HEADER_META,
        )

        return img

    # ── Body ──────────────────────────────────────────────────────────────

    def render_body(
        self,
        ctx: RenderContext,
        line_timings: tuple[LineTiming, ...],
    ) -> BodyAssets:
        """Pre-render one karaoke caption image per ``LineTiming`` entry.

        Each image is an RGBA ndarray produced by ``_render_karaoke_line``
        (Req 5.2).  The images are stored in ``BodyAssets.chunk_images``.
        No temp files are written.
        """
        chunk_images: list[np.ndarray] = []
        for lt in line_timings:
            pil_img = _render_karaoke_line(lt.text)
            chunk_images.append(np.array(pil_img.convert("RGBA")))

        return BodyAssets(chunk_images=tuple(chunk_images))

    # ── Per-frame composition ─────────────────────────────────────────────

    def compose_frame(
        self,
        t: float,
        ctx: RenderContext,
        header: np.ndarray,
        body: BodyAssets,
        line_timings: tuple[LineTiming, ...],
    ) -> np.ndarray:
        """Return one RGBA frame for time *t* (Req 4.1).

        Composites:
        1. Reddit-style header with pop-in + drift-up animation, plus optional
           dismiss fade (``dismiss_title_on_body``).
        2. Karaoke caption centred at ``KARAOKE_Y_PCT`` of the canvas height,
           with pop-in and fade-out transitions.

        The alpha channel of the returned frame doubles as the MoviePy mask
        (Req 4.2).  There is no separate ``compose_mask`` (Req 4.3).
        """
        W = ctx.canvas.width
        H = ctx.canvas.height

        # RGBA output frame (transparent background)
        frame = np.zeros((H, W, 4), dtype=np.uint8)

        # Derive title_duration from line_timings: it's the start of the first
        # body line timing entry (i.e. when the body audio begins).
        title_duration: float = line_timings[0].start if line_timings else 0.0

        # Total card animation duration (title + all body chunks)
        total_card_dur: float = (
            line_timings[-1].end if line_timings else title_duration
        )

        # ── Header alpha (dismiss logic, Req 7.6) ────────────────────────
        dismiss = bool(self.options.get("dismiss_title_on_body", False))
        h_alpha = self._header_alpha(t, title_duration, dismiss)

        # ── 1. Composite header ───────────────────────────────────────────
        if h_alpha > 0:
            # Determine display width based on content length
            title_len = len(ctx.title)
            text_len = len(ctx.body_text)
            total_content_len = title_len + text_len
            if total_content_len < 300:
                card_width_pct = 0.90
            elif total_content_len < 600:
                card_width_pct = 0.85
            elif total_content_len < 900:
                card_width_pct = 0.78
            else:
                card_width_pct = 0.72

            DISPLAY_W = int(W * card_width_pct)
            h_scale = DISPLAY_W / header.shape[1]
            HEADER_DISP_H = int(header.shape[0] * h_scale)

            scale = header_pop_zoom_scale(
                t,
                total_dur=total_card_dur,
                pop_dur=self.POP_DUR,
                zoom_amount=self.ZOOM_AMOUNT,
            )
            cur_w = max(1, int(DISPLAY_W * scale))
            cur_h = max(1, int(HEADER_DISP_H * scale))

            h_pil = Image.fromarray(header).resize((cur_w, cur_h), Image.LANCZOS)
            h_arr = np.array(h_pil)

            # Apply dismiss alpha to the header's alpha channel
            if h_alpha < 1.0:
                h_arr = h_arr.copy()
                h_arr[:, :, 3] = (
                    h_arr[:, :, 3].astype(np.float32) * h_alpha
                ).astype(np.uint8)

            x = (W - cur_w) // 2
            slide_progress = min(1.0, t / max(0.001, total_card_dur))
            base_y_start = int(H * self.HEADER_Y_START)
            base_y_end = int(H * self.HEADER_Y_END)
            base_y = int(base_y_start + (base_y_end - base_y_start) * slide_progress)
            base_center_y = base_y + HEADER_DISP_H // 2
            y_off = base_center_y - cur_h // 2

            src_y = max(0, -y_off)
            dst_y = max(0, y_off)
            src_x = max(0, -x)
            dst_x = max(0, x)
            ph = min(cur_h - src_y, H - dst_y)
            pw = min(cur_w - src_x, W - dst_x)

            if ph > 0 and pw > 0:
                src_region = h_arr[src_y:src_y + ph, src_x:src_x + pw]
                dst_region = frame[dst_y:dst_y + ph, dst_x:dst_x + pw]

                src_alpha = src_region[:, :, 3:4].astype(np.float32) / 255.0
                src_rgb   = src_region[:, :, :3].astype(np.float32)
                dst_rgb   = dst_region[:, :, :3].astype(np.float32)
                dst_alpha = dst_region[:, :, 3:4].astype(np.float32) / 255.0

                out_alpha = src_alpha + dst_alpha * (1.0 - src_alpha)
                safe_alpha = np.where(out_alpha > 0, out_alpha, 1.0)
                out_rgb = (
                    src_rgb * src_alpha + dst_rgb * dst_alpha * (1.0 - src_alpha)
                ) / safe_alpha

                frame[dst_y:dst_y + ph, dst_x:dst_x + pw, :3] = np.clip(out_rgb, 0, 255).astype(np.uint8)
                frame[dst_y:dst_y + ph, dst_x:dst_x + pw, 3] = np.clip(
                    out_alpha[:, :, 0] * 255, 0, 255
                ).astype(np.uint8)

        # ── 2. Composite karaoke body ─────────────────────────────────────
        if line_timings and t >= title_duration:
            t_body = t - title_duration

            # Find the active chunk: last entry whose start <= t_body
            active_idx: int | None = None
            for li, lt in enumerate(line_timings):
                if t_body >= lt.start:
                    active_idx = li

            if active_idx is not None and active_idx < len(body.chunk_images):
                lt = line_timings[active_idx]
                k_arr = body.chunk_images[active_idx].copy()
                kh, kw = k_arr.shape[:2]

                # Pop-in: scale 80%→100% over POP_DUR from chunk start
                elapsed = t_body - lt.start
                if elapsed < self.POP_DUR:
                    pop_p = elapsed / self.POP_DUR
                    pop_s = 0.8 + 0.2 * (1.0 - (1.0 - pop_p) ** 4)
                    nw = max(1, int(kw * pop_s))
                    nh = max(1, int(kh * pop_s))
                    k_pil = Image.fromarray(k_arr).resize((nw, nh), Image.LANCZOS)
                    k_arr = np.array(k_pil)
                    kh, kw = nh, nw

                # Fade-out: last FADE_OUT_DUR seconds before next chunk (or end)
                if active_idx + 1 < len(line_timings):
                    next_start = line_timings[active_idx + 1].start
                    time_left = next_start - t_body
                else:
                    time_left = lt.end - t_body

                if 0.0 <= time_left < self.FADE_OUT_DUR:
                    alpha_scale = time_left / self.FADE_OUT_DUR
                    k_arr = k_arr.copy()
                    k_arr[:, :, 3] = (
                        k_arr[:, :, 3].astype(np.float32) * alpha_scale
                    ).astype(np.uint8)

                # Centre horizontally; place at KARAOKE_Y_PCT down the screen
                bx = max(0, (W - kw) // 2)
                by = int(H * self.KARAOKE_Y_PCT) - kh // 2
                by = max(0, min(by, H - kh))

                src_y2 = max(0, -by)
                dst_y2 = max(0, by)
                src_x2 = max(0, -bx)
                dst_x2 = max(0, bx)
                ph2 = min(kh - src_y2, H - dst_y2)
                pw2 = min(kw - src_x2, W - dst_x2)

                if ph2 > 0 and pw2 > 0:
                    src_region2 = k_arr[src_y2:src_y2 + ph2, src_x2:src_x2 + pw2]
                    dst_region2 = frame[dst_y2:dst_y2 + ph2, dst_x2:dst_x2 + pw2]

                    src_alpha2 = src_region2[:, :, 3:4].astype(np.float32) / 255.0
                    src_rgb2   = src_region2[:, :, :3].astype(np.float32)
                    dst_rgb2   = dst_region2[:, :, :3].astype(np.float32)
                    dst_alpha2 = dst_region2[:, :, 3:4].astype(np.float32) / 255.0

                    out_alpha2 = src_alpha2 + dst_alpha2 * (1.0 - src_alpha2)
                    safe_alpha2 = np.where(out_alpha2 > 0, out_alpha2, 1.0)
                    out_rgb2 = (
                        src_rgb2 * src_alpha2 + dst_rgb2 * dst_alpha2 * (1.0 - src_alpha2)
                    ) / safe_alpha2

                    frame[dst_y2:dst_y2 + ph2, dst_x2:dst_x2 + pw2, :3] = np.clip(out_rgb2, 0, 255).astype(np.uint8)
                    frame[dst_y2:dst_y2 + ph2, dst_x2:dst_x2 + pw2, 3] = np.clip(
                        out_alpha2[:, :, 0] * 255, 0, 255
                    ).astype(np.uint8)

        return frame

    # ── Private helpers ───────────────────────────────────────────────────

    def _header_alpha(
        self,
        t: float,
        title_duration: float,
        dismiss: bool,
    ) -> float:
        """Return the header opacity at time *t* (Req 7.6).

        Returns 1.0 while the title is playing.  When ``dismiss`` is True,
        fades linearly from 1.0 to 0.0 over ``HEADER_DISMISS_DUR`` seconds
        after ``title_duration``.
        """
        if not dismiss or t < title_duration:
            return 1.0
        elapsed = t - title_duration
        if elapsed >= self.HEADER_DISMISS_DUR:
            return 0.0
        return 1.0 - elapsed / self.HEADER_DISMISS_DUR

    def _header_scale(self, t: float, total_card_dur: float) -> float:
        """Return the header scale factor at time *t*.

        Implements the same pop-in + slow-zoom curve as the other plugins.
        Delegates to ``header_pop_zoom_scale`` from ``styles.shared.animation``.
        """
        return header_pop_zoom_scale(
            t,
            total_dur=total_card_dur,
            pop_dur=self.POP_DUR,
            zoom_amount=self.ZOOM_AMOUNT,
        )
