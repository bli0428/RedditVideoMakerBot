# Implementation Plan: Card Rendering Refactor

## Overview

The refactor lands in five phases that each leave the build green and `make_final_video` behavior unchanged until the final switchover. Phase 1 carves out the `video_creation/render/` skeleton and moves pure helpers without changing behavior. Phase 2 extracts the timing math into a pure-Python `TimingEngine`. Phase 3 introduces the `CardStylePlugin` interface, four plugins as thin wrappers around the existing renderers, and a `RenderConfig` with a legacy flat-key fallback so the old `card_style` + `body_style` config still works. Phase 4 switches `make_final_video` to call into the new pipeline, lands `FrameCompositor`'s mask-from-alpha cache, makes plugins produce RGBA `numpy.ndarray`s natively, and adds the debug-dump path. Phase 5 deletes the deprecated surfaces, ships the `PreviewHarness`, removes the legacy config fallback, and lands the static-layout tests.

Property numbers (P1–P17) reference the design's Correctness Properties section. Requirement numbers (X.Y) reference the granular sub-requirements in `requirements.md`.

## Tasks

- [x] 1. Phase 1 — Carve out `video_creation/render/` skeleton (no behavior change)
  - [x] 1.1 Create the `video_creation/render/` package skeleton
    - Add empty `__init__.py` files for `render/`, `audio/`, `background/`, `timing/`, `output/`, `compositor/`, `styles/`, `styles/shared/`, `preview/`
    - Create empty placeholder modules listed in the design's Package Layout (`api.py`, `orchestrator.py`, `config.py`, `context.py`, `audio/assembler.py`, `audio/probe.py`, `background/preparer.py`, `output/writer.py`, `output/naming.py`, `compositor/frame.py`, `compositor/blend.py`, `styles/base.py`, `timing/models.py`, `timing/engine.py`, `preview/harness.py`, `preview/fake_timings.py`)
    - Add a `tests/render/` directory with `__init__.py` and `tests/render/strategies.py` placeholder
    - _Requirements: 12.2_

  - [x] 1.2 Add the `errors.py` hierarchy
    - Create `video_creation/render/errors.py` with `RenderError`, `UnknownStyleError(RenderError, KeyError)`, `ConfigError(RenderError, ValueError)`, `ConfigWarning(UserWarning)`, `AudioAssemblyError`, `BackgroundPreparationError`, `OutputWriteError`
    - _Requirements: 2.3, 3.7, 7.5, 8.4_

  - [x] 1.3 Move pure helpers out of `final_video.py` and `utils/card.py` into shared modules
    - `name_normalize` → `video_creation/render/output/naming.py`
    - `_strip_emojis`, `_wrap`, `_text_size`, `_format_count` → `video_creation/render/styles/shared/text.py`
    - `_load_font` and font path constants → `video_creation/render/styles/shared/fonts.py`
    - `_download_avatar` → `video_creation/render/styles/shared/avatar.py`
    - `_draw_heart`, `_draw_bubble`, `_make_checkmark` → `video_creation/render/styles/shared/icons.py`
    - `_render_emoji_row`, `_make_french_flag`, `_render_award_row` → `video_creation/render/styles/shared/emoji_row.py`
    - `_pop_and_zoom`, `_apply_zoom`, `header_pop_zoom_scale` → `video_creation/render/styles/shared/animation.py`
    - The inlined `_composite` alpha-composite primitive (currently in `test_transition.py`) → `video_creation/render/compositor/blend.py` as `composite_rgba_onto`
    - `_render_caption_image`, `_render_karaoke_line` → `video_creation/render/styles/shared/captions.py`
    - _Requirements: 11.1, 11.2, 12.3_

  - [x] 1.4 Re-import the moved helpers from their original locations
    - In `video_creation/final_video.py`, replace each helper definition with `from video_creation.render.<new_path> import <helper>` so `make_final_video` keeps the same behavior
    - In `utils/card.py`, replace each helper definition (`_load_font`, `_render_emoji_row`, `_make_french_flag`, etc.) with the new imports — keep the `_BaseCard` / `_CustomCard` / `_RedditStyleCard` / `render_card` / `render_post_card` API intact for now
    - _Requirements: 12.3_

- [x] 2. Checkpoint — Phase 1 complete; build is green; `make_final_video` produces byte-identical output to its pre-refactor behavior
  - Ensure all tests pass, ask the user if questions arise.

- [x] 3. Phase 2 — Extract pure-Python `TimingEngine`
  - [x] 3.1 Define timing data models
    - In `video_creation/render/timing/models.py`, add frozen dataclasses `WordTimestamp(word, start, end)`, `LineDefinition(text, word_count, y_top, y_bottom, page_index)`, `LineTiming(text, start, end, line_index, chunk_index, y_top, y_bottom, page_index)`, `TimingResult(title_duration, total_duration, entries)`
    - _Requirements: 6.1_

  - [x] 3.2 Implement `TimingEngine.compute` as a pure-Python class
    - In `video_creation/render/timing/engine.py`, lift the word→line/chunk timing block from `final_video.py:make_final_video` (the `for lp in line_positions: ... line_timings.append(...)` block) into `TimingEngine.compute(words, line_definitions, chunk_size, audio_speed, title_duration) -> TimingResult`
    - Validate inputs (e.g., sum of `line_definitions[*].word_count == len(words)`); raise `ValueError` on mismatch (no silent truncation)
    - Module MUST NOT import PIL, numpy, MoviePy, or FFmpeg — only stdlib
    - _Requirements: 3.3, 6.1, 6.2, 7.4_

  - [x] 3.3 Wire `TimingEngine` into `make_final_video`
    - Replace the inlined timing block in `video_creation/final_video.py` with a call to `TimingEngine().compute(...)`, converting the existing `line_positions` list-of-dicts into `LineDefinition`s and the `all_word_timestamps` list-of-dicts into `WordTimestamp`s at the boundary
    - Plugins-to-be (still inlined here as `body_style` branches) read `LineTiming.start`/`end` rather than re-deriving from word offsets
    - _Requirements: 3.3, 6.3_

  - [x] 3.4 Write property test for TimingEngine well-formedness and determinism
    - **Property 8: TimingEngine output is well-formed and deterministic**
    - **Validates: Requirements 6.1**
    - In `tests/render/test_timing_well_formed.py` using Hypothesis: generate `WordTimestamp` sequences with monotonically non-decreasing `start` and `start <= end`, plus matching `LineDefinition` sequences whose `word_count` sum equals `len(words)`; assert entries are ordered by `start`, each `start <= end`, the multiset of words consumed equals the input, and two `compute` calls with the same inputs return equal `TimingResult`s
    - Tag with `# Feature: card-rendering-refactor, Property 8`

  - [x] 3.5 Write property test for karaoke chunking math
    - **Property 9: Karaoke chunking splits lines by chunk_size**
    - **Validates: Requirements 7.4**
    - In `tests/render/test_timing_chunking.py` using Hypothesis: for any line definition with `n` words and any `chunk_size = k > 0`, assert `TimingEngine.compute` emits exactly `ceil(n / k)` `LineTiming` entries for that line, the entries' `text.split()` lengths sum to `n`, and the first `floor(n / k)` entries each have exactly `k` words
    - Tag with `# Feature: card-rendering-refactor, Property 9`

- [x] 4. Checkpoint — Phase 2 complete; timing math lives in a pure module and properties P8 and P9 hold
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Phase 3 — Plugin architecture as thin wrappers + legacy fallback
  - [x] 5.1 Define the `CardStylePlugin` ABC and its companion types
    - In `video_creation/render/styles/base.py`, add the `CardStylePlugin` ABC with `style_id`, `options_schema`, `__init__(options, canvas)`, and abstract methods `render_header(ctx) -> np.ndarray`, `render_body(ctx, line_timings) -> BodyAssets`, `compose_frame(t, ctx, header, body, line_timings) -> np.ndarray`
    - Add `BodyAssets(pages, chunk_images, extra)` frozen dataclass in the same module
    - In `video_creation/render/context.py`, add `CanvasSpec(width, height, zoom, opacity)` and `RenderContext(title, body_text, author, avatar_url, subreddit, upvotes, num_comments, canvas, theme)` with `RenderContext.from_reddit_obj(reddit_obj, config)` classmethod
    - _Requirements: 1.1, 1.4, 11.3_

  - [x] 5.2 Implement the `StyleRegistry`
    - In `video_creation/render/styles/__init__.py`, implement the `_REGISTRY` dict, the `@register_style` decorator that validates `cls.style_id`, the `available_styles()` function, and `get_style(style_id)` raising `UnknownStyleError` (re-exported from `errors.py`) listing the registered identifiers
    - _Requirements: 2.1, 2.2, 2.3, 2.4_

  - [x] 5.3 Wrap `_CustomCard` as the `custom-card` plugin
    - In `video_creation/render/styles/custom_card.py`, define `CustomCardStyle(CardStylePlugin)` with `style_id = "custom-card"` and `options_schema = {"theme": str, "dismiss_title_on_body": bool}`, decorated with `@register_style`
    - `render_header(ctx)` calls into `utils.card._CustomCard._render_header()` (writing a temp PNG) and returns `numpy.array(Image.open(path).convert("RGBA"))`
    - `render_body(ctx, line_timings)` similarly delegates to `_CustomCard._render_body_page` and returns `BodyAssets(pages=tuple(np.array(...) for each page))` with line-position metadata in `extra`
    - `compose_frame(t, ...)` returns the paginated mask-reveal RGBA frame currently produced by `final_video.py:make_combined_frame` for `body_style == "card"` and `card_style == "custom"`
    - Class-level constants for layout (display width pct, header Y, body Y, pop dur, scroll time, zoom amount) — no module-level constants shared with other plugins
    - _Requirements: 1.4, 7.1, 11.1, 11.2, 12.2_

  - [x] 5.4 Wrap `_CustomCard` as the `custom-karaoke` plugin
    - In `video_creation/render/styles/custom_karaoke.py`, define `CustomKaraokeStyle(CardStylePlugin)` with `style_id = "custom-karaoke"` and `options_schema = {"theme": str, "karaoke_words_per_chunk": int}`, decorated with `@register_style`
    - `render_header(ctx)` shares the custom header path (via `styles/shared/`, not via plugin-to-plugin imports)
    - `render_body(ctx, line_timings)` produces one centered caption RGBA per `line_timing` (via `styles.shared.captions._render_karaoke_line`), populating `BodyAssets.chunk_images`
    - `compose_frame(t, ...)` returns the karaoke pop-in / fade-out frame currently produced by `make_combined_frame` for `body_style == "karaoke"` and `card_style == "custom"`
    - _Requirements: 1.4, 7.1, 7.4, 11.1, 12.2, 12.3_

  - [x] 5.5 Wrap `_RedditStyleCard` as the `reddit-card` plugin
    - In `video_creation/render/styles/reddit_card.py`, define `RedditCardStyle` with `style_id = "reddit-card"` and `options_schema = {"theme": str, "dismiss_title_on_body": bool}`, decorated with `@register_style`
    - `render_header(ctx)` delegates to `utils.card._RedditStyleCard._render_header()`; `render_body` delegates to `_render_body_page`
    - `compose_frame(t, ...)` returns the reddit-header + paginated-body RGBA frame
    - Own class-level layout constants
    - _Requirements: 1.4, 7.1, 11.1, 12.2_

  - [x] 5.6 Wrap `_RedditStyleCard` as the `reddit-karaoke` plugin
    - In `video_creation/render/styles/reddit_karaoke.py`, define `RedditKaraokeStyle` with `style_id = "reddit-karaoke"` and `options_schema = {"theme": str, "karaoke_words_per_chunk": int, "dismiss_title_on_body": bool}`, decorated with `@register_style`
    - `render_header` shares the reddit header path; `render_body` produces karaoke RGBA captions
    - `compose_frame` returns the reddit-header + karaoke-body frame, including the `dismiss_title_on_body` header fade currently in `_header_alpha`
    - _Requirements: 1.4, 7.1, 7.4, 7.6, 11.1, 12.2, 12.3_

  - [x] 5.7 Implement `RenderConfig` with legacy flat-key fallback
    - In `video_creation/render/config.py`, add the frozen `RenderConfig` dataclass (`style_id`, `style_options`, `canvas`, `audio_speed`, `theme`, `debug_dump_intermediates`, `is_production`) and a `from_settings(settings_dict)` classmethod
    - When `settings["settings"]["style"]` is present, validate against `available_styles()` (raise `UnknownStyleError` listing registered ids) and read `[settings.style.<id>]` into `style_options`, validating against the plugin's `options_schema` (raise `ConfigError` for type mismatches; ignore unknown keys with `ConfigWarning`)
    - When `style` is missing, fall back to mapping legacy `card_style + body_style + karaoke_words_per_chunk + dismiss_title_on_body + theme` flat keys to one of the four `style_id`s (compatibility shim for one release; emit a `ConfigWarning` advising migration)
    - Coerce `karaoke_words_per_chunk <= 0` to the documented default `3` with a `ConfigWarning`
    - _Requirements: 7.5, 8.1, 8.2, 8.3, 8.4_

  - [x] 5.8 Implement the public API (`render_video`, `available_styles`, `plugin_options_schema`)
    - In `video_creation/render/api.py`, implement `render_video(style_id, reddit_obj, audio, config_overrides=None) -> Path` that builds a `RenderConfig`, looks up the plugin via `get_style`, and (in this phase) wires through to the existing `final_video` composition path so the four registered styles produce identical output
    - Implement `available_styles()` re-exporting `styles.available_styles`
    - Implement `plugin_options_schema(style_id) -> Mapping[str, type]` returning `get_style(style_id).options_schema`
    - In `video_creation/render/__init__.py`, re-export `render_video`, `available_styles`, `plugin_options_schema`
    - _Requirements: 1.3, 13.1, 13.2, 13.3_

  - [x] 5.9 Write property test for registry round-trip dispatch
    - **Property 1: Registry round-trip dispatch**
    - **Validates: Requirements 1.2, 2.1, 2.2, 2.4, 8.1, 8.3, 13.1**
    - In `tests/render/test_registry_dispatch.py` using Hypothesis: register a generated `CardStylePlugin` subclass with a random `style_id` (using a registry-reset fixture); for any registered `style_id` and any options conforming to its `options_schema`, assert that `render_video(style_id=id, ..., config=opts)` instantiates the class returned by `get_style(id)` with those options and uses it to produce the per-frame composition (verify via a spy on `compose_frame`)
    - Tag with `# Feature: card-rendering-refactor, Property 1`

  - [x] 5.10 Write property test for unknown style identifier error
    - **Property 2: Unknown style identifier error**
    - **Validates: Requirements 2.3, 8.4**
    - In `tests/render/test_unknown_style.py` using Hypothesis: for any string `s` not in `available_styles()`, assert that both `get_style(s)` and `RenderConfig.from_settings({"style": s, ...})` raise `UnknownStyleError` whose message contains the literal `s` and every currently-registered identifier
    - Tag with `# Feature: card-rendering-refactor, Property 2`

  - [x] 5.11 Write property test for frame shape and dtype
    - **Property 3: Frame is RGBA with canvas dimensions**
    - **Validates: Requirements 4.1, 11.3**
    - In `tests/render/test_frame_shape.py` using Hypothesis (cap `max_examples=30` because each call invokes PIL/numpy): for any registered plugin, any `RenderContext` with canvas `(W, H)` from the design's grid plus a small random sample, and any `t` in `[0, total_duration]`, assert `plugin.compose_frame(t, ctx, header, body, line_timings)` returns `numpy.ndarray` of shape `(H, W, 4)` and dtype `uint8`
    - Tag with `# Feature: card-rendering-refactor, Property 3`

  - [x] 5.12 Write property test for in-memory plugin renderer outputs
    - **Property 5: Plugin renderers return in-memory RGBA**
    - **Validates: Requirements 5.1, 5.2**
    - In `tests/render/test_renderer_returns.py` using Hypothesis: for any registered plugin and any valid `RenderContext`, assert `plugin.render_header(ctx)` returns `numpy.ndarray` (not a path), and `plugin.render_body(ctx, line_timings).pages` and `.chunk_images` entries are all `numpy.ndarray` with shape `(_, _, 4)`
    - Tag with `# Feature: card-rendering-refactor, Property 5`

  - [x] 5.13 Write property test for options schema reflection
    - **Property 15: Options schema reflection**
    - **Validates: Requirements 13.3**
    - In `tests/render/test_options_schema.py` using Hypothesis: for any registered `style_id`, assert `plugin_options_schema(style_id)` returns a non-empty `Mapping[str, type]` equal to `get_style(style_id).options_schema`
    - Tag with `# Feature: card-rendering-refactor, Property 15`

- [x] 6. Checkpoint — Phase 3 complete; the four plugins are registered, `render_video` runs them as wrappers around the existing renderers, and the legacy config still works
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Phase 4 — Pipeline switchover, native RGBA, debug-dump
  - [x] 7.1 Implement `AudioAssembler` and its dataclasses
    - In `video_creation/render/audio/assembler.py`, add the frozen `AudioAssets(title_mp3, body_mp3s, word_timestamp_jsons)` and `AudioBundle(track, durations, word_timestamps)` dataclasses
    - Implement `AudioAssembler.assemble(assets, config) -> AudioBundle`: ffmpeg-probe each mp3, scale durations and word timestamps by `audio_speed`, mix optional background music, raise `AudioAssemblyError` on missing/unprobable files (Req 3.7)
    - Move ffmpeg probing to `video_creation/render/audio/probe.py` so it has one home
    - _Requirements: 3.1, 3.7_

  - [x] 7.2 Implement `BackgroundPreparer`
    - In `video_creation/render/background/preparer.py`, lift `prepare_background` into `BackgroundPreparer.prepare(reddit_obj, config) -> VideoFileClip`, keeping the existing FFmpeg scale/crop/hue/eq filters (zoom, hue ±15°, brightness ±8%, contrast ±10%, saturation ±15%)
    - Seed the random tweaks from `extract_id(reddit_obj)` so reruns are deterministic for tests
    - Raise `BackgroundPreparationError` with the decoded `ffmpeg.Error.stderr` on FFmpeg failure
    - _Requirements: 3.2, 3.7_

  - [x] 7.3 Implement `FrameCompositor.build_clip` with mask-from-alpha cache
    - In `video_creation/render/compositor/frame.py`, implement `FrameCompositor(fps=30).build_clip(duration, make_frame)`: cache `(t, frame)` so the alpha-derivation doesn't re-render, build a `VideoClip` for RGB and a second `VideoClip(is_mask=True)` whose frame is `make_frame(t)[:, :, 3] / 255.0`, attach via `clip.with_mask(mask)`
    - This module is the ONLY place `is_mask=True` appears in the codebase (Req 4.3)
    - _Requirements: 4.1, 4.2, 4.3_

  - [x] 7.4 Implement `OutputWriter`
    - In `video_creation/render/output/writer.py`, implement `OutputWriter.write(background, overlay, audio, reddit_obj, config) -> Path`: composite background + overlay + watermark, encode to `results/<subreddit>/<name>.mp4` using `name_normalize` from `output/naming.py`, generate the thumbnail, hand off to `cleanup`, raise `OutputWriteError` on encode failure (delete partial mp4 on failure)
    - _Requirements: 3.5, 3.7, 5.6_

  - [x] 7.5 Implement `PipelineOrchestrator`
    - In `video_creation/render/orchestrator.py`, implement `PipelineOrchestrator.render(reddit_obj, assets) -> Path` following the design's High-Level Flow: AudioAssembler → BackgroundPreparer → TimingEngine → `get_style` → plugin.render_header / render_body / compose_frame → FrameCompositor.build_clip → OutputWriter.write
    - Module MUST NOT import PIL, numpy, MoviePy `VideoClip`, or `ffmpeg` directly — only stage classes (Req 3.6)
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7_

  - [x] 7.6 Rewrite `custom-card` plugin to produce native RGBA `numpy.ndarray`s
    - In `video_creation/render/styles/custom_card.py`, replace the `_CustomCard` wrapper paths with native PIL → `numpy.array` returns, no PNG round-trip
    - Move all layout constants (`CARD_WIDTH_PCT`, `HEADER_Y_START`, `HEADER_Y_END`, `BODY_Y`, `POP_DUR`, `SCROLL_TIME`, `ZOOM_AMOUNT`, `HEADER_DISMISS_DUR`) to class-level on `CustomCardStyle` (Req 11.1, 11.2)
    - Implement `compose_frame` from scratch using `compositor.blend.composite_rgba_onto`, `styles.shared.animation.header_pop_zoom_scale`, and the cached `LineTiming` lookups — replaces the old `if body_style ==` branches
    - _Requirements: 4.1, 5.1, 5.2, 7.1, 11.1, 11.2_

  - [x] 7.7 Rewrite `custom-karaoke` plugin similarly
    - Native RGBA returns from `render_header`/`render_body` (no temp PNGs)
    - Class-level layout constants on `CustomKaraokeStyle`
    - `compose_frame` produces the centered karaoke frame natively, using `LineTiming` to pick the active chunk
    - _Requirements: 4.1, 5.1, 5.2, 7.1, 7.4, 11.1, 11.2_

  - [x] 7.8 Rewrite `reddit-card` plugin similarly
    - Native RGBA returns; class-level layout constants on `RedditCardStyle`; `compose_frame` produces the reddit-header + paginated-body frame natively
    - _Requirements: 4.1, 5.1, 5.2, 7.1, 11.1, 11.2_

  - [x] 7.9 Rewrite `reddit-karaoke` plugin similarly
    - Native RGBA returns; class-level layout constants on `RedditKaraokeStyle`; `compose_frame` honors `dismiss_title_on_body` via `_header_alpha` semantics inlined as a class method
    - _Requirements: 4.1, 5.1, 5.2, 7.1, 7.4, 7.6, 11.1, 11.2_

  - [x] 7.10 Wire the debug-dump path under `assets/temp/<reddit_id>/debug/`
    - In `video_creation/render/api.py` (or `orchestrator.py`), when `config.debug_dump_intermediates` AND not `config.is_production`, save `header.png`, `body_page_<i>.png`, and `chunk_<i>.png` after the plugin renders header/body
    - Default `is_production=True` from `main.py`, `False` from tests and harness
    - When the flag is False or `is_production` is True, NO file is written under `assets/temp/<reddit_id>/debug/`
    - _Requirements: 5.3, 5.4, 5.5_

  - [x] 7.11 Replace `make_final_video` body with a call to `render_video`
    - In `video_creation/final_video.py`, replace the entire body of `make_final_video` with a call to `video_creation.render.api.render_video`, mapping today's `card_style`/`body_style`/etc. to the new `style_id` via `RenderConfig`'s legacy fallback
    - Delete the inlined `make_combined_frame` and `make_combined_mask` functions; the parallel mask path is gone (Req 4.3)
    - _Requirements: 1.3, 3.6, 4.3_

  - [x] 7.12 Write property test for mask-equals-frame-alpha at every timestamp
    - **Property 4: Mask equals frame alpha at every timestamp**
    - **Validates: Requirements 4.2**
    - In `tests/render/test_mask_alpha.py` using Hypothesis (cap iterations at 30): for any `make_frame: float -> ndarray(H, W, 4)` and any `t`, assert `FrameCompositor.build_clip(make_frame).mask.get_frame(t)` equals `make_frame(t)[:, :, 3].astype(float32) / 255.0` element-wise
    - Tag with `# Feature: card-rendering-refactor, Property 4`

  - [x] 7.13 Write property test for non-debug runs writing no intermediates
    - **Property 6: Non-debug runs write no intermediate images**
    - **Validates: Requirements 5.3, 5.5**
    - In `tests/render/test_no_debug_writes.py` using Hypothesis: for any run where `debug_dump_intermediates=False` OR `is_production=True`, assert no file is created under `assets/temp/<reddit_id>/debug/` after `render_video` runs (use a `tmp_path` fixture for `assets/temp`)
    - Tag with `# Feature: card-rendering-refactor, Property 6`

  - [x] 7.14 Write property test for debug-enabled non-production runs
    - **Property 7: Debug-enabled non-production runs write expected intermediates**
    - **Validates: Requirements 5.4**
    - In `tests/render/test_debug_writes.py` using Hypothesis: for any registered plugin and any run where `debug_dump_intermediates=True` AND `is_production=False`, assert that `assets/temp/<reddit_id>/debug/header.png` exists and at least one `body_page_*.png` (paginated styles) or `chunk_*.png` (karaoke styles) exists
    - Tag with `# Feature: card-rendering-refactor, Property 7`

  - [x] 7.15 Write property test for chunk_size coercion
    - **Property 10: Invalid chunk_size is replaced by the documented default**
    - **Validates: Requirements 7.5**
    - In `tests/render/test_chunk_size_coercion.py` using Hypothesis: for any `chunk_size <= 0` in the parsed `[settings.style.<id>]` block of a karaoke-supporting plugin, assert `RenderConfig.style_options["karaoke_words_per_chunk"] == 3` and a `ConfigWarning` is emitted (capture via `pytest.warns(ConfigWarning)`)
    - Tag with `# Feature: card-rendering-refactor, Property 10`

  - [x] 7.16 Write property test for theme-aware header pixels
    - **Property 11: Theme setting changes header pixels for theme-aware plugins**
    - **Validates: Requirements 7.3**
    - In `tests/render/test_theme_pixels.py` using Hypothesis: for any theme-aware plugin and any `RenderContext` differing only in `theme` (`"light"` vs `"dark"`), assert the central card-background pixel of `plugin.render_header(ctx)` differs between the two renders
    - Tag with `# Feature: card-rendering-refactor, Property 11`

  - [x] 7.17 Write property test for header dismiss alpha
    - **Property 12: Header dismiss zeroes header alpha after dismiss_dur**
    - **Validates: Requirements 7.6**
    - In `tests/render/test_header_dismiss.py` using Hypothesis: for any dismiss-supporting plugin, any `RenderContext`, and any `t > title_duration + plugin.HEADER_DISMISS_DUR`, assert the alpha channel in the header's display region of `plugin.compose_frame(t, ...)` is `0` when `dismiss_title_on_body=True` and nonzero in the same region when `False`
    - Tag with `# Feature: card-rendering-refactor, Property 12`

  - [x] 7.18 Write property test for per-style options scoping round-trip
    - **Property 13: Per-style options scoping round-trip**
    - **Validates: Requirements 8.2**
    - In `tests/render/test_options_scoping.py` using Hypothesis: for any registered `style_id` and any `opts` matching its `options_schema`, assert `RenderConfig` built from `[settings] style="<id>"` and `[settings.style.<id>] = opts` produces `RenderConfig.style_options == opts`, regardless of what's under sibling `[settings.style.<other_id>]` blocks
    - Tag with `# Feature: card-rendering-refactor, Property 13`

  - [x] 7.19 Write property test for plugin independence under monkeypatching
    - **Property 14: Plugin independence under monkeypatching**
    - **Validates: Requirements 12.1**
    - In `tests/render/test_plugin_independence.py` using Hypothesis: for any pair of distinct registered plugins `(P_target, P_other)`, assert that monkeypatching `P_target.compose_frame` to return a constant frame does NOT change the byte-output of `render_video(style_id=P_other.style_id, ...)` compared to a baseline run with no monkeypatch (use a fixed seed for `BackgroundPreparer`)
    - Tag with `# Feature: card-rendering-refactor, Property 14`

  - [x] 7.20 Write integration test for orchestrator delegation
    - In `tests/render/test_orchestrator_delegation.py`: for each of audio / background / timing / compositor / output, replace the stage with a spy and assert it receives the right inputs; AST-assert that `orchestrator.py` does not import PIL, numpy, `ffmpeg`, or `moviepy.VideoClip`
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7_

  - [x] 7.21 Write integration test for four-style smoke render
    - In `tests/render/test_styles_smoke.py`: for each of `custom-card`, `custom-karaoke`, `reddit-card`, `reddit-karaoke`, render a 1-second MP4 against `tests/render/fixtures/short_post.json` via `render_video` and assert the file exists and has nonzero size
    - _Requirements: 7.1, 7.2, 13.1_

- [x] 8. Checkpoint — Phase 4 complete; the new pipeline owns frame composition, native RGBA, and debug-dump; all four plugins produce videos through `render_video`
  - Ensure all tests pass, ask the user if questions arise.

- [x] 9. Phase 5 — Remove deprecated code, ship `PreviewHarness`, land static-layout tests
  - [x] 9.1 Delete `utils/card.py`
    - Confirm no remaining production callers (only `final_video.py` at this point) and remove the file
    - _Requirements: 9.1, 9.3_

  - [x] 9.2 Delete `test_transition.py`
    - Remove the standalone preview script; its replacement is `PreviewHarness` (task 9.6)
    - _Requirements: 9.2_

  - [x] 9.3 Delete `video_creation/final_video.py` and update `main.py`
    - Remove `video_creation/final_video.py` (replaced by `render/api.py`)
    - Update `main.py` to import `render_video` directly from `video_creation.render` instead of `make_final_video`
    - _Requirements: 9.3, 13.1_

  - [x] 9.4 Remove the legacy flat-key fallback from `RenderConfig`
    - In `video_creation/render/config.py`, delete the legacy `card_style + body_style → style_id` mapping branch added in task 5.7
    - From this commit forward, `config.toml` MUST use the new `style = "..."` schema; missing `style` raises `ConfigError`
    - _Requirements: 8.1, 8.4_

  - [x] 9.5 Update `config.toml` to the new schema with documentation comments
    - Replace the flat `card_style`, `body_style`, `dismiss_title_on_body`, `karaoke_words_per_chunk`, `theme` keys under `[settings]` with a single `style = "reddit-karaoke"` (or current default)
    - Add `[settings.style.custom-card]`, `[settings.style.custom-karaoke]`, `[settings.style.reddit-card]`, `[settings.style.reddit-karaoke]` blocks with the per-style options described in the design's Configuration Schema
    - Add comments describing each setting (Req 8.5)
    - _Requirements: 8.1, 8.2, 8.5_

  - [x] 9.6 Implement `PreviewHarness` and its fake-timing synthesizer
    - In `video_creation/render/preview/fake_timings.py`, implement `synth_word_timestamps(words, wps) -> tuple[WordTimestamp, ...]`: contiguous timestamps where each `end - start == 1.0 / wps`, total span `len(words) / wps` (Req 10.4)
    - In `video_creation/render/preview/harness.py`, implement the CLI described in the design: `--style`, `--post-fixture`, `--timings {fake|real}`, `--audio-dir`, `--wps`, `--output`; load fixture, build `AudioAssets` (real or synthesized silent track), call public `render_video(...)` (Req 10.1, 10.2)
    - When `--timings=real`, real `WordTimestamp`s flow through the same `TimingEngine` (Req 10.5); when `--timings=fake`, only the input layer differs (Req 10.4)
    - Add `video_creation/render/preview/__main__.py` to make `python -m video_creation.render.preview` work
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5_

  - [x] 9.7 Write property test for fake-timing synthesizer math
    - **Property 16: Fake-timing synthesizer math**
    - **Validates: Requirements 10.4**
    - In `tests/render/test_fake_timing.py` using Hypothesis: for any non-empty list of words and any `wps > 0`, assert `synth_word_timestamps(words, wps)` returns a tuple of length `len(words)`, each consecutive pair satisfies `next.start == prev.end`, each timestamp satisfies `end - start == 1.0 / wps`, and the total span equals `len(words) / wps`
    - Tag with `# Feature: card-rendering-refactor, Property 16`

  - [x] 9.8 Write property test for preview harness dispatch
    - **Property 17: Preview harness dispatches to the requested plugin**
    - **Validates: Requirements 10.3**
    - In `tests/render/test_preview_dispatch.py` using Hypothesis: for any registered `style_id`, invoking `PreviewHarness.run(--style style_id, --post-fixture <fixture>, --timings fake, --output <tmp>)` produces a non-zero MP4 at the requested path, and the plugin returned by `get_style(style_id)` receives at least one `compose_frame` call (verify via spy)
    - Tag with `# Feature: card-rendering-refactor, Property 17`

  - [x] 9.9 Write integration test for preview harness with real timings
    - In `tests/render/test_preview_real_timings.py`: invoke `PreviewHarness.run(--style <id> --timings real --audio-dir <pre-recorded fixture>)` and assert `synth_word_timestamps` was NOT called (verify via spy/mock); the same `TimingEngine` runs against the real word JSONs (Req 10.5)
    - _Requirements: 10.5_

  - [x] 9.10 Write static-layout tests
    - In `tests/render/test_static_layout.py`, AST-assert:
      - `orchestrator.py` does NOT import `PIL`, `numpy`, `ffmpeg`, or `moviepy.VideoClip` (Req 3.6)
      - `timing/` modules do NOT import `PIL`, `numpy`, `moviepy`, or `ffmpeg` (Req 6.2)
      - No `styles/<plugin>.py` imports from another `styles/<plugin>.py` (Req 12.3)
      - No `if style ==` / `if card_style ==` / `if body_style ==` outside `styles/` (Req 1.3)
      - `is_mask=True` appears exactly once in `compositor/frame.py` and nowhere else (Req 4.3)
      - `from utils.card import render_post_card` raises `ImportError` (Req 9.1)
      - `Path("test_transition.py").exists()` is `False` (Req 9.2)
      - Each registered plugin's `cls.__module__` starts with `video_creation.render.styles.` (Req 12.2)
      - `available_styles() == ('custom-card', 'custom-karaoke', 'reddit-card', 'reddit-karaoke')` (Req 7.1, 13.2)
      - No module-level layout constants in `video_creation/render/` are read by more than one plugin module (Req 11.2)
    - _Requirements: 1.3, 3.6, 4.3, 6.2, 7.1, 9.1, 9.2, 11.2, 12.2, 12.3, 13.2_

- [x] 10. Final checkpoint — Phase 5 complete; deprecated code removed, harness shipped, static-layout tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP, but the property tests are the single biggest source of confidence in the registry / timing / frame contracts and should land before the final cleanup phase.
- Each phase's checkpoint is a deliberate stopping point: the build is green and existing functionality still works after every phase.
- Phase 1 → 4 keep `make_final_video` callable so the rest of the codebase (`main.py`) is untouched. Only Phase 5 deletes the shim and forces callers onto `render_video`.
- The legacy `card_style + body_style → style_id` fallback added in task 5.7 is removed in task 9.4 — that's the intentional one-release window for migrating `config.toml`.
- Property tests reference the seventeen Correctness Properties in `design.md`; each property has its own sub-task close to the implementation that introduces the behavior it validates.
- Smoke / static / integration tests cover the SMOKE and INTEGRATION items from the design's prework that don't fit the universal-property mold.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2"] },
    { "id": 1, "tasks": ["1.3"] },
    { "id": 2, "tasks": ["1.4", "3.1"] },
    { "id": 3, "tasks": ["3.2"] },
    { "id": 4, "tasks": ["3.3", "3.4", "3.5", "5.1"] },
    { "id": 5, "tasks": ["5.2"] },
    { "id": 6, "tasks": ["5.3", "5.4", "5.5", "5.6", "5.7"] },
    { "id": 7, "tasks": ["5.8"] },
    { "id": 8, "tasks": ["5.9", "5.10", "5.11", "5.12", "5.13", "7.1", "7.2", "7.3", "7.4"] },
    { "id": 9, "tasks": ["7.5"] },
    { "id": 10, "tasks": ["7.6", "7.7", "7.8", "7.9"] },
    { "id": 11, "tasks": ["7.10", "7.11"] },
    { "id": 12, "tasks": ["7.12", "7.13", "7.14", "7.15", "7.16", "7.17", "7.18", "7.19", "7.20", "7.21"] },
    { "id": 13, "tasks": ["9.1", "9.2"] },
    { "id": 14, "tasks": ["9.3", "9.4", "9.6"] },
    { "id": 15, "tasks": ["9.5", "9.7", "9.8", "9.9", "9.10"] }
  ]
}
```
