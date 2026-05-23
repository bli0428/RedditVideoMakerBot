"""Property test for registry round-trip dispatch.

# Feature: card-rendering-refactor, Property 1

**Validates: Requirements 1.2, 2.1, 2.2, 2.4, 8.1, 8.3, 13.1**

Property 1: Registry round-trip dispatch.

For any registered ``style_id`` and any options conforming to the plugin's
``options_schema``, calling ``render_video(style_id=id, ...)`` SHALL
instantiate the class returned by ``get_style(id)`` with those options and
use it to produce the per-frame composition.

This test file verifies:
1. ``get_style(style_id)`` returns the registered class.
2. ``available_styles()`` includes the registered ``style_id``.
3. For any generated ``style_id`` (valid Python identifier), registering a
   ``CardStylePlugin`` subclass and then looking it up via ``get_style``
   returns the same class.
"""

from __future__ import annotations

import contextlib
import string
from typing import Any, Mapping
from unittest.mock import patch

import numpy as np
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from video_creation.render.styles import (
    _REGISTRY,
    available_styles,
    get_style,
    register_style,
)
from video_creation.render.styles.base import BodyAssets, CardStylePlugin
from video_creation.render.context import CanvasSpec, RenderContext
from video_creation.render.errors import UnknownStyleError


# ---------------------------------------------------------------------------
# Registry-reset helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def clean_registry():
    """Save and restore the ``_REGISTRY`` dict around each test.

    This prevents test-registered plugins from leaking into other tests and
    avoids ``ValueError: style_id already registered`` on repeated runs.
    """
    saved = dict(_REGISTRY)
    yield
    _REGISTRY.clear()
    _REGISTRY.update(saved)


@contextlib.contextmanager
def _isolated_registry():
    """Context manager version of the registry reset for use inside @given tests.

    Hypothesis does not reset function-scoped fixtures between generated
    examples, so property tests that modify the registry must use this
    context manager instead.
    """
    saved = dict(_REGISTRY)
    try:
        yield
    finally:
        _REGISTRY.clear()
        _REGISTRY.update(saved)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_plugin_class(style_id: str, options_schema: Mapping[str, type] | None = None):
    """Dynamically create a minimal ``CardStylePlugin`` subclass.

    The subclass has trivial implementations of all abstract methods so it
    can be instantiated and called without real rendering infrastructure.
    """
    if options_schema is None:
        options_schema = {}

    _schema = dict(options_schema)
    _sid = style_id

    class _DynamicPlugin(CardStylePlugin):
        style_id = _sid
        options_schema = _schema

        def render_header(self, ctx: RenderContext) -> np.ndarray:
            return np.zeros((1, 1, 4), dtype=np.uint8)

        def render_body(self, ctx: RenderContext, line_timings) -> BodyAssets:
            return BodyAssets()

        def compose_frame(
            self,
            t: float,
            ctx: RenderContext,
            header: np.ndarray,
            body: BodyAssets,
            line_timings,
        ) -> np.ndarray:
            return np.zeros((ctx.canvas.height, ctx.canvas.width, 4), dtype=np.uint8)

    _DynamicPlugin.__name__ = f"DynamicPlugin_{style_id}"
    _DynamicPlugin.__qualname__ = f"DynamicPlugin_{style_id}"

    return _DynamicPlugin


def _make_render_context(canvas: CanvasSpec | None = None) -> RenderContext:
    """Return a minimal ``RenderContext`` for testing."""
    if canvas is None:
        canvas = CanvasSpec(width=1, height=1, zoom=1.0, opacity=1.0)
    return RenderContext(
        title="Test Title",
        body_text="Test body text.",
        author="test_author",
        avatar_url="",
        subreddit="test",
        upvotes=42,
        num_comments=7,
        canvas=canvas,
        theme="light",
    )


# ---------------------------------------------------------------------------
# Strategy: valid style_ids (non-empty, starts with letter, no built-in ids)
# ---------------------------------------------------------------------------

_STYLE_ID_ALPHABET = string.ascii_lowercase + string.digits + "-"

_BUILTIN_IDS = frozenset(
    ("custom-card", "custom-karaoke", "reddit-card", "reddit-karaoke")
)

_style_id_strategy = st.text(
    alphabet=_STYLE_ID_ALPHABET,
    min_size=3,
    max_size=20,
).filter(
    lambda s: (
        s[0].isalpha()
        and s not in _BUILTIN_IDS
        and not s.startswith("-")
        and not s.endswith("-")
        and "--" not in s
    )
)


# ---------------------------------------------------------------------------
# Unit tests (non-property)
# ---------------------------------------------------------------------------


def test_get_style_returns_registered_class(clean_registry):
    """``get_style(style_id)`` returns the class registered under that id."""
    plugin_cls = _make_plugin_class("test-unit-style")
    register_style(plugin_cls)

    result = get_style("test-unit-style")
    assert result is plugin_cls


def test_available_styles_includes_registered_id(clean_registry):
    """``available_styles()`` includes a freshly registered style_id."""
    plugin_cls = _make_plugin_class("test-available-style")
    register_style(plugin_cls)

    assert "test-available-style" in available_styles()


def test_get_style_raises_unknown_style_error_for_unregistered(clean_registry):
    """``get_style`` raises ``UnknownStyleError`` for an unregistered id."""
    with pytest.raises(UnknownStyleError):
        get_style("definitely-not-registered-xyz")


def test_register_style_duplicate_raises(clean_registry):
    """Registering the same ``style_id`` twice raises ``ValueError``."""
    plugin_cls = _make_plugin_class("test-dup-style")
    register_style(plugin_cls)

    plugin_cls2 = _make_plugin_class("test-dup-style")
    with pytest.raises(ValueError, match="already registered"):
        register_style(plugin_cls2)


def test_compose_frame_called_on_registered_plugin(clean_registry):
    """Instantiating the class from ``get_style`` and calling ``compose_frame``
    works correctly — the spy confirms the method is invoked.
    """
    plugin_cls = _make_plugin_class("test-compose-style")
    register_style(plugin_cls)

    canvas = CanvasSpec(width=4, height=4, zoom=1.0, opacity=1.0)
    ctx = _make_render_context(canvas)

    retrieved_cls = get_style("test-compose-style")
    assert retrieved_cls is plugin_cls

    instance = retrieved_cls(options={}, canvas=canvas)

    with patch.object(instance, "compose_frame", wraps=instance.compose_frame) as spy:
        header = instance.render_header(ctx)
        body = instance.render_body(ctx, ())
        frame = instance.compose_frame(0.0, ctx, header, body, ())

        spy.assert_called_once()
        assert frame.shape == (4, 4, 4)
        assert frame.dtype == np.uint8


# ---------------------------------------------------------------------------
# Property-based tests
# ---------------------------------------------------------------------------


@given(style_id=_style_id_strategy)
@settings(
    max_examples=50,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_registry_round_trip_get_style(style_id, clean_registry):
    """Property 1 (partial): ``get_style(id)`` returns the registered class.

    **Validates: Requirements 2.1, 2.2, 2.4**

    For any generated ``style_id``:
    - Registering a plugin under that id and calling ``get_style(id)``
      returns the same class.
    - ``available_styles()`` includes the id after registration.
    """
    with _isolated_registry():
        plugin_cls = _make_plugin_class(style_id)
        register_style(plugin_cls)

        # Round-trip: get_style returns the exact class we registered.
        retrieved = get_style(style_id)
        assert retrieved is plugin_cls, (
            f"get_style({style_id!r}) returned {retrieved!r}, expected {plugin_cls!r}"
        )

        # available_styles() must include the registered id.
        assert style_id in available_styles(), (
            f"{style_id!r} not found in available_styles() = {available_styles()!r}"
        )


@given(style_id=_style_id_strategy)
@settings(
    max_examples=50,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_registry_round_trip_compose_frame_dispatch(style_id, clean_registry):
    """Property 1 (full): ``get_style(id)`` returns the class whose
    ``compose_frame`` is used for per-frame composition.

    **Validates: Requirements 1.2, 2.1, 2.2, 2.4, 8.1, 8.3, 13.1**

    For any registered ``style_id``:
    - The class returned by ``get_style(id)`` can be instantiated with empty
      options and a minimal canvas.
    - Calling ``compose_frame`` on the instance (via a spy) confirms the
      correct plugin class is dispatched.
    """
    with _isolated_registry():
        plugin_cls = _make_plugin_class(style_id)
        register_style(plugin_cls)

        canvas = CanvasSpec(width=2, height=2, zoom=1.0, opacity=1.0)
        ctx = _make_render_context(canvas)

        retrieved_cls = get_style(style_id)
        assert retrieved_cls is plugin_cls

        instance = retrieved_cls(options={}, canvas=canvas)

        # Spy on compose_frame to confirm it is called.
        with patch.object(instance, "compose_frame", wraps=instance.compose_frame) as spy:
            header = instance.render_header(ctx)
            body = instance.render_body(ctx, ())
            frame = instance.compose_frame(0.0, ctx, header, body, ())

            # compose_frame was called exactly once.
            spy.assert_called_once()

            # The returned frame has the correct shape and dtype.
            assert isinstance(frame, np.ndarray), (
                f"compose_frame returned {type(frame)!r}, expected np.ndarray"
            )
            assert frame.shape == (canvas.height, canvas.width, 4), (
                f"Frame shape {frame.shape!r} != expected ({canvas.height}, {canvas.width}, 4)"
            )
            assert frame.dtype == np.uint8, (
                f"Frame dtype {frame.dtype!r} != uint8"
            )
