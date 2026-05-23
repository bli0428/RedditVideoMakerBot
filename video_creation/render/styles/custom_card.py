"""CustomCardStyle — custom-card plugin with native PIL → numpy rendering.

Implements the ``CardStylePlugin`` interface for the clean minimal card style
(white rounded rectangle, avatar + username, title in header; paginated body
with mask-reveal scroll).  No PNG round-trip: all intermediate images are
produced in-memory and returned as RGBA ``numpy.ndarray``s.

Satisfies: Requirements 4.1, 5.1, 5.2, 7.1, 11.1, 11.2
"""

from __future__ import annotations

import random
from typing import Any, List, Mapping, Tuple

import numpy as np
from PIL import Image, ImageDraw

from video_creation.render.context import RenderContext
from video_creation.render.styles.base import BodyAssets, CardStylePlugin
from video_creation.render.styles import register_style
from video_creation.render.timing.models import LineTiming
from video_creation.render.compositor.blend import composite_rgba_onto
from video_creation.render.styles.shared.animation import header_pop_zoom_scale
from video_creation.render.styles.shared.fonts import (
    FONT_BOLD,
    FONT_MEDIUM,
    _load_font,
)
from video_creation.render.styles.shared.text import (
    _strip_emojis,
    _text_size,
    _wrap,
)
from video_creation.render.styles.shared.avatar import _download_avatar


@register_style
class CustomCardStyle(CardStylePlugin):
    """Custom-header + paginated-card-body visual treatment.

    Renders header and body natively using PIL and returns RGBA
    ``numpy.ndarray``s — no temporary PNG files are written.

    Class-level layout constants (Req 11.1, 11.2)
    -----------------------------------------------
    All layout constants are class-level; none are shared with other plugins.
    """

    # ── Plugin identity ────────────────────────────────────────────────────
    style_id = "custom-card"
    options_schema: Mapping[str, type] = {
        "theme": str,
        "dismiss_title_on_body": bool,
    }

    # ── Card visual constants ──────────────────────────────────────────────
    # Palette
    CARD_BG      = "#ffffff"
    CARD_BORDER  = "#e0e0e0"
    CARD_TEXT    = "#1a1a1a"
    CARD_META    = "#555555"
    CARD_RADIUS  = 20
    CARD_BORDER_W = 2
    CARD_INSET   = 8    # gap between canvas edge and rounded rect
    CARD_PADDING = 40   # inner padding

    # Font sizes
    TITLE_FONT_SIZE    = 36
    USERNAME_FONT_SIZE = 30
    BODY_FONT_SIZE     = 34
    AVATAR_SIZE        = 56

    # ── Layout constants (Req 11.1, 11.2) ─────────────────────────────────
    # Display width as a fraction of canvas width — chosen dynamically based
    # on content length, but bounded by these class-level defaults.
    CARD_WIDTH_PCT_SHORT  = 0.90   # total_content_len < 300
    CARD_WIDTH_PCT_MEDIUM = 0.85   # total_content_len < 600
    CARD_WIDTH_PCT_LONG   = 0.78   # total_content_len < 900
    CARD_WIDTH_PCT_XLONG  = 0.72   # total_content_len >= 900

    # Header vertical position (fraction of canvas height, before random jitter)
    HEADER_Y_START_FRAC = 0.12
    HEADER_Y_END_FRAC   = 0.10

    # Body vertical position (fraction of canvas height, before random jitter)
    BODY_Y_FRAC = 0.55

    # Animation timings (seconds)
    POP_DUR           = 0.25   # header pop-in duration
    SCROLL_TIME       = 0.3    # body mask-reveal scroll duration per line
    ZOOM_AMOUNT       = 0.0    # no zoom after pop-in
    HEADER_DISMISS_DUR = 0.4   # seconds to fade header out once body starts

    # Body pagination
    LINES_PER_PAGE = 6

    # ── Initialisation ─────────────────────────────────────────────────────

    def __init__(self, options: Mapping[str, Any], canvas: Any) -> None:
        super().__init__(options, canvas)
        # Resolved option values (with defaults)
        self._theme: str = options.get("theme", "light")
        self._dismiss_title_on_body: bool = bool(
            options.get("dismiss_title_on_body", False)
        )

    # ── Internal helpers ───────────────────────────────────────────────────

    def _card_width_pct(self, ctx: RenderContext) -> float:
        """Return the display-width fraction based on content length."""
        title_len = len(ctx.title)
        body_len  = len(ctx.body_text)
        total     = title_len + body_len
        if total < 300:
            return self.CARD_WIDTH_PCT_SHORT
        if total < 600:
            return self.CARD_WIDTH_PCT_MEDIUM
        if total < 900:
            return self.CARD_WIDTH_PCT_LONG
        return self.CARD_WIDTH_PCT_XLONG

    def _render_header_image(self, ctx: RenderContext) -> Image.Image:
        """Render the header card as a PIL RGBA Image (no disk I/O).

        Draws a white rounded rectangle with the author avatar, username,
        and post title — matching the visual output of
        ``_CustomCard._render_header``.
        """
        pad = self.CARD_PADDING
        w   = int(ctx.canvas.width * self._card_width_pct(ctx))

        title_font    = _load_font(FONT_BOLD,   self.TITLE_FONT_SIZE)
        username_font = _load_font(FONT_BOLD,   self.USERNAME_FONT_SIZE)
        avatar_size   = self.AVATAR_SIZE

        dummy_draw = ImageDraw.Draw(Image.new("RGBA", (1, 1)))

        clean_title  = _strip_emojis(ctx.title)
        clean_author = ctx.author

        title_lines = _wrap(clean_title, title_font, w - pad * 2) if clean_title else []
        _, title_lh = _text_size(dummy_draw, "Ag", title_font)

        avatar = _download_avatar(ctx.avatar_url, avatar_size)

        # Compute total height
        content_h = avatar_size + 15
        if title_lines:
            content_h += len(title_lines) * (title_lh + 8) + 10
        h = pad + content_h + pad

        img  = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.rounded_rectangle(
            [self.CARD_INSET, self.CARD_INSET, w - self.CARD_INSET, h - self.CARD_INSET],
            radius=self.CARD_RADIUS,
            fill=self.CARD_BG,
            outline=self.CARD_BORDER,
            width=self.CARD_BORDER_W,
        )

        y = pad
        if avatar:
            img.paste(avatar, (pad, y), avatar)

        username_x = pad + avatar_size + 16 if avatar else pad
        _, un_h = _text_size(dummy_draw, clean_author, username_font)
        username_y = y + (avatar_size - un_h) // 2 if avatar else y
        draw.text((username_x, username_y), clean_author, font=username_font, fill=self.CARD_META)

        y += avatar_size + 15
        for line in title_lines:
            draw.text((pad, y), line, font=title_font, fill=self.CARD_TEXT)
            y += title_lh + 8

        return img

    def _render_body_page_image(
        self,
        page_lines: List[str],
        card_width: int,
    ) -> Tuple[Image.Image, List[dict]]:
        """Render one body page as a PIL RGBA Image (no disk I/O).

        Returns ``(image, line_positions)`` where each entry in
        ``line_positions`` is ``{"text": str, "y_top": int, "y_bottom": int}``.
        Matches the visual output of ``_CustomCard._render_body_page``.
        """
        pad  = self.CARD_PADDING
        w    = card_width
        font = _load_font(FONT_MEDIUM, self.BODY_FONT_SIZE)

        dummy_draw = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
        _, lh = _text_size(dummy_draw, "Ag", font)
        spacing = int(lh * 0.6)

        content_h = len(page_lines) * (lh + spacing) + 30
        h = pad + content_h + pad

        img  = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.rounded_rectangle(
            [self.CARD_INSET, self.CARD_INSET, w - self.CARD_INSET, h - self.CARD_INSET],
            radius=self.CARD_RADIUS,
            fill=self.CARD_BG,
            outline=self.CARD_BORDER,
            width=self.CARD_BORDER_W,
        )

        y = pad
        positions: List[dict] = []
        for line in page_lines:
            draw.text((pad, y), line, font=font, fill=self.CARD_TEXT)
            positions.append({"text": line, "y_top": y, "y_bottom": y + lh + spacing})
            y += lh + spacing

        return img, positions

    # ── CardStylePlugin interface ──────────────────────────────────────────

    def render_header(self, ctx: RenderContext) -> np.ndarray:
        """Render the custom header card and return it as an RGBA ndarray.

        Draws the card natively using PIL — no temp PNG is written.

        Returns
        -------
        numpy.ndarray
            Shape ``(H, W, 4)``, dtype ``uint8``, RGBA.
        """
        img = self._render_header_image(ctx)
        return np.array(img.convert("RGBA"))

    def render_body(
        self,
        ctx: RenderContext,
        line_timings: tuple[LineTiming, ...],
    ) -> BodyAssets:
        """Render all body pages and return them as RGBA ndarrays.

        Draws each page natively using PIL — no temp PNGs are written.

        Returns
        -------
        BodyAssets
            ``pages``: one RGBA ndarray per page.
            ``extra``: ``{"line_positions": list[dict]}`` with ``y_top`` /
            ``y_bottom`` / ``text`` per line, and
            ``{"page_line_positions": list[list[dict]]}`` per page.
        """
        W = ctx.canvas.width
        card_width_pct = self._card_width_pct(ctx)
        display_w = int(W * card_width_pct)

        font = _load_font(FONT_MEDIUM, self.BODY_FONT_SIZE)
        body_lines = _wrap(
            _strip_emojis(ctx.body_text),
            font,
            display_w - self.CARD_PADDING * 2,
        )

        pages: list[np.ndarray] = []
        all_line_positions: list[dict] = []
        page_line_positions: list[list[dict]] = []

        for page_start in range(0, max(1, len(body_lines)), self.LINES_PER_PAGE):
            chunk = body_lines[page_start: page_start + self.LINES_PER_PAGE]
            img, positions = self._render_body_page_image(chunk, display_w)
            arr = np.array(img.convert("RGBA"))
            pages.append(arr)
            all_line_positions.extend(positions)
            page_line_positions.append(positions)

        extra: dict = {
            "line_positions": all_line_positions,
            "page_line_positions": page_line_positions,
        }
        return BodyAssets(pages=tuple(pages), extra=extra)

    def compose_frame(
        self,
        t: float,
        ctx: RenderContext,
        header: np.ndarray,
        body: BodyAssets,
        line_timings: tuple[LineTiming, ...],
    ) -> np.ndarray:
        """Return one RGBA frame for time *t*.

        Implements the mask-reveal card body logic plus the header pop-in /
        zoom / dismiss logic using ``composite_rgba_onto`` and
        ``header_pop_zoom_scale``.

        Returns
        -------
        numpy.ndarray
            Shape ``(H, W, 4)``, dtype ``uint8``, RGBA.
        """
        W = ctx.canvas.width
        H = ctx.canvas.height
        opacity = ctx.canvas.opacity

        # ── Derive layout from header image and canvas ─────────────────────
        card_width_pct = self._card_width_pct(ctx)
        DISPLAY_W = int(W * card_width_pct)

        h_scale = DISPLAY_W / header.shape[1]
        HEADER_DISP_H = int(header.shape[0] * h_scale)

        # Stable per-render jitter: use a hash of title+author for determinism
        # (same as the original code which used random.randint at setup time).
        _jitter_seed = hash((ctx.title, ctx.author)) & 0xFFFF
        _rng = random.Random(_jitter_seed)
        y_var = _rng.randint(-30, 30)

        HEADER_Y_START = int(H * self.HEADER_Y_START_FRAC) + y_var
        HEADER_Y_END   = int(H * self.HEADER_Y_END_FRAC)   + y_var
        BODY_Y         = int(H * self.BODY_Y_FRAC)          + y_var

        # ── Timing ────────────────────────────────────────────────────────
        title_dur = 0.0
        if line_timings:
            title_dur = line_timings[0].start

        if line_timings:
            total_card_dur = line_timings[-1].end
        else:
            total_card_dur = max(t, 1.0)

        # ── Build page timing structures from body.extra ───────────────────
        page_line_positions: list[list[dict]] = []
        if body.extra and "page_line_positions" in body.extra:
            page_line_positions = body.extra["page_line_positions"]

        page_imgs = list(body.pages)

        # Assign line_timings to pages sequentially based on page sizes.
        # page_index on LineTiming is always 0 (set by the orchestrator which
        # has no image context), so we can't use it for grouping.
        # Also, y_top/y_bottom on LineTiming are 0 (orchestrator has no image
        # context), so we take pixel coords from page_line_positions instead.
        page_line_timings: list[list[dict]] = [[] for _ in page_imgs]
        lt_list = list(line_timings)
        lt_idx = 0
        for pi, page_positions in enumerate(page_line_positions):
            for pos in page_positions:
                if lt_idx >= len(lt_list):
                    break
                lt = lt_list[lt_idx]
                page_line_timings[pi].append({
                    "text": lt.text,
                    "y_top": pos["y_top"],       # real pixel coords from rendered image
                    "y_bottom": pos["y_bottom"],
                    "start": lt.start,
                    "end": lt.end,
                })
                lt_idx += 1

        def get_active_page_and_mask(t_body: float) -> tuple[int, int, int]:
            """Return (page_index, mask_bottom, mask_start) for body time t_body."""
            active_page = 0
            for pi, plt in enumerate(page_line_timings):
                if plt and t >= plt[0]["start"]:
                    active_page = pi

            plt = page_line_timings[active_page]
            if page_line_positions and active_page < len(page_line_positions):
                bp_positions = page_line_positions[active_page]
            else:
                bp_positions = plt

            mask_start = bp_positions[0]["y_top"] if bp_positions else 0
            bottom = mask_start
            for lt_d in plt:
                if t >= lt_d["start"]:
                    elapsed = t - lt_d["start"]
                    progress = min(1.0, elapsed / self.SCROLL_TIME)
                    eased = 1 - (1 - progress) ** 3
                    line_bottom = lt_d["y_top"] + (lt_d["y_bottom"] - lt_d["y_top"]) * eased
                    bottom = max(bottom, int(line_bottom))
            if page_imgs:
                page_h = page_imgs[active_page].shape[0]
                return active_page, min(bottom, page_h), mask_start
            return active_page, bottom, mask_start

        # ── Header alpha (dismiss fade) ────────────────────────────────────
        def _header_alpha(t: float) -> float:
            if not self._dismiss_title_on_body or t < title_dur:
                return opacity
            elapsed = t - title_dur
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

            # Apply opacity to the alpha channel before compositing
            h_arr = np.array(h_pil)  # RGBA uint8
            if h_alpha < 1.0:
                h_arr = h_arr.copy()
                h_arr[:, :, 3] = (h_arr[:, :, 3].astype(np.float32) * h_alpha).astype(np.uint8)

            x = (W - cur_w) // 2
            slide_progress = min(1.0, t / max(0.001, total_card_dur))
            base_y = int(HEADER_Y_START + (HEADER_Y_END - HEADER_Y_START) * slide_progress)
            base_center_y = base_y + HEADER_DISP_H // 2
            y_off = base_center_y - cur_h // 2

            composite_rgba_onto(frame, h_arr, x, y_off)

        # ── Body: mask-reveal card pages ───────────────────────────────────
        if t >= title_dur and page_imgs:
            t_body = t - title_dur
            page_idx, mb, mask_start = get_active_page_and_mask(t_body)

            if mb > mask_start:
                cur_body = page_imgs[page_idx].copy()
                # Zero out alpha below the reveal mask
                cur_body[mb:, :, 3] = 0

                cur_h_b, cur_w_b = cur_body.shape[:2]
                disp_h = max(1, int(cur_h_b * (DISPLAY_W / cur_w_b)))
                b_pil = Image.fromarray(cur_body).resize((DISPLAY_W, disp_h), Image.LANCZOS)
                b_arr = np.array(b_pil)  # RGBA

                bx = (W - DISPLAY_W) // 2
                composite_rgba_onto(frame, b_arr, bx, BODY_Y)

        return frame
