# Requirements Document

## Introduction

The Reddit video pipeline currently renders each post in one of four visual treatments: two header card styles (`custom`, `reddit`) crossed with two body presentation styles (`card`, `karaoke`). These styles were added incrementally, and as a result they are bolted on across two large modules:

- `utils/card.py` (~690 lines) defines the header/body still-image rendering using an ABC + factory.
- `video_creation/final_video.py` (~864 lines) contains a single `make_final_video` function (>500 lines) that assembles audio, prepares the background, computes word→line timings, and runs per-frame composition with `if body_style == "karaoke" else …` branches duplicated inside both `make_combined_frame` and `make_combined_mask`.
- `test_transition.py` is a standalone preview script that re-implements much of the same composition logic, indicating the rendering pipeline is not reusable.

Adding a new visual treatment today requires editing both `card.py` (header/body image generation) and `final_video.py` (per-frame composition + timing), with no single object that owns "a style." This refactor consolidates the visual treatments behind a unified style abstraction, decomposes `make_final_video` into focused modules, eliminates the duplicated frame/mask logic, removes the deprecated `render_post_card` shim and the stale `test_transition.py` harness, and switches the internal image pipeline to pass images in-memory rather than via temporary PNG files. The four current visual treatments must continue to be reproducible after the refactor, but the configuration schema and visual output may evolve as a natural consequence of the cleaner architecture.

## Glossary

- **Render_Pipeline**: The end-to-end system that turns a Reddit post + audio assets into a final MP4 video.
- **Pipeline_Orchestrator**: The top-level coordinator that replaces today's monolithic `make_final_video` and delegates each stage to a focused module.
- **Card_Style_Plugin**: A single class that owns one complete visual treatment, including header rendering, body rendering, and per-frame composition for that treatment.
- **Style_Registry**: The lookup that maps a style identifier (string) to its `Card_Style_Plugin` class.
- **Card_Renderer**: The part of a `Card_Style_Plugin` that produces the static post header image (handle, title, avatar, counts).
- **Body_Renderer**: The part of a `Card_Style_Plugin` that produces the body presentation (e.g., a paginated card body image, a stream of karaoke caption images).
- **Frame_Compositor**: The per-frame function inside a `Card_Style_Plugin` that returns an RGBA frame layer for a given time `t`; the alpha mask used by MoviePy is derived from the alpha channel of this layer.
- **Timing_Engine**: The module that maps word-level TTS timestamps to per-line and per-chunk start/end times, independent of any image library.
- **Audio_Assembler**: The module that builds the combined audio track (TTS + background music + sound effects).
- **Background_Preparer**: The module that runs FFmpeg preprocessing on the background video (scale, crop, hue, brightness, contrast, saturation).
- **Output_Writer**: The module that handles final encoding, file naming, thumbnail generation, and cleanup.
- **Theme**: A named palette (e.g., `light`, `dark`) consumed by a `Card_Style_Plugin`.
- **Preview_Harness**: A standalone CLI/script that exercises the public `Render_Pipeline` API to produce a preview video without running a full TTS pass; replaces the current `test_transition.py`.
- **Style_Identifier**: The string key (e.g., `custom-card`, `reddit-karaoke`) selecting one `Card_Style_Plugin`.
- **Visual_Treatment**: A pair (header style, body style) that today is selected by two independent config keys (`card_style`, `body_style`); after this refactor it is selected by a single `Style_Identifier`.

## Requirements

### Requirement 1: Unified Style Abstraction

**User Story:** As a developer adding a new visual treatment, I want one class to implement, so that I don't have to thread changes across `card.py`, `final_video.py`, and a preview script.

#### Acceptance Criteria

1. THE Render_Pipeline SHALL define a `Card_Style_Plugin` interface that exposes header rendering, body rendering, and per-frame composition as a single contract.
2. WHEN a developer adds a new `Card_Style_Plugin` subclass and registers it with the `Style_Registry`, THE Render_Pipeline SHALL be able to render videos using that style without modifying any other module.
3. THE Render_Pipeline SHALL select the active `Card_Style_Plugin` exclusively through the `Style_Registry`, with no `if style == "..."` branches outside `Card_Style_Plugin` implementations.
4. THE Card_Style_Plugin interface SHALL be the only place where header rendering, body rendering, and per-frame composition for a given style are co-located.

### Requirement 2: Style Registry and Identifier

**User Story:** As a developer, I want styles to be discoverable through a single registry, so that I can list and select styles without grepping for string literals.

#### Acceptance Criteria

1. THE Style_Registry SHALL expose a function that returns the list of registered Style_Identifiers.
2. WHEN given a registered Style_Identifier, THE Style_Registry SHALL return the corresponding `Card_Style_Plugin` class or instance.
3. IF the Style_Registry is queried with an unregistered Style_Identifier, THEN THE Style_Registry SHALL raise an error that names the unknown identifier and lists the registered identifiers.
4. WHERE a new `Card_Style_Plugin` is added to the codebase, THE Style_Registry SHALL register that plugin through a single declarative call (e.g., a decorator or a single `register(...)` line).

### Requirement 3: Pipeline Decomposition

**User Story:** As a developer maintaining the video pipeline, I want each stage in its own focused module, so that I can change one concern without reading 500+ lines of unrelated logic.

#### Acceptance Criteria

1. THE Pipeline_Orchestrator SHALL delegate audio assembly to the Audio_Assembler module.
2. THE Pipeline_Orchestrator SHALL delegate background preparation to the Background_Preparer module.
3. THE Pipeline_Orchestrator SHALL delegate word→line/chunk timing computation to the Timing_Engine module.
4. THE Pipeline_Orchestrator SHALL delegate per-frame composition to the active `Card_Style_Plugin`.
5. THE Pipeline_Orchestrator SHALL delegate final encoding, thumbnail generation, file naming, and cleanup to the Output_Writer module.
6. THE Pipeline_Orchestrator SHALL contain only stage coordination logic, with no inline image manipulation, audio probing, FFmpeg invocations, or per-frame numpy operations.
7. THE Pipeline_Orchestrator SHALL delegate input validation (e.g., audio file probing, asset existence checks) to the owning module and SHALL receive validated outputs or structured errors back from that module.

### Requirement 4: Single-Source Frame Composition

**User Story:** As a developer, I want frame and mask composition to live in one place, so that logic changes can't drift between the RGB and alpha paths.

#### Acceptance Criteria

1. THE Frame_Compositor SHALL produce a single RGBA frame per timestamp.
2. THE Render_Pipeline SHALL derive any per-frame alpha mask required by MoviePy from the alpha channel of the RGBA frame produced by the Frame_Compositor.
3. THE Render_Pipeline SHALL NOT contain duplicate composition logic that returns RGB and mask separately with parallel branching.

### Requirement 5: In-Memory Image Pipeline

**User Story:** As a developer, I want intermediate card images to be passed in memory, so that the pipeline avoids unnecessary disk I/O and the module boundary is cleaner.

#### Acceptance Criteria

1. THE Card_Renderer SHALL return header images as in-memory image objects (e.g., `numpy.ndarray` or `PIL.Image.Image`) rather than file paths.
2. THE Body_Renderer SHALL return body content as in-memory image objects rather than file paths.
3. THE Render_Pipeline SHALL NOT write header or body intermediate PNGs to disk during a normal production run.
4. WHERE a debug-dump option is enabled AND the run is a non-production debug run, THE Render_Pipeline SHALL write header and body intermediate images to a designated debug directory.
5. WHILE the run is a production run, THE Render_Pipeline SHALL NOT write debug intermediate images to disk regardless of the debug-dump option.
6. THE Render_Pipeline SHALL continue to write final outputs (final video file, thumbnail PNG) to disk.

### Requirement 6: Decouple Timing from Rendering

**User Story:** As a developer changing how text is paced, I want timing logic separated from image rendering, so that I can adjust pacing without touching PIL or numpy code.

#### Acceptance Criteria

1. THE Timing_Engine SHALL accept word-level timestamps, audio-speed scaling, line definitions, and chunking configuration as inputs and SHALL return per-line and per-chunk timing entries (text, start, end, line index) as outputs.
2. THE Timing_Engine SHALL NOT import PIL, numpy, MoviePy, or FFmpeg.
3. WHEN a `Card_Style_Plugin` needs to know which line or chunk is active at time `t`, THE Card_Style_Plugin SHALL consult Timing_Engine output rather than recomputing word offsets.

### Requirement 7: Visual-Treatment Coverage Preservation

**User Story:** As a user of the bot, I want all four current visual treatments to keep working after the refactor, so that videos continue rendering with the styles I've configured.

#### Acceptance Criteria

1. THE Style_Registry SHALL include `Card_Style_Plugin` implementations covering each of today's four visual treatments: custom-header + card-body, custom-header + karaoke-body, reddit-header + card-body, reddit-header + karaoke-body.
2. THE Render_Pipeline SHALL produce a successful MP4 output for each of the four registered visual treatments using a representative input post.
3. THE Render_Pipeline SHALL honor the `theme` setting (light/dark) for any `Card_Style_Plugin` that supports themes.
4. WHEN the karaoke chunk size is configured to a positive integer, THE Render_Pipeline SHALL split each line into chunks of that size for any karaoke-based `Card_Style_Plugin`.
5. IF the karaoke chunk size is configured to zero or a negative integer, THEN THE Render_Pipeline SHALL reject the value and substitute a documented default positive chunk size.
6. WHERE a `Card_Style_Plugin` supports dismissing the header when the body begins, THE Render_Pipeline SHALL apply that behavior when configured to do so.

### Requirement 8: Configuration Schema

**User Story:** As a user configuring the bot, I want a single, coherent way to choose a visual treatment, so that I don't have to set two related keys that combine multiplicatively.

#### Acceptance Criteria

1. THE Render_Pipeline SHALL select a visual treatment through a single Style_Identifier in the configuration file.
2. THE Render_Pipeline SHALL expose per-style options (theme, dismiss-title-on-body, karaoke chunk size) as fields scoped to the active style configuration rather than as flat top-level keys.
3. WHEN the configuration file uses a recognized Style_Identifier, THE Render_Pipeline SHALL select the matching `Card_Style_Plugin`.
4. IF the configuration file uses an unrecognized Style_Identifier, THEN THE Render_Pipeline SHALL fail with an error message that names the offending identifier and lists the available Style_Identifiers.
5. THE Render_Pipeline SHALL document the new configuration schema in `config.toml` with comments describing each setting.

### Requirement 9: Removal of Deprecated Code

**User Story:** As a maintainer, I want the deprecated card shim and the stale preview script removed, so that the codebase has one way to do each thing.

#### Acceptance Criteria

1. THE Render_Pipeline SHALL NOT export the `render_post_card` function from `utils/card.py`.
2. THE repository SHALL NOT contain the `test_transition.py` script in its current form.
3. THE Render_Pipeline SHALL provide a single public entry point for rendering a card image, exposed through the `Card_Style_Plugin` interface.

### Requirement 10: Replacement Preview Harness

**User Story:** As a developer iterating on a style, I want a fast preview tool, so that I can see how a style looks without running a full TTS pass.

#### Acceptance Criteria

1. THE Preview_Harness SHALL render a preview MP4 using only the public `Render_Pipeline` API.
2. THE Preview_Harness SHALL NOT re-implement frame composition, header rendering, body rendering, or timing logic that exists in the `Render_Pipeline`.
3. THE Preview_Harness SHALL accept a Style_Identifier as input and SHALL produce a preview video using the corresponding `Card_Style_Plugin`.
4. WHERE real TTS audio and word timestamps are unavailable, THE Preview_Harness SHALL synthesize fake word timings at a fixed words-per-second rate and pass them through the same Timing_Engine used by the Render_Pipeline.
5. WHERE real TTS audio and word timestamps are available, THE Preview_Harness SHALL pass those real timestamps directly to the Timing_Engine without invoking the fake-timing synthesizer.

### Requirement 11: Layout Constant Encapsulation

**User Story:** As a developer tweaking a style's appearance, I want layout constants owned by the style, so that one style's tweak can't accidentally change another style.

#### Acceptance Criteria

1. THE Card_Style_Plugin SHALL own all layout constants used by its rendering (e.g., display width percentage, header Y position, body Y position, pop duration, scroll time, fade-out time, header dismiss duration, zoom amount).
2. THE Render_Pipeline SHALL NOT define module-level layout constants that are read by more than one `Card_Style_Plugin`.
3. WHERE a constant is shared by multiple styles by design (e.g., output resolution), THE Render_Pipeline SHALL source that constant from the configuration file rather than from a module-level literal.

### Requirement 12: Style Implementation Independence

**User Story:** As a developer working on one style, I want changes to that style isolated, so that I can't accidentally break another style.

#### Acceptance Criteria

1. WHEN a `Card_Style_Plugin` is modified in isolation (no changes to shared modules), THE Render_Pipeline SHALL continue to render every other registered visual treatment without modification to any other file.
4. IF a change to one `Card_Style_Plugin` modifies a shared helper module that other plugins depend on, THEN THE Render_Pipeline MAY require coordinated updates to the affected plugins, and THE shared helper module SHALL document its dependents so the coordination scope is discoverable.
2. THE Render_Pipeline SHALL place each `Card_Style_Plugin` implementation in its own module under a styles package.
3. THE Render_Pipeline SHALL allow `Card_Style_Plugin` implementations to share helper utilities through an explicit shared module rather than through cross-style imports.

### Requirement 13: Public API Surface

**User Story:** As a caller integrating the pipeline (e.g., the preview harness or a future CLI), I want a small, documented public API, so that I don't have to reach into private internals.

#### Acceptance Criteria

1. THE Render_Pipeline SHALL expose a documented public function that accepts a Style_Identifier, a post payload, and audio assets, and SHALL return a path to the rendered MP4.
2. THE Render_Pipeline SHALL expose a documented public function that returns the list of available Style_Identifiers.
3. THE Render_Pipeline SHALL document, for each `Card_Style_Plugin`, which configuration options it accepts.
