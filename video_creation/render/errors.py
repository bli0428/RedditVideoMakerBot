"""Exception hierarchy for the video_creation.render package.

All render-specific exceptions inherit from ``RenderError`` so callers can
catch the entire family with a single ``except RenderError`` clause while
still being able to target individual failure modes when needed.
"""

from __future__ import annotations


class RenderError(Exception):
    """Base class for all errors raised by the render pipeline.

    Catching this class catches every render-specific exception.
    """


class UnknownStyleError(RenderError, KeyError):
    """Raised when a style identifier is not found in the ``StyleRegistry``.

    Inherits from both ``RenderError`` and ``KeyError`` so it can be caught
    by code that already handles ``KeyError`` from dict look-ups.

    Parameters
    ----------
    requested:
        The style identifier that was requested but not found.
    available:
        The style identifiers that are currently registered.
    """

    def __init__(self, requested: str, available: tuple[str, ...]) -> None:
        available_str = ", ".join(sorted(available)) if available else "<none>"
        message = (
            f"Unknown style {requested!r} ({requested}). "
            f"Available styles: {available_str}"
        )
        # KeyError stores its arg as a tuple; pass the message string so that
        # str(exc) and repr(exc) both show the human-readable text.
        super().__init__(message)
        self.requested = requested
        self.available = available

    def __str__(self) -> str:  # KeyError.__str__ wraps in quotes; override it.
        return self.args[0]


class ConfigError(RenderError, ValueError):
    """Raised when a configuration value has the wrong type or is otherwise
    invalid (e.g. a string where an integer is expected).

    Inherits from both ``RenderError`` and ``ValueError`` so it integrates
    naturally with code that validates configuration via ``ValueError``.
    """


class ConfigWarning(UserWarning):
    """Warning emitted for deprecated or auto-corrected configuration usage.

    Examples
    --------
    * A legacy flat-key config (``card_style`` + ``body_style``) is detected
      and automatically mapped to the new ``style`` identifier.
    * ``karaoke_words_per_chunk`` is ``<= 0`` and is coerced to the default
      value of ``3``.

    Use ``warnings.warn("...", ConfigWarning)`` to emit this warning.
    """


class AudioAssemblyError(RenderError):
    """Raised when the ``AudioAssembler`` cannot build the audio track.

    Typical causes include missing MP3 files, files that cannot be probed by
    FFmpeg, or a mismatch between the number of audio clips and the number of
    word-timestamp sidecar files.
    """


class BackgroundPreparationError(RenderError):
    """Raised when the ``BackgroundPreparer`` cannot produce a background clip.

    Typical causes include FFmpeg failures during scale/crop/hue/eq
    processing.  The decoded ``ffmpeg.Error.stderr`` output should be
    included in the exception message to aid debugging.
    """


class OutputWriteError(RenderError):
    """Raised when the ``OutputWriter`` cannot encode or save the final video.

    Any partially-written output file should be deleted before this exception
    is raised so the caller does not encounter a corrupt artefact on disk.
    """
