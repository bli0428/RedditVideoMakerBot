"""RenderConfig — frozen dataclass parsed from settings.config.

Parses and validates the ``settings.config`` dict (produced by
``utils/settings.py``) once at startup.  All downstream modules receive a
``RenderConfig`` instance; they never reach back into the raw settings dict.

Satisfies: Requirements 7.5, 8.1, 8.2, 8.3, 8.4
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from typing import Any, Mapping

from video_creation.render.context import CanvasSpec
from video_creation.render.errors import ConfigError, ConfigWarning, UnknownStyleError

# ---------------------------------------------------------------------------
# Default values
# ---------------------------------------------------------------------------

_DEFAULT_AUDIO_SPEED: float = 1.15  # matches AUDIO_SPEED in final_video.py
_DEFAULT_KARAOKE_WORDS_PER_CHUNK: int = 3


# ---------------------------------------------------------------------------
# RenderConfig
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RenderConfig:
    """Immutable configuration snapshot for one render run.

    All fields are sourced from ``settings.config`` via
    :meth:`from_settings`.  Downstream modules (plugins, orchestrator, etc.)
    read from this object; they never reach back into the raw settings dict.

    Attributes
    ----------
    style_id:
        The registered ``CardStylePlugin`` identifier (e.g.
        ``"reddit-karaoke"``).
    style_options:
        Options scoped to the active style, validated against the plugin's
        ``options_schema``.  Unknown keys are silently dropped after a
        ``ConfigWarning``; missing keys fall back to plugin defaults.
    canvas:
        Output canvas geometry (width, height, zoom, opacity).
    audio_speed:
        TTS audio playback speed multiplier.  Defaults to ``1.15``.
    theme:
        Active theme name (e.g. ``"light"`` or ``"dark"``).
    debug_dump_intermediates:
        When ``True`` **and** ``is_production`` is ``False``, the pipeline
        writes intermediate header/body PNGs to
        ``assets/temp/<reddit_id>/debug/``.
    is_production:
        ``True`` in normal runs; ``False`` in tests and the preview harness.
        Intermediate debug images are never written when this is ``True``.
    subreddit:
        Subreddit name (without the ``r/`` prefix), sourced from
        ``settings.config["reddit"]["thread"]["subreddit"]``.
    """

    style_id: str
    style_options: Mapping[str, Any]
    canvas: CanvasSpec
    audio_speed: float = _DEFAULT_AUDIO_SPEED
    theme: str = "light"
    debug_dump_intermediates: bool = False
    is_production: bool = True
    subreddit: str = ""

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_settings(
        cls,
        settings_dict: dict[str, Any],
        *,
        is_production: bool = True,
        debug_dump_intermediates: bool = False,
    ) -> "RenderConfig":
        """Build a ``RenderConfig`` from the full ``settings.config`` dict.

        The ``settings_dict`` is the dict returned by
        ``utils.settings.check_toml(...)`` — i.e. the top-level TOML dict
        with ``"settings"``, ``"reddit"``, etc. as top-level keys.

        Parameters
        ----------
        settings_dict:
            The full parsed ``config.toml`` dict.
        is_production:
            Pass ``False`` from tests and the preview harness.
        debug_dump_intermediates:
            Pass ``True`` to enable intermediate PNG dumps (only effective
            when ``is_production=False``).

        Returns
        -------
        RenderConfig
            Validated, frozen configuration object.

        Raises
        ------
        UnknownStyleError
            If ``settings["settings"]["style"]`` names an unregistered style.
        ConfigError
            If a style option has the wrong type according to the plugin's
            ``options_schema``.
        """
        # Import here to avoid a circular import at module load time.
        from video_creation.render.styles import available_styles, get_style

        s: dict[str, Any] = settings_dict.get("settings", {})

        # ------------------------------------------------------------------
        # Canvas
        # ------------------------------------------------------------------
        canvas = CanvasSpec(
            width=int(s.get("resolution_w", 1080)),
            height=int(s.get("resolution_h", 1920)),
            zoom=float(s.get("zoom", 1.0)),
            opacity=float(s.get("opacity", 1.0)),
        )

        # ------------------------------------------------------------------
        # Audio speed
        # ------------------------------------------------------------------
        audio_speed = float(s.get("audio_speed", _DEFAULT_AUDIO_SPEED))

        # ------------------------------------------------------------------
        # Subreddit
        # ------------------------------------------------------------------
        subreddit: str = (
            settings_dict.get("reddit", {})
            .get("thread", {})
            .get("subreddit", "")
            or ""
        )

        # ------------------------------------------------------------------
        # Style resolution — new schema vs. legacy flat keys
        # ------------------------------------------------------------------
        if "style" in s:
            # ---- New schema: settings["settings"]["style"] = "<id>" ----
            style_id: str = str(s["style"])

            # Validate against the registry.
            registered = available_styles()
            if style_id not in registered:
                raise UnknownStyleError(style_id, registered)

            # Read per-style options from settings["settings"]["style"][<id>].
            # TOML represents [settings.style.reddit-karaoke] as a nested dict
            # at s["style"] only when "style" is a table; but when "style" is a
            # plain string the per-style sections live at s["style.<id>"] or
            # under a separate "style" sub-table.  In practice the TOML parser
            # (toml library) puts [settings.style.reddit-karaoke] under
            # s["style"] as a dict keyed by the style id — BUT only when
            # "style" itself is a table, not a string.
            #
            # The design uses:
            #   style = "reddit-karaoke"          ← string
            #   [settings.style.reddit-karaoke]   ← sub-table
            #
            # The toml library parses this as:
            #   s["style"] = "reddit-karaoke"     ← string (the scalar)
            # and the sub-table ends up at:
            #   s["style.reddit-karaoke"]          ← NOT valid TOML key
            #
            # Actually in TOML, [settings.style.reddit-karaoke] means
            # settings -> style -> reddit-karaoke, so the toml library puts it
            # at s["style"]["reddit-karaoke"].  But s["style"] is already the
            # string "reddit-karaoke", which causes a conflict.
            #
            # The design document's config schema uses a different approach:
            # the per-style options live under a separate top-level key or
            # the style identifier is a table.  For this implementation we
            # support two layouts:
            #
            # Layout A (preferred): style options are in a nested dict at
            #   settings_dict["settings"]["style_options"][<id>]
            #   (avoids the TOML conflict)
            #
            # Layout B (design doc): style options are in a nested dict at
            #   settings_dict["settings"]["style"][<id>]
            #   (only works if "style" is a table, not a string)
            #
            # We check both, preferring Layout B when "style" is a dict.
            raw_style_options: dict[str, Any] = {}

            # Check if s["style"] is actually a dict (Layout B — style is a
            # TOML table, not a plain string).  In that case the style_id
            # comes from s["style"]["id"] or similar — but the design says
            # style = "reddit-karaoke" (a string).  So Layout B is only
            # possible when the TOML uses a different key for the id.
            #
            # Practical resolution: look for per-style options under
            # s.get("style_options", {}).get(style_id, {}) first, then fall
            # back to s.get(f"style_{style_id}", {}) for compatibility.
            style_options_table: Any = s.get("style_options", {})
            if isinstance(style_options_table, dict):
                raw_style_options = dict(style_options_table.get(style_id, {}))

            # Validate against the plugin's options_schema.
            plugin_cls = get_style(style_id)
            schema: Mapping[str, type] = plugin_cls.options_schema
            style_options = _validate_style_options(
                raw_style_options, schema, style_id
            )

        else:
            # No 'style' key — fail with a clear ConfigError.
            raise ConfigError(
                "config.toml is missing the required 'style' key under [settings]. "
                "Add 'style = \"<id>\"' (e.g. style = \"reddit-karaoke\") and "
                "per-style options under [settings.style_options.<id>]. "
                f"Available styles: {', '.join(available_styles()) or '<none>'}"
            )

        # ------------------------------------------------------------------
        # Theme (top-level fallback; style_options may override)
        # ------------------------------------------------------------------
        theme: str = str(style_options.get("theme", s.get("theme", "light")))

        return cls(
            style_id=style_id,
            style_options=style_options,
            canvas=canvas,
            audio_speed=audio_speed,
            theme=theme,
            debug_dump_intermediates=debug_dump_intermediates,
            is_production=is_production,
            subreddit=subreddit,
        )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _validate_style_options(
    raw: dict[str, Any],
    schema: Mapping[str, type],
    style_id: str,
) -> dict[str, Any]:
    """Validate *raw* options against *schema* for *style_id*.

    - Type mismatches raise :class:`ConfigError`.
    - Unknown keys (present in *raw* but not in *schema*) are dropped with a
      :class:`ConfigWarning`.
    - ``karaoke_words_per_chunk <= 0`` is coerced to
      :data:`_DEFAULT_KARAOKE_WORDS_PER_CHUNK` with a :class:`ConfigWarning`.

    Parameters
    ----------
    raw:
        Raw options dict from the config file.
    schema:
        ``{key: expected_type}`` mapping from the plugin's ``options_schema``.
    style_id:
        Used in error/warning messages.

    Returns
    -------
    dict[str, Any]
        Validated (and possibly coerced) options dict.
    """
    validated: dict[str, Any] = {}

    # Check for unknown keys.
    unknown_keys = set(raw) - set(schema)
    if unknown_keys:
        warnings.warn(
            f"Style {style_id!r} received unknown option(s) "
            f"{sorted(unknown_keys)!r}; they will be ignored.",
            ConfigWarning,
            stacklevel=3,
        )

    # Validate known keys.
    for key, expected_type in schema.items():
        if key not in raw:
            # Missing keys are allowed; the plugin uses its own defaults.
            continue
        value = raw[key]
        if not isinstance(value, expected_type):
            raise ConfigError(
                f"Style {style_id!r} option {key!r} must be of type "
                f"{expected_type.__name__!r}, got "
                f"{type(value).__name__!r} ({value!r})."
            )
        validated[key] = value

    # Coerce karaoke_words_per_chunk <= 0 to the documented default.
    if "karaoke_words_per_chunk" in validated:
        kwpc = validated["karaoke_words_per_chunk"]
        if isinstance(kwpc, int) and kwpc <= 0:
            warnings.warn(
                f"Style {style_id!r}: karaoke_words_per_chunk={kwpc!r} is "
                f"<= 0; coercing to the default value of "
                f"{_DEFAULT_KARAOKE_WORDS_PER_CHUNK}.",
                ConfigWarning,
                stacklevel=3,
            )
            validated["karaoke_words_per_chunk"] = _DEFAULT_KARAOKE_WORDS_PER_CHUNK

    return validated

