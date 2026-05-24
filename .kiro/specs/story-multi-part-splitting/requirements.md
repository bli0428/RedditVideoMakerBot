# Requirements Document

## Introduction

Today, `utils/subreddit.py` enforces a firm `storymode_max_length` cutoff (default `1000` chars in `config.toml.sample`): any storymode post longer than that is filtered out at scrape time. This works for subreddits like `r/whowouldwin` where each post is a self-contained prompt and a multi-part video would feel artificial, but it discards good source material on subreddits like `r/relationships`, where stories naturally exceed 1000 characters and a "Part 1 / Part 2" split is normal viewer behavior.

This feature introduces a `Story_Splitter` stage that runs **after translation and before TTS** (between `Translation_Service` and `save_text_to_mp3` in `main.py::main`) and turns a single `Reddit_Content` whose `thread_post` exceeds the configured target length into a `Split_Plan`: an ordered list of `Story_Part` objects, each rendered as its own video by the rest of the pipeline.

Key behaviors driven by user input:

1. **Per-subreddit policy**: each subreddit selects either `cutoff` mode (preserve current "filter long posts" behavior, e.g., `r/whowouldwin`) or `split` mode (produce multi-part videos, e.g., `r/relationships`).
2. **Soft target with tolerance**: the existing `storymode_max_length` becomes the *target* length (`Soft_Max_Length`). A configured tolerance multiplier (e.g., `1.5x`) lets stories up to `Hard_Max_Length` stay as a single part, so a `1100`-char story does not produce an awkward `1000 + 100` split.
3. **Semantic boundaries**: splits land on paragraph breaks first, sentence breaks second; never mid-word.
4. **Minimum part length**: no part may fall below a configured floor; the splitter redistributes content from the previous part rather than emitting a stub tail.
5. **Per-part decoration**: an operator-customizable template (default: append "Follow for part 2!" to non-final parts, prepend "Part N:" to non-first parts) is applied to each `Story_Part` after splitting and before the part is handed to TTS / screenshots / final-video.
6. **Per-part output**: each part renders as a separate video file, with part numbering reflected in titles and filenames.
7. **Pipeline integration**: this slots cleanly between the existing `Translation_Service` step (see `.kiro/specs/claude-translation/`) and the existing `save_text_to_mp3` step, and the Orchestrator (`main.py::main`) iterates the rest of the pipeline once per `Story_Part`.

This spec only addresses storymode posts (`storymode = true`). Comment-rendering mode (`storymode = false`) is out of scope; for that mode, comment-by-comment iteration already provides natural per-segment pacing.

## Glossary

- **Story_Splitter**: The new module that converts a translated `Reddit_Content` into a `Split_Plan`. Single public entry point: `Story_Splitter.split(reddit_content) -> Split_Plan`.
- **Reddit_Content**: The post-translation dictionary produced by `Translation_Service.translate(...)`, with `thread_title`, `thread_post` (a `str`), `thread_id`, `comments`, and other fields defined by the claude-translation spec.
- **Story_Part**: A dictionary describing one part of a multi-part split. Contains at least: `part_number` (1-indexed `int`), `total_parts` (`int`), `part_thread_id` (the `Reddit_Content.thread_id` plus a `-pN` suffix), `part_thread_title` (the decorated title), `part_thread_post` (the decorated body string for this part), `part_raw_post` (the undecorated body string for this part — used for round-trip verification), and the parent `Reddit_Content` keys preserved (`comments`, `is_nsfw`, `author`, etc.).
- **Split_Plan**: An ordered list of one or more `Story_Part` dictionaries. A `Split_Plan` of length 1 represents a no-split (single-part) outcome.
- **Split_Mode**: The per-subreddit policy. Valid values: `cutoff` (preserve the existing filter behavior — long posts are skipped at scrape time, and `Story_Splitter` always returns a single-part `Split_Plan`) and `split` (long posts are split into multiple `Story_Part`s).
- **Soft_Max_Length**: The target maximum character count for a single part. Configured via `[splitting] soft_max_length`. Defaults to the current `[settings] storymode_max_length` value.
- **Single_Part_Tolerance**: A multiplicative factor (`>= 1.0`) applied to `Soft_Max_Length` to compute `Hard_Max_Length`. A story whose length is at most `Hard_Max_Length` stays as a single part, even if it exceeds `Soft_Max_Length`. Configured via `[splitting] single_part_tolerance`. Default: `1.5`.
- **Hard_Max_Length**: `floor(Soft_Max_Length × Single_Part_Tolerance)`. The absolute character ceiling for any single `Story_Part.part_raw_post`. Computed; not configured directly.
- **Min_Part_Length**: The floor below which any `Story_Part.part_raw_post` may not fall, except when the entire story is shorter than `Min_Part_Length` (single-part case). Configured via `[splitting] min_part_length`. Default: `300`.
- **Max_Parts**: The maximum number of `Story_Part`s a `Split_Plan` may contain. Configured via `[splitting] max_parts`. Default: `5`. Posts that would require more than `Max_Parts` parts are skipped (see Requirement 8).
- **Split_Boundary**: A character position in `thread_post` at which a part may end. Valid boundary types, in preference order: (1) paragraph break (`\n\n` or `\r\n\r\n`), (2) sentence terminator (`.`, `!`, `?`) followed by whitespace, (3) line break (`\n`). Splits SHALL NOT land mid-word.
- **Part_Template**: An operator-configurable string template applied to a `Story_Part` to produce its decorated title and decorated body. Configured via `[splitting.templates]`. See Requirement 6.
- **Subreddit_Name**: The lowercased name of the subreddit a post was scraped from, derived from `[reddit.thread] subreddit` (the configured query) with any leading `r/` stripped. For multi-subreddit queries (e.g., `relationships+confessions`), the Subreddit_Name SHALL be resolved from the actual scraped submission when available, falling back to the first configured subreddit otherwise.
- **Orchestrator**: The entry-point function that drives a single video run end-to-end: `main.py::main` (and its `batch.py` counterpart, where applicable). The Orchestrator owns Pipeline_Stage_Order.
- **Pipeline_Stage_Order**: The required execution order of pipeline stages within a single run: `get_subreddit_threads` → `Translation_Service` → `Story_Splitter` → for each `Story_Part`: `posttextparser` (when `storymodemethod = 1`) → `save_text_to_mp3` → `get_screenshots_of_reddit_posts` → `chop_background` → `make_final_video`.
- **Per_Part_Loop**: The Orchestrator-owned iteration that runs the consumer stages (`posttextparser` through `make_final_video`) once for each `Story_Part` in a `Split_Plan`.
- **Decorated_Body**: `Story_Part.part_thread_post`, the body text after `Part_Template` substitution.
- **Raw_Body**: `Story_Part.part_raw_post`, the body text **before** `Part_Template` substitution. Used to verify reconstruction and conservation properties.
- **TTS_Step**: The existing `video_creation/voices.save_text_to_mp3(reddit_obj)` call (which dispatches to ElevenLabs, OpenAI, etc.).

## Requirements

### Requirement 1: Story_Splitter Pipeline Stage

**User Story:** As a maintainer, I want splitting to happen at one explicit point in the pipeline, so that downstream stages always receive a well-formed `Story_Part` and never have to reason about whether the input is a full story or a slice.

#### Acceptance Criteria

1. THE Orchestrator SHALL invoke the Story_Splitter exactly once per video run, after `Translation_Service.translate` has returned and before `save_text_to_mp3`, `get_screenshots_of_reddit_posts`, `chop_background`, or `make_final_video` are called.
2. THE Orchestrator SHALL pass the translated `Reddit_Content` returned by `Translation_Service.translate` to the Story_Splitter as the sole input.
3. THE Story_Splitter SHALL return a `Split_Plan` containing at least one `Story_Part`.
4. THE Orchestrator SHALL execute the Per_Part_Loop once for each `Story_Part` in the `Split_Plan`, in `part_number` order, passing each `Story_Part` to the consumer stages.
5. THE Story_Splitter SHALL NOT call `posttextparser`, `save_text_to_mp3`, `get_screenshots_of_reddit_posts`, `chop_background`, or `make_final_video`.
6. THE Story_Splitter SHALL NOT modify the input `Reddit_Content` dictionary in place.
7. WHEN `storymode` is `false`, THE Story_Splitter SHALL return a single-part `Split_Plan` whose only `Story_Part` carries `part_raw_post` and `part_thread_post` equal to the input `thread_post`, `part_number = 1`, and `total_parts = 1`, and SHALL NOT split.

### Requirement 2: Per-Subreddit Split Mode

**User Story:** As an operator, I want different subreddits to use different long-post policies, so that `r/whowouldwin` keeps its current cutoff behavior while `r/relationships` produces multi-part videos.

#### Acceptance Criteria

1. THE Pipeline SHALL read per-subreddit splitting configuration from a `[splitting.subreddits.<subreddit_name>]` table in `config.toml`. Subreddit-name keys SHALL be matched case-insensitively against the resolved `Subreddit_Name`.
2. WHEN a `[splitting.subreddits.<subreddit_name>]` table is present, the `mode` field of that table SHALL determine the `Split_Mode` for posts from that subreddit.
3. WHEN no `[splitting.subreddits.<subreddit_name>]` table matches the resolved `Subreddit_Name`, THE Story_Splitter SHALL use the value of `[splitting] default_mode` as the `Split_Mode`. Default value of `[splitting] default_mode` is `cutoff`.
4. WHEN `Split_Mode` is `cutoff`, THE Story_Splitter SHALL return a single-part `Split_Plan` whose only `Story_Part` carries `part_raw_post` and `part_thread_post` equal to the input `thread_post`, regardless of `thread_post` length.
5. IF `Split_Mode` is `cutoff` AND `len(thread_post)` exceeds `Hard_Max_Length`, THEN THE Pipeline SHALL skip the post at the scrape-time filter in `utils/subreddit.py::get_subreddit_undone` (preserving the current "post is too long" behavior).
6. WHEN `Split_Mode` is `split`, THE Pipeline SHALL replace the `utils/subreddit.py::get_subreddit_undone` length-cutoff filter with a check against `Max_Parts × Hard_Max_Length` instead of `Hard_Max_Length`, so posts that the Story_Splitter can accommodate within `Max_Parts` parts are not rejected at scrape time.
7. WHEN `Split_Mode` is `split`, THE Pipeline SHALL NOT apply the `Hard_Max_Length` rejection rule from criterion 5; rejection in `split` mode is governed solely by the `Max_Parts × Hard_Max_Length` ceiling defined in criterion 6 and by the per-post `StorySplitError` failure policy in Requirement 8.
8. IF the configured `[splitting] default_mode` is set to a value other than `cutoff` or `split`, THEN THE Pipeline SHALL log an error naming the offending value and listing the supported modes, SHALL set the in-memory effective `default_mode` to `cutoff` for the remainder of the run, and SHALL continue running rather than aborting at startup.

### Requirement 3: Soft and Hard Length Thresholds

**User Story:** As an operator, I want a tolerance band above the soft target so that a story slightly over the limit stays as one video instead of producing a tiny tail part.

#### Acceptance Criteria

1. THE `[splitting]` section SHALL expose `soft_max_length` (`int`, default equal to `[settings] storymode_max_length` at config load time, fallback `1000` when neither is set), `single_part_tolerance` (`float`, `>= 1.0`, default `1.5`), `min_part_length` (`int`, `>= 1`, default `300`), and `max_parts` (`int`, `>= 1`, default `5`).
2. THE Story_Splitter SHALL compute `Hard_Max_Length = floor(soft_max_length × single_part_tolerance)`.
3. WHEN `Split_Mode` is `split` AND `len(thread_post)` is at most `Hard_Max_Length`, THE Story_Splitter SHALL return a single-part `Split_Plan` whose only `Story_Part` carries `part_raw_post` equal to the input `thread_post` byte-for-byte.
4. WHEN `Split_Mode` is `split` AND `len(thread_post)` exceeds `Hard_Max_Length`, THE Story_Splitter SHALL split `thread_post` into a `Split_Plan` of length `N`, where `N` is the smallest integer such that splitting `thread_post` into `N` parts can satisfy Requirements 4, 5, and 7 simultaneously, and `N <= max_parts`.
5. FOR each `Story_Part` in a `Split_Plan` produced when `Split_Mode` is `split`, `len(part_raw_post)` SHALL be at most `Hard_Max_Length`.
6. IF `single_part_tolerance` resolves to a value less than `1.0`, THEN THE Pipeline SHALL log a warning naming the offending value, SHALL clamp the in-memory effective value to `1.0` for the remainder of the run, and SHALL continue running.

### Requirement 4: Semantic Split Boundaries

**User Story:** As a viewer, I want each part to end at a natural breakpoint (paragraph or sentence), so that a story doesn't cut off mid-thought.

#### Acceptance Criteria

1. WHEN the Story_Splitter chooses a split point in `thread_post`, it SHALL prefer a paragraph-break boundary (`\n\n`, `\r\n\r\n`) over any other boundary type, provided such a boundary exists within the search window defined by criterion 4.
2. WHEN no paragraph-break boundary exists within the search window, AND a sentence-terminator boundary (`.`, `!`, or `?` immediately followed by whitespace or end-of-string) exists within the search window, THE Story_Splitter SHALL fall back to a sentence-terminator boundary.
3. WHEN no paragraph-break or sentence-terminator boundary exists within the search window, AND a single line-break boundary (`\n`) exists within the search window, THE Story_Splitter SHALL fall back to a line-break boundary.
4. THE Story_Splitter SHALL search for a Split_Boundary within the character range `[Min_Part_Length, Hard_Max_Length]` measured from the start of the current part, and SHALL select the boundary closest to `Soft_Max_Length` from below, breaking ties by preferring paragraph > sentence > line.
5. THE Story_Splitter SHALL NOT split mid-word: every chosen split point SHALL fall on a whitespace, paragraph-break, or sentence-terminator character as defined above.
6. IF no Split_Boundary of any type exists within `[Min_Part_Length, Hard_Max_Length]` for the current part (for example, a `1500`-character paragraph with no internal punctuation), THEN THE Story_Splitter SHALL fall back to a whitespace boundary (any run of one or more whitespace characters) within the same range, selecting the position closest to `Soft_Max_Length` from below.
7. IF criterion 6 also yields no candidate (for example, a contiguous block of non-whitespace characters longer than `Hard_Max_Length`), THEN THE Story_Splitter SHALL apply the per-subreddit failure policy defined in Requirement 8.

### Requirement 5: Minimum Part Length and Tail Handling

**User Story:** As a viewer, I want every part to feel substantive, so that I don't watch a "Part 2" that's just a 100-character afterthought.

#### Acceptance Criteria

1. FOR every `Story_Part` in a `Split_Plan` of length `N >= 2`, `len(part_raw_post)` SHALL be at least `Min_Part_Length`.
2. WHEN the natural last-part remainder (the text after the final chosen split boundary) would be shorter than `Min_Part_Length`, THE Story_Splitter SHALL move the previous part's split boundary earlier — to the next-earlier valid Split_Boundary in the search window — so that the final part meets the minimum, and SHALL repeat this redistribution as needed until either the final part meets `Min_Part_Length` or no earlier valid boundary exists.
3. IF after redistribution the final part still falls below `Min_Part_Length` AND no earlier valid Split_Boundary remains, THEN THE Story_Splitter SHALL produce a `Split_Plan` of length `N - 1` by appending the would-be final-part text to the previous part's `part_raw_post`, provided the resulting `part_raw_post` does not exceed `Hard_Max_Length`. Otherwise, THE Story_Splitter SHALL apply the per-subreddit failure policy in Requirement 8.
4. THE Min_Part_Length floor SHALL NOT apply when the entire `thread_post` is shorter than `Min_Part_Length` and the resulting `Split_Plan` has length `1`.

### Requirement 6: Per-Part Decoration Templates

**User Story:** As an operator, I want to customize how each part is announced (e.g., "Follow for part 2!" at the end of part 1, "Part 2:" at the start of part 2), so that the videos read naturally as a series.

#### Acceptance Criteria

1. THE `[splitting.templates]` section SHALL expose four string fields with the following defaults:
   - `title_first_part = "{title} (Part {part_number}/{total_parts})"`
   - `title_other_part = "{title} (Part {part_number}/{total_parts})"`
   - `body_prefix_other_part = "Part {part_number}: "`
   - `body_suffix_non_final_part = "\n\nFollow for part {next_part_number}!"`
2. WHERE a `Story_Part` has `part_number == 1`, THE Story_Splitter SHALL set `Story_Part.part_thread_title` to `title_first_part` after substituting `{title}`, `{part_number}`, and `{total_parts}` placeholders.
3. WHERE a `Story_Part` has `part_number > 1`, THE Story_Splitter SHALL set `Story_Part.part_thread_title` to `title_other_part` after substituting `{title}`, `{part_number}`, and `{total_parts}` placeholders.
4. THE Story_Splitter SHALL set `Story_Part.part_thread_post` to `body_prefix + part_raw_post + body_suffix`, where:
   - `body_prefix` is `body_prefix_other_part` (with placeholder substitution) when `part_number > 1`, else the empty string.
   - `body_suffix` is `body_suffix_non_final_part` (with placeholder substitution) when `part_number < total_parts`, else the empty string.
5. THE supported placeholders SHALL be `{title}`, `{part_number}`, `{total_parts}`, `{next_part_number}` (equal to `part_number + 1`), and `{prev_part_number}` (equal to `part_number - 1`).
6. WHEN `total_parts == 1`, THE Story_Splitter SHALL set `Story_Part.part_thread_title` equal to the input `thread_title` byte-for-byte AND `Story_Part.part_thread_post` equal to the input `thread_post` byte-for-byte, with no template substitution applied. The `title_first_part` and `body_*` templates SHALL NOT be invoked in the single-part case.
7. IF a configured template field references an unknown placeholder name (e.g., `{partname}`), THEN THE Story_Splitter SHALL log a warning naming the offending placeholder and the template field, SHALL leave the unknown placeholder unsubstituted in the output of that field (preserving the literal `{partname}` text), SHALL continue to apply substitution to all other template fields independently of the failing field, and SHALL continue.

### Requirement 7: Per-Part Output Artifacts

**User Story:** As an operator, I want each part rendered as its own video file with the part number visible, so that I can upload them as a series without renaming.

#### Acceptance Criteria

1. THE Orchestrator SHALL derive the effective thread identifier passed to the consumer stages (`save_text_to_mp3`, `get_screenshots_of_reddit_posts`, `chop_background`, `make_final_video`) as `Story_Part.part_thread_id`, where `part_thread_id` SHALL be `<original_thread_id>-p<part_number>` for any `Split_Plan` of length `>= 2`, and SHALL equal the original `thread_id` byte-for-byte for any `Split_Plan` of length `1`. (The other orchestrator responsibilities — passing the decorated title and decorated body, and writing per-part artifact directories and "done" records — are covered by criteria 2 through 5 below; criterion 1 covers only the thread-identifier derivation.)
2. THE Orchestrator SHALL pass `Story_Part.part_thread_title` (the decorated title) to the consumer stages as the effective thread title, and `Story_Part.part_thread_post` (the decorated body) as the effective thread post.
3. THE per-part artifact directory under `assets/temp/` SHALL be keyed by `part_thread_id`, so part 1 and part 2 of the same story produce disjoint artifact trees that can be cleaned up independently.
4. THE final video filename for each part SHALL include the `part_thread_id` so it does not overwrite the file produced for any other part of the same story.
5. THE `video_creation/data/videos.json` "done" record SHALL be written once per `Story_Part`, keyed by `part_thread_id`, so re-running the bot resumes from the next undone part rather than restarting from part 1.
6. WHEN the Story_Splitter produces a `Split_Plan` of length `1`, the output filenames, artifact directory, and "done" record SHALL be byte-for-byte identical to those produced by the pre-feature pipeline for an equivalent storymode post (no `-p1` suffix is added in the single-part case).

### Requirement 8: Skip-Post Failure Policy

**User Story:** As an operator, I want the bot to skip posts that can't be split sensibly, so that one pathological post doesn't abort the run.

#### Acceptance Criteria

1. IF `Split_Mode` is `split` AND a valid `Split_Plan` cannot be produced under Requirements 3, 4, and 5 (for example, because the post would require more than `Max_Parts` parts, or no valid Split_Boundary exists within `[Min_Part_Length, Hard_Max_Length]` per Requirement 4.7, or the redistribution in Requirement 5.3 cannot satisfy `Hard_Max_Length`), THEN THE Story_Splitter SHALL raise a `StorySplitError` exception naming the post `thread_id` and the specific failure reason.
2. THE Orchestrator SHALL catch `StorySplitError`, log a warning identifying the post and the reason, mark the post as "done" in `video_creation/data/videos.json` so it is not retried, and SHALL continue with the next iteration of the run loop.
3. THE Story_Splitter SHALL NOT silently truncate or discard text in any failure path described by criterion 1; the only paths that produce a successful `Split_Plan` are those where every Story_Part's `part_raw_post` is preserved verbatim from a contiguous slice of the input `thread_post` (per Requirement 9).

### Requirement 9: Splitter Correctness Properties

**User Story:** As a developer, I want the splitter's behavior pinned down by property tests, so that future changes don't silently regress reconstruction or length invariants.

#### Acceptance Criteria

1. **Reconstruction property**: FOR ALL inputs where `Story_Splitter.split` returns a successful `Split_Plan`, the concatenation `"".join(part.part_raw_post for part in split_plan)` SHALL equal the input `thread_post` after both sides have been normalized by stripping any whitespace introduced solely by the chosen Split_Boundary character (i.e., the splitter's selected boundary whitespace SHALL be the only difference between the joined raw parts and the input).
2. **Character conservation property**: FOR ALL inputs where `Story_Splitter.split` returns a successful `Split_Plan`, `sum(len(part.part_raw_post) for part in split_plan)` SHALL be at least `len(thread_post) - 4 × (len(split_plan) - 1)` and at most `len(thread_post)`. The lower bound accounts for at most four whitespace characters consumed at each split boundary (`\r\n\r\n`).
3. **Hard maximum invariant**: FOR ALL `Story_Part`s produced by a successful `Split_Plan`, `len(part.part_raw_post)` SHALL be at most `Hard_Max_Length`.
4. **Minimum length invariant**: FOR ALL `Story_Part`s in a `Split_Plan` of length `>= 2`, `len(part.part_raw_post)` SHALL be at least `Min_Part_Length`.
5. **Determinism property**: WHEN `Story_Splitter.split` is invoked twice on the same input `Reddit_Content` with the same configuration, the two returned `Split_Plan`s SHALL be equal (same length, same `part_raw_post` and `part_thread_post` for each part, same `part_number` and `total_parts`).
6. **Single-part identity property**: FOR ALL inputs where `len(thread_post) <= Hard_Max_Length` AND `Split_Mode` is `split`, the returned `Split_Plan` SHALL have length `1`, the only `Story_Part`'s `part_raw_post` SHALL equal `thread_post` byte-for-byte, and the only `Story_Part`'s `part_thread_post` and `part_thread_title` SHALL equal the input `thread_post` and `thread_title` byte-for-byte (i.e., no template decoration applies in the single-part case, per Requirement 6.6).
7. **Cutoff-mode identity property**: FOR ALL inputs where `Split_Mode` is `cutoff` AND `len(thread_post) <= Hard_Max_Length`, the returned `Split_Plan` SHALL have length `1` and its only `Story_Part`'s `part_raw_post` SHALL equal `thread_post` byte-for-byte.
8. **No mid-word split property**: FOR ALL `Split_Plan`s of length `>= 2`, the character at position `len(thread_post[: split_offset_i])` immediately preceding each split offset SHALL be a whitespace character, a paragraph-break character, or a sentence-terminator character (`.`, `!`, `?`).
9. **Boundary positioning property**: FOR ALL split offsets `i` in a `Split_Plan` of length `>= 2`, the offset SHALL fall within the search window `[Min_Part_Length, Hard_Max_Length]` measured from the start of the current part, except when Requirement 5.3's redistribution moves the boundary earlier to satisfy the minimum-length floor.
10. **Decoration round-trip property**: FOR ALL `Story_Part`s where the configured `body_prefix_other_part` and `body_suffix_non_final_part` templates are non-empty and contain no overlapping content with the post body, removing the rendered prefix and suffix from `part_thread_post` SHALL produce `part_raw_post` byte-for-byte.

### Requirement 10: Configuration Schema

**User Story:** As an operator, I want all splitter knobs in `config.toml`, so that I can tune behavior without editing code.

#### Acceptance Criteria

1. THE Pipeline SHALL read splitting configuration from a new `[splitting]` section in `config.toml` and `utils/.config.template.toml`, with the following fields and defaults:
   - `default_mode` (`str`, default `"cutoff"`, options `["cutoff", "split"]`).
   - `soft_max_length` (`int`, `>= 1`, default `1000`).
   - `single_part_tolerance` (`float`, `>= 1.0`, default `1.5`).
   - `min_part_length` (`int`, `>= 1`, default `300`).
   - `max_parts` (`int`, `>= 1`, default `5`).
2. THE Pipeline SHALL read per-subreddit overrides from `[splitting.subreddits.<subreddit_name>]` tables, with each table allowed to override any of the fields in criterion 1 (default `mode` field of the table maps to the per-post `Split_Mode`).
3. THE Pipeline SHALL read template configuration from a new `[splitting.templates]` section, with the four fields and defaults defined in Requirement 6.1.
4. THE Pipeline SHALL document every field added by this spec in `utils/.config.template.toml` with explanations and example values.
5. WHEN `[settings] storymode_max_length` is present in `config.toml` AND `[splitting] soft_max_length` is absent, THE Pipeline SHALL use the `storymode_max_length` value as the effective `soft_max_length`. WHEN both are present, `[splitting] soft_max_length` SHALL take precedence. WHEN both are absent, the Pipeline SHALL use the documented default `soft_max_length = 1000`.
6. IF the resolved effective `soft_max_length` value is less than `1`, THEN THE Pipeline SHALL log a warning naming the offending value and source key, SHALL fall back to the documented default `soft_max_length = 1000` for the remainder of the run, and SHALL continue running. (This includes the case `storymode_max_length = 0` or `soft_max_length = 0`.)
7. THE Pipeline SHALL preserve `[settings] storymode_max_length` as a documented setting for backwards compatibility, but its semantics (post-rejection cutoff at scrape time) SHALL apply only when `Split_Mode` is `cutoff`.

### Requirement 11: Backwards Compatibility

**User Story:** As an existing user with no `[splitting]` configuration, I want the bot to behave exactly as it does today, so that upgrading is safe.

#### Acceptance Criteria

1. WHEN `config.toml` contains no `[splitting]` section AND no `[splitting.subreddits.*]` tables AND no `[splitting.templates]` section, THE Pipeline SHALL default `default_mode` to `cutoff`, and `Story_Splitter.split` SHALL always return a single-part `Split_Plan` whose only `Story_Part` carries `part_raw_post` equal to the input `thread_post` byte-for-byte.
2. WHEN `default_mode` is `cutoff` and no per-subreddit override applies, the scrape-time length filter in `utils/subreddit.py::get_subreddit_undone` SHALL behave identically to its pre-feature behavior: posts with `len(submission.selftext) > storymode_max_length` SHALL be rejected.
3. WHEN `default_mode` is `cutoff`, the Per_Part_Loop SHALL execute exactly once (the `Split_Plan` has length 1), and the resulting output filenames, artifact directory, and `videos.json` "done" record SHALL be byte-for-byte identical to those produced by the pre-feature pipeline for an equivalent post.

### Requirement 12: Observability

**User Story:** As an operator, I want to see what the splitter did during a run, so that I can verify the part boundaries are sensible and tune thresholds.

#### Acceptance Criteria

1. THE Story_Splitter SHALL log, at the start of each invocation, the resolved `Split_Mode`, `Soft_Max_Length`, `Hard_Max_Length`, `Min_Part_Length`, `Max_Parts`, and resolved `Subreddit_Name`.
2. THE Story_Splitter SHALL log, after producing the `Split_Plan`, the number of parts produced, the character lengths of each `part_raw_post`, and the boundary-type (paragraph / sentence / line / whitespace) chosen at each split point.
3. WHEN the Story_Splitter raises `StorySplitError`, the log message SHALL include the `thread_id`, the failure reason category, and the input `len(thread_post)`.
4. THE Orchestrator SHALL log, at the start of each iteration of the Per_Part_Loop, the `part_number`, `total_parts`, and `part_thread_id`.

### Requirement 13: Concurrency with `claude-translation`

**User Story:** As a maintainer, I want this spec to land cleanly alongside the in-flight `claude-translation` spec, so that the two do not block or conflict with each other.

#### Acceptance Criteria

1. THE Story_Splitter SHALL accept the post-translation `Reddit_Content` produced by `Translation_Service.translate` and SHALL NOT call `Translation_Service` itself.
2. THE Story_Splitter SHALL NOT modify any file in the claude-translation spec's scope: `utils/translation/*`, `reddit/subreddit.py` (beyond the per-subreddit cutoff logic in `utils/subreddit.py::get_subreddit_undone` covered by Requirement 2.6), or `main.py` translation invocation.
3. THE Orchestrator's call sequence in `main.py::main` SHALL continue to invoke `Translation_Service.translate` exactly once per run, immediately followed by `Story_Splitter.split`, and only the consumer stages (`posttextparser`, `save_text_to_mp3`, `get_screenshots_of_reddit_posts`, `chop_background`, `make_final_video`) SHALL execute inside the Per_Part_Loop.
4. THE Story_Splitter SHALL be insensitive to whether translation actually ran: if `Translation_Service.translate` returned the input unchanged (e.g., `provider = "none"` or source-equals-target detection), the Story_Splitter SHALL behave as if it received the untranslated content directly.

## Open Questions

1. **Subreddit name resolution for multi-subreddit queries.** When `[reddit.thread] subreddit = "relationships+confessions"`, the `Subreddit_Name` used to look up `[splitting.subreddits.<name>]` should ideally come from the actual scraped submission. The current `_RedditPost` lightweight model in `reddit/subreddit.py` does not expose `submission.subreddit`. A design-phase decision is needed: either (a) extend `_RedditPost` to carry the subreddit name, or (b) match on every configured subreddit and require exact agreement, falling back to `default_mode` when ambiguous. This requirement is captured in the Glossary entry for `Subreddit_Name` but the implementation choice is deferred to design.
2. **Interaction with `storymodemethod = 1` sentence segmentation.** The Per_Part_Loop currently runs `posttextparser` once per `Story_Part`. Sentence segmentation crosses paragraph boundaries cleanly, but a sentence that spans a part boundary is now segmented into two truncated halves. The splitter's preference for paragraph and sentence boundaries (Requirement 4) makes this rare, but design should confirm whether to (a) run `posttextparser` over the full `thread_post` first, then split on sentence-list indices, or (b) keep the current "split raw text, then segment per part" order. This spec assumes (b) but does not mandate it.
3. **NSFW / blocked-words re-checks per part.** The scrape-time blocked-words filter checks the full `thread_post`. After splitting, an individual part might contain or omit the offending phrase, but the post as a whole was already accepted. Design should confirm that no per-part re-filtering is required.
