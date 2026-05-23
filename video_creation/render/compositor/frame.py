"""FrameCompositor — the only place that constructs moviepy.VideoClip.

Takes a ``make_frame: float -> np.ndarray (RGBA, uint8)`` callable and
produces a ``VideoClip`` whose mask is derived from the same call's alpha
channel.  A one-slot cache avoids re-rendering when MoviePy requests the
RGB and mask frames back-to-back at the same timestamp.

This is the ONLY module in the codebase where ``is_mask=True`` is used
(Requirement 4.3).
"""

from __future__ import annotations

import numpy as np
from moviepy import VideoClip


class FrameCompositor:
    """Build a MoviePy ``VideoClip`` whose mask comes from the RGBA alpha channel.

    Parameters
    ----------
    fps:
        Frames per second for the produced clip (default 30).
    """

    def __init__(self, fps: int = 30) -> None:
        self.fps = fps

    def build_clip(self, duration: float, make_frame) -> VideoClip:
        """Build a masked ``VideoClip`` from an RGBA frame function.

        Parameters
        ----------
        duration:
            Length of the clip in seconds.
        make_frame:
            Callable ``(t: float) -> np.ndarray`` returning an RGBA
            ``uint8`` array of shape ``(H, W, 4)`` for timestamp *t*.

        Returns
        -------
        VideoClip
            An RGB ``VideoClip`` with an attached mask derived from the
            alpha channel of ``make_frame``.  The cache ensures that when
            MoviePy calls the RGB function and the mask function at the
            same *t*, ``make_frame`` is only invoked once.
        """
        # One-slot cache: stores the most recently rendered (t, frame) pair
        # so the alpha-derivation path doesn't trigger a second render call.
        cache: dict = {"t": None, "frame": None}

        def _frame_rgb(t):
            f = make_frame(t)
            cache["t"], cache["frame"] = t, f
            return f[:, :, :3]

        def _frame_alpha(t):
            if cache["t"] != t:
                cache["t"] = t
                cache["frame"] = make_frame(t)
            return cache["frame"][:, :, 3].astype(np.float32) / 255.0

        clip = VideoClip(_frame_rgb, duration=duration).with_fps(self.fps)
        mask = VideoClip(_frame_alpha, duration=duration, is_mask=True).with_fps(self.fps)
        return clip.with_mask(mask)
