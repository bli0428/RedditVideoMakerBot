"""Property test for plugin independence under monkeypatching.

# Feature: card-rendering-refactor, Property 14

**Validates: Requirements 12.1**

Property 14: Plugin independence under monkeypatching.

For any pair of distinct registered plugins (P_target, P_other), monkeypatching
P_target.compose_frame to return a constant frame does NOT change the byte-output
of P_other.compose_frame compared to a baseline run with no monkeypatch.

This test verifies that each plugin's compose_frame is fully independent — a
modification to one plugin cannot affect another plugin's output.
"""

from __future__ import annotations

import itertools
from typing import Any, Mapping
from unittest.mock import patch

import numpy as np
import pytest

# Ensure all four plugins are registered by importing the styles package.
import video_creation.render.styles  # noqa: F401

from video_creation.render.context import CanvasSpec, RenderContext
from video_creation.render.styles import available_styles, get_style
from video_creation.render.styles.base import BodyAssets
from video_creation.render.timing.models import LineTiming


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_canvas(width: int = 540, height: int = 960) -> CanvasSpec:
    return CanvasSpec(width=width, height=height, zoom=1.0, opacity=1.0)


def _make_ctx(canvas: CanvasSpec | None = None) -> RenderContext:
    return RenderContext(
        title="Test title for independence test",
        body_text="Hello world this is a test body for independence.",
        author="testuser",
        avatar_url="",
        subreddit="test",
        upvotes=42,
        num_comments=7,
        canvas=canvas or _make_canvas(),
        theme="light",
    )


def _make_line_timings() -> tuple[LineTiming, ...]:
    return (
        LineTiming(
            text="Hello world this is a test",
            start=0.5,
            end=2.0,
            line_index=0,
            chunk_index=0,
            y_top=10,
            y_bottom=40,
            page_index=0,
        ),
    )


def _default_options(plugin_cls: type) -> dict[str, Any]:
    """Build a minimal valid options dict for a plugin class."""
    options: dict[str, Any] = {}
    schema: Mapping[str, type] = getattr(plugin_cls, "options_schema", {})
    if "theme" in schema:
        options["theme"] = "light"
    if "dismiss_title_on_body" in schema:
        options["dismiss_title_on_body"] = False
    if "karaoke_words_per_chunk" in schema:
        options["karaoke_words_per_chunk"] = 3
    return options


# ---------------------------------------------------------------------------
# Build all pairs of distinct registered style IDs
# ---------------------------------------------------------------------------

_ALL_STYLES = list(available_styles())
_DISTINCT_PAIRS = [
    (target, other)
    for target, other in itertools.permutations(_ALL_STYLES, 2)
]


# ---------------------------------------------------------------------------
# Property test
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("target_style_id,other_style_id", _DISTINCT_PAIRS)
def test_plugin_independence_under_monkeypatching(
    target_style_id: str,
    other_style_id: str,
) -> None:
    """Property 14: Plugin independence under monkeypatching.

    **Validates: Requirements 12.1**

    Monkeypatching P_target.compose_frame to return a constant zero frame
    must NOT change the byte-output of P_other.compose_frame.

    Steps:
    1. Instantiate P_other and call compose_frame to get a baseline frame.
    2. Monkeypatch P_target.compose_frame to return a constant zero frame.
    3. Call P_other.compose_frame again.
    4. Assert the two P_other frames are identical (byte-for-byte).
    """
    canvas = _make_canvas()
    ctx = _make_ctx(canvas)
    line_timings = _make_line_timings()
    t = 1.0

    # ── Instantiate P_other ────────────────────────────────────────────────
    other_cls = get_style(other_style_id)
    other_options = _default_options(other_cls)
    p_other = other_cls(options=other_options, canvas=canvas)

    # Pre-render header and body for P_other (these are independent of P_target)
    other_header = p_other.render_header(ctx)
    other_body = p_other.render_body(ctx, line_timings)

    # ── Baseline: call P_other.compose_frame without any monkeypatch ───────
    baseline_frame = p_other.compose_frame(t, ctx, other_header, other_body, line_timings)

    # ── Monkeypatch P_target.compose_frame ─────────────────────────────────
    # Replace P_target's compose_frame with a function that always returns
    # a constant zero (black transparent) frame of the correct shape.
    H = canvas.height
    W = canvas.width
    constant_frame = np.zeros((H, W, 4), dtype=np.uint8)

    target_cls = get_style(target_style_id)

    def _constant_compose_frame(self, t, ctx, header, body, line_timings):
        return constant_frame.copy()

    with patch.object(target_cls, "compose_frame", _constant_compose_frame):
        # ── Call P_other.compose_frame again under the monkeypatch ─────────
        # P_other is a different class — the patch on P_target must not affect it.
        patched_frame = p_other.compose_frame(t, ctx, other_header, other_body, line_timings)

    # ── Assert byte-for-byte equality ─────────────────────────────────────
    assert np.array_equal(baseline_frame, patched_frame), (
        f"Monkeypatching {target_style_id!r}.compose_frame changed the output of "
        f"{other_style_id!r}.compose_frame.\n"
        f"  baseline shape: {baseline_frame.shape}, dtype: {baseline_frame.dtype}\n"
        f"  patched  shape: {patched_frame.shape}, dtype: {patched_frame.dtype}\n"
        f"  max diff: {np.abs(baseline_frame.astype(int) - patched_frame.astype(int)).max()}"
    )
