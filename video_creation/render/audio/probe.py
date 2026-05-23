"""FFmpeg probe wrapper — single home for all ffmpeg.probe calls.

Every module that needs to know the duration of an audio/video file should
call :func:`probe_duration` from here rather than calling ``ffmpeg.probe``
directly.  This keeps the FFmpeg dependency in one place and gives a
consistent error type (:class:`~video_creation.render.errors.AudioAssemblyError`)
on failure.

Satisfies: Requirements 3.1, 3.7
"""

from __future__ import annotations

from pathlib import Path

import ffmpeg

from video_creation.render.errors import AudioAssemblyError


def probe_duration(path: Path) -> float:
    """Return the duration (in seconds) of the audio/video file at *path*.

    Uses ``ffmpeg.probe`` to read the container metadata.  The duration is
    taken from ``format.duration`` in the probe output.

    Parameters
    ----------
    path:
        Path to the audio or video file to probe.

    Returns
    -------
    float
        Duration in seconds.

    Raises
    ------
    AudioAssemblyError
        If *path* does not exist, cannot be opened, or ``ffmpeg.probe``
        fails for any reason.  The original FFmpeg error message is included
        in the exception text.
    """
    if not Path(path).exists():
        raise AudioAssemblyError(
            f"Audio file not found: {path}"
        )

    try:
        info = ffmpeg.probe(str(path))
    except ffmpeg.Error as exc:
        stderr = exc.stderr.decode("utf-8", errors="replace") if exc.stderr else str(exc)
        raise AudioAssemblyError(
            f"ffmpeg.probe failed for {path!r}: {stderr}"
        ) from exc

    try:
        duration = float(info["format"]["duration"])
    except (KeyError, TypeError, ValueError) as exc:
        raise AudioAssemblyError(
            f"Could not read duration from ffmpeg.probe output for {path!r}: {exc}"
        ) from exc

    return duration
