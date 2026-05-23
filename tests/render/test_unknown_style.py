"""Property test for unknown style identifier error.

# Feature: card-rendering-refactor, Property 2

**Validates: Requirements 2.3, 8.4**

Property 2: Unknown style identifier error.

For any string ``s`` that is not in ``available_styles()``, looking up ``s``
(via ``get_style(s)`` or via ``RenderConfig.from_settings({"style": s, ...})``)
SHALL raise ``UnknownStyleError`` whose message contains the literal string
``s`` and every currently-registered style identifier.
"""

from __future__ import annotations

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from video_creation.render.errors import UnknownStyleError
from video_creation.render.styles import available_styles, get_style
from video_creation.render.config import RenderConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _minimal_settings_dict(style_id: str) -> dict:
    """Build a minimal settings dict with the given style identifier."""
    return {
        "settings": {
            "style": style_id,
            "resolution_w": 1080,
            "resolution_h": 1920,
            "zoom": 1.0,
            "opacity": 1.0,
        }
    }


# ---------------------------------------------------------------------------
# Property tests
# ---------------------------------------------------------------------------


@given(s=st.text())
@settings(max_examples=100)
def test_get_style_raises_unknown_style_error(s: str) -> None:
    """Property 2 (get_style path): UnknownStyleError is raised for any
    string not in available_styles(), and the error message contains both
    the requested identifier and every registered identifier.

    **Validates: Requirements 2.3, 8.4**
    """
    assume(s not in available_styles())

    with pytest.raises(UnknownStyleError) as exc_info:
        get_style(s)

    error_message = str(exc_info.value)

    # The message must contain the requested (unknown) identifier.
    assert s in error_message, (
        f"UnknownStyleError message {error_message!r} does not contain "
        f"the requested identifier {s!r}"
    )

    # The message must contain every currently-registered identifier.
    for registered_id in available_styles():
        assert registered_id in error_message, (
            f"UnknownStyleError message {error_message!r} does not contain "
            f"registered identifier {registered_id!r}"
        )


@given(s=st.text())
@settings(max_examples=100)
def test_render_config_from_settings_raises_unknown_style_error(s: str) -> None:
    """Property 2 (RenderConfig.from_settings path): UnknownStyleError is
    raised for any style string not in available_styles(), and the error
    message contains both the requested identifier and every registered
    identifier.

    **Validates: Requirements 2.3, 8.4**
    """
    assume(s not in available_styles())

    settings_dict = _minimal_settings_dict(s)

    with pytest.raises(UnknownStyleError) as exc_info:
        RenderConfig.from_settings(settings_dict)

    error_message = str(exc_info.value)

    # The message must contain the requested (unknown) identifier.
    assert s in error_message, (
        f"UnknownStyleError message {error_message!r} does not contain "
        f"the requested identifier {s!r}"
    )

    # The message must contain every currently-registered identifier.
    for registered_id in available_styles():
        assert registered_id in error_message, (
            f"UnknownStyleError message {error_message!r} does not contain "
            f"registered identifier {registered_id!r}"
        )
