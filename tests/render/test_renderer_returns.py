"""Property test for in-memory plugin renderer outputs.

# Feature: card-rendering-refactor, Property 5

**Validates: Requirements 5.1, 5.2**

Property 5: Plugin renderers return in-memory RGBA.

For any registered plugin and any valid RenderContext:
  - ``plugin.render_header(ctx)`` SHALL return a ``numpy.ndarray`` (not a
    file path or PIL Image), and
  - ``plugin.render_body(ctx, line_timings).pages`` and
    ``.chunk_images`` entries SHALL all be ``numpy.ndarray`` with
    ``ndim == 3`` and ``shape[2] == 4`` (RGBA).
"""

from __future__ import annotations

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

# Ensure all four plugins are registered by importing the styles package.
import video_creation.render.styles  # noqa: F401

from video_creation.render.context import CanvasSpec, RenderContext
from video_creation.render.styles import available_styles, get_style
from video_creation.render.timing.models import LineTiming


# ---------------------------------------------------------------------------
# Minimal helpers
# ---------------------------------------------------------------------------

def _make_canvas(width: int = 540, height: int = 960) -> CanvasSpec:
    """Return a small but valid CanvasSpec for testing."""
    return CanvasSpec(width=width, height=height, zoom=1.0, opacity=1.0)


def _make_ctx(
    title: str = "Test title",
    body_text: str = "Hello world this is a test body.",
    author: str = "testuser",
    canvas: CanvasSpec | None = None,
) -> RenderContext:
    """Build a minimal RenderContext suitable for plugin calls."""
    return RenderContext(
        title=title,
        body_text=body_text,
        author=author,
        avatar_url="",
        subreddit="test",
        upvotes=42,
        num_comments=7,
        canvas=canvas or _make_canvas(),
        theme="light",
    )


def _make_line_timings(n: int = 2) -> tuple[LineTiming, ...]:
    """Return a minimal tuple of LineTiming entries."""
    entries = []
    for i in range(n):
        entries.append(
            LineTiming(
                text=f"word{i}",
                start=float(i),
                end=float(i) + 0.9,
                line_index=i,
                chunk_index=0,
                y_top=i * 30,
                y_bottom=i * 30 + 28,
                page_index=0,
            )
        )
    return tuple(entries)


# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

@st.composite
def render_context_strategy(draw) -> RenderContext:
    """Generate a minimal but varied RenderContext."""
    title = draw(
        st.text(
            alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd", "Zs")),
            min_size=1,
            max_size=40,
        ).map(str.strip).filter(lambda s: len(s) >= 1)
    )
    body_text = draw(
        st.text(
            alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd", "Zs")),
            min_size=1,
            max_size=80,
        ).map(str.strip).filter(lambda s: len(s) >= 1)
    )
    author = draw(
        st.text(
            alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd")),
            min_size=1,
            max_size=20,
        )
    )
    return _make_ctx(title=title, body_text=body_text, author=author)


# ---------------------------------------------------------------------------
# Parametrised property tests — one test per registered plugin
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("style_id", available_styles())
@given(ctx=render_context_strategy())
@settings(max_examples=10)
def test_render_header_returns_ndarray(style_id: str, ctx: RenderContext) -> None:
    """Property 5 (header): render_header returns numpy.ndarray, not a path.

    **Validates: Requirements 5.1**
    """
    plugin_cls = get_style(style_id)
    plugin = plugin_cls(options={}, canvas=ctx.canvas)

    result = plugin.render_header(ctx)

    # Must be a numpy array — not a str, Path, or PIL Image.
    assert isinstance(result, np.ndarray), (
        f"[{style_id}] render_header returned {type(result).__name__}, "
        f"expected numpy.ndarray"
    )
    # Must be 3-dimensional (H, W, C).
    assert result.ndim == 3, (
        f"[{style_id}] render_header returned ndarray with ndim={result.ndim}, "
        f"expected 3"
    )
    # Must have 4 channels (RGBA).
    assert result.shape[2] == 4, (
        f"[{style_id}] render_header returned shape {result.shape}, "
        f"expected (..., ..., 4)"
    )


@pytest.mark.parametrize("style_id", available_styles())
@given(ctx=render_context_strategy())
@settings(max_examples=10)
def test_render_body_returns_ndarray_entries(style_id: str, ctx: RenderContext) -> None:
    """Property 5 (body): render_body returns BodyAssets whose pages and
    chunk_images entries are all numpy.ndarray with shape (_, _, 4).

    **Validates: Requirements 5.2**
    """
    plugin_cls = get_style(style_id)
    plugin = plugin_cls(options={}, canvas=ctx.canvas)

    line_timings = _make_line_timings(n=2)
    body = plugin.render_body(ctx, line_timings)

    # Check pages entries.
    for i, page in enumerate(body.pages):
        assert isinstance(page, np.ndarray), (
            f"[{style_id}] body.pages[{i}] is {type(page).__name__}, "
            f"expected numpy.ndarray"
        )
        assert page.ndim == 3, (
            f"[{style_id}] body.pages[{i}] has ndim={page.ndim}, expected 3"
        )
        assert page.shape[2] == 4, (
            f"[{style_id}] body.pages[{i}] has shape {page.shape}, "
            f"expected (..., ..., 4)"
        )

    # Check chunk_images entries.
    for i, chunk in enumerate(body.chunk_images):
        assert isinstance(chunk, np.ndarray), (
            f"[{style_id}] body.chunk_images[{i}] is {type(chunk).__name__}, "
            f"expected numpy.ndarray"
        )
        assert chunk.ndim == 3, (
            f"[{style_id}] body.chunk_images[{i}] has ndim={chunk.ndim}, expected 3"
        )
        assert chunk.shape[2] == 4, (
            f"[{style_id}] body.chunk_images[{i}] has shape {chunk.shape}, "
            f"expected (..., ..., 4)"
        )

    # At least one of pages or chunk_images must be non-empty — a plugin that
    # returns both empty would be vacuously passing the shape checks above.
    assert len(body.pages) > 0 or len(body.chunk_images) > 0, (
        f"[{style_id}] render_body returned BodyAssets with both pages and "
        f"chunk_images empty"
    )
