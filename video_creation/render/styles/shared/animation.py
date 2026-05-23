"""Animation helpers for card pop-in and zoom effects.

Moved from ``video_creation/final_video.py``.
"""

from __future__ import annotations

# Default zoom amount used when none is specified.
ZOOM_AMOUNT = 0.10


def _pop_and_zoom(clip, pop_duration: float = 0.25, zoom_amount: float = ZOOM_AMOUNT):
    """Apply a quick snap 80%→100% pop-in followed by a slow zoom to *clip*.

    Returns the resized clip.  Requires a MoviePy ``VideoClip`` (or compatible)
    object with a ``resized`` method and a ``duration`` attribute.
    """
    def _resize_func(t: float) -> float:
        if t < pop_duration:
            progress = t / pop_duration
            eased = 1 - (1 - progress) ** 4
            return 0.8 + 0.2 * eased
        zoom_progress = (t - pop_duration) / (clip.duration - pop_duration)
        return 1.0 + zoom_amount * zoom_progress

    return clip.resized(_resize_func)


def _apply_zoom(clip, zoom_amount: float = ZOOM_AMOUNT):
    """Apply a simple linear zoom over the full duration of *clip*."""
    return clip.resized(lambda t: 1 + zoom_amount * (t / clip.duration))


def header_pop_zoom_scale(
    t: float,
    total_dur: float,
    pop_dur: float = 0.25,
    zoom_amount: float = ZOOM_AMOUNT,
) -> float:
    """Return the scale factor for the header card at time *t*.

    Implements the same curve as ``_pop_and_zoom`` but as a pure function
    (no MoviePy dependency) so plugins can call it directly inside their
    ``compose_frame`` implementations.

    Args:
        t:           Current time in seconds.
        total_dur:   Total duration of the card animation in seconds.
        pop_dur:     Duration of the initial pop-in phase.
        zoom_amount: Fractional zoom applied after the pop-in.

    Returns:
        A scale factor ≥ 0.8.
    """
    if t < pop_dur:
        progress = t / pop_dur
        eased = 1 - (1 - progress) ** 4
        return 0.8 + 0.2 * eased
    zoom_progress = (t - pop_dur) / max(0.01, total_dur - pop_dur)
    return 1.0 + zoom_amount * zoom_progress
