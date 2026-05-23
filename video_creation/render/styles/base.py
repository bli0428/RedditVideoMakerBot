"""CardStylePlugin ABC and BodyAssets companion type.

Every visual treatment (custom-card, custom-karaoke, reddit-card, reddit-karaoke)
implements CardStylePlugin: render_header, render_body, compose_frame.

Satisfies: Requirements 1.1, 1.4, 11.3
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Mapping

import numpy as np

from video_creation.render.context import RenderContext
from video_creation.render.timing.models import LineTiming


@dataclass(frozen=True)
class BodyAssets:
    """Pre-rendered body images plus any plugin-specific per-line metadata.

    A 'paginated card' style fills ``pages`` with one RGBA ndarray per page.
    A 'karaoke' style fills ``chunk_images`` with one RGBA ndarray per chunk.
    Plugins use whichever fields they need; both may be empty.

    ``extra`` is an optional plugin-private mapping for any additional metadata
    (e.g., line-position dicts, scroll offsets) that the plugin's
    ``compose_frame`` needs but that doesn't belong in the public contract.
    """

    pages: tuple[np.ndarray, ...] = field(default_factory=tuple)
    chunk_images: tuple[np.ndarray, ...] = field(default_factory=tuple)
    extra: Mapping[str, Any] | None = None


class CardStylePlugin(ABC):
    """One visual treatment: header + body + per-frame composition.

    Each subclass owns all layout constants for its treatment (Req 11.1, 11.2)
    and is the single place where header rendering, body rendering, and
    per-frame composition for that treatment are co-located (Req 1.4).

    Class attributes
    ----------------
    style_id : str
        Unique identifier used by the StyleRegistry as the lookup key.
        Must be a non-empty string (e.g. ``"custom-card"``).
    options_schema : Mapping[str, type]
        Declarative map of option name → expected Python type for the
        ``[settings.style.<id>]`` config block.  Used by ``RenderConfig``
        validation and ``plugin_options_schema()`` reflection (Req 13.3).
    """

    #: Class-level identifier; the StyleRegistry uses this as the key.
    style_id: str

    #: Declarative options this plugin accepts under [settings.style.<id>].
    #: Used by config validation and `available_styles()` reflection (Req 13.3).
    options_schema: Mapping[str, type]

    def __init__(self, options: Mapping[str, Any], canvas: "CanvasSpec") -> None:  # noqa: F821
        """Initialise the plugin with resolved options and canvas geometry.

        Parameters
        ----------
        options:
            Key/value pairs from ``[settings.style.<style_id>]``, already
            validated against ``options_schema`` by ``RenderConfig``.
        canvas:
            Output canvas dimensions and zoom/opacity settings sourced from
            ``resolution_w``, ``resolution_h``, ``zoom``, and ``opacity`` in
            ``config.toml`` (Req 11.3).
        """
        self.options = options
        self.canvas = canvas

    # ---- Header ----------------------------------------------------------

    @abstractmethod
    def render_header(self, ctx: RenderContext) -> np.ndarray:
        """Return the static header card as an RGBA ndarray (Req 5.1).

        Parameters
        ----------
        ctx:
            Frozen render context containing post metadata and canvas spec.

        Returns
        -------
        numpy.ndarray
            Shape ``(H, W, 4)``, dtype ``uint8``, RGBA colour order.
            The returned array is in-memory; no PNG is written to disk
            during a normal production run (Req 5.3).
        """

    # ---- Body ------------------------------------------------------------

    @abstractmethod
    def render_body(
        self,
        ctx: RenderContext,
        line_timings: tuple[LineTiming, ...],
    ) -> BodyAssets:
        """Return body content as in-memory RGBA images (Req 5.2).

        Parameters
        ----------
        ctx:
            Frozen render context.
        line_timings:
            Sequence of per-line (or per-chunk) timing entries produced by
            ``TimingEngine.compute``.  Plugins use these to determine how
            many pages / caption images to pre-render.

        Returns
        -------
        BodyAssets
            ``pages`` for paginated styles; ``chunk_images`` for karaoke
            styles.  All ndarray entries have shape ``(_, _, 4)`` and dtype
            ``uint8``.
        """

    # ---- Per-frame -------------------------------------------------------

    @abstractmethod
    def compose_frame(
        self,
        t: float,
        ctx: RenderContext,
        header: np.ndarray,
        body: BodyAssets,
        line_timings: tuple[LineTiming, ...],
    ) -> np.ndarray:
        """Return ONE RGBA frame for time *t* (Req 4.1).

        The mask MoviePy needs is derived from the alpha channel of this
        frame (Req 4.2).  There is no parallel ``compose_mask`` method
        (Req 4.3).

        Parameters
        ----------
        t:
            Current playback time in seconds.
        ctx:
            Frozen render context (canvas dimensions, post metadata, theme).
        header:
            Pre-rendered header ndarray from ``render_header``.
        body:
            Pre-rendered body assets from ``render_body``.
        line_timings:
            Timing entries used to determine which line/chunk is active at
            time *t*.

        Returns
        -------
        numpy.ndarray
            Shape ``(H, W, 4)`` matching ``ctx.canvas.height`` ×
            ``ctx.canvas.width``, dtype ``uint8``, RGBA colour order.
        """


# Re-export CanvasSpec here for convenience so callers can do:
#   from video_creation.render.styles.base import CardStylePlugin, CanvasSpec
from video_creation.render.context import CanvasSpec  # noqa: E402, F401
