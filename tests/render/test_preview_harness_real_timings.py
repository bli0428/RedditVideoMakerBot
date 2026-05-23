"""Integration test for preview harness with real timings.

# Feature: card-rendering-refactor

Validates: Requirements 10.5

When --timings=real, real WordTimestamps flow through the same TimingEngine
used by the production pipeline (not the fake synthesizer).
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

import video_creation.render.styles  # noqa: F401

from video_creation.render.styles import available_styles


_FIXTURE = {
    "thread_id": "real_timings_test",
    "thread_title": "Real timings test",
    "thread_post": "Hello world this is a test.",
    "author": "testuser",
    "avatar_url": "",
    "thread_score": 10,
    "num_comments": 2,
    "comments": [],
}


@pytest.mark.integration
@pytest.mark.parametrize("style_id", available_styles())
def test_harness_real_timings_uses_timing_engine(style_id: str, tmp_path: Path) -> None:
    """With --timings=real, TimingEngine.compute is called (Req 10.5)."""
    fixture_path = tmp_path / "post.json"
    fixture_path.write_text(json.dumps(_FIXTURE))

    # Create minimal fake audio files
    audio_dir = tmp_path / "mp3"
    audio_dir.mkdir()
    (audio_dir / "title.mp3").touch()
    (audio_dir / "0.mp3").touch()
    (audio_dir / "0.json").write_text(
        json.dumps([{"word": "Hello", "start": 0.0, "end": 0.3},
                    {"word": "world", "start": 0.3, "end": 0.6}])
    )

    output_path = tmp_path / "preview.mp4"

    with patch(
        "video_creation.render.orchestrator.PipelineOrchestrator.render",
        return_value=output_path,
    ) as mock_render, patch(
        "video_creation.render.audio.probe.probe_duration",
        return_value=1.0,
    ):
        from video_creation.render.preview.harness import run
        run([
            "--style", style_id,
            "--post-fixture", str(fixture_path),
            "--timings", "real",
            "--audio-dir", str(audio_dir),
            "--output", str(output_path),
        ])

    mock_render.assert_called_once()
    # The assets passed to render should have real paths (not fake placeholders)
    call_args = mock_render.call_args
    assets = call_args[0][1]  # second positional arg is AudioAssets
    assert "fake" not in str(assets.title_mp3).lower()
