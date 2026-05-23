"""Property test for options schema reflection.

# Feature: card-rendering-refactor, Property 15

**Validates: Requirements 13.3**

Property 15: Options schema reflection.

For any registered ``style_id``, ``plugin_options_schema(style_id)`` SHALL
return a non-empty ``Mapping[str, type]`` equal to
``get_style(style_id).options_schema``.

Also verifies that ``plugin_options_schema`` raises ``UnknownStyleError``
for an unregistered style identifier.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from video_creation.render.api import plugin_options_schema
from video_creation.render.errors import UnknownStyleError
from video_creation.render.styles import available_styles, get_style


# ---------------------------------------------------------------------------
# Parametrized tests over every registered style
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("style_id", available_styles())
def test_plugin_options_schema_is_non_empty_mapping(style_id: str) -> None:
    """For each registered style_id, plugin_options_schema returns a
    non-empty Mapping[str, type].

    **Validates: Requirements 13.3**
    """
    schema = plugin_options_schema(style_id)

    # Must be a Mapping
    assert isinstance(schema, Mapping), (
        f"plugin_options_schema({style_id!r}) returned {type(schema)!r}, "
        f"expected a Mapping"
    )

    # Must be non-empty
    assert len(schema) > 0, (
        f"plugin_options_schema({style_id!r}) returned an empty mapping"
    )

    # All values must be types
    for key, val in schema.items():
        assert isinstance(key, str), (
            f"options_schema key {key!r} for style {style_id!r} is not a str"
        )
        assert isinstance(val, type), (
            f"options_schema value for key {key!r} in style {style_id!r} "
            f"is {val!r}, expected a type"
        )


@pytest.mark.parametrize("style_id", available_styles())
def test_plugin_options_schema_equals_class_attribute(style_id: str) -> None:
    """For each registered style_id, plugin_options_schema returns a mapping
    equal to get_style(style_id).options_schema.

    **Validates: Requirements 13.3**
    """
    schema_from_api = plugin_options_schema(style_id)
    schema_from_class = get_style(style_id).options_schema

    assert dict(schema_from_api) == dict(schema_from_class), (
        f"plugin_options_schema({style_id!r}) returned {dict(schema_from_api)!r} "
        f"but get_style({style_id!r}).options_schema is {dict(schema_from_class)!r}"
    )


# ---------------------------------------------------------------------------
# Property test: unknown style raises UnknownStyleError
# ---------------------------------------------------------------------------


@given(s=st.text())
@settings(max_examples=100)
def test_plugin_options_schema_raises_for_unknown_style(s: str) -> None:
    """For any string not in available_styles(), plugin_options_schema SHALL
    raise UnknownStyleError.

    **Validates: Requirements 13.3**
    """
    assume(s not in available_styles())

    with pytest.raises(UnknownStyleError):
        plugin_options_schema(s)
