"""OutputWriter — final encoding, file naming, thumbnail generation, and cleanup.

Owns the last stage of the render pipeline:
  1. Composite background + overlay + watermark into a final ``CompositeVideoClip``.
  2. Encode to ``results/<subreddit>/<name>.mp4`` using :func:`name_normalize`.
  3. Generate the thumbnail (when configured).
  4. Hand off to :func:`~utils.cleanup.cleanup`.
  5. Raise :class:`~video_creation.render.errors.OutputWriteError` on encode
     failure, deleting any partial output file first.

Satisfies: Requirements 3.5, 3.7, 5.6
"""

from __future__ import annotations

import multiprocessing
import os
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from moviepy import (
    AudioFileClip,
    CompositeVideoClip,
    ImageClip,
    VideoClip,
    VideoFileClip,
)
from PIL import Image, ImageDraw, ImageFont

from utils import settings
from utils.cleanup import cleanup
from utils.console import print_step, print_substep
from utils.id import extract_id
from utils.thumbnail import create_thumbnail
from utils.videos import save_data
from video_creation.render.errors import OutputWriteError
from video_creation.render.output.naming import name_normalize
from video_creation.render.styles.shared.animation import _apply_zoom

if TYPE_CHECKING:
    from video_creation.render.config import RenderConfig


class OutputWriter:
    """Encodes the final video, generates the thumbnail, and cleans up.

    All public state is passed through :meth:`write`; this class is
    stateless and can be instantiated once and reused across runs.
    """

    # ------------------------------------------------------------------
    # Layout constants
    # ------------------------------------------------------------------

    #: Watermark text rendered in the bottom-centre of every video.
    WATERMARK_TEXT: str = "Gameplay from Dino Duel"
    #: Font size for the watermark.
    WATERMARK_FONT_SIZE: int = 44
    #: Opacity of the watermark overlay (0.0–1.0).
    WATERMARK_OPACITY: float = 0.3
    #: Pixels from the bottom edge to the watermark baseline.
    WATERMARK_BOTTOM_MARGIN: int = 30

    #: Background zoom applied to the background clip.
    BACKGROUND_ZOOM_AMOUNT: float = 0.03  # 0.10 * 0.3 from final_video.py

    #: FFmpeg codec used for the output video stream.
    VIDEO_CODEC: str = "libx264"
    #: FFmpeg codec used for the output audio stream.
    AUDIO_CODEC: str = "aac"
    #: Target video bitrate.
    VIDEO_BITRATE: str = "20M"
    #: FFmpeg encoding preset (speed/quality trade-off).
    ENCODING_PRESET: str = "medium"
    #: Output frames per second.
    FPS: int = 30

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def write(
        self,
        background: VideoFileClip,
        overlay: VideoClip,
        audio: AudioFileClip,
        reddit_obj: dict,
        config: "RenderConfig",
    ) -> Path:
        """Composite, encode, thumbnail, and clean up.

        Parameters
        ----------
        background:
            Pre-processed background ``VideoFileClip`` (already scaled/cropped
            by ``BackgroundPreparer``).
        overlay:
            The card overlay clip produced by ``FrameCompositor.build_clip``.
            Must have a mask attached (alpha channel).
        audio:
            The final mixed ``AudioFileClip`` (TTS + optional background
            music).
        reddit_obj:
            Raw Reddit post dict.  Used for file naming, thumbnail text, and
            the ``save_data`` call.
        config:
            Frozen ``RenderConfig`` supplying canvas dimensions, subreddit,
            and thumbnail settings.

        Returns
        -------
        Path
            Absolute path to the written ``.mp4`` file.

        Raises
        ------
        OutputWriteError
            If FFmpeg fails to encode the video.  Any partial output file is
            deleted before the exception is raised.
        """
        W: int = config.canvas.width
        H: int = config.canvas.height
        total_duration: float = audio.duration

        # ── 1. Loop / trim background to match audio duration ─────────────
        if background.duration < total_duration:
            from moviepy.video.fx import Loop
            loops_needed = int(total_duration / background.duration) + 1
            background = background.with_effects([Loop(n=loops_needed)])
        background = background.subclipped(0, total_duration)
        background = _apply_zoom(background, zoom_amount=self.BACKGROUND_ZOOM_AMOUNT)

        # ── 2. Build watermark ImageClip ──────────────────────────────────
        watermark_clip = self._build_watermark(total_duration, H)

        # ── 3. Composite final video ──────────────────────────────────────
        final_video = CompositeVideoClip(
            [background, overlay, watermark_clip],
            size=(W, H),
        ).with_duration(total_duration).with_audio(audio)

        # ── 4. Determine output path ──────────────────────────────────────
        title_for_file = extract_id(reddit_obj, "thread_title")
        reddit_id = extract_id(reddit_obj)
        subreddit = config.subreddit or settings.config["reddit"]["thread"]["subreddit"]

        filename = f"{name_normalize(title_for_file)[:251]}"
        results_dir = Path(f"./results/{subreddit}")
        results_dir.mkdir(parents=True, exist_ok=True)

        output_path = results_dir / (filename[:251] + ".mp4")

        # ── 5. Encode ─────────────────────────────────────────────────────
        print_step("Rendering the video 🎥")
        try:
            final_video.write_videofile(
                str(output_path),
                fps=self.FPS,
                codec=self.VIDEO_CODEC,
                audio_codec=self.AUDIO_CODEC,
                bitrate=self.VIDEO_BITRATE,
                preset=self.ENCODING_PRESET,
                threads=multiprocessing.cpu_count(),
                logger="bar",
            )
        except Exception as exc:
            # Delete any partial file so callers don't encounter a corrupt
            # artefact on disk (Req 3.7).
            if output_path.exists():
                try:
                    output_path.unlink()
                except OSError:
                    pass
            raise OutputWriteError(
                f"Failed to encode video to {output_path!r}: {exc}"
            ) from exc

        # ── 6. Thumbnail ──────────────────────────────────────────────────
        self._generate_thumbnail(reddit_obj, reddit_id, subreddit)

        # ── 7. Save metadata and clean up ─────────────────────────────────
        background_credit = ""
        save_data(subreddit, filename + ".mp4", title_for_file, reddit_id, background_credit)

        print_step("Removing temporary files 🗑")
        cleanups = cleanup(reddit_id)
        print_substep(f"Removed {cleanups} temporary files 🗑")
        print_step("Done! 🎉 The video is in the results folder 📁")

        return output_path.resolve()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_watermark(self, duration: float, frame_height: int) -> ImageClip:
        """Render the watermark text as a semi-transparent ``ImageClip``."""
        font_path = os.path.join("fonts", "Roboto-Regular.ttf")
        watermark_font = ImageFont.truetype(font_path, self.WATERMARK_FONT_SIZE)

        # Measure text bounding box.
        wm_dummy = Image.new("RGBA", (1, 1))
        wm_draw = ImageDraw.Draw(wm_dummy)
        wm_bbox = wm_draw.textbbox((0, 0), self.WATERMARK_TEXT, font=watermark_font)
        wm_w = wm_bbox[2] - wm_bbox[0] + 20
        wm_h = wm_bbox[3] - wm_bbox[1] + 14

        # Render onto a transparent canvas.
        wm_img = Image.new("RGBA", (wm_w, wm_h), (0, 0, 0, 0))
        wm_d = ImageDraw.Draw(wm_img)
        wm_d.text((10, 5), self.WATERMARK_TEXT, font=watermark_font, fill=(255, 255, 255, 255))
        wm_arr = np.array(wm_img)

        return (
            ImageClip(wm_arr, duration=duration)
            .with_opacity(self.WATERMARK_OPACITY)
            .with_position(("center", frame_height - wm_h - self.WATERMARK_BOTTOM_MARGIN))
        )

    def _generate_thumbnail(
        self,
        reddit_obj: dict,
        reddit_id: str,
        subreddit: str,
    ) -> None:
        """Generate and save the thumbnail PNG when configured to do so."""
        try:
            settingsbackground = settings.config["settings"]["background"]
        except (KeyError, TypeError):
            return

        if not settingsbackground.get("background_thumbnail"):
            return

        thumbnails_dir = Path(f"./results/{subreddit}/thumbnails")
        thumbnails_dir.mkdir(parents=True, exist_ok=True)

        first_image = next(
            (f for f in os.listdir("assets/backgrounds") if f.endswith(".png")),
            None,
        )
        if not first_image:
            return

        thumbnail = Image.open(f"assets/backgrounds/{first_image}")
        w_t, h_t = thumbnail.size
        title_thumb: str = reddit_obj.get("thread_title", "")

        thumb_save = create_thumbnail(
            thumbnail,
            settingsbackground["background_thumbnail_font_family"],
            settingsbackground["background_thumbnail_font_size"],
            settingsbackground["background_thumbnail_font_color"],
            w_t,
            h_t,
            title_thumb,
        )
        thumb_save.save(f"./assets/temp/{reddit_id}/thumbnail.png")
