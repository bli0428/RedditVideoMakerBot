"""Static-layout tests for all four registered plugins.

Validates that each plugin's render_header and render_body produce images
with the expected structural properties (correct channel count, non-zero
content, reasonable dimensions relative to the canvas).

Satisfies: Requirements 7.1, 11.1, 11.2, 11.3
"""

from __future__ import annotations

import pytest
import numpy as np

import video_creation.render.styles  # noqa: F401

from video_creation.render.context import CanvasSpec, RenderContext
from video_creation.render.styles import available_styles, get_style
from video_creation.render.timing.models import LineTiming


_CANVAS = CanvasSpec(width=540, height=960, zoom=1.0, opacity=1.0)

_CTX = RenderContext(
    title="Static layout test post title",
    body_text="This is the body text used for static layout testing.",
    author="testuser",
    avatar_url="",
    subreddit="test",
    upvotes=100,
    num_comments=10,
    canvas=_CANVAS,
    theme="light",
)

_LINE_TIMINGS = (
    LineTiming(text="This is the body", start=0.5, end=1.5,
               line_index=0, chunk_index=0, y_top=10, y_bottom=40, page_index=0),
    LineTiming(text="text used for testing.", start=1.5, end=2.5,
               line_index=1, chunk_index=0, y_top=50, y_bottom=80, page_index=0),
)


def _make_plugin(style_id: str):
    plugin_cls = get_style(style_id)
    options = {}
    if "theme" in plugin_cls.options_schema:
        options["theme"] = "light"
    if "dismiss_title_on_body" in plugin_cls.options_schema:
        options["dismiss_title_on_body"] = False
    if "karaoke_words_per_chunk" in plugin_cls.options_schema:
        options["karaoke_words_per_chunk"] = 3
    return plugin_cls(options=options, canvas=_CANVAS)


@pytest.mark.parametrize("style_id", available_styles())
def test_render_header_is_rgba_ndarray(style_id: str) -> None:
    """render_header returns an RGBA ndarray (Req 5.1, 11.3)."""
    plugin = _make_plugin(style_id)
    header = plugin.render_header(_CTX)
    assert isinstance(header, np.ndarray), f"[{style_id}] header is not ndarray"
    assert header.ndim == 3, f"[{style_id}] header ndim={header.ndim}"
    assert header.shape[2] == 4, f"[{style_id}] header channels={header.shape[2]}"
    assert header.dtype == np.uint8, f"[{style_id}] header dtype={header.dtype}"


@pytest.mark.parametrize("style_id", available_styles())
def test_render_header_has_nonzero_content(style_id: str) -> None:
    """render_header produces a non-blank image."""
    plugin = _make_plugin(style_id)
    header = plugin.render_header(_CTX)
    assert np.any(header[:, :, 3] > 0), f"[{style_id}] header is fully transparent"


@pytest.mark.parametrize("style_id", available_styles())
def test_render_header_width_matches_canvas_fraction(style_id: str) -> None:
    """Header width is a reasonable fraction of the canvas width (Req 11.1)."""
    plugin = _make_plugin(style_id)
    header = plugin.render_header(_CTX)
    W = _CANVAS.width
    # Header should be between 50% and 100% of canvas width
    assert header.shape[1] >= W * 0.5, (
        f"[{style_id}] header width {header.shape[1]} < 50% of canvas {W}"
    )
    assert header.shape[1] <= W, (
        f"[{style_id}] header width {header.shape[1]} > canvas width {W}"
    )


@pytest.mark.parametrize("style_id", available_styles())
def test_render_body_returns_body_assets(style_id: str) -> None:
    """render_body returns BodyAssets with at least one image (Req 5.2)."""
    from video_creation.render.styles.base import BodyAssets
    plugin = _make_plugin(style_id)
    body = plugin.render_body(_CTX, _LINE_TIMINGS)
    assert isinstance(body, BodyAssets)
    total = len(body.pages) + len(body.chunk_images)
    assert total > 0, f"[{style_id}] render_body returned empty BodyAssets"


@pytest.mark.parametrize("style_id", available_styles())
def test_render_body_images_are_rgba(style_id: str) -> None:
    """All body images are RGBA ndarrays (Req 5.2)."""
    plugin = _make_plugin(style_id)
    body = plugin.render_body(_CTX, _LINE_TIMINGS)
    for i, page in enumerate(body.pages):
        assert isinstance(page, np.ndarray), f"[{style_id}] pages[{i}] not ndarray"
        assert page.shape[2] == 4, f"[{style_id}] pages[{i}] channels={page.shape[2]}"
    for i, chunk in enumerate(body.chunk_images):
        assert isinstance(chunk, np.ndarray), f"[{style_id}] chunks[{i}] not ndarray"
        assert chunk.shape[2] == 4, f"[{style_id}] chunks[{i}] channels={chunk.shape[2]}"


@pytest.mark.parametrize("style_id", available_styles())
def test_compose_frame_shape_at_t0(style_id: str) -> None:
    """compose_frame at t=0 returns (H, W, 4) uint8 (Req 4.1, 11.3)."""
    plugin = _make_plugin(style_id)
    header = plugin.render_header(_CTX)
    body = plugin.render_body(_CTX, _LINE_TIMINGS)
    frame = plugin.compose_frame(0.0, _CTX, header, body, _LINE_TIMINGS)
    H, W = _CANVAS.height, _CANVAS.width
    assert frame.shape == (H, W, 4), f"[{style_id}] frame shape {frame.shape} != ({H},{W},4)"
    assert frame.dtype == np.uint8, f"[{style_id}] frame dtype {frame.dtype}"


@pytest.mark.parametrize("style_id", available_styles())
def test_layout_constants_are_class_level(style_id: str) -> None:
    """Each plugin owns its layout constants as class attributes (Req 11.1, 11.2)."""
    plugin_cls = get_style(style_id)
    # Every plugin should have at least POP_DUR and ZOOM_AMOUNT as class attrs
    assert hasattr(plugin_cls, "POP_DUR"), f"[{style_id}] missing POP_DUR"
    assert hasattr(plugin_cls, "ZOOM_AMOUNT"), f"[{style_id}] missing ZOOM_AMOUNT"
    # Values should be positive numbers
    assert plugin_cls.POP_DUR > 0, f"[{style_id}] POP_DUR <= 0"
    assert plugin_cls.ZOOM_AMOUNT > 0, f"[{style_id}] ZOOM_AMOUNT <= 0"
