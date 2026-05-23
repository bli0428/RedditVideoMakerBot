"""Timing data models for the TimingEngine.

All dataclasses are frozen (immutable) and use only stdlib types.
This module MUST NOT import PIL, numpy, MoviePy, or FFmpeg.

Satisfies: Requirements 6.1
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WordTimestamp:
    """A single word with its TTS timing, post-audio-speed-scaling.

    ``start`` and ``end`` are in seconds. The caller (AudioAssembler) is
    responsible for scaling raw TTS timestamps by ``audio_speed`` before
    constructing these objects.
    """

    word: str
    start: float  # seconds — when this word begins
    end: float    # seconds — when this word ends


@dataclass(frozen=True)
class LineDefinition:
    """A wrapped line of body text with its on-image y-coordinates.

    The plugin pre-wraps the body text (using PIL text metrics) and hands
    a sequence of these definitions to ``TimingEngine.compute``.  The engine
    uses ``word_count`` to slice the word-timestamp stream; it uses the
    y-coordinates to populate ``LineTiming`` entries so plugins never need
    to re-derive layout from the timing output.
    """

    text: str        # full text of this wrapped line
    word_count: int  # number of whitespace-separated words in ``text``
    y_top: int       # top pixel coordinate of this line on the body image
    y_bottom: int    # bottom pixel coordinate of this line on the body image
    page_index: int  # which paginated page this line belongs to (0-based)


@dataclass(frozen=True)
class LineTiming:
    """Resolved timing for one line or one karaoke chunk within a line.

    When ``chunk_size <= 0`` (or the style is not karaoke), each
    ``LineDefinition`` produces exactly one ``LineTiming`` with
    ``chunk_index = 0``.  When ``chunk_size > 0``, each ``LineDefinition``
    produces ``ceil(word_count / chunk_size)`` entries, one per chunk.
    """

    text: str         # text of this line or chunk
    start: float      # seconds — when this line/chunk begins
    end: float        # seconds — when this line/chunk ends
    line_index: int   # index of the originating ``LineDefinition`` (0-based)
    chunk_index: int  # 0 if not chunked; index within the line if chunked
    y_top: int        # inherited from the parent ``LineDefinition``
    y_bottom: int     # inherited from the parent ``LineDefinition``
    page_index: int   # inherited from the parent ``LineDefinition``


@dataclass(frozen=True)
class TimingResult:
    """The complete output of ``TimingEngine.compute``.

    ``entries`` is ordered by ``start`` time.  ``title_duration`` is passed
    through unchanged from the input so plugins can reference it without
    carrying it separately.
    """

    title_duration: float           # seconds — duration of the title audio clip
    total_duration: float           # seconds — full audio track duration
    entries: tuple[LineTiming, ...]  # all line/chunk timings, ordered by start
