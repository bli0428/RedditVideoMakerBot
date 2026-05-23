"""Property test for theme-aware header pixels.

# Feature: card-rendering-refactor, Property 11

**Validates: Requirements 7.3**

Property 11: Theme setting changes header pixels for theme-aware plugins.

For any theme-aware plugin and any ``RenderContext`` differing only in
``theme`` (``"light"`` vs ``"dark"``), the central card-background pixel of
``plugin.render_header(ctx)`` SHALL differ between the two renders.

Note: The current plugins (custom-card, custom-karaoke, reddit-card,
reddit-karaoke) all declare ``"theme": str`` in their ``options_schema`` but
do not yet implement theme-based color changes — they use a white background
regardless of theme.  The tests below are therefore marked ``xfail`` until
theme support is implemented.
"""

from __future__ import annotations

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

# Ensure all four plugins are registered.
import video_creation.render.styles  # noqa: F401

from video_creation.render.context import CanvasSpec, RenderContext
from video_creation.render.styles import available_styles, get_style


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _theme_aware_styles() -> list[str]:
    """Return style IDs whose options_schema includes a 'theme' key."""
    return [
        sid for sid in available_styles()
        if "theme" in get_style(sid).options_schema
    ]


def _make_canvas(width: int = 540, height: int = 960) -> CanvasSpec:
    return CanvasSpec(width=width, height=height, zoom=1.0, opacity=1.0)


def _make_ctx(
    title: str,
    body_text: str,
    author: str,
    theme: str,
    canvas: CanvasSpec | None = None,
) -> RenderContext:
    return RenderContext(
        title=title,
        body_text=body_text,
        author=author,
        avatar_url="",
        subreddit="test",
        upvotes=42,
        num_comments=7,
        canvas=canvas or _make_canvas(),
        theme=theme,
    )


# ---------------------------------------------------------------------------
# Hypothesis strategy
# ---------------------------------------------------------------------------

@st.composite
def render_context_pair_strategy(draw):
    """Generate a (ctx_light, ctx_dark) pair identical except for theme."""
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
    canvas = _make_canvas()
    ctx_light = _make_ctx(title=title, body_text=body_text, author=author,
                          theme="light", canvas=canvas)
    ctx_dark  = _make_ctx(title=title, body_text=body_text, author=author,
                          theme="dark",  canvas=canvas)
    return ctx_light, ctx_dark


# ---------------------------------------------------------------------------
# Property tests — one per theme-aware plugin
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("style_id", _theme_aware_styles())
@pytest.mark.xfail(
    reason=(
        "Theme-based color changes are not yet implemented in any plugin. "
        "All plugins currently use a white background regardless of the "
        "'theme' option.  Remove xfail once dark-theme palettes are added "
        "(Requirement 7.3)."
    ),
    strict=True,
)
@given(ctx_pair=render_context_pair_strategy())
@settings(max_examples=10)
def test_theme_changes_header_central_pixel(
    style_id: str,
    ctx_pair: tuple[RenderContext, RenderContext],
) -> None:
    """Property 11: central header pixel differs between light and dark themes.

    **Validates: Requirements 7.3**

    Renders the header twice with identical contexts except for ``theme``.
    Asserts that the central pixel (at ``[H//2, W//2]``) of the RGBA ndarray
    returned by ``render_header`` differs between the two renders.
    """
    ctx_light, ctx_dark = ctx_pair

    plugin_cls = get_style(style_id)
    # Pass theme through options so plugins that read from options also see it.
    plugin_light = plugin_cls(options={"theme": "light"}, canvas=ctx_light.canvas)
    plugin_dark  = plugin_cls(options={"theme": "dark"},  canvas=ctx_dark.canvas)

    header_light = plugin_light.render_header(ctx_light)
    header_dark  = plugin_dark.render_header(ctx_dark)

    # Both headers must be valid RGBA ndarrays.
    assert isinstance(header_light, np.ndarray), (
        f"[{style_id}] render_header(light) returned {type(header_light).__name__}"
    )
    assert isinstance(header_dark, np.ndarray), (
        f"[{style_id}] render_header(dark) returned {type(header_dark).__name__}"
    )

    H_l, W_l = header_light.shape[:2]
    H_d, W_d = header_dark.shape[:2]

    # Sample the central pixel of each header.
    pixel_light = header_light[H_l // 2, W_l // 2]
    pixel_dark  = header_dark[H_d // 2, W_d // 2]

    assert not np.array_equal(pixel_light, pixel_dark), (
        f"[{style_id}] Central header pixel is identical for light and dark "
        f"themes: light={pixel_light.tolist()}, dark={pixel_dark.tolist()}. "
        f"Theme-aware color changes are required by Requirement 7.3."
    )
