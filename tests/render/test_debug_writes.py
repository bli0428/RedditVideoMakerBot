"""Property test for debug-enabled non-production runs writing expected intermediates.

# Feature: card-rendering-refactor, Property 7

**Validates: Requirements 5.4**

Property 7: Debug-enabled non-production runs write expected intermediates.

For any registered plugin and any run where ``debug_dump_intermediates=True``
AND ``is_production=False``, the rendering pipeline SHALL write
``assets/temp/<reddit_id>/debug/header.png`` and at least one body asset
(a ``body_page_*.png`` for paginated styles or a ``chunk_*.png`` for karaoke
styles) under ``assets/temp/<reddit_id>/debug/``.

Implementation notes:
- Tests ``_dump_debug_intermediates`` directly (not the full pipeline).
- Creates a ``PipelineOrchestrator`` instance with a config that has
  ``debug_dump_intermediates=True`` and ``is_production=False``.
- Uses ``os.chdir`` inside the test body (via a tempfile.TemporaryDirectory)
  to redirect ``assets/temp/`` to a temp directory (the method uses
  ``Path("assets") / "temp" / ...``).
- Creates minimal header (numpy RGBA array) and body (BodyAssets with pages
  or chunk_images) and calls ``orchestrator._dump_debug_intermediates``
  directly.
- Asserts ``header.png`` exists and at least one body file exists.
"""

from __future__ import annotations

import os
import re
import tempfile
import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pathlib import Path

# Ensure all four plugins are registered by importing the styles package.
import video_creation.render.styles  # noqa: F401

from video_creation.render.config import RenderConfig
from video_creation.render.context import CanvasSpec, RenderContext
from video_creation.render.orchestrator import PipelineOrchestrator
from video_creation.render.styles import available_styles, get_style
from video_creation.render.timing.models import LineTiming


# ---------------------------------------------------------------------------
# Helpers
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
    return tuple(
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
        for i in range(n)
    )


def _make_debug_config(style_id: str) -> RenderConfig:
    """Build a RenderConfig with debug_dump_intermediates=True, is_production=False."""
    plugin_cls = get_style(style_id)
    options: dict = {}
    if "theme" in plugin_cls.options_schema:
        options["theme"] = "light"
    if "dismiss_title_on_body" in plugin_cls.options_schema:
        options["dismiss_title_on_body"] = False
    if "karaoke_words_per_chunk" in plugin_cls.options_schema:
        options["karaoke_words_per_chunk"] = 3

    return RenderConfig(
        style_id=style_id,
        style_options=options,
        canvas=_make_canvas(),
        debug_dump_intermediates=True,
        is_production=False,
    )


def _make_orchestrator(style_id: str) -> PipelineOrchestrator:
    """Build a PipelineOrchestrator with debug config; stage objects are None
    because we only call _dump_debug_intermediates directly."""
    config = _make_debug_config(style_id)
    return PipelineOrchestrator(
        config=config,
        audio=None,       # type: ignore[arg-type]
        background=None,  # type: ignore[arg-type]
        timing=None,      # type: ignore[arg-type]
        compositor=None,  # type: ignore[arg-type]
        output=None,      # type: ignore[arg-type]
    )


def _make_reddit_obj(reddit_id: str = "abc123") -> dict:
    """Build a minimal reddit_obj dict with a thread_id."""
    return {
        "thread_id": reddit_id,
        "thread_title": "Test post",
        "thread_post": "Hello world this is a test body.",
        "author": "testuser",
        "thread_score": 42,
        "num_comments": 7,
    }


# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

@st.composite
def reddit_id_strategy(draw) -> str:
    """Generate a valid reddit_id (alphanumeric + underscore, no special chars)."""
    return draw(
        st.text(
            alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd")),
            min_size=3,
            max_size=12,
        )
    )


# ---------------------------------------------------------------------------
# Property tests — one per registered plugin
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("style_id", list(available_styles()))
@given(reddit_id=reddit_id_strategy())
@settings(max_examples=10, deadline=None)
def test_debug_writes_header_and_body(
    style_id: str,
    reddit_id: str,
) -> None:
    """Property 7: Debug-enabled non-production runs write expected intermediates.

    **Validates: Requirements 5.4**

    For any registered plugin and any run where ``debug_dump_intermediates=True``
    AND ``is_production=False``, calling ``_dump_debug_intermediates`` SHALL
    write ``header.png`` and at least one body file (``body_page_*.png`` or
    ``chunk_*.png``) under ``assets/temp/<reddit_id>/debug/``.
    """
    # Use a TemporaryDirectory and os.chdir inside the test body so that
    # Path("assets") / "temp" / ... resolves inside the temp dir.
    # We save and restore the original cwd to avoid side effects between runs.
    original_cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        os.chdir(tmp_path)
        try:
            # Build the orchestrator with debug config.
            orchestrator = _make_orchestrator(style_id)

            # Build a real plugin to produce real header/body arrays.
            plugin_cls = get_style(style_id)
            options: dict = {}
            if "theme" in plugin_cls.options_schema:
                options["theme"] = "light"
            if "dismiss_title_on_body" in plugin_cls.options_schema:
                options["dismiss_title_on_body"] = False
            if "karaoke_words_per_chunk" in plugin_cls.options_schema:
                options["karaoke_words_per_chunk"] = 3

            canvas = _make_canvas()
            plugin = plugin_cls(options=options, canvas=canvas)
            ctx = _make_ctx()
            line_timings = _make_line_timings(n=2)

            header = plugin.render_header(ctx)
            body = plugin.render_body(ctx, line_timings)

            reddit_obj = _make_reddit_obj(reddit_id=reddit_id)

            # Call the method under test.
            orchestrator._dump_debug_intermediates(reddit_obj, header, body)

            # Derive the expected debug directory path (same logic as the method).
            clean_id = re.sub(r"[^\w\s-]", "", reddit_id)
            debug_dir = tmp_path / "assets" / "temp" / clean_id / "debug"

            # Assert header.png was written.
            header_path = debug_dir / "header.png"
            assert header_path.exists(), (
                f"[{style_id}] Expected header.png at {header_path} but it was not created. "
                f"debug_dir contents: {list(debug_dir.iterdir()) if debug_dir.exists() else 'dir missing'}"
            )

            # Assert at least one body file was written (body_page_*.png or chunk_*.png).
            body_pages = list(debug_dir.glob("body_page_*.png"))
            chunk_images = list(debug_dir.glob("chunk_*.png"))
            assert len(body_pages) > 0 or len(chunk_images) > 0, (
                f"[{style_id}] Expected at least one body_page_*.png or chunk_*.png "
                f"under {debug_dir}, but found none. "
                f"Files present: {list(debug_dir.iterdir()) if debug_dir.exists() else 'dir missing'}"
            )
        finally:
            os.chdir(original_cwd)
