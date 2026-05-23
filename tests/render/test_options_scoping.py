"""Property test for per-style options scoping round-trip.

# Feature: card-rendering-refactor, Property 13

**Validates: Requirements 8.2**

Property 13: Per-style options scoping round-trip.

For any registered ``style_id`` and any ``opts`` matching its
``options_schema``, a ``RenderConfig`` built from::

    settings["settings"]["style"] = "<id>"
    settings["settings"]["style_options"][<id>] = opts

SHALL produce ``RenderConfig.style_options == opts``, regardless of what
is stored under sibling ``settings["settings"]["style_options"][<other_id>]``
blocks.

The ``from_settings`` method reads options from
``settings["settings"]["style_options"][<id>]``.  This test verifies that:

1. Only the active style's options are loaded into ``style_options``.
2. Options from sibling (non-active) styles do NOT appear in
   ``style_options``.
"""

from __future__ import annotations

import warnings
from typing import Any

import pytest
from hypothesis import given, settings as hyp_settings
from hypothesis import strategies as st

from video_creation.render.config import RenderConfig
from video_creation.render.errors import ConfigWarning
from video_creation.render.styles import available_styles, get_style


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _value_strategy_for_type(t: type) -> st.SearchStrategy:
    """Return a Hypothesis strategy that generates valid values for type *t*."""
    if t is str:
        # Use printable ASCII strings to avoid encoding surprises.
        return st.text(
            alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd")),
            min_size=1,
            max_size=20,
        )
    if t is int:
        # Use positive ints so karaoke_words_per_chunk coercion doesn't fire.
        return st.integers(min_value=1, max_value=100)
    if t is bool:
        return st.booleans()
    if t is float:
        return st.floats(min_value=0.1, max_value=10.0, allow_nan=False)
    # Fallback: just use None (will be skipped by the validator).
    return st.just(None)


def _opts_strategy_for_style(style_id: str) -> st.SearchStrategy[dict[str, Any]]:
    """Return a strategy that generates a valid options dict for *style_id*.

    Generates a dict containing ALL keys declared in the plugin's
    ``options_schema`` with values of the correct type.
    """
    plugin_cls = get_style(style_id)
    schema = plugin_cls.options_schema

    if not schema:
        return st.just({})

    # Build a fixed_dictionaries strategy from the schema.
    field_strategies = {
        key: _value_strategy_for_type(expected_type)
        for key, expected_type in schema.items()
    }
    return st.fixed_dictionaries(field_strategies)


def _sibling_opts_strategy_for_style(style_id: str) -> st.SearchStrategy[dict[str, Any]]:
    """Return a strategy for a sibling style's options dict.

    Picks a different registered style (if any) and generates valid options
    for it.  Returns an empty dict if there is only one registered style.
    """
    all_styles = available_styles()
    siblings = [s for s in all_styles if s != style_id]
    if not siblings:
        return st.just({})
    # Pick a fixed sibling (the first alphabetically) to keep things simple.
    sibling_id = siblings[0]
    return _opts_strategy_for_style(sibling_id)


def _build_settings_dict(
    style_id: str,
    opts: dict[str, Any],
    sibling_style_id: str | None,
    sibling_opts: dict[str, Any],
) -> dict[str, Any]:
    """Build a full settings dict for ``RenderConfig.from_settings``."""
    style_options_table: dict[str, Any] = {style_id: opts}
    if sibling_style_id and sibling_opts:
        style_options_table[sibling_style_id] = sibling_opts

    return {
        "settings": {
            "style": style_id,
            "style_options": style_options_table,
            "resolution_w": 1080,
            "resolution_h": 1920,
            "zoom": 1.0,
            "opacity": 1.0,
        },
        "reddit": {"thread": {"subreddit": "test_sub"}},
    }


# ---------------------------------------------------------------------------
# Parametrized property tests — one per registered style
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("style_id", available_styles())
def test_active_style_options_round_trip(style_id: str) -> None:
    """For each registered style, verify that valid opts round-trip through
    RenderConfig.from_settings unchanged.

    **Validates: Requirements 8.2**
    """
    all_styles = available_styles()
    siblings = [s for s in all_styles if s != style_id]
    sibling_id = siblings[0] if siblings else None

    plugin_cls = get_style(style_id)
    schema = plugin_cls.options_schema

    # Build a concrete opts dict with one valid value per schema key.
    opts: dict[str, Any] = {}
    for key, expected_type in schema.items():
        if expected_type is str:
            opts[key] = "light"
        elif expected_type is int:
            opts[key] = 3
        elif expected_type is bool:
            opts[key] = False
        elif expected_type is float:
            opts[key] = 1.0

    # Build sibling opts (arbitrary valid values for the sibling style).
    sibling_opts: dict[str, Any] = {}
    if sibling_id:
        sibling_cls = get_style(sibling_id)
        for key, expected_type in sibling_cls.options_schema.items():
            if expected_type is str:
                sibling_opts[key] = "dark"
            elif expected_type is int:
                sibling_opts[key] = 5
            elif expected_type is bool:
                sibling_opts[key] = True
            elif expected_type is float:
                sibling_opts[key] = 2.0

    settings_dict = _build_settings_dict(style_id, opts, sibling_id, sibling_opts)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", ConfigWarning)
        rc = RenderConfig.from_settings(settings_dict, is_production=False)

    # The active style's options must all be present and correct.
    for key, expected_value in opts.items():
        assert key in rc.style_options, (
            f"style_id={style_id!r}: key {key!r} missing from rc.style_options "
            f"(got {dict(rc.style_options)!r})"
        )
        assert rc.style_options[key] == expected_value, (
            f"style_id={style_id!r}: rc.style_options[{key!r}] = "
            f"{rc.style_options[key]!r}, expected {expected_value!r}"
        )

    # Sibling options must NOT bleed into the active style's options.
    if sibling_id:
        sibling_cls = get_style(sibling_id)
        sibling_schema_keys = set(sibling_cls.options_schema.keys())
        active_schema_keys = set(schema.keys())
        # Keys that are ONLY in the sibling schema (not shared with active)
        sibling_only_keys = sibling_schema_keys - active_schema_keys
        for key in sibling_only_keys:
            # If the sibling had a different value for a sibling-only key,
            # it must not appear in the active style's options.
            if key in sibling_opts and key not in opts:
                assert key not in rc.style_options, (
                    f"style_id={style_id!r}: sibling key {key!r} from "
                    f"{sibling_id!r} leaked into rc.style_options"
                )


@pytest.mark.parametrize("style_id", available_styles())
@given(data=st.data())
@hyp_settings(max_examples=50)
def test_active_style_options_round_trip_property(
    style_id: str, data: st.DataObject
) -> None:
    """Property 13: For any registered style_id and any opts matching its
    options_schema, RenderConfig.from_settings produces
    rc.style_options == opts (for the keys present in opts), regardless of
    what is under sibling style blocks.

    **Validates: Requirements 8.2**
    """
    all_styles = available_styles()
    siblings = [s for s in all_styles if s != style_id]
    sibling_id = siblings[0] if siblings else None

    # Draw valid opts for the active style.
    opts = data.draw(_opts_strategy_for_style(style_id), label="opts")

    # Draw sibling opts (may be empty if no siblings).
    sibling_opts: dict[str, Any] = {}
    if sibling_id:
        sibling_opts = data.draw(
            _sibling_opts_strategy_for_style(style_id), label="sibling_opts"
        )

    settings_dict = _build_settings_dict(style_id, opts, sibling_id, sibling_opts)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", ConfigWarning)
        rc = RenderConfig.from_settings(settings_dict, is_production=False)

    # --- Assertion 1: active style's options are present and correct -------
    for key, expected_value in opts.items():
        assert key in rc.style_options, (
            f"style_id={style_id!r}: key {key!r} missing from rc.style_options "
            f"(got {dict(rc.style_options)!r})"
        )
        assert rc.style_options[key] == expected_value, (
            f"style_id={style_id!r}: rc.style_options[{key!r}] = "
            f"{rc.style_options[key]!r}, expected {expected_value!r}"
        )

    # --- Assertion 2: sibling options do NOT bleed into active style -------
    if sibling_id:
        sibling_cls = get_style(sibling_id)
        active_schema_keys = set(get_style(style_id).options_schema.keys())
        sibling_only_keys = set(sibling_cls.options_schema.keys()) - active_schema_keys

        for key in sibling_only_keys:
            if key in sibling_opts:
                assert key not in rc.style_options, (
                    f"style_id={style_id!r}: sibling key {key!r} from "
                    f"{sibling_id!r} leaked into rc.style_options "
                    f"(rc.style_options={dict(rc.style_options)!r})"
                )
