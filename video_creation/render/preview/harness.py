"""PreviewHarness — CLI replacement for test_transition.py.

Renders a preview MP4 using only the public Render_Pipeline API.
Does NOT re-implement frame composition, header/body rendering, or timing.

Usage::

    python -m video_creation.render.preview \\
        --style reddit-karaoke \\
        --post-fixture fixtures/tifu.json \\
        --timings fake \\
        --wps 3.0 \\
        --output preview.mp4

    python -m video_creation.render.preview \\
        --style custom-card \\
        --post-fixture fixtures/tifu.json \\
        --timings real \\
        --audio-dir assets/temp/<reddit_id>/mp3 \\
        --output preview.mp4

Satisfies: Requirements 10.1, 10.2, 10.3, 10.4, 10.5
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m video_creation.render.preview",
        description="Render a preview MP4 without running a full TTS pass.",
    )
    p.add_argument(
        "--style",
        required=True,
        help="Style identifier (e.g. reddit-karaoke, custom-card).",
    )
    p.add_argument(
        "--post-fixture",
        required=True,
        metavar="PATH",
        help="Path to a JSON file containing the Reddit post payload.",
    )
    p.add_argument(
        "--timings",
        choices=["fake", "real"],
        default="fake",
        help=(
            "'fake' synthesizes word timestamps at --wps words/sec; "
            "'real' reads timestamps from --audio-dir/*.json sidecars."
        ),
    )
    p.add_argument(
        "--audio-dir",
        metavar="DIR",
        default=None,
        help="Directory containing title.mp3, body MP3s, and .json sidecars "
             "(required when --timings=real).",
    )
    p.add_argument(
        "--wps",
        type=float,
        default=3.0,
        help="Words per second for fake timing synthesis (default: 3.0).",
    )
    p.add_argument(
        "--output",
        default="preview.mp4",
        metavar="PATH",
        help="Output MP4 path (default: preview.mp4).",
    )
    return p


def run(argv: list[str] | None = None) -> None:
    """Entry point for the preview harness CLI."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    # ------------------------------------------------------------------
    # 1. Load the post fixture
    # ------------------------------------------------------------------
    fixture_path = Path(args.post_fixture)
    if not fixture_path.exists():
        print(f"Error: post fixture not found: {fixture_path}", file=sys.stderr)
        sys.exit(1)

    with open(fixture_path, "r", encoding="utf-8") as fh:
        reddit_obj: dict = json.load(fh)

    # ------------------------------------------------------------------
    # 2. Build AudioAssets
    # ------------------------------------------------------------------
    from video_creation.render.audio.assembler import AudioAssets

    if args.timings == "real":
        if not args.audio_dir:
            print(
                "Error: --audio-dir is required when --timings=real",
                file=sys.stderr,
            )
            sys.exit(1)

        audio_dir = Path(args.audio_dir)
        if not audio_dir.is_dir():
            print(f"Error: audio directory not found: {audio_dir}", file=sys.stderr)
            sys.exit(1)

        # Discover body MP3s: 0.mp3, 1.mp3, ... or postaudio.mp3
        title_mp3 = audio_dir / "title.mp3"
        body_mp3s: list[Path] = []
        sidecar_jsons: list[Path] = []

        # Try numbered clips first (comment mode / storymodemethod=1)
        i = 0
        while (audio_dir / f"{i}.mp3").exists():
            body_mp3s.append(audio_dir / f"{i}.mp3")
            sidecar_jsons.append(audio_dir / f"{i}.json")
            i += 1

        # Fall back to postaudio.mp3 (storymodemethod=0)
        if not body_mp3s and (audio_dir / "postaudio.mp3").exists():
            body_mp3s.append(audio_dir / "postaudio.mp3")
            sidecar_jsons.append(audio_dir / "postaudio.json")

        assets = AudioAssets(
            title_mp3=title_mp3,
            body_mp3s=tuple(body_mp3s),
            word_timestamp_jsons=tuple(sidecar_jsons),
        )

    else:
        # --timings=fake: synthesize timestamps from the post body text
        from video_creation.render.preview.fake_timings import synth_word_timestamps

        # Extract body text from the fixture
        thread_post = reddit_obj.get("thread_post", "")
        if isinstance(thread_post, list):
            body_text = " ".join(thread_post)
        else:
            body_text = str(thread_post or "")

        words = body_text.split()
        fake_ts = synth_word_timestamps(words, wps=args.wps)

        # Build a minimal AudioAssets with non-existent paths — the
        # FakeAudioAssembler below will ignore them.
        assets = AudioAssets(
            title_mp3=Path("__fake_title__.mp3"),
            body_mp3s=(Path("__fake_body__.mp3"),),
            word_timestamp_jsons=(Path("__fake_body__.json"),),
        )

    # ------------------------------------------------------------------
    # 3. Build RenderConfig
    # ------------------------------------------------------------------
    from video_creation.render.config import RenderConfig
    from video_creation.render.context import CanvasSpec
    from video_creation.render.styles import available_styles, get_style

    registered = available_styles()
    if args.style not in registered:
        print(
            f"Error: unknown style {args.style!r}. "
            f"Available: {', '.join(registered)}",
            file=sys.stderr,
        )
        sys.exit(1)

    plugin_cls = get_style(args.style)
    options: dict = {}
    if "theme" in plugin_cls.options_schema:
        options["theme"] = "light"
    if "dismiss_title_on_body" in plugin_cls.options_schema:
        options["dismiss_title_on_body"] = False
    if "karaoke_words_per_chunk" in plugin_cls.options_schema:
        options["karaoke_words_per_chunk"] = 3

    config = RenderConfig(
        style_id=args.style,
        style_options=options,
        canvas=CanvasSpec(width=1080, height=1920, zoom=1.0, opacity=1.0),
        audio_speed=1.0,
        theme="light",
        debug_dump_intermediates=False,
        is_production=False,
        subreddit=reddit_obj.get("subreddit", "preview"),
    )

    # ------------------------------------------------------------------
    # 4. Run the pipeline via the public API
    # ------------------------------------------------------------------
    from video_creation.render.audio.assembler import AudioAssembler, AudioBundle
    from video_creation.render.background.preparer import BackgroundPreparer
    from video_creation.render.compositor.frame import FrameCompositor
    from video_creation.render.orchestrator import PipelineOrchestrator
    from video_creation.render.output.writer import OutputWriter
    from video_creation.render.timing.engine import TimingEngine
    from video_creation.render.timing.models import WordTimestamp

    import numpy as np

    output_path = Path(args.output)

    if args.timings == "fake":
        # Use a fake assembler that returns the synthesized timestamps
        # without touching the filesystem.
        _fake_ts = fake_ts  # captured from above

        class _FakeAudioAssembler:
            def assemble(self, _assets, _config):
                from moviepy import AudioClip

                total_dur = len(_fake_ts) / args.wps if _fake_ts else 1.0
                title_dur = 0.5  # synthetic title duration

                def _silence(t):
                    if np.isscalar(t):
                        return np.zeros(2)
                    return np.zeros((len(t), 2))

                silent = AudioClip(_silence, duration=title_dur + total_dur, fps=44100)
                return AudioBundle(
                    track=silent,
                    durations=(title_dur, total_dur),
                    word_timestamps=_fake_ts,
                )

        audio_stage = _FakeAudioAssembler()
    else:
        audio_stage = AudioAssembler()

    class _FakeBackgroundPreparer:
        """Returns a minimal solid-colour clip without running FFmpeg."""

        def prepare(self, _reddit_obj, cfg):
            from moviepy import VideoClip

            W = cfg.canvas.width
            H = cfg.canvas.height
            frame = np.zeros((H, W, 3), dtype=np.uint8)

            def _make_frame(t):
                return frame

            return VideoClip(_make_frame, duration=60).with_fps(30)

    class _PreviewOutputWriter:
        """Writes the preview MP4 to the requested output path."""

        def write(self, background, overlay, audio, reddit_obj, config):
            from moviepy import CompositeVideoClip

            W = config.canvas.width
            H = config.canvas.height

            try:
                final = CompositeVideoClip([background, overlay], size=(W, H))
                final = final.with_duration(audio.duration)
                final = final.with_audio(audio)
            except Exception:
                final = background.with_duration(min(audio.duration, 10.0))

            output_path.parent.mkdir(parents=True, exist_ok=True)
            final.write_videofile(
                str(output_path),
                fps=30,
                codec="libx264",
                audio_codec="aac",
                logger="bar",
            )
            return output_path

    orchestrator = PipelineOrchestrator(
        config=config,
        audio=audio_stage,
        background=_FakeBackgroundPreparer(),
        timing=TimingEngine(),
        compositor=FrameCompositor(fps=30),
        output=_PreviewOutputWriter(),
    )

    result = orchestrator.render(reddit_obj, assets)
    print(f"Preview written to: {result}")
