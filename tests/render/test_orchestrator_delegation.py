"""Integration tests for PipelineOrchestrator delegation.

Verifies two things:
1. The orchestrator correctly delegates to each stage (audio, background,
   timing, compositor, output) and passes the right inputs between them.
2. ``orchestrator.py`` does NOT import PIL, numpy, ``ffmpeg``, or
   ``moviepy.VideoClip`` at the module level (AST check).

Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7
"""

from __future__ import annotations

import ast
import textwrap
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, call, patch

import numpy as np
import pytest

from video_creation.render.audio.assembler import AudioAssets, AudioBundle
from video_creation.render.compositor.frame import FrameCompositor
from video_creation.render.context import CanvasSpec, RenderContext
from video_creation.render.orchestrator import PipelineOrchestrator
from video_creation.render.styles.base import BodyAssets
from video_creation.render.timing.models import (
    LineTiming,
    TimingResult,
    WordTimestamp,
)

# ---------------------------------------------------------------------------
# Path to the orchestrator source file
# ---------------------------------------------------------------------------

_ORCHESTRATOR_PY = (
    Path(__file__).parent.parent.parent
    / "video_creation"
    / "render"
    / "orchestrator.py"
)


# ---------------------------------------------------------------------------
# AST check: orchestrator.py must not import PIL, numpy, ffmpeg, or
# moviepy.VideoClip at the module level.
# ---------------------------------------------------------------------------


class TestOrchestratorImportConstraints:
    """AST-level checks that orchestrator.py stays free of heavy dependencies."""

    def _collect_imports(self, source: str) -> list[str]:
        """Walk the AST and collect all imported names / module paths.

        Returns a flat list of strings like:
        - ``"PIL"`` for ``import PIL``
        - ``"PIL.Image"`` for ``import PIL.Image``
        - ``"numpy"`` for ``import numpy``
        - ``"ffmpeg"`` for ``import ffmpeg``
        - ``"moviepy.VideoClip"`` for ``from moviepy import VideoClip``
        - ``"moviepy.video.VideoClip"`` for ``from moviepy.video import VideoClip``
        """
        tree = ast.parse(source)
        imported: list[str] = []

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for alias in node.names:
                    imported.append(f"{module}.{alias.name}" if module else alias.name)

        return imported

    def test_orchestrator_source_exists(self):
        """The orchestrator.py file must exist at the expected path."""
        assert _ORCHESTRATOR_PY.exists(), (
            f"orchestrator.py not found at {_ORCHESTRATOR_PY}"
        )

    def test_no_pil_import(self):
        """orchestrator.py must not import PIL at the module level.

        PIL is allowed only inside the ``_dump_debug_intermediates`` helper
        (a local import), but must not appear as a top-level import.
        """
        source = _ORCHESTRATOR_PY.read_text(encoding="utf-8")
        tree = ast.parse(source)

        # Only check top-level import statements (not those inside functions).
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("PIL"), (
                        f"orchestrator.py has a top-level 'import {alias.name}' "
                        f"— PIL must not be imported at module level (Req 3.6)"
                    )
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                assert not module.startswith("PIL"), (
                    f"orchestrator.py has a top-level 'from {module} import ...' "
                    f"— PIL must not be imported at module level (Req 3.6)"
                )

    def test_no_numpy_import(self):
        """orchestrator.py must not import numpy at the module level."""
        source = _ORCHESTRATOR_PY.read_text(encoding="utf-8")
        tree = ast.parse(source)

        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name != "numpy" and not alias.name.startswith("numpy."), (
                        f"orchestrator.py has a top-level 'import {alias.name}' "
                        f"— numpy must not be imported at module level (Req 3.6)"
                    )
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                assert module != "numpy" and not module.startswith("numpy."), (
                    f"orchestrator.py has a top-level 'from {module} import ...' "
                    f"— numpy must not be imported at module level (Req 3.6)"
                )

    def test_no_ffmpeg_import(self):
        """orchestrator.py must not import ffmpeg at the module level."""
        source = _ORCHESTRATOR_PY.read_text(encoding="utf-8")
        tree = ast.parse(source)

        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name != "ffmpeg" and not alias.name.startswith("ffmpeg."), (
                        f"orchestrator.py has a top-level 'import {alias.name}' "
                        f"— ffmpeg must not be imported at module level (Req 3.6)"
                    )
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                assert module != "ffmpeg" and not module.startswith("ffmpeg."), (
                    f"orchestrator.py has a top-level 'from {module} import ...' "
                    f"— ffmpeg must not be imported at module level (Req 3.6)"
                )

    def test_no_moviepy_videoclip_import(self):
        """orchestrator.py must not import moviepy.VideoClip at the module level.

        The orchestrator is allowed to import stage classes (AudioAssembler,
        BackgroundPreparer, etc.) but must not import VideoClip directly —
        that belongs to FrameCompositor (Req 3.6, 4.3).
        """
        source = _ORCHESTRATOR_PY.read_text(encoding="utf-8")
        tree = ast.parse(source)

        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    # e.g. "import moviepy.VideoClip"
                    assert "VideoClip" not in alias.name, (
                        f"orchestrator.py has a top-level 'import {alias.name}' "
                        f"— VideoClip must not be imported at module level (Req 3.6)"
                    )
            elif isinstance(node, ast.ImportFrom):
                # e.g. "from moviepy import VideoClip"
                for alias in node.names:
                    assert alias.name != "VideoClip", (
                        f"orchestrator.py has a top-level "
                        f"'from {node.module} import {alias.name}' "
                        f"— VideoClip must not be imported at module level (Req 3.6)"
                    )


# ---------------------------------------------------------------------------
# Helpers for delegation tests
# ---------------------------------------------------------------------------


def _make_reddit_obj() -> dict:
    """Return a minimal reddit_obj dict for testing."""
    return {
        "thread_id": "test123",
        "thread_title": "Test Post Title",
        "thread_post": "This is the body text of the post with several words.",
        "author": "test_author",
        "avatar_url": "",
        "thread_score": 100,
        "num_comments": 42,
    }


def _make_audio_assets(tmp_path: Path) -> AudioAssets:
    """Return a minimal AudioAssets pointing at dummy files."""
    title_mp3 = tmp_path / "title.mp3"
    body_mp3 = tmp_path / "body_0.mp3"
    sidecar = tmp_path / "body_0.json"
    # Create empty placeholder files so Path.exists() checks pass if needed.
    title_mp3.touch()
    body_mp3.touch()
    sidecar.touch()
    return AudioAssets(
        title_mp3=title_mp3,
        body_mp3s=(body_mp3,),
        word_timestamp_jsons=(sidecar,),
    )


def _make_word_timestamps() -> tuple[WordTimestamp, ...]:
    """Return a small sequence of word timestamps for testing."""
    words = "This is the body text of the post with several words".split()
    return tuple(
        WordTimestamp(word=w, start=i * 0.3, end=i * 0.3 + 0.25)
        for i, w in enumerate(words)
    )


def _make_timing_result(word_timestamps: tuple[WordTimestamp, ...]) -> TimingResult:
    """Return a minimal TimingResult consistent with the word timestamps."""
    entries = (
        LineTiming(
            text="This is the body text of the post with several words",
            start=word_timestamps[0].start if word_timestamps else 0.0,
            end=word_timestamps[-1].end if word_timestamps else 1.0,
            line_index=0,
            chunk_index=0,
            y_top=0,
            y_bottom=100,
            page_index=0,
        ),
    )
    title_duration = 1.0
    total_duration = title_duration + (word_timestamps[-1].end if word_timestamps else 1.0)
    return TimingResult(
        title_duration=title_duration,
        total_duration=total_duration,
        entries=entries,
    )


def _make_render_config(style_id: str = "custom-card") -> MagicMock:
    """Return a MagicMock that looks like a RenderConfig."""
    config = MagicMock()
    config.style_id = style_id
    config.style_options = {"theme": "light"}
    config.canvas = CanvasSpec(width=1080, height=1920, zoom=1.0, opacity=1.0)
    config.audio_speed = 1.0
    config.theme = "light"
    config.debug_dump_intermediates = False
    config.is_production = True
    config.subreddit = "test"
    return config


def _make_audio_bundle(word_timestamps: tuple[WordTimestamp, ...]) -> AudioBundle:
    """Return a MagicMock AudioBundle with real word timestamps."""
    bundle = MagicMock(spec=AudioBundle)
    bundle.track = MagicMock()
    bundle.durations = (1.0, 0.5)  # title + one body clip
    bundle.word_timestamps = word_timestamps
    return bundle


def _make_header_array() -> np.ndarray:
    """Return a minimal RGBA header array."""
    return np.zeros((100, 100, 4), dtype=np.uint8)


def _make_body_assets() -> BodyAssets:
    """Return a minimal BodyAssets."""
    page = np.zeros((100, 100, 4), dtype=np.uint8)
    return BodyAssets(pages=(page,), chunk_images=(), extra=None)


# ---------------------------------------------------------------------------
# Delegation tests
# ---------------------------------------------------------------------------


class TestOrchestratorDelegation:
    """Verify that PipelineOrchestrator delegates to each stage correctly.

    Each test replaces one or more stages with a MagicMock spy and asserts
    that the stage's method is called with the expected arguments.
    """

    def _build_orchestrator(
        self,
        config: MagicMock,
        audio_spy: MagicMock,
        background_spy: MagicMock,
        timing_spy: MagicMock,
        compositor_spy: MagicMock,
        output_spy: MagicMock,
    ) -> PipelineOrchestrator:
        return PipelineOrchestrator(
            config=config,
            audio=audio_spy,
            background=background_spy,
            timing=timing_spy,
            compositor=compositor_spy,
            output=output_spy,
        )

    def _setup_spies(
        self,
        word_timestamps: tuple[WordTimestamp, ...],
        timing_result: TimingResult,
        output_path: Path,
        style_id: str = "custom-card",
    ) -> tuple[MagicMock, MagicMock, MagicMock, MagicMock, MagicMock, MagicMock]:
        """Create all stage spies with appropriate return values."""
        config = _make_render_config(style_id)

        # AudioAssembler spy
        audio_spy = MagicMock()
        audio_bundle = _make_audio_bundle(word_timestamps)
        audio_spy.assemble.return_value = audio_bundle

        # BackgroundPreparer spy
        background_spy = MagicMock()
        bg_clip = MagicMock()
        background_spy.prepare.return_value = bg_clip

        # TimingEngine spy
        timing_spy = MagicMock()
        timing_spy.compute.return_value = timing_result

        # FrameCompositor spy
        compositor_spy = MagicMock()
        overlay_clip = MagicMock()
        compositor_spy.build_clip.return_value = overlay_clip

        # OutputWriter spy
        output_spy = MagicMock()
        output_spy.write.return_value = output_path

        return config, audio_spy, background_spy, timing_spy, compositor_spy, output_spy

    def test_audio_assembler_called_with_assets_and_config(self, tmp_path):
        """AudioAssembler.assemble is called with (assets, config) — Req 3.1."""
        word_timestamps = _make_word_timestamps()
        timing_result = _make_timing_result(word_timestamps)
        assets = _make_audio_assets(tmp_path)
        output_path = tmp_path / "output.mp4"

        config, audio_spy, background_spy, timing_spy, compositor_spy, output_spy = (
            self._setup_spies(word_timestamps, timing_result, output_path)
        )

        reddit_obj = _make_reddit_obj()

        with patch(
            "video_creation.render.orchestrator.get_style",
            return_value=_make_plugin_class_for_test(),
        ):
            orch = self._build_orchestrator(
                config, audio_spy, background_spy, timing_spy, compositor_spy, output_spy
            )
            orch.render(reddit_obj, assets)

        # AudioAssembler.assemble must be called exactly once with (assets, config).
        audio_spy.assemble.assert_called_once_with(assets, config)

    def test_background_preparer_called_with_reddit_obj_and_config(self, tmp_path):
        """BackgroundPreparer.prepare is called with (reddit_obj, config) — Req 3.2."""
        word_timestamps = _make_word_timestamps()
        timing_result = _make_timing_result(word_timestamps)
        assets = _make_audio_assets(tmp_path)
        output_path = tmp_path / "output.mp4"

        config, audio_spy, background_spy, timing_spy, compositor_spy, output_spy = (
            self._setup_spies(word_timestamps, timing_result, output_path)
        )

        reddit_obj = _make_reddit_obj()

        with patch(
            "video_creation.render.orchestrator.get_style",
            return_value=_make_plugin_class_for_test(),
        ):
            orch = self._build_orchestrator(
                config, audio_spy, background_spy, timing_spy, compositor_spy, output_spy
            )
            orch.render(reddit_obj, assets)

        # BackgroundPreparer.prepare must be called exactly once with (reddit_obj, config).
        background_spy.prepare.assert_called_once_with(reddit_obj, config)

    def test_timing_engine_called_with_word_timestamps_and_line_definitions(
        self, tmp_path
    ):
        """TimingEngine.compute is called with the word timestamps from AudioBundle — Req 3.3."""
        word_timestamps = _make_word_timestamps()
        timing_result = _make_timing_result(word_timestamps)
        assets = _make_audio_assets(tmp_path)
        output_path = tmp_path / "output.mp4"

        config, audio_spy, background_spy, timing_spy, compositor_spy, output_spy = (
            self._setup_spies(word_timestamps, timing_result, output_path)
        )

        reddit_obj = _make_reddit_obj()

        with patch(
            "video_creation.render.orchestrator.get_style",
            return_value=_make_plugin_class_for_test(),
        ):
            orch = self._build_orchestrator(
                config, audio_spy, background_spy, timing_spy, compositor_spy, output_spy
            )
            orch.render(reddit_obj, assets)

        # TimingEngine.compute must be called exactly once.
        timing_spy.compute.assert_called_once()

        # The first positional argument must be the word_timestamps from the bundle.
        call_kwargs = timing_spy.compute.call_args
        assert call_kwargs.kwargs["words"] == word_timestamps, (
            "TimingEngine.compute must receive the word_timestamps from AudioBundle"
        )

        # audio_speed must come from config.
        assert call_kwargs.kwargs["audio_speed"] == config.audio_speed, (
            "TimingEngine.compute must receive audio_speed from config"
        )

        # title_duration must be the first element of audio_bundle.durations.
        assert call_kwargs.kwargs["title_duration"] == audio_spy.assemble.return_value.durations[0], (
            "TimingEngine.compute must receive title_duration from AudioBundle.durations[0]"
        )

    def test_compositor_called_with_duration_and_make_frame(self, tmp_path):
        """FrameCompositor.build_clip is called with (duration, make_frame) — Req 3.4."""
        word_timestamps = _make_word_timestamps()
        timing_result = _make_timing_result(word_timestamps)
        assets = _make_audio_assets(tmp_path)
        output_path = tmp_path / "output.mp4"

        config, audio_spy, background_spy, timing_spy, compositor_spy, output_spy = (
            self._setup_spies(word_timestamps, timing_result, output_path)
        )

        reddit_obj = _make_reddit_obj()

        with patch(
            "video_creation.render.orchestrator.get_style",
            return_value=_make_plugin_class_for_test(),
        ):
            orch = self._build_orchestrator(
                config, audio_spy, background_spy, timing_spy, compositor_spy, output_spy
            )
            orch.render(reddit_obj, assets)

        # FrameCompositor.build_clip must be called exactly once.
        compositor_spy.build_clip.assert_called_once()

        call_kwargs = compositor_spy.build_clip.call_args
        # duration must equal timing_result.total_duration.
        assert call_kwargs.kwargs["duration"] == timing_result.total_duration, (
            "FrameCompositor.build_clip must receive duration=timing_result.total_duration"
        )
        # make_frame must be a callable.
        assert callable(call_kwargs.kwargs["make_frame"]), (
            "FrameCompositor.build_clip must receive a callable make_frame"
        )

    def test_output_writer_called_with_all_stage_outputs(self, tmp_path):
        """OutputWriter.write is called with all stage outputs — Req 3.5."""
        word_timestamps = _make_word_timestamps()
        timing_result = _make_timing_result(word_timestamps)
        assets = _make_audio_assets(tmp_path)
        output_path = tmp_path / "output.mp4"

        config, audio_spy, background_spy, timing_spy, compositor_spy, output_spy = (
            self._setup_spies(word_timestamps, timing_result, output_path)
        )

        reddit_obj = _make_reddit_obj()

        with patch(
            "video_creation.render.orchestrator.get_style",
            return_value=_make_plugin_class_for_test(),
        ):
            orch = self._build_orchestrator(
                config, audio_spy, background_spy, timing_spy, compositor_spy, output_spy
            )
            result = orch.render(reddit_obj, assets)

        # OutputWriter.write must be called exactly once.
        output_spy.write.assert_called_once()

        call_kwargs = output_spy.write.call_args
        # background must be the return value of BackgroundPreparer.prepare.
        assert call_kwargs.kwargs["background"] is background_spy.prepare.return_value, (
            "OutputWriter.write must receive background from BackgroundPreparer.prepare"
        )
        # overlay must be the return value of FrameCompositor.build_clip.
        assert call_kwargs.kwargs["overlay"] is compositor_spy.build_clip.return_value, (
            "OutputWriter.write must receive overlay from FrameCompositor.build_clip"
        )
        # audio must be the track from AudioBundle.
        assert call_kwargs.kwargs["audio"] is audio_spy.assemble.return_value.track, (
            "OutputWriter.write must receive audio from AudioBundle.track"
        )
        # reddit_obj must be passed through unchanged.
        assert call_kwargs.kwargs["reddit_obj"] is reddit_obj, (
            "OutputWriter.write must receive the original reddit_obj"
        )
        # config must be passed through.
        assert call_kwargs.kwargs["config"] is config, (
            "OutputWriter.write must receive the config"
        )

        # render() must return the path from OutputWriter.write.
        assert result is output_path, (
            "PipelineOrchestrator.render must return the path from OutputWriter.write"
        )

    def test_all_stages_called_exactly_once(self, tmp_path):
        """All five stages are called exactly once per render() invocation."""
        word_timestamps = _make_word_timestamps()
        timing_result = _make_timing_result(word_timestamps)
        assets = _make_audio_assets(tmp_path)
        output_path = tmp_path / "output.mp4"

        config, audio_spy, background_spy, timing_spy, compositor_spy, output_spy = (
            self._setup_spies(word_timestamps, timing_result, output_path)
        )

        reddit_obj = _make_reddit_obj()

        with patch(
            "video_creation.render.orchestrator.get_style",
            return_value=_make_plugin_class_for_test(),
        ):
            orch = self._build_orchestrator(
                config, audio_spy, background_spy, timing_spy, compositor_spy, output_spy
            )
            orch.render(reddit_obj, assets)

        audio_spy.assemble.assert_called_once()
        background_spy.prepare.assert_called_once()
        timing_spy.compute.assert_called_once()
        compositor_spy.build_clip.assert_called_once()
        output_spy.write.assert_called_once()

    def test_plugin_render_header_and_body_called(self, tmp_path):
        """The plugin's render_header and render_body are called — Req 3.4."""
        word_timestamps = _make_word_timestamps()
        timing_result = _make_timing_result(word_timestamps)
        assets = _make_audio_assets(tmp_path)
        output_path = tmp_path / "output.mp4"

        config, audio_spy, background_spy, timing_spy, compositor_spy, output_spy = (
            self._setup_spies(word_timestamps, timing_result, output_path)
        )

        reddit_obj = _make_reddit_obj()

        plugin_cls = _make_plugin_class_for_test()
        # Spy on the class to track instantiation and method calls.
        with patch(
            "video_creation.render.orchestrator.get_style",
            return_value=plugin_cls,
        ):
            orch = self._build_orchestrator(
                config, audio_spy, background_spy, timing_spy, compositor_spy, output_spy
            )
            orch.render(reddit_obj, assets)

        # The plugin instance's render_header and render_body must have been called.
        # We verify this by checking the plugin class's call tracking.
        assert plugin_cls._render_header_call_count == 1, (
            "plugin.render_header must be called exactly once"
        )
        assert plugin_cls._render_body_call_count == 1, (
            "plugin.render_body must be called exactly once"
        )

    def test_make_frame_calls_plugin_compose_frame(self, tmp_path):
        """The make_frame lambda passed to FrameCompositor calls plugin.compose_frame."""
        word_timestamps = _make_word_timestamps()
        timing_result = _make_timing_result(word_timestamps)
        assets = _make_audio_assets(tmp_path)
        output_path = tmp_path / "output.mp4"

        config, audio_spy, background_spy, timing_spy, compositor_spy, output_spy = (
            self._setup_spies(word_timestamps, timing_result, output_path)
        )

        reddit_obj = _make_reddit_obj()

        plugin_cls = _make_plugin_class_for_test()

        with patch(
            "video_creation.render.orchestrator.get_style",
            return_value=plugin_cls,
        ):
            orch = self._build_orchestrator(
                config, audio_spy, background_spy, timing_spy, compositor_spy, output_spy
            )
            orch.render(reddit_obj, assets)

        # Extract the make_frame callable passed to compositor.build_clip.
        call_kwargs = compositor_spy.build_clip.call_args
        make_frame = call_kwargs.kwargs["make_frame"]

        # Calling make_frame(t) should invoke plugin.compose_frame.
        frame = make_frame(0.0)
        assert isinstance(frame, np.ndarray), (
            "make_frame(t) must return a numpy.ndarray"
        )
        assert frame.shape[-1] == 4, (
            "make_frame(t) must return an RGBA array (last dim == 4)"
        )
        assert plugin_cls._compose_frame_call_count >= 1, (
            "make_frame(t) must call plugin.compose_frame"
        )


# ---------------------------------------------------------------------------
# Helper: a minimal plugin class with call tracking
# ---------------------------------------------------------------------------


def _make_plugin_class_for_test():
    """Create a minimal CardStylePlugin subclass with call counters.

    The class-level counters are reset each time this factory is called,
    so each test gets a fresh plugin class.
    """
    from video_creation.render.styles.base import CardStylePlugin

    class _TestPlugin(CardStylePlugin):
        style_id = "test-delegation-plugin"
        options_schema = {"theme": str}

        # Class-level call counters (reset per factory call).
        _render_header_call_count = 0
        _render_body_call_count = 0
        _compose_frame_call_count = 0

        def render_header(self, ctx: RenderContext) -> np.ndarray:
            type(self)._render_header_call_count += 1
            return _make_header_array()

        def render_body(self, ctx: RenderContext, line_timings) -> BodyAssets:
            type(self)._render_body_call_count += 1
            return _make_body_assets()

        def compose_frame(
            self,
            t: float,
            ctx: RenderContext,
            header: np.ndarray,
            body: BodyAssets,
            line_timings,
        ) -> np.ndarray:
            type(self)._compose_frame_call_count += 1
            canvas = ctx.canvas
            return np.zeros((canvas.height, canvas.width, 4), dtype=np.uint8)

    # Reset counters for this fresh class.
    _TestPlugin._render_header_call_count = 0
    _TestPlugin._render_body_call_count = 0
    _TestPlugin._compose_frame_call_count = 0

    return _TestPlugin
