"""Property test for header dismiss alpha.

# Feature: card-rendering-refactor, Property 12

**Validates: Requirements 7.6**

Property 12: Header dismiss zeroes header alpha after dismiss_dur.

For any dismiss-supporting plugin, any RenderContext, and any
t > title_duration + plugin.HEADER_DISMISS_DUR, the alpha channel in the
header's display region of plugin.compose_frame(t, ...) is 0 when
dismiss_title_on_body=True and nonzero in the same region when False.
"""

from __future__ import annotations

import pytest
import numpy as np
from hypothesis import given, settings
from hypothesis import strategies as st

# Ensure all four plugins are registered.
import video_creation.render.styles  # noqa: F401

from video_creation.render.styles import available_styles, get_style
from video_creation.render.context import CanvasSpec, RenderContext
from video_creation.render.timing.models import LineTiming


# ---------------------------------------------------------------------------
# Identify dismiss-supporting plugins
# ---------------------------------------------------------------------------

def _dismiss_supporting_style_ids() -> list[str]:
    """Return style_ids for plugins that have 'dismiss_title_on_body' in options_schema."""
    return [
        sid
        for sid in available_styles()
        if "dismiss_title_on_body" in get_style(sid).options_schema
    ]


DISMISS_STYLE_IDS = _dismiss_supporting_style_ids()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CANVAS_W = 540
_CANVAS_H = 960

# title_duration = line_timings[0].start = 1.0 seconds
_TITLE_DURATION = 1.0


def _make_canvas() -> CanvasSpec:
    return CanvasSpec(width=_CANVAS_W, height=_CANVAS_H, zoom=1.0, opacity=1.0)


def _make_ctx(title: str, body_text: str, author: str) -> RenderContext:
    return RenderContext(
        title=title,
        body_text=body_text,
        author=author,
        avatar_url="",
        subreddit="test",
        upvotes=42,
        num_comments=7,
        canvas=_make_canvas(),
        theme="light",
    )


def _make_line_timings(title_duration: float = _TITLE_DURATION) -> tuple[LineTiming, ...]:
    """Return a minimal line_timings tuple where line_timings[0].start == title_duration."""
    return (
        LineTiming(
            text="First body line for testing.",
            start=title_duration,
            end=title_duration + 1.5,
            line_index=0,
            chunk_index=0,
            y_top=10,
            y_bottom=50,
            page_index=0,
        ),
        LineTiming(
            text="Second body line for testing.",
            start=title_duration + 1.5,
            end=title_duration + 3.0,
            line_index=1,
            chunk_index=0,
            y_top=60,
            y_bottom=100,
            page_index=0,
        ),
    )


def _header_region_alpha(frame: np.ndarray) -> np.ndarray:
    """Return the alpha channel of the top third of the frame (header region)."""
    H = frame.shape[0]
    return frame[: H // 3, :, 3]


# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

@st.composite
def render_contexts(draw) -> RenderContext:
    """Generate a RenderContext with varied but valid post metadata."""
    title = draw(st.text(
        alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd", "Zs")),
        min_size=5,
        max_size=80,
    ))
    body_text = draw(st.text(
        alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd", "Zs")),
        min_size=10,
        max_size=200,
    ))
    author = draw(st.text(
        alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd")),
        min_size=3,
        max_size=20,
    ))
    return _make_ctx(title=title, body_text=body_text, author=author)


# ---------------------------------------------------------------------------
# Property test
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("style_id", DISMISS_STYLE_IDS)
@given(ctx=render_contexts())
@settings(max_examples=20, deadline=None)
def test_header_dismiss_alpha_zeroed_when_dismiss_true(
    style_id: str,
    ctx: RenderContext,
) -> None:
    """Property 12: Header dismiss zeroes header alpha after dismiss_dur.

    **Validates: Requirements 7.6**

    For any dismiss-supporting plugin and any RenderContext, at time
    t = title_duration + HEADER_DISMISS_DUR + 0.1 (well past the dismiss
    window), the alpha channel in the header region (y=0 to H//3) of
    compose_frame(..., dismiss_title_on_body=True) must be all zeros.
    """
    plugin_cls = get_style(style_id)
    canvas = _make_canvas()

    # Build plugin with dismiss_title_on_body=True
    options_dismiss: dict = {}
    if "theme" in plugin_cls.options_schema:
        options_dismiss["theme"] = "light"
    if "karaoke_words_per_chunk" in plugin_cls.options_schema:
        options_dismiss["karaoke_words_per_chunk"] = 3
    options_dismiss["dismiss_title_on_body"] = True

    plugin = plugin_cls(options=options_dismiss, canvas=canvas)

    # Use a fresh ctx with the correct canvas dimensions
    ctx_fixed = RenderContext(
        title=ctx.title,
        body_text=ctx.body_text,
        author=ctx.author,
        avatar_url="",
        subreddit="test",
        upvotes=ctx.upvotes,
        num_comments=ctx.num_comments,
        canvas=canvas,
        theme="light",
    )

    line_timings = _make_line_timings(_TITLE_DURATION)

    # Render header and body
    header = plugin.render_header(ctx_fixed)
    body = plugin.render_body(ctx_fixed, line_timings)

    # t is well past the dismiss window
    t = _TITLE_DURATION + plugin.HEADER_DISMISS_DUR + 0.1

    frame = plugin.compose_frame(t, ctx_fixed, header, body, line_timings)

    # The alpha channel in the header region must be all zeros
    header_alpha = _header_region_alpha(frame)
    assert np.all(header_alpha == 0), (
        f"[{style_id}] Expected all-zero alpha in header region at t={t:.3f} "
        f"(title_dur={_TITLE_DURATION}, dismiss_dur={plugin.HEADER_DISMISS_DUR}) "
        f"with dismiss_title_on_body=True, but found nonzero values. "
        f"Max alpha in region: {header_alpha.max()}"
    )


@pytest.mark.parametrize("style_id", DISMISS_STYLE_IDS)
@given(ctx=render_contexts())
@settings(max_examples=20, deadline=None)
def test_header_visible_when_dismiss_false(
    style_id: str,
    ctx: RenderContext,
) -> None:
    """Property 12 (complement): Header region has nonzero alpha when dismiss=False.

    **Validates: Requirements 7.6**

    For any dismiss-supporting plugin and any RenderContext, at the same time
    t = title_duration + HEADER_DISMISS_DUR + 0.1, the alpha channel in the
    header region of compose_frame(..., dismiss_title_on_body=False) must
    contain some nonzero values (the header is still visible).
    """
    plugin_cls = get_style(style_id)
    canvas = _make_canvas()

    # Build plugin with dismiss_title_on_body=False
    options_no_dismiss: dict = {}
    if "theme" in plugin_cls.options_schema:
        options_no_dismiss["theme"] = "light"
    if "karaoke_words_per_chunk" in plugin_cls.options_schema:
        options_no_dismiss["karaoke_words_per_chunk"] = 3
    options_no_dismiss["dismiss_title_on_body"] = False

    plugin = plugin_cls(options=options_no_dismiss, canvas=canvas)

    # Use a fresh ctx with the correct canvas dimensions
    ctx_fixed = RenderContext(
        title=ctx.title,
        body_text=ctx.body_text,
        author=ctx.author,
        avatar_url="",
        subreddit="test",
        upvotes=ctx.upvotes,
        num_comments=ctx.num_comments,
        canvas=canvas,
        theme="light",
    )

    line_timings = _make_line_timings(_TITLE_DURATION)

    # Render header and body
    header = plugin.render_header(ctx_fixed)
    body = plugin.render_body(ctx_fixed, line_timings)

    # Same t as the dismiss test
    t = _TITLE_DURATION + plugin.HEADER_DISMISS_DUR + 0.1

    frame = plugin.compose_frame(t, ctx_fixed, header, body, line_timings)

    # The alpha channel in the header region must have some nonzero values
    header_alpha = _header_region_alpha(frame)
    assert np.any(header_alpha > 0), (
        f"[{style_id}] Expected nonzero alpha in header region at t={t:.3f} "
        f"(title_dur={_TITLE_DURATION}, dismiss_dur={plugin.HEADER_DISMISS_DUR}) "
        f"with dismiss_title_on_body=False, but found all-zero alpha. "
        f"The header should still be visible when dismiss is disabled."
    )
