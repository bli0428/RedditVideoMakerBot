"""Public API for the card rendering pipeline.

This module is the single documented entry point for callers (main.py,
the PreviewHarness, tests, and any future CLI).  It exposes three functions:

- :func:`render_video` — render a Reddit post to an MP4 file.
- :func:`available_styles` — list registered style identifiers.
- :func:`plugin_options_schema` — reflect a plugin's accepted options.

Satisfies: Requirements 1.3, 13.1, 13.2, 13.3
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from video_creation.render.styles import available_styles as _available_styles
from video_creation.render.styles import get_style


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def render_video(
    style_id: str,
    reddit_obj: dict,
    audio: Any,
    config_overrides: Mapping[str, Any] | None = None,
    **kwargs: Any,
) -> Path:
    """Render a Reddit post to an MP4 file and return its path.

    In Phase 4 this function builds a :class:`~video_creation.render.config.RenderConfig`
    from ``settings.config`` (with *style_id* as an override), constructs
    :class:`~video_creation.render.audio.assembler.AudioAssets` from the
    ``assets/temp/<reddit_id>/mp3/`` directory, and delegates the full render
    to :class:`~video_creation.render.orchestrator.PipelineOrchestrator`.

    Parameters
    ----------
    style_id:
        A registered :class:`~video_creation.render.styles.base.CardStylePlugin`
        identifier (e.g. ``"reddit-karaoke"``).  Raises
        :class:`~video_creation.render.errors.UnknownStyleError` if the
        identifier is not in the registry.
    reddit_obj:
        The Reddit post payload dict as produced by the scraping layer.
    audio:
        Accepted for API compatibility.  When ``None`` (the normal case),
        :class:`~video_creation.render.audio.assembler.AudioAssets` is built
        automatically from the ``assets/temp/<reddit_id>/mp3/`` directory.
        When an :class:`~video_creation.render.audio.assembler.AudioAssets`
        instance is passed directly it is used as-is (useful for tests and
        the PreviewHarness).
    config_overrides:
        Optional mapping of extra keyword arguments.  Recognised keys:
        ``number_of_clips``, ``length``, ``background_config``.
    **kwargs:
        Additional keyword arguments.  These take precedence over
        *config_overrides* when the same key appears in both.

    Returns
    -------
    Path
        Path to the rendered MP4 file.

    Raises
    ------
    UnknownStyleError
        If *style_id* is not registered in the
        :class:`~video_creation.render.styles.StyleRegistry`.
    """
    from utils import settings
    from utils.id import extract_id
    from video_creation.render.audio.assembler import AudioAssets, AudioAssembler
    from video_creation.render.background.preparer import BackgroundPreparer
    from video_creation.render.compositor.frame import FrameCompositor
    from video_creation.render.config import RenderConfig
    from video_creation.render.orchestrator import PipelineOrchestrator
    from video_creation.render.output.writer import OutputWriter
    from video_creation.render.timing.engine import TimingEngine

    # Validate the style_id — raises UnknownStyleError if not registered.
    get_style(style_id)

    # Merge config_overrides and kwargs into a single call-args dict.
    call_kwargs: dict[str, Any] = {}
    if config_overrides:
        call_kwargs.update(config_overrides)
    call_kwargs.update(kwargs)

    number_of_clips: int = int(call_kwargs.pop("number_of_clips", 0))

    # Build RenderConfig from settings, injecting the requested style_id.
    # We temporarily patch the settings dict so from_settings picks up the
    # style_id without requiring the user to have migrated config.toml yet.
    import warnings
    from video_creation.render.errors import ConfigWarning

    settings_dict: dict[str, Any] = dict(settings.config)
    # Inject style into the settings sub-dict so from_settings uses the new schema.
    settings_sub = dict(settings_dict.get("settings", {}))
    settings_sub["style"] = style_id
    settings_dict = dict(settings_dict)
    settings_dict["settings"] = settings_sub

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", ConfigWarning)
        config = RenderConfig.from_settings(settings_dict)

    # Build AudioAssets from the reddit_obj paths when not supplied directly.
    from video_creation.render.audio.assembler import AudioAssets as _AudioAssets

    if isinstance(audio, _AudioAssets):
        assets = audio
    else:
        assets = _build_audio_assets(reddit_obj, number_of_clips, settings.config)

    # Construct stage objects and run the orchestrator.
    orchestrator = PipelineOrchestrator(
        config=config,
        audio=AudioAssembler(),
        background=BackgroundPreparer(),
        timing=TimingEngine(),
        compositor=FrameCompositor(fps=30),
        output=OutputWriter(),
    )

    return orchestrator.render(reddit_obj, assets)


def available_styles() -> tuple[str, ...]:
    """Return the registered style identifiers in sorted order.

    This is a thin re-export of
    :func:`video_creation.render.styles.available_styles`.

    Returns
    -------
    tuple[str, ...]
        Sorted tuple of all currently-registered style identifier strings.

    Satisfies: Requirement 13.2
    """
    return _available_styles()


def plugin_options_schema(style_id: str) -> Mapping[str, type]:
    """Return the options schema for the plugin identified by *style_id*.

    Parameters
    ----------
    style_id:
        A registered style identifier.

    Returns
    -------
    Mapping[str, type]
        The ``options_schema`` class attribute of the plugin, mapping option
        names to their expected Python types.

    Raises
    ------
    UnknownStyleError
        If *style_id* is not registered.

    Satisfies: Requirement 13.3
    """
    return get_style(style_id).options_schema


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _build_audio_assets(
    reddit_obj: dict,
    number_of_clips: int,
    settings_config: dict,
) -> "AudioAssets":  # type: ignore[name-defined]
    """Build an :class:`~video_creation.render.audio.assembler.AudioAssets`
    from the ``assets/temp/<reddit_id>/mp3/`` directory layout.

    Mirrors the audio-path construction logic that was previously inlined in
    ``make_final_video``.

    Parameters
    ----------
    reddit_obj:
        Raw Reddit post dict.
    number_of_clips:
        Number of comment/body clips (excluding the title clip).
    settings_config:
        The full ``settings.config`` dict.

    Returns
    -------
    AudioAssets
        Paths to the title MP3, body MP3s, and their word-timestamp sidecars.
    """
    from pathlib import Path as _Path

    from utils.id import extract_id
    from video_creation.render.audio.assembler import AudioAssets

    reddit_id = extract_id(reddit_obj)
    mp3_dir = _Path(f"assets/temp/{reddit_id}/mp3")

    s = settings_config.get("settings", {})

    if s.get("storymode", False):
        if s.get("storymodemethod", 0) == 0:
            body_mp3s: tuple[_Path, ...] = (mp3_dir / "postaudio.mp3",)
            sidecar_jsons: tuple[_Path, ...] = (mp3_dir / "postaudio.json",)
        else:
            body_mp3s = tuple(
                mp3_dir / f"postaudio-{i}.mp3"
                for i in range(number_of_clips + 1)
            )
            sidecar_jsons = tuple(
                mp3_dir / f"postaudio-{i}.json"
                for i in range(number_of_clips + 1)
            )
    else:
        body_mp3s = tuple(mp3_dir / f"{i}.mp3" for i in range(number_of_clips))
        sidecar_jsons = tuple(mp3_dir / f"{i}.json" for i in range(number_of_clips))

    return AudioAssets(
        title_mp3=mp3_dir / "title.mp3",
        body_mp3s=body_mp3s,
        word_timestamp_jsons=sidecar_jsons,
    )


def _derive_output_path(reddit_obj: dict) -> Path:
    """Best-effort reconstruction of the output path from *reddit_obj*.

    Kept for backward compatibility with any callers that relied on the
    Phase 3 fallback.
    """
    from utils import settings
    from utils.id import extract_id
    from video_creation.render.output.naming import name_normalize

    title_for_file = extract_id(reddit_obj, "thread_title")
    subreddit = settings.config["reddit"]["thread"].get("subreddit", "unknown")
    filename = f"{name_normalize(title_for_file)[:251]}.mp4"
    return Path("results") / subreddit / filename
