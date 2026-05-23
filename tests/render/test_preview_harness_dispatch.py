"""Property test for preview harness dispatch.

# Feature: card-rendering-refactor, Property 17

Validates: Requirements 10.1, 10.2, 10.3

The PreviewHarness SHALL render using only the public Render_Pipeline API
and SHALL NOT re-implement frame composition, header/body rendering, or timing.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure all four plugins are registered.
import video_creation.render.styles  # noqa: F401

from video_creation.render.styles import available_styles


_FIXTURE = {
    "thread_id": "harness_test",
    "thread_title": "Harness test post",
    "thread_post": "This is the body text for the harness test.",
    "author": "testuser",
    "avatar_url": "",
    "thread_score": 42,
    "num_comments": 5,
    "comments": [],
}


@pytest.mark.parametrize("style_id", available_styles())
def test_harness_calls_orchestrator_render(style_id: str, tmp_path: Path) -> None:
    """PreviewHarness calls PipelineOrchestrator.render (Req 10.1, 10.3)."""
    fixture_path = tmp_path / "post.json"
    fixture_path.write_text(json.dumps(_FIXTURE))
    output_path = tmp_path / "preview.mp4"

    # Patch PipelineOrchestrator.render to avoid real FFmpeg/audio
    with patch(
        "video_creation.render.orchestrator.PipelineOrchestrator.render",
        return_value=output_path,
    ) as mock_render:
        from video_creation.render.preview.harness import run
        run([
            "--style", style_id,
            "--post-fixture", str(fixture_path),
            "--timings", "fake",
            "--wps", "3.0",
            "--output", str(output_path),
        ])

    mock_render.assert_called_once()


def test_harness_does_not_reimplement_compose_frame(tmp_path: Path) -> None:
    """PreviewHarness source must not define compose_frame (Req 10.2)."""
    import ast
    harness_src = Path(__file__).parent.parent.parent / "video_creation" / "render" / "preview" / "harness.py"
    tree = ast.parse(harness_src.read_text())
    func_names = [
        node.name for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    assert "compose_frame" not in func_names
    assert "render_header" not in func_names
    assert "render_body" not in func_names
