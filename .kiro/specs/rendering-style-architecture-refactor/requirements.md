# Requirements Document

## Introduction

The Reddit Video Maker Bot composes each output video from two independent style dimensions: a **title-card style** (currently `custom` or `reddit`) and a **body-text style** (currently `card` paginated mask-reveal, or `karaoke` pop-in centred line). Title-card rendering already follows a clean class hierarchy in `utils/card.py` (`_BaseCard` → `_CustomCard`, `_RedditStyleCard`). Body-text rendering, in contrast, is inlined into two ~200-line per-frame closures inside `video_creation/final_video.py` (`make_combined_frame` and `make_combined_mask`), with `if body_style == "karaoke": ... else: ...` branches duplicated across both closures. Animation constants (pop, scroll, fade, zoom, dismiss, layout) are scattered across module-level globals, function-local literals, and inline magic numbers. Configuration is read ad-hoc inside `make_final_video`, and the preview script `test_transition.py` re-implements much of the same logic.

This refactor reorganises the existing rendering code so that the two style dimensions are equally first-class, independently composable, and trivially extensible. It introduces a single composition pipeline driven by a unified overlay protocol, centralises animation and layout parameters, and extracts timing computation into its own module. No new visual styles are added, and the rendered output for every existing `(card_style, body_style)` combination is preserved.

## Glossary

- **Title_Card_Style**: A class implementing the rendering of the static post header image (avatar, author, title, etc.). Examples: `CustomCard`, `RedditStyleCard`.
- **Body_Style**: A class implementing the time-varying rendering of the post body text during playback. Examples: `CardBody` (paginated mask-reveal), `KaraokeBody` (pop-in centred chunk).
- **Style_Registry**: A lookup table mapping a string identifier (e.g. `"custom"`, `"karaoke"`) to its corresponding `Title_Card_Style` or `Body_Style` class.
- **Overlay**: A timeline element that exposes, for a given time `t`, an RGBA image plus a destination position. The Compositor draws Overlays onto the per-frame canvas.
- **Compositor**: A single component responsible for blending all active Overlays at time `t` into the output frame's RGB channels and alpha mask.
- **Render_Config**: A dataclass that holds every animation, layout, and timing parameter used by the rendering pipeline (durations, easing constants, screen positions, font paths, font sizes, `LINES_PER_PAGE`, `AUDIO_SPEED`, etc.).
- **Timeline_Builder**: The component that converts per-word TTS timestamps and rendered body-page line positions into a list of `LineTiming` records (text, screen position, start, end).
- **LineTiming**: A record `{text, y_top, y_bottom, start, end}` describing when and where a single line or karaoke chunk is shown.
- **Renderer**: The overall video-rendering subsystem (currently `make_final_video` and friends).
- **Final_Video**: The orchestration function that assembles audio, overlays, background, watermark, and writes the output file.
- **Legacy_Shim**: The deprecated `render_post_card` function in `utils/card.py`, currently retained for backward compatibility with any unknown callers.
- **Preview_Script**: `test_transition.py`, a developer-facing sandbox that previews style combinations without running the full pipeline.

## Requirements

### Requirement 1: First-class Title_Card_Style abstraction

**User Story:** As a developer adding a new title-card variant, I want a single base class to subclass and a single place to register it, so that I can add a style without touching unrelated code.

#### Acceptance Criteria

1. THE Renderer SHALL expose a `Title_Card_Style` abstract base class that defines the contract for rendering the post header image.
2. THE Renderer SHALL implement the existing `custom` and `reddit` styles as concrete subclasses of `Title_Card_Style`.
3. THE Renderer SHALL register every concrete `Title_Card_Style` in the `Style_Registry` keyed by a string identifier.
4. WHERE a new `Title_Card_Style` subclass is added and registered, THE Renderer SHALL select that style at runtime via the `card_style` configuration key without requiring changes to `Final_Video`, the Compositor, or the `Body_Style` code.

### Requirement 2: First-class Body_Style abstraction

**User Story:** As a developer adding a new body-text rendering variant, I want body-text styles to be classes with the same shape as title-card styles, so that the two style dimensions are symmetric and easy to extend.

#### Acceptance Criteria

1. THE Renderer SHALL expose a `Body_Style` abstract base class that defines, at minimum, a method to pre-build per-style resources (e.g. line images) and a method to produce the active overlay(s) at time `t`.
2. THE Renderer SHALL implement the existing `card` (paginated mask-reveal) and `karaoke` (pop-in centred chunk) body styles as concrete subclasses of `Body_Style`.
3. THE Renderer SHALL register every concrete `Body_Style` in the `Style_Registry` keyed by a string identifier.
4. WHERE a new `Body_Style` subclass is added and registered, THE Renderer SHALL select that style at runtime via the `body_style` configuration key without requiring changes to `Final_Video`, the Compositor, or the `Title_Card_Style` code.
5. THE Renderer SHALL locate the `karaoke` body-style implementation in the same module (or sibling module under the same package) as the `card` body-style implementation.

### Requirement 3: Single Compositor replacing the duplicated frame/mask closures

**User Story:** As a maintainer, I want one place that knows how to draw Overlays onto a frame and into the alpha mask, so that I never have to keep two near-identical 200-line closures in sync again.

#### Acceptance Criteria

1. THE Compositor SHALL accept a list of Overlay records produced by `Title_Card_Style` and `Body_Style` instances at time `t` and SHALL produce both the RGB frame and the alpha mask for that time.
2. THE Compositor SHALL contain the only alpha-blending and bounds-clipping code in the rendering pipeline.
3. THE Renderer SHALL NOT contain duplicate per-style branching logic in both an RGB-frame builder and an alpha-mask builder.
4. WHEN the Compositor renders frame `t` for a given `(card_style, body_style)` configuration, THE Compositor SHALL produce an RGB frame and an alpha mask whose paired output is byte-for-byte equivalent to the output produced by the pre-refactor `make_combined_frame` and `make_combined_mask` for the same inputs, deterministic seeds, and configuration.

### Requirement 4: Centralised Render_Config

**User Story:** As a maintainer, I want every animation, timing, and layout constant in one named place, so that I can tune the look without grepping the codebase for magic numbers.

#### Acceptance Criteria

1. THE Renderer SHALL define a `Render_Config` dataclass that contains all animation and layout parameters used by the rendering pipeline, including: pop-in duration, header dismiss duration, scroll-reveal duration, line fade-out duration, slow-zoom amount, header Y range, body Y, caption vertical centre, lines-per-page, audio speed multiplier, caption font path, caption font size, caption stroke width and colour.
2. THE Renderer SHALL read every animation, timing, and layout constant from a `Render_Config` instance rather than from per-function or per-module literal values.
3. THE Renderer SHALL NOT redefine `LINES_PER_PAGE` in more than one location.
4. THE Renderer SHALL NOT contain numeric animation literals inside `Final_Video`, the Compositor, `Title_Card_Style` subclasses, or `Body_Style` subclasses except as default values defined on `Render_Config` itself.

### Requirement 5: Timeline_Builder extracted from Final_Video

**User Story:** As a maintainer, I want word-timestamp loading, audio-speed adjustment, and per-line/per-chunk timing assembly to live in their own module, so that `Final_Video` reads as orchestration rather than implementation.

#### Acceptance Criteria

1. THE Timeline_Builder SHALL accept a list of audio file paths, a list of body-page line positions, the configured `body_style`, and the configured `karaoke_words_per_chunk` value, and SHALL return a list of `LineTiming` records.
2. THE Timeline_Builder SHALL apply the `Render_Config.audio_speed` multiplier to all returned timestamps.
3. WHEN a TTS word-timestamp JSON file is missing for a given audio segment, THE Timeline_Builder SHALL fall back to the same behaviour the current code uses (assigning a default duration based on word count).
4. THE Timeline_Builder SHALL live in a separate module from `Final_Video` and from the `Body_Style` subclasses.

### Requirement 6: Style_Registry with explicit style selection

**User Story:** As a developer, I want a single function call to look up a style class by name, so that the selection logic is consistent and unknown style names produce a clear error.

#### Acceptance Criteria

1. THE Style_Registry SHALL expose a function that returns the `Title_Card_Style` class for a given identifier.
2. THE Style_Registry SHALL expose a function that returns the `Body_Style` class for a given identifier.
3. IF the requested style identifier is not registered, THEN THE Style_Registry SHALL raise an exception that names both the unknown identifier and the list of registered identifiers.
4. THE Renderer SHALL use the Style_Registry as the only path from a configuration string to a style class.

### Requirement 7: Final_Video as orchestration only

**User Story:** As a maintainer, I want `make_final_video` to read top-to-bottom as a sequence of named stages, so that I can navigate the pipeline without scrolling through 200-line closures.

#### Acceptance Criteria

1. THE Final_Video SHALL delegate static header rendering to a `Title_Card_Style` instance.
2. THE Final_Video SHALL delegate body-page generation, per-frame Overlay production, and chunk image rendering to a `Body_Style` instance.
3. THE Final_Video SHALL delegate per-line timing computation to the Timeline_Builder.
4. THE Final_Video SHALL delegate per-frame and per-mask compositing to the Compositor.
5. THE Final_Video SHALL NOT contain inline implementations of header pop-in scaling, slow-zoom scaling, header dismiss fade, line mask reveal, karaoke pop-in, or karaoke fade-out.

### Requirement 8: Behavioural preservation across all existing style combinations

**User Story:** As an end user of the bot, I want my videos to look the same after the refactor as before, so that I do not have to re-tune any settings.

#### Acceptance Criteria

1. WHEN `card_style="custom"` and `body_style="card"` are configured, THE Renderer SHALL produce frames whose pixel content matches the pre-refactor output to within 1 LSB per channel for the same inputs and seeds.
2. WHEN `card_style="custom"` and `body_style="karaoke"` are configured, THE Renderer SHALL produce frames whose pixel content matches the pre-refactor output to within 1 LSB per channel for the same inputs and seeds.
3. WHEN `card_style="reddit"` and `body_style="card"` are configured, THE Renderer SHALL produce frames whose pixel content matches the pre-refactor output to within 1 LSB per channel for the same inputs and seeds.
4. WHEN `card_style="reddit"` and `body_style="karaoke"` are configured, THE Renderer SHALL produce frames whose pixel content matches the pre-refactor output to within 1 LSB per channel for the same inputs and seeds.
5. THE Renderer SHALL preserve the existing header-only-while-title and dismiss-on-body behaviour governed by `dismiss_title_on_body`.
6. THE Renderer SHALL preserve the existing chunked karaoke behaviour governed by `karaoke_words_per_chunk`.
7. THE Renderer SHALL preserve the existing random per-video Y jitter applied to `HEADER_Y_START`, `HEADER_Y_END`, and `BODY_Y`.

### Requirement 9: Backward-compatible configuration

**User Story:** As an existing user, I want my current `config.toml` to keep working without edits, so that the refactor is invisible to me.

#### Acceptance Criteria

1. THE Renderer SHALL read the existing `[settings].card_style` key.
2. THE Renderer SHALL read the existing `[settings].body_style` key.
3. THE Renderer SHALL read the existing `[settings].dismiss_title_on_body` key.
4. THE Renderer SHALL read the existing `[settings].karaoke_words_per_chunk` key.
5. THE Renderer SHALL read the existing `[settings].theme` key.
6. WHEN any of `card_style`, `body_style`, `dismiss_title_on_body`, `karaoke_words_per_chunk`, or `theme` is absent from `config.toml`, THE Renderer SHALL apply the same default value the pre-refactor code applied.
7. THE Renderer SHALL NOT introduce new required configuration keys.

### Requirement 10: Configuration validation

**User Story:** As a user editing `config.toml`, I want a clear error when I mistype a style name, so that I do not waste time staring at silently-wrong output.

#### Acceptance Criteria

1. IF `card_style` in configuration does not match any registered `Title_Card_Style` identifier, THEN THE Renderer SHALL raise an exception naming the bad value and listing the registered identifiers.
2. IF `body_style` in configuration does not match any registered `Body_Style` identifier, THEN THE Renderer SHALL raise an exception naming the bad value and listing the registered identifiers.

### Requirement 11: Preview_Script alignment

**User Story:** As a developer iterating on styles, I want the preview script to use the same abstractions as the production pipeline, so that what I see in preview is what I get in the output video.

#### Acceptance Criteria

1. THE Preview_Script SHALL render its preview using the same `Title_Card_Style`, `Body_Style`, Compositor, and `Render_Config` types used by `Final_Video`.
2. THE Preview_Script SHALL NOT contain its own inlined re-implementations of caption rendering, pop-in scaling, mask-reveal logic, or chunk-fade-out logic.
3. THE Preview_Script SHALL retain the ability to swap `card_style`, `body_style`, `dismiss_title_on_body`, and `karaoke_words_per_chunk` via a settings block at the top of the file.

### Requirement 12: Legacy_Shim removed

**User Story:** As a maintainer, I want the deprecated `render_post_card` shim removed so that there is exactly one public entry point for card rendering.

#### Acceptance Criteria

1. THE Renderer SHALL NOT export a `render_post_card` function.
2. THE Renderer SHALL expose `render_card` (or its successor in the new architecture) as the sole public function for card rendering.
3. THE Renderer SHALL contain no in-tree callers of `render_post_card` after the refactor.

### Requirement 13: No regression in rendering performance

**User Story:** As a user rendering long videos, I want the refactored pipeline to render in roughly the same wall-clock time as before, so that I do not pay a performance tax for cleaner code.

#### Acceptance Criteria

1. WHEN the same `(card_style, body_style)` configuration, post text, audio files, and resolution are rendered with the pre-refactor and post-refactor code, THE Renderer SHALL complete the post-refactor render within 110% of the pre-refactor wall-clock time on the same machine.
2. THE Renderer SHALL pre-build per-style static resources (line images, page images, header image) once per render, not per frame.

### Requirement 14: Extension-point documentation

**User Story:** As a developer encountering the codebase for the first time, I want a short module-level docstring in each new module that explains how to add a new style, so that I do not need to reverse-engineer the architecture.

#### Acceptance Criteria

1. THE Renderer SHALL include, in the module that defines the `Title_Card_Style` base class, a docstring listing the registry function and the steps to add a new title-card style.
2. THE Renderer SHALL include, in the module that defines the `Body_Style` base class, a docstring listing the registry function and the steps to add a new body style.
3. THE Renderer SHALL include, in the module that defines `Render_Config`, a docstring describing each parameter and its current default value.
