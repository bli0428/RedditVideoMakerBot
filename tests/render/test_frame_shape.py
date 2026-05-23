"""Property test for frame shape and dtype.

# Feature: card-rendering-refactor, Property 3

**Validates: Requirements 4.1, 11.3**

Property 3: Frame is RGBA with canvas dimensions.

For any registered plugin, any RenderContext with canvas (W, H) from the
design's grid plus a small random sample, and any t in [0, total_duration],
plugin.compose_frame(t, ctx, header, body, line_timings) SHALL return a
numpy.ndarray of shape (H, W, 4) and dtype uint8.
"""

from __future__ import annotations

import pytest
import numpy as np
from hypothesis import given, settings, assume
from hypothesis import strategies as st

# Ensure all four plugins are registered by importing the styles package.
import video_creation.render.styles  # noqa: F401

from video_creation.render.styles import available_styles, get_style
from video_creation.render.context import CanvasSpec, RenderContext
from video_creation.render.timing.models import LineTiming


# ---------------------------------------------------------------------------
# Canvas sizes from the design's grid
# ---------------------------------------------------------------------------

CANVAS_SIZES = [
    (1080, 1920),
    (720, 1280),
    (540, 960),
]


# ---------------------------------------------------------------------------
# Helpers to build minimal test fixtures
# ---------------------------------------------------------------------------

def _make_canvas(width: int, height: int) -> CanvasSpec:
    return CanvasSpec(width=width, height=height, zoom=1.0, opacity=1.0)


def _make_ctx(width: int, height: int) -> RenderContext:
    return RenderContext(
        title="Test title for property test",
        body_text="This is a short body text used for testing.",
        author="testuser",
        avatar_url="",
        subreddit="test",
        upvotes=42,
        num_comments=7,
        canvas=_make_canvas(width, height),
        theme="light",
    )


def _make_line_timings() -> tuple[LineTiming, ...]:
    """Return a minimal single-entry LineTiming tuple."""
    return (
        LineTiming(
            text="This is a short body text used for testing.",
            start=0.5,
            end=2.0,
            line_index=0,
            chunk_index=0,
            y_top=10,
            y_bottom=40,
            page_index=0,
        ),
    )


# ---------------------------------------------------------------------------
# Parametrize over registered styles
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def registered_style_ids():
    return list(available_styles())


# ---------------------------------------------------------------------------
# Property test
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("style_id", list(available_styles()))
@given(
    canvas_size=st.sampled_from(CANVAS_SIZES),
    t=st.floats(min_value=0.0, max_value=2.0, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=30, deadline=None)
def test_compose_frame_shape_and_dtype(style_id: str, canvas_size: tuple, t: float):
    """Property 3: Frame is RGBA with canvas dimensions.

    **Validates: Requirements 4.1, 11.3**

    For any registered plugin, any RenderContext with canvas (W, H) from the
    design's grid, and any t in [0.0, 2.0], compose_frame must return a
    numpy.ndarray of shape (H, W, 4) and dtype uint8.
    """
    W, H = canvas_size

    # Build plugin instance with minimal options
    plugin_cls = get_style(style_id)
    canvas = _make_canvas(W, H)
    options: dict = {}
    # Provide sensible defaults for known option keys
    if "theme" in plugin_cls.options_schema:
        options["theme"] = "light"
    if "dismiss_title_on_body" in plugin_cls.options_schema:
        options["dismiss_title_on_body"] = False
    if "karaoke_words_per_chunk" in plugin_cls.options_schema:
        options["karaoke_words_per_chunk"] = 3

    plugin = plugin_cls(options=options, canvas=canvas)

    # Build a minimal RenderContext
    ctx = _make_ctx(W, H)

    # Build minimal line_timings
    line_timings = _make_line_timings()

    # Render header and body using the real plugin methods
    header = plugin.render_header(ctx)
    body = plugin.render_body(ctx, line_timings)

    # Call compose_frame
    frame = plugin.compose_frame(t, ctx, header, body, line_timings)

    # Assert shape is (H, W, 4)
    assert isinstance(frame, np.ndarray), (
        f"[{style_id}] compose_frame returned {type(frame)}, expected numpy.ndarray"
    )
    assert frame.shape == (H, W, 4), (
        f"[{style_id}] compose_frame shape {frame.shape} != expected ({H}, {W}, 4) "
        f"for canvas ({W}x{H}) at t={t}"
    )
    assert frame.dtype == np.uint8, (
        f"[{style_id}] compose_frame dtype {frame.dtype} != uint8"
    )
