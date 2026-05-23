"""BackgroundPreparer — FFmpeg scale/crop/hue/eq wrapper.

Lifts the ``prepare_background`` function from ``final_video.py`` into a
class whose random visual tweaks are seeded from the reddit post ID so that
reruns produce deterministic output (useful for tests and reproducibility).

Satisfies: Requirements 3.2, 3.7
"""

from __future__ import annotations

import multiprocessing
import random
from typing import TYPE_CHECKING

import ffmpeg
from moviepy import VideoFileClip

from utils.id import extract_id
from video_creation.render.errors import BackgroundPreparationError

if TYPE_CHECKING:
    from video_creation.render.config import RenderConfig


class BackgroundPreparer:
    """Prepare the background video clip for a render run.

    The FFmpeg pipeline applies the same scale/crop/hue/eq filters that
    ``prepare_background`` in ``final_video.py`` used, but the random
    visual tweaks (hue shift, brightness, contrast, saturation) are now
    seeded from the reddit post ID so that re-running the pipeline with the
    same post always produces the same background.

    Usage::

        clip = BackgroundPreparer().prepare(reddit_obj, config)
    """

    def prepare(self, reddit_obj: dict, config: "RenderConfig") -> VideoFileClip:
        """Scale, crop, and apply deterministic visual tweaks to the background.

        The output file is written to
        ``assets/temp/<reddit_id>/background_noaudio.mp4`` and the result is
        returned as a :class:`~moviepy.VideoFileClip` already resized to
        ``(W, H)``.

        Random per-video variations (seeded from the post ID for
        determinism):

        - Hue shift: ±15 degrees
        - Brightness: ±8%
        - Contrast: ±10%
        - Saturation: ±15%

        Parameters
        ----------
        reddit_obj:
            The reddit post dict (must contain ``thread_id``).
        config:
            The active :class:`~video_creation.render.config.RenderConfig`.

        Returns
        -------
        VideoFileClip
            The processed background clip, resized to ``(W, H)``.

        Raises
        ------
        BackgroundPreparationError
            If FFmpeg fails during processing.  The decoded stderr output
            from FFmpeg is included in the exception message.
        """
        reddit_id = extract_id(reddit_obj)
        W = config.canvas.width
        H = config.canvas.height

        output_path = f"assets/temp/{reddit_id}/background_noaudio.mp4"

        # Seed from the post ID so reruns are deterministic.
        rng = random.Random(reddit_id)

        hue_shift = rng.uniform(-15, 15)
        brightness = rng.uniform(-0.08, 0.08)
        contrast = rng.uniform(0.9, 1.1)
        saturation = rng.uniform(0.85, 1.15)

        stream = (
            ffmpeg.input(f"assets/temp/{reddit_id}/background.mp4")
            .filter("scale", W, H, force_original_aspect_ratio="increase")
            .filter("crop", W, H)
            .filter("hue", h=hue_shift, s=saturation)
            .filter("eq", brightness=brightness, contrast=contrast)
        )

        output = (
            stream.output(
                output_path,
                an=None,
                **{
                    "c:v": "libx264",
                    "b:v": "20M",
                    "threads": multiprocessing.cpu_count(),
                },
            )
            .overwrite_output()
        )

        try:
            output.run(quiet=True)
        except ffmpeg.Error as e:
            raise BackgroundPreparationError(e.stderr.decode("utf-8")) from e

        return VideoFileClip(output_path).resized((W, H))
