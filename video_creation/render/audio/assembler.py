"""AudioAssembler — FFmpeg probing, audio concatenation, and word-timestamp loading.

Owns the full audio-assembly pipeline:
  1. Probe each MP3 for its raw duration via :mod:`probe`.
  2. Scale durations and word timestamps by ``config.audio_speed``.
  3. Concatenate TTS clips into a single track.
  4. Optionally mix in background music.
  5. Load word-timestamp JSON sidecars and convert to
     :class:`~video_creation.render.timing.models.WordTimestamp` objects.

Returns a structured :class:`AudioBundle` so the orchestrator only deals
with typed outputs or raised :class:`~video_creation.render.errors.AudioAssemblyError`s.

Satisfies: Requirements 3.1, 3.7
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from os.path import exists
from pathlib import Path

from moviepy import AudioFileClip, CompositeAudioClip, concatenate_audioclips

from video_creation.render.audio.probe import probe_duration
from video_creation.render.errors import AudioAssemblyError
from video_creation.render.timing.models import WordTimestamp


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AudioAssets:
    """Paths to the raw audio files produced by the TTS stage.

    Parameters
    ----------
    title_mp3:
        Path to the title TTS audio file.
    body_mp3s:
        Paths to the body TTS audio files, one per content clip (sentence or
        comment), in order.
    word_timestamp_jsons:
        Paths to the word-timestamp JSON sidecar files, parallel to
        *body_mp3s*.  A missing sidecar is treated as an empty word list for
        that clip (no ``AudioAssemblyError`` is raised for missing sidecars —
        only for missing MP3s).
    """

    title_mp3: Path
    body_mp3s: tuple[Path, ...]
    word_timestamp_jsons: tuple[Path, ...]


@dataclass(frozen=True)
class AudioBundle:
    """The assembled audio track plus timing metadata.

    All durations and timestamps are already scaled by ``audio_speed``.

    Parameters
    ----------
    track:
        The final mixed :class:`~moviepy.AudioFileClip` (TTS + optional
        background music).
    durations:
        Per-clip durations in seconds, post-speed-scaling.  Index 0 is the
        title clip; indices 1..N are the body clips.
    word_timestamps:
        All word timestamps from the body clips, concatenated in order and
        offset so each timestamp is relative to the start of the full track
        (i.e. after the title duration).  Already scaled by ``audio_speed``.
    """

    track: AudioFileClip
    durations: tuple[float, ...]
    word_timestamps: tuple[WordTimestamp, ...]


# ---------------------------------------------------------------------------
# Assembler
# ---------------------------------------------------------------------------


class AudioAssembler:
    """Assembles the audio track from raw TTS assets.

    Usage::

        bundle = AudioAssembler().assemble(assets, config)
    """

    def assemble(
        self,
        assets: AudioAssets,
        config: "RenderConfig",  # type: ignore[name-defined]
        *,
        bg_audio_volume: float = 0.0,
    ) -> AudioBundle:
        """Build an :class:`AudioBundle` from *assets* and *config*.

        Steps
        -----
        1. Validate that all MP3 files exist.
        2. Probe each MP3 for its raw duration.
        3. Build speed-scaled :class:`~moviepy.AudioFileClip` objects.
        4. Scale raw durations by ``config.audio_speed``.
        5. Concatenate TTS clips.
        6. Optionally mix in background music.
        7. Load and offset word-timestamp JSON sidecars.

        Parameters
        ----------
        assets:
            Paths to the raw TTS audio files and their JSON sidecars.
        config:
            Render configuration; ``config.audio_speed`` is used for scaling.
        bg_audio_volume:
            Volume multiplier for the optional background music track
            (``assets/temp/<reddit_id>/background.mp3``).  Pass ``0.0``
            (the default) to skip background music mixing.

        Returns
        -------
        AudioBundle
            Assembled track with scaled durations and word timestamps.

        Raises
        ------
        AudioAssemblyError
            If any MP3 file is missing or cannot be probed by FFmpeg.
        """
        audio_speed: float = config.audio_speed

        # ------------------------------------------------------------------
        # 1 + 2. Validate existence and probe durations
        # ------------------------------------------------------------------
        all_mp3s: list[Path] = [assets.title_mp3] + list(assets.body_mp3s)

        raw_durations: list[float] = []
        for mp3_path in all_mp3s:
            # probe_duration raises AudioAssemblyError on missing/unprobable files
            raw_durations.append(probe_duration(mp3_path))

        # ------------------------------------------------------------------
        # 3 + 4. Build speed-scaled clips and scale durations
        # ------------------------------------------------------------------
        tts_clips: list[AudioFileClip] = [
            AudioFileClip(str(mp3)).with_speed_scaled(audio_speed)
            for mp3 in all_mp3s
        ]
        scaled_durations: tuple[float, ...] = tuple(
            d / audio_speed for d in raw_durations
        )

        # ------------------------------------------------------------------
        # 5. Concatenate TTS clips
        # ------------------------------------------------------------------
        tts_audio = concatenate_audioclips(tts_clips)

        # ------------------------------------------------------------------
        # 6. Optional background music mix
        # ------------------------------------------------------------------
        # Background music lives at assets/temp/<reddit_id>/background.mp3.
        # We derive the reddit_id from the title_mp3 path:
        #   assets/temp/<reddit_id>/mp3/title.mp3  →  assets/temp/<reddit_id>/
        try:
            bg_music_path = assets.title_mp3.parent.parent / "background.mp3"
        except Exception:
            bg_music_path = None

        if bg_audio_volume > 0 and bg_music_path and exists(str(bg_music_path)):
            bg_music = AudioFileClip(str(bg_music_path)).with_volume_scaled(bg_audio_volume)
            total_tts_dur = tts_audio.duration
            if bg_music.duration >= total_tts_dur:
                bg_music = bg_music.subclipped(0, total_tts_dur)
            final_track = CompositeAudioClip([tts_audio, bg_music])
        else:
            final_track = tts_audio

        # ------------------------------------------------------------------
        # 7. Load word-timestamp JSON sidecars
        # ------------------------------------------------------------------
        word_timestamps: list[WordTimestamp] = []
        # The title clip (index 0) has no sidecar; body clips start at index 1.
        # scaled_durations[0] is the title duration — used as the initial offset.
        time_offset: float = scaled_durations[0]

        for idx, (body_mp3, sidecar_path) in enumerate(
            zip(assets.body_mp3s, assets.word_timestamp_jsons)
        ):
            sidecar = Path(sidecar_path)
            if sidecar.exists():
                try:
                    with open(sidecar, "r", encoding="utf-8") as fh:
                        raw_words: list[dict] = json.load(fh)
                except (OSError, json.JSONDecodeError) as exc:
                    raise AudioAssemblyError(
                        f"Failed to read word-timestamp sidecar {sidecar!r}: {exc}"
                    ) from exc

                for w in raw_words:
                    word_timestamps.append(
                        WordTimestamp(
                            word=w["word"],
                            start=w["start"] / audio_speed + time_offset,
                            end=w["end"] / audio_speed + time_offset,
                        )
                    )

            # Advance offset by this body clip's scaled duration
            # (index into scaled_durations is idx + 1 because index 0 is title)
            time_offset += scaled_durations[idx + 1]

        return AudioBundle(
            track=final_track,
            durations=scaled_durations,
            word_timestamps=tuple(word_timestamps),
        )
