"""Property test for chunk_size coercion.

# Feature: card-rendering-refactor, Property 10

Property 10: Invalid chunk_size is replaced by the documented default
Validates: Requirements 7.5

For any ``chunk_size <= 0`` in the parsed ``[settings.style.<id>]`` block of a
karaoke-supporting plugin, the resulting
``RenderConfig.style_options["karaoke_words_per_chunk"]`` SHALL equal the
documented default ``3``, and a ``ConfigWarning`` SHALL be emitted.
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from video_creation.render.config import RenderConfig
from video_creation.render.errors import ConfigWarning
from video_creation.render.styles import available_styles, get_style


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _karaoke_style_ids() -> list[str]:
    """Return the style IDs of all registered karaoke-supporting plugins.

    A plugin is considered karaoke-supporting if its ``options_schema``
    contains the ``"karaoke_words_per_chunk"`` key.
    """
    return [
        sid
        for sid in available_styles()
        if "karaoke_words_per_chunk" in get_style(sid).options_schema
    ]


def _settings_dict_with_chunk_size(style_id: str, chunk_size: int) -> dict:
    """Build a minimal settings dict that sets ``karaoke_words_per_chunk``
    for the given *style_id* to *chunk_size*."""
    return {
        "settings": {
            "style": style_id,
            "resolution_w": 1080,
            "resolution_h": 1920,
            "zoom": 1.0,
            "opacity": 1.0,
            "style_options": {
                style_id: {
                    "karaoke_words_per_chunk": chunk_size,
                }
            },
        }
    }


# ---------------------------------------------------------------------------
# Property 10
# ---------------------------------------------------------------------------

@given(chunk_size=st.integers(max_value=0))
@settings(max_examples=200)
def test_invalid_chunk_size_coerced_to_default(chunk_size: int) -> None:
    """Property 10: Invalid chunk_size is replaced by the documented default.

    **Validates: Requirements 7.5**

    For any ``chunk_size <= 0`` supplied in the ``[settings.style.<id>]``
    block of a karaoke-supporting plugin:
    - ``RenderConfig.style_options["karaoke_words_per_chunk"]`` must equal
      the documented default ``3``.
    - A ``ConfigWarning`` must be emitted.
    """
    karaoke_ids = _karaoke_style_ids()
    assert karaoke_ids, (
        "No karaoke-supporting plugins are registered; "
        "cannot run Property 10 test."
    )

    for style_id in karaoke_ids:
        settings_dict = _settings_dict_with_chunk_size(style_id, chunk_size)

        with pytest.warns(ConfigWarning):
            rc = RenderConfig.from_settings(settings_dict)

        assert rc.style_options["karaoke_words_per_chunk"] == 3, (
            f"Style {style_id!r}: expected karaoke_words_per_chunk=3 after "
            f"coercion of invalid value {chunk_size!r}, "
            f"got {rc.style_options['karaoke_words_per_chunk']!r}"
        )
