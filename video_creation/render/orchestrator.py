"""PipelineOrchestrator — coordinates all rendering stages.

Replaces the ``make_final_video`` god function with focused stage delegation.
This module MUST NOT import PIL, numpy, MoviePy ``VideoClip``, or ``ffmpeg``
directly — it only holds references to the stage objects (Req 3.6).

Satisfies: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import TYPE_CHECKING, Any

from video_creation.render.audio.assembler import AudioAssets, AudioAssembler
from video_creation.render.background.preparer import BackgroundPreparer
from video_creation.render.compositor.frame import FrameCompositor
from video_creation.render.context import RenderContext
from video_creation.render.output.writer import OutputWriter
from video_creation.render.styles import get_style
from video_creation.render.timing.engine import TimingEngine
from video_creation.render.timing.models import LineDefinition

if TYPE_CHECKING:
    from video_creation.render.config import RenderConfig

# ---------------------------------------------------------------------------
# Words per line for the simple word-split approach used when the orchestrator
# cannot call PIL (Req 3.6).  Plugins that need precise text-metric wrapping
# do their own wrapping inside render_body.
# ---------------------------------------------------------------------------
_WORDS_PER_LINE: int = 10


class PipelineOrchestrator:
    """Coordinates the full render pipeline without doing any image work.

    All image manipulation, FFmpeg calls, and per-frame logic live in the
    stage objects injected at construction time.  The orchestrator only
    calls their public methods and passes typed results between them.

    Parameters
    ----------
    config:
        Frozen render configuration for this run.
    audio:
        Stage responsible for assembling the audio track.
    background:
        Stage responsible for preparing the background video clip.
    timing:
        Stage responsible for computing per-line/chunk timing.
    compositor:
        Stage responsible for building the overlay ``VideoClip``.
    output:
        Stage responsible for encoding and writing the final MP4.
    """

    def __init__(
        self,
        config: "RenderConfig",
        audio: AudioAssembler,
        background: BackgroundPreparer,
        timing: TimingEngine,
        compositor: FrameCompositor,
        output: OutputWriter,
    ) -> None:
        self.config = config
        self.audio = audio
        self.background = background
        self.timing = timing
        self.compositor = compositor
        self.output = output

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def render(self, reddit_obj: dict, assets: AudioAssets) -> Path:
        """Run the full render pipeline and return the path to the output MP4.

        High-Level Flow (Req 3.1–3.5):
        1. AudioAssembler assembles the audio track and word timestamps.
        2. BackgroundPreparer prepares the background video clip.
        3. TimingEngine computes per-line/chunk timing from word timestamps.
        4. StyleRegistry resolves the plugin; plugin renders header and body.
        5. FrameCompositor builds the overlay clip from plugin.compose_frame.
        6. OutputWriter composites, encodes, and writes the final MP4.

        Parameters
        ----------
        reddit_obj:
            Raw Reddit post dict as produced by the scraper.
        assets:
            Paths to the TTS audio files and their word-timestamp sidecars.

        Returns
        -------
        Path
            Absolute path to the written ``.mp4`` file.
        """
        # ── 1. Assemble audio (Req 3.1, 3.7) ─────────────────────────────
        audio_bundle = self.audio.assemble(assets, self.config)
        audio_track = audio_bundle.track
        audio_durs = audio_bundle.durations
        word_ts = audio_bundle.word_timestamps

        # ── 2. Prepare background (Req 3.2, 3.7) ─────────────────────────
        bg_clip = self.background.prepare(reddit_obj, self.config)

        # ── 3. Compute timing (pure Python, Req 3.3) ──────────────────────
        ctx = RenderContext.from_reddit_obj(reddit_obj, self.config)
        line_definitions = self._derive_line_definitions(ctx.body_text)

        chunk_size: int = int(
            self.config.style_options.get("karaoke_words_per_chunk", 0) or 0
        )
        title_duration: float = audio_durs[0] if audio_durs else 0.0

        timing_result = self.timing.compute(
            words=word_ts,
            line_definitions=line_definitions,
            chunk_size=chunk_size,
            audio_speed=self.config.audio_speed,
            title_duration=title_duration,
        )

        # ── 4. Resolve plugin and render header/body (Req 1.3, 3.4) ──────
        plugin_cls = get_style(self.config.style_id)
        plugin = plugin_cls(self.config.style_options, self.config.canvas)

        header = plugin.render_header(ctx)
        body = plugin.render_body(ctx, timing_result.entries)

        # ── 4b. Debug-dump intermediates (Req 5.3, 5.4, 5.5) ─────────────
        if self.config.debug_dump_intermediates and not self.config.is_production:
            self._dump_debug_intermediates(reddit_obj, header, body)

        # ── 5. Build overlay clip (Req 4) ─────────────────────────────────
        line_timings = timing_result.entries
        overlay_clip = self.compositor.build_clip(
            duration=timing_result.total_duration,
            make_frame=lambda t: plugin.compose_frame(
                t, ctx, header, body, line_timings
            ),
        )

        # ── 6. Write output (Req 3.5) ─────────────────────────────────────
        return self.output.write(
            background=bg_clip,
            overlay=overlay_clip,
            audio=audio_track,
            reddit_obj=reddit_obj,
            config=self.config,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _derive_line_definitions(
        self, body_text: str
    ) -> tuple[LineDefinition, ...]:
        """Derive ``LineDefinition`` objects from *body_text* without PIL.

        Uses a simple word-split approach (groups of ``_WORDS_PER_LINE``
        words) so the orchestrator stays free of PIL/numpy imports (Req 3.6).
        Plugins that need precise text-metric wrapping do their own wrapping
        inside ``render_body``; the ``LineDefinition``s produced here are
        used only to drive the ``TimingEngine`` word-count slicing.

        Y-coordinates are set to placeholder values ``(0, 0)`` because the
        orchestrator has no image context.  Plugins read layout from their
        own pre-rendered ``BodyAssets``, not from ``LineTiming.y_top/bottom``.

        Parameters
        ----------
        body_text:
            The full body text of the post.

        Returns
        -------
        tuple[LineDefinition, ...]
            One ``LineDefinition`` per group of up to ``_WORDS_PER_LINE``
            words.  Returns a single zero-word definition when *body_text*
            is empty or whitespace-only.
        """
        words = body_text.split()

        if not words:
            # Return a single zero-word line so TimingEngine gets a valid
            # (empty) sequence rather than an empty tuple.
            return (
                LineDefinition(
                    text="",
                    word_count=0,
                    y_top=0,
                    y_bottom=0,
                    page_index=0,
                ),
            )

        definitions: list[LineDefinition] = []
        num_lines = math.ceil(len(words) / _WORDS_PER_LINE)

        for line_idx in range(num_lines):
            start = line_idx * _WORDS_PER_LINE
            end = min(start + _WORDS_PER_LINE, len(words))
            line_words = words[start:end]
            definitions.append(
                LineDefinition(
                    text=" ".join(line_words),
                    word_count=len(line_words),
                    y_top=0,
                    y_bottom=0,
                    page_index=0,
                )
            )

        return tuple(definitions)

    def _dump_debug_intermediates(
        self,
        reddit_obj: dict,
        header: Any,
        body: Any,
    ) -> None:
        """Write intermediate header/body PNGs to the debug directory.

        Only called when ``config.debug_dump_intermediates`` is ``True``
        **and** ``config.is_production`` is ``False`` (Req 5.3, 5.4, 5.5).

        Writes:
        - ``assets/temp/<reddit_id>/debug/header.png``
        - ``assets/temp/<reddit_id>/debug/body_page_<i>.png`` for each page
        - ``assets/temp/<reddit_id>/debug/chunk_<i>.png`` for each chunk

        Parameters
        ----------
        reddit_obj:
            Raw Reddit post dict; used to derive the ``reddit_id``.
        header:
            RGBA ``numpy.ndarray`` returned by ``plugin.render_header``.
        body:
            :class:`~video_creation.render.styles.base.BodyAssets` returned
            by ``plugin.render_body``.
        """
        # PIL is imported here (not at module level) to keep the orchestrator
        # free of PIL imports in the normal code path (Req 3.6).  The debug
        # path is only exercised in non-production runs.
        from PIL import Image  # type: ignore[import]

        from utils.id import extract_id

        reddit_id = extract_id(reddit_obj, "thread_id")
        debug_dir = Path("assets") / "temp" / reddit_id / "debug"
        debug_dir.mkdir(parents=True, exist_ok=True)

        # Save header.
        Image.fromarray(header).save(debug_dir / "header.png")

        # Save body pages (paginated card styles).
        for i, page in enumerate(body.pages):
            Image.fromarray(page).save(debug_dir / f"body_page_{i}.png")

        # Save chunk images (karaoke styles).
        for i, chunk in enumerate(body.chunk_images):
            Image.fromarray(chunk).save(debug_dir / f"chunk_{i}.png")
