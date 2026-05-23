"""Unit tests for RenderConfig.from_settings (task 5.7).

Tests cover:
- New-schema style resolution and option validation
- Legacy flat-key fallback and style_id mapping
- karaoke_words_per_chunk <= 0 coercion
- UnknownStyleError for unregistered style ids
- ConfigError for type mismatches
- ConfigWarning for unknown option keys and legacy usage
"""

from __future__ import annotations

import warnings
from typing import Any, Mapping
from unittest.mock import patch

import pytest

from video_creation.render.config import RenderConfig, _DEFAULT_KARAOKE_WORDS_PER_CHUNK
from video_creation.render.context import CanvasSpec
from video_creation.render.errors import ConfigError, ConfigWarning, UnknownStyleError


# ---------------------------------------------------------------------------
# Helpers — minimal settings dicts
# ---------------------------------------------------------------------------

def _base_settings(**overrides: Any) -> dict[str, Any]:
    """Return a minimal settings dict with sensible defaults."""
    s: dict[str, Any] = {
        "resolution_w": 1080,
        "resolution_h": 1920,
        "zoom": 1.0,
        "opacity": 1.0,
        "theme": "light",
    }
    s.update(overrides)
    return {"settings": s, "reddit": {"thread": {"subreddit": "test_sub"}}}


# ---------------------------------------------------------------------------
# Fake plugin for registry isolation
# ---------------------------------------------------------------------------

class _FakePlugin:
    """Minimal CardStylePlugin stand-in for testing config validation."""
    style_id = "fake-style"
    options_schema: Mapping[str, type] = {
        "theme": str,
        "karaoke_words_per_chunk": int,
        "dismiss_title_on_body": bool,
    }


# ---------------------------------------------------------------------------
# New-schema tests
# ---------------------------------------------------------------------------

class TestNewSchema:
    """Tests for the new settings["settings"]["style"] = "<id>" path."""

    def _settings_with_style(
        self,
        style_id: str,
        style_options: dict[str, Any] | None = None,
        **extra_settings: Any,
    ) -> dict[str, Any]:
        d = _base_settings(style=style_id, **extra_settings)
        if style_options:
            d["settings"]["style_options"] = {style_id: style_options}
        return d

    def test_unknown_style_raises_unknown_style_error(self) -> None:
        """UnknownStyleError is raised for an unregistered style id."""
        cfg = self._settings_with_style("nonexistent-style")
        with pytest.raises(UnknownStyleError) as exc_info:
            RenderConfig.from_settings(cfg)
        err = exc_info.value
        assert "nonexistent-style" in str(err)

    def test_unknown_style_error_lists_registered_ids(self) -> None:
        """UnknownStyleError message lists all registered style ids."""
        from video_creation.render.styles import available_styles
        cfg = self._settings_with_style("no-such-style")
        with pytest.raises(UnknownStyleError) as exc_info:
            RenderConfig.from_settings(cfg)
        err_msg = str(exc_info.value)
        for sid in available_styles():
            assert sid in err_msg

    def test_valid_style_resolves_correctly(self) -> None:
        """A registered style id is accepted and stored on the config."""
        from video_creation.render.styles import available_styles
        registered = available_styles()
        if not registered:
            pytest.skip("No styles registered yet")
        style_id = registered[0]
        cfg = self._settings_with_style(style_id)
        rc = RenderConfig.from_settings(cfg)
        assert rc.style_id == style_id

    def test_canvas_fields_populated(self) -> None:
        """Canvas geometry is read from settings."""
        from video_creation.render.styles import available_styles
        registered = available_styles()
        if not registered:
            pytest.skip("No styles registered yet")
        style_id = registered[0]
        cfg = self._settings_with_style(style_id)
        rc = RenderConfig.from_settings(cfg)
        assert rc.canvas == CanvasSpec(width=1080, height=1920, zoom=1.0, opacity=1.0)

    def test_subreddit_populated(self) -> None:
        """Subreddit is read from reddit.thread.subreddit."""
        from video_creation.render.styles import available_styles
        registered = available_styles()
        if not registered:
            pytest.skip("No styles registered yet")
        style_id = registered[0]
        cfg = self._settings_with_style(style_id)
        rc = RenderConfig.from_settings(cfg)
        assert rc.subreddit == "test_sub"

    def test_type_mismatch_raises_config_error(self) -> None:
        """ConfigError is raised when a style option has the wrong type."""
        from video_creation.render.styles import available_styles, get_style
        registered = available_styles()
        # Find a style with a str option in its schema.
        target_style = None
        target_key = None
        for sid in registered:
            plugin_cls = get_style(sid)
            for k, t in plugin_cls.options_schema.items():
                if t is str:
                    target_style = sid
                    target_key = k
                    break
            if target_style:
                break
        if not target_style:
            pytest.skip("No registered style with a str option")
        cfg = self._settings_with_style(
            target_style, style_options={target_key: 12345}  # int instead of str
        )
        with pytest.raises(ConfigError):
            RenderConfig.from_settings(cfg)

    def test_unknown_option_key_emits_config_warning(self) -> None:
        """ConfigWarning is emitted for unknown option keys."""
        from video_creation.render.styles import available_styles
        registered = available_styles()
        if not registered:
            pytest.skip("No styles registered yet")
        style_id = registered[0]
        cfg = self._settings_with_style(
            style_id, style_options={"totally_unknown_key_xyz": "value"}
        )
        with pytest.warns(ConfigWarning, match="unknown option"):
            RenderConfig.from_settings(cfg)

    def test_karaoke_words_per_chunk_zero_coerced(self) -> None:
        """karaoke_words_per_chunk=0 is coerced to the default with a warning."""
        from video_creation.render.styles import available_styles, get_style
        registered = available_styles()
        karaoke_style = None
        for sid in registered:
            plugin_cls = get_style(sid)
            if "karaoke_words_per_chunk" in plugin_cls.options_schema:
                karaoke_style = sid
                break
        if not karaoke_style:
            pytest.skip("No karaoke style registered")
        cfg = self._settings_with_style(
            karaoke_style, style_options={"karaoke_words_per_chunk": 0}
        )
        with pytest.warns(ConfigWarning):
            rc = RenderConfig.from_settings(cfg)
        assert rc.style_options["karaoke_words_per_chunk"] == _DEFAULT_KARAOKE_WORDS_PER_CHUNK

    def test_karaoke_words_per_chunk_negative_coerced(self) -> None:
        """karaoke_words_per_chunk=-5 is coerced to the default with a warning."""
        from video_creation.render.styles import available_styles, get_style
        registered = available_styles()
        karaoke_style = None
        for sid in registered:
            plugin_cls = get_style(sid)
            if "karaoke_words_per_chunk" in plugin_cls.options_schema:
                karaoke_style = sid
                break
        if not karaoke_style:
            pytest.skip("No karaoke style registered")
        cfg = self._settings_with_style(
            karaoke_style, style_options={"karaoke_words_per_chunk": -5}
        )
        with pytest.warns(ConfigWarning):
            rc = RenderConfig.from_settings(cfg)
        assert rc.style_options["karaoke_words_per_chunk"] == _DEFAULT_KARAOKE_WORDS_PER_CHUNK

    def test_is_production_default_true(self) -> None:
        """is_production defaults to True."""
        from video_creation.render.styles import available_styles
        registered = available_styles()
        if not registered:
            pytest.skip("No styles registered yet")
        style_id = registered[0]
        cfg = self._settings_with_style(style_id)
        rc = RenderConfig.from_settings(cfg)
        assert rc.is_production is True

    def test_is_production_can_be_set_false(self) -> None:
        """is_production=False is respected."""
        from video_creation.render.styles import available_styles
        registered = available_styles()
        if not registered:
            pytest.skip("No styles registered yet")
        style_id = registered[0]
        cfg = self._settings_with_style(style_id)
        rc = RenderConfig.from_settings(cfg, is_production=False)
        assert rc.is_production is False

    def test_debug_dump_intermediates_default_false(self) -> None:
        """debug_dump_intermediates defaults to False."""
        from video_creation.render.styles import available_styles
        registered = available_styles()
        if not registered:
            pytest.skip("No styles registered yet")
        style_id = registered[0]
        cfg = self._settings_with_style(style_id)
        rc = RenderConfig.from_settings(cfg)
        assert rc.debug_dump_intermediates is False


# ---------------------------------------------------------------------------
# Legacy flat-key fallback tests
# ---------------------------------------------------------------------------

class TestLegacyFallback:
    """Tests for the legacy card_style + body_style → style_id mapping."""

    def _legacy_settings(
        self,
        card_style: str = "reddit",
        body_style: str = "karaoke",
        **extra: Any,
    ) -> dict[str, Any]:
        return _base_settings(
            card_style=card_style,
            body_style=body_style,
            **extra,
        )

    def test_custom_card_mapping(self) -> None:
        """card_style=custom + body_style=card → style_id=custom-card."""
        cfg = self._legacy_settings("custom", "card")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", ConfigWarning)
            rc = RenderConfig.from_settings(cfg)
        assert rc.style_id == "custom-card"

    def test_custom_karaoke_mapping(self) -> None:
        """card_style=custom + body_style=karaoke → style_id=custom-karaoke."""
        cfg = self._legacy_settings("custom", "karaoke")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", ConfigWarning)
            rc = RenderConfig.from_settings(cfg)
        assert rc.style_id == "custom-karaoke"

    def test_reddit_card_mapping(self) -> None:
        """card_style=reddit + body_style=card → style_id=reddit-card."""
        cfg = self._legacy_settings("reddit", "card")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", ConfigWarning)
            rc = RenderConfig.from_settings(cfg)
        assert rc.style_id == "reddit-card"

    def test_reddit_karaoke_mapping(self) -> None:
        """card_style=reddit + body_style=karaoke → style_id=reddit-karaoke."""
        cfg = self._legacy_settings("reddit", "karaoke")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", ConfigWarning)
            rc = RenderConfig.from_settings(cfg)
        assert rc.style_id == "reddit-karaoke"

    def test_default_fallback_when_no_style_keys(self) -> None:
        """Missing card_style/body_style defaults to reddit-karaoke."""
        cfg = _base_settings()  # no card_style or body_style
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", ConfigWarning)
            rc = RenderConfig.from_settings(cfg)
        assert rc.style_id == "reddit-karaoke"

    def test_legacy_emits_config_warning(self) -> None:
        """Legacy flat-key config emits a ConfigWarning advising migration."""
        cfg = self._legacy_settings("reddit", "karaoke")
        with pytest.warns(ConfigWarning, match="legacy"):
            RenderConfig.from_settings(cfg)

    def test_legacy_warning_mentions_new_style_id(self) -> None:
        """The migration warning mentions the resolved style_id."""
        cfg = self._legacy_settings("custom", "card")
        with pytest.warns(ConfigWarning) as record:
            RenderConfig.from_settings(cfg)
        assert any("custom-card" in str(w.message) for w in record.list)

    def test_legacy_karaoke_words_per_chunk_zero_coerced(self) -> None:
        """Legacy karaoke_words_per_chunk=0 is coerced to default."""
        cfg = self._legacy_settings("reddit", "karaoke", karaoke_words_per_chunk=0)
        with pytest.warns(ConfigWarning):
            rc = RenderConfig.from_settings(cfg)
        assert rc.style_options.get("karaoke_words_per_chunk") == _DEFAULT_KARAOKE_WORDS_PER_CHUNK

    def test_legacy_karaoke_words_per_chunk_negative_coerced(self) -> None:
        """Legacy karaoke_words_per_chunk=-1 is coerced to default."""
        cfg = self._legacy_settings("reddit", "karaoke", karaoke_words_per_chunk=-1)
        with pytest.warns(ConfigWarning):
            rc = RenderConfig.from_settings(cfg)
        assert rc.style_options.get("karaoke_words_per_chunk") == _DEFAULT_KARAOKE_WORDS_PER_CHUNK

    def test_legacy_theme_propagated(self) -> None:
        """Theme from flat settings is propagated to style_options."""
        cfg = self._legacy_settings("reddit", "karaoke", theme="dark")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", ConfigWarning)
            rc = RenderConfig.from_settings(cfg)
        assert rc.theme == "dark"

    def test_legacy_dismiss_title_on_body_propagated(self) -> None:
        """dismiss_title_on_body from flat settings is propagated."""
        cfg = self._legacy_settings("reddit", "karaoke", dismiss_title_on_body=True)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", ConfigWarning)
            rc = RenderConfig.from_settings(cfg)
        assert rc.style_options.get("dismiss_title_on_body") is True


# ---------------------------------------------------------------------------
# Frozen dataclass tests
# ---------------------------------------------------------------------------

class TestFrozenDataclass:
    """RenderConfig must be immutable (frozen=True)."""

    def test_render_config_is_frozen(self) -> None:
        """Assigning to a field raises FrozenInstanceError."""
        from video_creation.render.styles import available_styles
        registered = available_styles()
        if not registered:
            pytest.skip("No styles registered yet")
        style_id = registered[0]
        cfg = _base_settings(style=style_id)
        rc = RenderConfig.from_settings(cfg)
        with pytest.raises(Exception):  # FrozenInstanceError or AttributeError
            rc.style_id = "other-style"  # type: ignore[misc]
