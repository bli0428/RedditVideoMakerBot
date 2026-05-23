"""Fake word-timestamp synthesizer for the PreviewHarness.

When real TTS audio is unavailable, ``synth_word_timestamps`` generates
contiguous ``WordTimestamp`` objects at a fixed words-per-second rate so the
same ``TimingEngine`` used in production can be exercised without running TTS.

Satisfies: Requirements 10.4
"""

from __future__ import annotations

from video_creation.render.timing.models import WordTimestamp


def synth_word_timestamps(
    words: list[str],
    wps: float = 3.0,
) -> tuple[WordTimestamp, ...]:
    """Generate contiguous fake word timestamps at *wps* words per second.

    Each word occupies exactly ``1.0 / wps`` seconds with no gap between
    words.  The total span is ``len(words) / wps`` seconds.

    Parameters
    ----------
    words:
        List of word strings to timestamp.
    wps:
        Words per second.  Must be > 0.

    Returns
    -------
    tuple[WordTimestamp, ...]
        One ``WordTimestamp`` per word, with contiguous start/end times.

    Raises
    ------
    ValueError
        If *wps* is <= 0.
    """
    if wps <= 0:
        raise ValueError(f"wps must be > 0, got {wps!r}")

    slot = 1.0 / wps
    result = []
    for i, word in enumerate(words):
        start = i * slot
        end = start + slot
        result.append(WordTimestamp(word=word, start=start, end=end))
    return tuple(result)
