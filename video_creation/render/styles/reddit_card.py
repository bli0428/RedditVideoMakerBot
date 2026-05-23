"""RedditCardStyle — ``reddit-card`` plugin.

Twitter/X-style Reddit card: circular avatar, @u/author handle, verified
checkmark, award emoji row, bold post title, heart/comment counts.
Body: paginated card pages revealed line-by-line with a smooth scroll mask.

All rendering is done natively with PIL — no temp files, no delegation to
``utils.card._RedditStyleCard``.

Satisfies: Requirements 4.1, 5.1, 5.2, 7.1, 11.1, 11.2
"""

from __future__ import annotations

import random
from typing import Any, List, Mapping, Tuple

import numpy as np
from PIL import Image, ImageDraw

from video_creation.render.compositor.blend import composite_rgba_onto
from video_creation.render.context import RenderContext
from video_creation.render.styles.base import BodyAssets, CardStylePlugin
from video_creation.render.styles.shared.animation import header_pop_zoom_scale
from video_creation.render.styles.shared.avatar import _download_avatar
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

# Lines of body text shown per paginated card page.
_LINES_PER_PAGE = 6


@register_style
class RedditCardStyle(CardStylePlugin):
    """Twitter/X-style Reddit card with paginated mask-reveal body.

    Header: circular avatar, @u/author, verified checkmark, award emoji row,
    bold post title, heart/comment counts.
    Body: paginated card pages revealed line-by-line with a smooth scroll mask.

    All rendering is native PIL — no PNG round-trips, no delegation to
    ``utils.card``.
    """

    style_id = "reddit-card"
    options_schema: Mapping[str, type] = {
        "theme": str,
        "dismiss_title_on_body": bool,
    }

    # ── Card palette ──────────────────────────────────────────────────────
    _BG       = "#FFFFFF"
    _BORDER   = "#CFD9DE"
    _TEXT     = "#0F1419"
    _META     = "#536471"
    _RADIUS   = 24
    _BORDER_W = 2
    _INSET    = 6
    _PADDING  = 44

    # ── Layout constants (class-level, Req 11.1, 11.2) ───────────────────
    #: Fraction of canvas width used for the displayed card (content-adaptive).
    CARD_WIDTH_PCT_SHORT  = 0.90   # total_content_len < 300
    CARD_WIDTH_PCT_MEDIUM = 0.85   # total_content_len < 600
    CARD_WIDTH_PCT_LONG   = 0.78   # total_content_len < 900
    CARD_WIDTH_PCT_XLONG  = 0.72   # total_content_len >= 900

    #: Vertical start position of the header (fraction of canvas height).
    HEADER_Y_START_FRAC: float = 0.12

    #: Vertical end position of the header after drift (fraction of canvas height).
    HEADER_Y_END_FRAC: float = 0.10

    #: Vertical position of the body card (fraction of canvas height).
    BODY_Y_FRAC: float = 0.55

    #: Duration of the header pop-in animation in seconds.
    POP_DUR: float = 0.25

    #: Duration of the mask-reveal scroll per line in seconds.
    SCROLL_TIME: float = 0.3

    #: Fractional zoom applied to the header over the full card duration.
    ZOOM_AMOUNT: float = 0.0   # no zoom after pop-in

    #: Duration of the header dismiss fade-out in seconds.
    HEADER_DISMISS_DUR: float = 0.4

    # ── Initialisation ────────────────────────────────────────────────────

    def __init__(self, options: Mapping[str, Any], canvas: Any) -> None:
        super().__init__(options, canvas)
        self._theme: str = options.get("theme", "light")
        self._dismiss_title_on_body: bool = bool(
            options.get("dismiss_title_on_body", False)
        )

    # ── Internal helpers ──────────────────────────────────────────────────

    def _card_width_pct(self, ctx: RenderContext) -> float:
        """Return the display-width fraction based on content length."""
        total = len(ctx.title) + len(ctx.body_text)
        if total < 300:
            return self.CARD_WIDTH_PCT_SHORT
        if total < 600:
            return self.CARD_WIDTH_PCT_MEDIUM
        if total < 900:
            return self.CARD_WIDTH_PCT_LONG
        return self.CARD_WIDTH_PCT_XLONG

    def _body_font(self):
        return _load_font(FONT_MEDIUM, 36)

    # ── CardStylePlugin interface ─────────────────────────────────────────

    def render_header(self, ctx: RenderContext) -> np.ndarray:
        """Render the Reddit-style header card natively and return an RGBA ndarray.

        Draws: circular avatar, @u/author handle, verified checkmark, award
        emoji row, bold post title (word-wrapped), heart/comment counts.

        Args:
            ctx: Frozen render context with post metadata and canvas spec.

        Returns:
            numpy.ndarray of shape ``(H, W, 4)``, dtype ``uint8``, RGBA.
        """
        pad = self._PADDING
        w   = int(ctx.canvas.width * self._card_width_pct(ctx))

        handle_font = _load_font(FONT_BLACK,  32)
        title_font  = _load_font(FONT_BLACK,  54)
        count_font  = _load_font(FONT_MEDIUM, 28)

        avatar_size = 88
        check_size  = 26
        icon_size   = 28
        gap         = 22   # vertical gap between rows

        dummy_draw = ImageDraw.Draw(Image.new("RGBA", (1, 1)))

        # Avatar (may be None)
        avatar = _download_avatar(ctx.avatar_url, avatar_size)

        # Handle text
        handle_text = f"@u/{ctx.author}"
        handle_w, handle_h = _text_size(dummy_draw, handle_text, handle_font)

        # Title lines — wrap to pixel width
        title_lines = _wrap(ctx.title, title_font, w - pad * 2) if ctx.title else []
        _, title_lh = _text_size(dummy_draw, "Ag", title_font)
        title_block_h = len(title_lines) * (title_lh + 6) if title_lines else 0

        # Row heights
        row_a_h      = avatar_size if avatar else handle_h + 8
        row_awards_h = 40
        row_b_h      = title_block_h
        row_c_h      = icon_size + 8

        content_h = row_a_h + gap + row_awards_h + gap + row_b_h + gap + row_c_h
        card_h    = pad + content_h + pad

        img  = Image.new("RGBA", (w, card_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        draw.rounded_rectangle(
            [self._INSET, self._INSET, w - self._INSET, card_h - self._INSET],
            radius=self._RADIUS, fill=self._BG,
            outline=self._BORDER, width=self._BORDER_W,
        )

        # ── Row A: avatar + handle + checkmark ────────────────────────────
        y = pad
        x = pad

        if avatar:
            img.paste(avatar, (x, y), avatar)
            text_x = x + avatar_size + 18
        else:
            text_x = x

        handle_y = y + (avatar_size - handle_h) // 2 if avatar else y
        draw.text((text_x, handle_y), handle_text, font=handle_font, fill=self._TEXT)

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
            draw.text((pad, y), line, font=title_font, fill=self._TEXT)
            y += title_lh + 6

        y += gap

        # ── Row C: heart count + bubble count ─────────────────────────────
        heart_label   = _format_count(ctx.upvotes)      if ctx.upvotes      else "99+"
        comment_label = _format_count(ctx.num_comments) if ctx.num_comments else "99+"

        _draw_heart(draw, x + icon_size // 2, y + icon_size // 4, icon_size // 2, self._META)
        count_x = x + icon_size + 8
        _, count_h = _text_size(dummy_draw, heart_label, count_font)
        count_y = y + (icon_size - count_h) // 2
        draw.text((count_x, count_y), heart_label, font=count_font, fill=self._META)

        count_w, _ = _text_size(dummy_draw, heart_label, count_font)
        bubble_x = count_x + count_w + 36

        _draw_bubble(draw, bubble_x, y, icon_size, self._META)
        draw.text((bubble_x + icon_size + 8, count_y), comment_label, font=count_font, fill=self._META)

        return np.array(img.convert("RGBA"))

    def render_body(
        self,
        ctx: RenderContext,
        line_timings: tuple[LineTiming, ...],
    ) -> BodyAssets:
        """Render all body pages natively and return them as RGBA ndarrays.

        Draws paginated rounded-rect body cards with body text.  Line position
        metadata is stored in ``BodyAssets.extra`` for use by ``compose_frame``.

        Args:
            ctx:          Frozen render context.
            line_timings: Per-line timing entries from ``TimingEngine``.

        Returns:
            ``BodyAssets`` with ``pages`` populated (one RGBA ndarray per page)
            and ``extra["line_positions"]`` / ``extra["page_line_positions"]``.
        """
        pad  = self._PADDING
        w    = int(ctx.canvas.width * self._card_width_pct(ctx))
        font = self._body_font()

        body_lines = _wrap(ctx.body_text, font, w - pad * 2)

        pages: List[np.ndarray] = []
        all_line_positions: List[dict] = []
        page_line_positions: List[List[dict]] = []

        dummy_draw = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
        _, lh = _text_size(dummy_draw, "Ag", font)
        spacing = int(lh * 0.5)

        for page_start in range(0, max(1, len(body_lines)), _LINES_PER_PAGE):
            chunk = body_lines[page_start: page_start + _LINES_PER_PAGE]
            img, positions = self._render_body_page(chunk, w, pad, font, lh, spacing)
            pages.append(np.array(img.convert("RGBA")))
            all_line_positions.extend(positions)
            page_line_positions.append(positions)

        return BodyAssets(
            pages=tuple(pages),
            extra={
                "line_positions": all_line_positions,
                "page_line_positions": page_line_positions,
            },
        )

    def _render_body_page(
        self,
        page_lines: List[str],
        w: int,
        pad: int,
        font,
        lh: int,
        spacing: int,
    ) -> Tuple[Image.Image, List[dict]]:
        """Draw one body page and return ``(image, line_positions)``."""
        content_h = len(page_lines) * (lh + spacing)
        h = pad + content_h + pad

        img  = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.rounded_rectangle(
            [self._INSET, self._INSET, w - self._INSET, h - self._INSET],
            radius=self._RADIUS, fill=self._BG,
            outline=self._BORDER, width=self._BORDER_W,
        )

        y = pad
        positions: List[dict] = []
        for line in page_lines:
            draw.text((pad, y), line, font=font, fill=self._TEXT)
            positions.append({"text": line, "y_top": y, "y_bottom": y + lh + spacing})
            y += lh + spacing

        return img, positions

    def compose_frame(
        self,
        t: float,
        ctx: RenderContext,
        header: np.ndarray,
        body: BodyAssets,
        line_timings: tuple[LineTiming, ...],
    ) -> np.ndarray:
        """Compose one RGBA frame for time *t*.

        Implements the card-mode mask-reveal composition:
        - Header: pop-in (80%→100%) + slow upward drift + optional dismiss fade.
        - Body: paginated card pages revealed line-by-line with a smooth scroll
          mask (cubic ease-out).

        Uses ``composite_rgba_onto`` from ``compositor/blend.py`` (Req 4.1).

        Args:
            t:            Current playback time in seconds.
            ctx:          Frozen render context.
            header:       Pre-rendered header RGBA ndarray.
            body:         Pre-rendered body assets from ``render_body``.
            line_timings: Per-line timing entries.

        Returns:
            numpy.ndarray of shape ``(H, W, 4)``, dtype ``uint8``, RGBA.
            The alpha channel doubles as the MoviePy mask (Req 4.2).
        """
        W = ctx.canvas.width
        H = ctx.canvas.height
        opacity = ctx.canvas.opacity

        # ── Derive layout from content length ─────────────────────────────
        card_width_pct = self._card_width_pct(ctx)
        DISPLAY_W = int(W * card_width_pct)

        h_scale = DISPLAY_W / header.shape[1]
        HEADER_DISP_H = int(header.shape[0] * h_scale)

        # Stable per-render jitter derived from context (deterministic)
        _jitter_seed = hash((ctx.title, ctx.author)) & 0xFFFF
        _rng = random.Random(_jitter_seed)
        y_var = _rng.randint(-30, 30)

        HEADER_Y_START = int(H * self.HEADER_Y_START_FRAC) + y_var
        HEADER_Y_END   = int(H * self.HEADER_Y_END_FRAC)   + y_var
        BODY_Y         = int(H * self.BODY_Y_FRAC)          + y_var

        # ── Timing ────────────────────────────────────────────────────────
        title_dur = line_timings[0].start if line_timings else 0.0
        total_card_dur = line_timings[-1].end if line_timings else max(t, 1.0)

        # ── Build page timing structures ───────────────────────────────────
        page_line_positions: List[List[dict]] = (
            body.extra.get("page_line_positions", []) if body.extra else []
        )
        page_imgs = list(body.pages)

        page_line_timings: List[List[dict]] = [[] for _ in page_imgs]
        lt_list2 = list(line_timings)
        lt_idx2 = 0
        for pi, page_positions in enumerate(page_line_positions):
            for pos in page_positions:
                if lt_idx2 >= len(lt_list2):
                    break
                lt = lt_list2[lt_idx2]
                page_line_timings[pi].append({
                    "text":    lt.text,
                    "y_top":   pos["y_top"],
                    "y_bottom": pos["y_bottom"],
                    "start":   lt.start,
                    "end":     lt.end,
                })
                lt_idx2 += 1

        def _get_active_page_and_mask(t_body: float) -> Tuple[int, int, int]:
            """Return (page_index, mask_bottom, mask_start) for body time t_body."""
            active_page = 0
            for pi, plt in enumerate(page_line_timings):
                if plt and t >= plt[0]["start"]:
                    active_page = pi

            plt = page_line_timings[active_page]
            bp_positions = (
                page_line_positions[active_page]
                if active_page < len(page_line_positions)
                else plt
            )
            mask_start = bp_positions[0]["y_top"] if bp_positions else 0
            bottom = mask_start
            for lt_d in plt:
                if t >= lt_d["start"]:
                    elapsed  = t - lt_d["start"]
                    progress = min(1.0, elapsed / self.SCROLL_TIME)
                    eased    = 1 - (1 - progress) ** 3
                    line_bottom = lt_d["y_top"] + (lt_d["y_bottom"] - lt_d["y_top"]) * eased
                    bottom = max(bottom, int(line_bottom))
            if page_imgs:
                page_h = page_imgs[active_page].shape[0]
                return active_page, min(bottom, page_h), mask_start
            return active_page, bottom, mask_start

        # ── Header alpha (dismiss fade) ────────────────────────────────────
        def _header_alpha(t_: float) -> float:
            if not self._dismiss_title_on_body or t_ < title_dur:
                return opacity
            elapsed = t_ - title_dur
            if elapsed >= self.HEADER_DISMISS_DUR:
                return 0.0
            return opacity * (1.0 - elapsed / self.HEADER_DISMISS_DUR)

        # ── Build RGBA frame ───────────────────────────────────────────────
        frame = np.zeros((H, W, 4), dtype=np.uint8)

        # ── Header: pop-in + drift up + optional dismiss ───────────────────
        h_alpha = _header_alpha(t)
        if h_alpha > 0:
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
            base_y = int(HEADER_Y_START + (HEADER_Y_END - HEADER_Y_START) * slide_progress)
            base_center_y = base_y + HEADER_DISP_H // 2
            y_off = base_center_y - cur_h // 2

            composite_rgba_onto(frame, h_arr, x, y_off)

        # ── Body: mask-reveal card pages ───────────────────────────────────
        if t >= title_dur and page_imgs:
            t_body = t - title_dur
            page_idx, mb, mask_start = _get_active_page_and_mask(t_body)

            if mb > mask_start and page_idx < len(page_imgs):
                cur_body = page_imgs[page_idx].copy()
                cur_body[mb:, :, 3] = 0  # mask out lines not yet revealed

                cur_h_b, cur_w_b = cur_body.shape[:2]
                disp_h = max(1, int(cur_h_b * (DISPLAY_W / cur_w_b)))
                b_pil = Image.fromarray(cur_body).resize((DISPLAY_W, disp_h), Image.LANCZOS)
                b_arr = np.array(b_pil)

                bx = (W - DISPLAY_W) // 2
                composite_rgba_onto(frame, b_arr, bx, BODY_Y)

        return frame
