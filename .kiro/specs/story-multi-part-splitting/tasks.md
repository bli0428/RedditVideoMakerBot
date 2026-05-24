# Implementation Plan: Story Multi-Part Splitting

## Overview

This plan delivers the `Story_Splitter` pipeline stage that turns a translated `Reddit_Content` whose `thread_post` exceeds the configured ceiling into a `Split_Plan` of one or more `Story_Part` dictionaries, then iterates the consumer stages once per part. The work proceeds bottom-up: pure modules (errors, types) first; configuration resolver and the boundary/template helpers next; the splitter algorithm with its full property-test suite; then ingestion (`subreddit_name` plumbing), scrape-time filter changes, and finally orchestrator wiring in `main.py` and `batch.py`. Static AST checks and integration smokes guard the scope-isolation contract with `claude-translation` and the byte-for-byte backwards-compat guarantee.

Property-based tests (Hypothesis, ≥100 examples each) are written alongside the modules they cover. Each property test references its design property number and the requirement clause(s) it validates, per Requirement 9 and the design's "Correctness Properties" section.

## Tasks

- [x] 1. Set up foundational types and errors for the splitter package
  - [x] 1.1 Create `utils/story_splitter/errors.py` defining `StorySplitError`
    - Implement the exception class per the design's "StorySplitError" data model: `__init__(*, thread_id, reason, detail)`, expose `thread_id`, `reason`, `detail`, format the message as `f"{reason}: {detail}"`.
    - Constrain `reason` documentation to the closed set `{"no_valid_boundary", "too_many_parts", "tail_redistribution_failed"}`.
    - _Requirements: 8.1, 8.3_
  
  - [x] 1.2 Create `utils/story_splitter/types.py` with `Story_Part`, `Split_Plan`, `SplittingConfig`, `TemplateConfig`
    - Define `Story_Part` as a `TypedDict(total=False)` with the splitter-specific fields (`part_number`, `total_parts`, `part_thread_id`, `part_raw_post`, `part_thread_title`, `part_thread_post`) plus the substituted Reddit_Content keys (`thread_id`, `thread_title`, `thread_post`).
    - Define `Split_Plan = list[Story_Part]`.
    - Define `TemplateConfig` and `SplittingConfig` as `@dataclass(frozen=True)` with the fields and types in the design's "Components and Interfaces" section, including the `hard_max_length` property `int(soft_max_length * single_part_tolerance)`.
    - _Requirements: 1.3, 3.2, 6.1, 10.1, 10.3_
  
  - [x] 1.3 Add shared Hypothesis strategies in `tests/_strategies.py`
    - Implement `multi_paragraph_text(min_size, max_size)` mixing `\n\n`, sentence terminators (`. `, `! `, `? `), and `\n`.
    - Implement `pathological_text(length)` (length non-whitespace characters with no punctuation).
    - Implement `splitting_config()` covering valid ranges (`soft_max_length` in `[100, 5000]`, `single_part_tolerance` in `[1.0, 3.0]`, `min_part_length` in `[1, soft_max_length // 2]`, `max_parts` in `[1, 10]`) and `degenerate_config()` for clamp-path coverage.
    - Implement `template_string()` mixing known and unknown placeholder names.
    - Implement `reddit_content()` producing dicts with `thread_id`, `thread_title`, `thread_post`, `comments`, `is_nsfw`, `author`, `subreddit_name`.
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.8, 9.9, 9.10_

- [ ] 2. Add splitter configuration schema and resolver
  - [x] 2.1 Add `[splitting]`, `[splitting.templates]`, and example `[splitting.subreddits.<name>]` sections to `config.toml.sample`
    - Add `default_mode = "cutoff"`, `soft_max_length = 1000`, `single_part_tolerance = 1.5`, `min_part_length = 300`, `max_parts = 5` under `[splitting]`.
    - Add the four template defaults under `[splitting.templates]` per Requirement 6.1.
    - Add commented examples for `[splitting.subreddits.relationships]` (`mode = "split"`) and `[splitting.subreddits.whowouldwin]` (`mode = "cutoff"`).
    - Leave `[settings] storymode_max_length` in place untouched for backwards compatibility.
    - _Requirements: 10.1, 10.3, 10.7, 11.1_
  
  - [x] 2.2 Document every new field in `utils/.config.template.toml`
    - Add `[splitting]`, `[splitting.templates]`, and `[splitting.subreddits.<name>]` table schemas with `optional`, `default`, `explanation`, and `example` keys per the project's existing template conventions.
    - Cover all five `[splitting]` fields, the four template fields, and the per-subreddit override structure.
    - _Requirements: 10.1, 10.2, 10.3, 10.4_
  
  - [x] 2.3 Implement `utils/story_splitter/config.py` with `SplittingConfig.from_settings`
    - Read top-level `[splitting]` defaults; fall back to `[settings] storymode_max_length` when `[splitting] soft_max_length` is absent (Req 10.5).
    - Apply per-subreddit overrides from `[splitting.subreddits.<lower(subreddit_name)>]`, mapping the table's `mode` field to the per-post `Split_Mode` (Req 2.1, 2.2, 2.3).
    - Read `[splitting.templates]` with the Requirement 6.1 defaults.
    - Validate and degrade-on-error: invalid `default_mode` → log error and fall back to `"cutoff"` (Req 2.8); `single_part_tolerance < 1.0` → warn and clamp to `1.0` (Req 3.6); resolved `soft_max_length < 1` → warn and fall back to `1000` (Req 10.6); `min_part_length < 1` and `max_parts < 1` → warn and clamp to `1`.
    - Never raise; follow the `utils/translation/config.py` "log + degrade + continue" pattern.
    - _Requirements: 2.1, 2.2, 2.3, 2.8, 3.1, 3.2, 3.6, 10.1, 10.2, 10.3, 10.5, 10.6_
  
  - [x] 2.4 Write property test for `Hard_Max_Length` arithmetic
    - **Property 11: Hard_Max_Length arithmetic**
    - Test in `tests/test_splitting_config_properties.py`. For all `(soft_max_length, single_part_tolerance)` from `splitting_config()`, assert `SplittingConfig.hard_max_length == math.floor(soft_max_length * single_part_tolerance)`.
    - **Validates: Requirements 3.2**
  
  - [ ] 2.5 Write property test for the config resolver
    - **Property 14: Config resolver — per-subreddit override and fallback**
    - Test in `tests/test_splitting_config_properties.py`. Drive `SplittingConfig.from_settings` with synthesized `(default_mode, override_table_keys, override_mode_value, soft_max_length_present, storymode_max_length_present, single_part_tolerance_value)` tuples and assert: per-subreddit `mode` wins when valid; invalid `default_mode` falls back to `"cutoff"` with a warning; `soft_max_length` resolution order `[splitting]` → `[settings].storymode_max_length` → `1000`; `< 1` falls back to `1000`; `single_part_tolerance < 1.0` clamps to `1.0`.
    - **Validates: Requirements 2.1, 2.2, 2.3, 2.8, 3.6, 10.5, 10.6**

- [x] 3. Implement boundary search
  - [x] 3.1 Implement `utils/story_splitter/boundaries.py`
    - Implement `_find_paragraph_break`, `_find_sentence_terminator`, `_find_line_break`, `_find_whitespace` per the design's "Step 3: Boundary search" section. Each returns the highest valid offset in `[start, min(stop, target+1))`, falling back to the lowest valid offset in `[target+1, stop)`.
    - Implement `_find_boundary(text, start, stop, target) -> tuple[int|None, str|None]` trying paragraph → sentence → line → whitespace in priority order.
    - Implement `_advance_past_whitespace(post, boundary_offset, boundary_type)` returning the offset of the next non-whitespace character, used to consume boundary whitespace between parts.
    - Boundary detection rules: paragraph = `\n\n` or `\r\n\r\n` (boundary at first `\n`); sentence = regex `[.!?](?=\s|$)` (boundary immediately after terminator); line = single `\n` not part of a paragraph break; whitespace = any whitespace position.
    - The module is pure: no I/O, no settings access.
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7_
  
  - [x] 3.2 Write boundary search example unit tests
    - Test in `tests/test_story_splitter_examples.py`. Cover each boundary type independently: paragraph > sentence > line > whitespace priority, "closest from below" preference, fallback to above-target when nothing fits below, and the `min_part_length > hard_max_length` empty-window case.
    - Cover `_advance_past_whitespace` on each boundary type (paragraph, sentence, line, whitespace).
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6_

- [ ] 4. Implement template substitution
  - [x] 4.1 Implement `utils/story_splitter/templates.py`
    - Implement `_substitute(template, *, title, part_number, total_parts)` using `re.sub(r"\{(\w+)\}", repl, template)`. Known placeholders: `title`, `part_number`, `total_parts`, `next_part_number = part_number + 1`, `prev_part_number = part_number - 1`. Unknown placeholders are left literal and a warning is emitted naming the placeholder and the template field (Req 6.7).
    - Implement `_decorate_title(reddit_content, part_number, total_parts, config)` selecting `title_first_part` for `part_number == 1` and `title_other_part` otherwise.
    - Implement `_decorate_body(raw_post, part_number, total_parts, config)` returning `body_prefix + raw_post + body_suffix` where `body_prefix = body_prefix_other_part` for `part_number > 1` (else `""`) and `body_suffix = body_suffix_non_final_part` for `part_number < total_parts` (else `""`).
    - For `total_parts == 1`, callers SHALL NOT invoke template substitution (the splitter short-circuits in this case per Req 6.6).
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.7_
  
  - [x] 4.2 Write property test for title decoration template selection
    - **Property 15: Title decoration template selection**
    - Test in `tests/test_templates_properties.py`. For all multi-part `Story_Part`s (`total_parts >= 2`), assert `part_thread_title` equals the substitution of `title_first_part` when `part_number == 1` and `title_other_part` otherwise, with all five placeholders correctly substituted.
    - **Validates: Requirements 6.2, 6.3, 6.5**
  
  - [ ] 4.3 Write property test for body decoration formula
    - **Property 16: Body decoration prefix+raw+suffix formula**
    - Test in `tests/test_templates_properties.py`. For all multi-part `Story_Part`s, assert `part_thread_post == body_prefix + part_raw_post + body_suffix`, with `body_prefix` empty for `part_number == 1` and `body_suffix` empty for the final part.
    - **Validates: Requirements 6.4**
  
  - [ ] 4.4 Write property test for unknown placeholder passthrough
    - **Property 17: Unknown placeholder passthrough**
    - Test in `tests/test_templates_properties.py`. For all template strings containing one or more placeholders outside the known set, assert each unknown placeholder appears verbatim (with surrounding `{` and `}`) in the substituted output, a warning is emitted naming each unknown placeholder and the template field, and known placeholders in the same template are still substituted.
    - **Validates: Requirements 6.7**
  
  - [ ] 4.5 Write property test for decoration round-trip
    - **Property 9: Decoration round-trip**
    - Test in `tests/test_templates_properties.py`. For all `Story_Part`s where `body_prefix_other_part` and `body_suffix_non_final_part` are non-empty and contain no overlapping content with `part_raw_post`, assert that stripping the rendered prefix (when `part_number > 1`) and rendered suffix (when `part_number < total_parts`) from `part_thread_post` yields `part_raw_post` byte-for-byte.
    - **Validates: Requirements 9.10, 6.4**

- [ ] 5. Implement Story_Splitter core algorithm
  - [x] 5.1 Implement `utils/story_splitter/splitter.py`
    - Implement `Story_Splitter.__init__(self, config: SplittingConfig)` and `Story_Splitter.split(self, reddit_content: dict) -> Split_Plan`.
    - Step 1 (single-part short-circuits): when `storymode is False` (Req 1.7), `mode == "cutoff"` (Req 2.4), or `len(thread_post) <= hard_max_length` (Req 3.3, 9.6) → return `[_single_part(reddit_content)]`. `_single_part` builds a `Story_Part` with `part_number=1`, `total_parts=1`, `part_raw_post = thread_post`, `part_thread_post = thread_post`, `part_thread_title = thread_title`, `part_thread_id = thread_id` (no `-pN` suffix; Req 6.6, 7.6, 9.6).
    - Step 2 (`_split_iterative`): greedy split using `_find_boundary` from `boundaries.py`, advancing past boundary whitespace between parts, raising `StorySplitError(reason="no_valid_boundary")` when no boundary exists in the search window and `StorySplitError(reason="too_many_parts")` when the result exceeds `max_parts`.
    - Step 3 (`_redistribute_tail`): when the natural tail is below `min_part_length`, walk the previous boundary earlier through the search window using `_find_boundary_below` (Req 5.2). When no earlier boundary remains, attempt to merge the tail into the previous part (Req 5.3); raise `StorySplitError(reason="tail_redistribution_failed")` when the merge would exceed `hard_max_length`.
    - Step 4 (`_materialize`): build the per-part `Story_Part` dicts copying parent keys, deriving `part_thread_id = thread_id` for `total_parts == 1` and `f"{thread_id}-p{part_number}"` otherwise, calling `templates.py` to compute `part_thread_title` / `part_thread_post`, and mirroring the decorated values onto `thread_id` / `thread_title` / `thread_post` so consumer stages keep reading those keys unchanged.
    - The splitter MUST NOT mutate `reddit_content`; all parent-key reads use `dict.get` or comprehensions that produce a new dict.
    - Emit observability logs (Requirement 12.1, 12.2, 12.3) at the start of `split` (resolved mode and ceilings), after producing the plan (part lengths and per-boundary types), and on `StorySplitError` (thread_id, reason, `len(thread_post)`).
    - _Requirements: 1.3, 1.5, 1.6, 1.7, 2.4, 3.3, 3.4, 3.5, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 5.1, 5.2, 5.3, 5.4, 6.6, 7.1, 7.6, 8.1, 8.3, 12.1, 12.2, 12.3_
  
  - [ ] 5.2 Wire `utils/story_splitter/__init__.py` public API
    - Re-export `Story_Splitter`, `Story_Part`, `Split_Plan`, `SplittingConfig`, `TemplateConfig`, `StorySplitError`.
    - Set `__all__` to match the design's "Public API" section.
    - _Requirements: 1.3, 13.1_
  
  - [ ] 5.3 Write property test for reconstruction
    - **Property 1: Reconstruction**
    - Test in `tests/test_story_splitter_properties.py`. For all `Reddit_Content` for which `Story_Splitter.split` returns a successful `Split_Plan`, assert `"".join(part["part_raw_post"] for part in split_plan)` equals `reddit_content["thread_post"]` after re-inserting the whitespace consumed at each chosen boundary.
    - **Validates: Requirements 9.1, 8.3**
  
  - [ ] 5.4 Write property test for character conservation
    - **Property 2: Character conservation**
    - Test in `tests/test_story_splitter_properties.py`. For all successful `Split_Plan`s, assert `len(thread_post) - 4 * (len(split_plan) - 1) <= sum(len(part["part_raw_post"]) for part in split_plan) <= len(thread_post)`.
    - **Validates: Requirements 9.2**
  
  - [ ] 5.5 Write property test for hard maximum invariant
    - **Property 3: Hard maximum invariant**
    - Test in `tests/test_story_splitter_properties.py`. For all `Story_Part`s in successful `Split_Plan`s, assert `len(part["part_raw_post"]) <= hard_max_length`.
    - **Validates: Requirements 9.3, 3.5**
  
  - [ ] 5.6 Write property test for minimum length invariant
    - **Property 4: Minimum length invariant**
    - Test in `tests/test_story_splitter_properties.py`. For all `Story_Part`s in `Split_Plan`s of length `>= 2`, assert `len(part["part_raw_post"]) >= min_part_length`.
    - **Validates: Requirements 9.4, 5.1**
  
  - [ ] 5.7 Write property test for determinism
    - **Property 5: Determinism**
    - Test in `tests/test_story_splitter_properties.py`. For any `Reddit_Content` and `SplittingConfig`, two successive invocations of `Story_Splitter.split` return equal `Split_Plan`s (same length, same `part_raw_post`, `part_thread_post`, `part_number`, `total_parts`, `part_thread_id` for each part).
    - **Validates: Requirements 9.5**
  
  - [ ] 5.8 Write property test for single-part identity
    - **Property 6: Single-part identity**
    - Test in `tests/test_story_splitter_properties.py`. Parameterize over the four single-part entry conditions: (a) `storymode == False` (Req 1.7); (b) `mode == "cutoff"` and `len(thread_post) <= hard_max_length` (Req 9.7, 2.4); (c) `mode == "split"` and `len(thread_post) <= hard_max_length` (Req 9.6, 3.3); (d) no `[splitting]` section and the post survives the scrape-time filter (Req 11.1, 11.3). In each case, assert the returned plan has length `1`, and the only `Story_Part` satisfies `part_raw_post == thread_post`, `part_thread_post == thread_post`, `part_thread_title == thread_title`, `part_thread_id == thread_id` byte-for-byte.
    - **Validates: Requirements 9.6, 9.7, 1.7, 2.4, 3.3, 6.6, 7.6, 11.1, 11.3**
  
  - [ ] 5.9 Write property test for no mid-word split
    - **Property 7: No mid-word split**
    - Test in `tests/test_story_splitter_properties.py`. For all `Split_Plan`s of length `>= 2`, the character at position `start_offset_i - 1` (the character immediately before each part's start offset within `thread_post`) is a whitespace character, a paragraph-break character (`\n` or `\r`), or a sentence-terminator character (`.`, `!`, `?`).
    - **Validates: Requirements 9.8, 4.5**
  
  - [ ] 5.10 Write property test for boundary positioning
    - **Property 8: Boundary positioning**
    - Test in `tests/test_story_splitter_properties.py`. For all split offsets `i` in a `Split_Plan` of length `>= 2`, the offset falls within the search window `[min_part_length, hard_max_length]` measured from the start of the current part, except when Requirement 5.3's redistribution moved the boundary earlier (in which case the offset is bounded below by `min_part_length` from the part start).
    - **Validates: Requirements 9.9, 4.4**
  
  - [ ] 5.11 Write property test for input non-mutation
    - **Property 10: Splitter does not mutate input**
    - Test in `tests/test_story_splitter_properties.py`. For all `Reddit_Content`, after `Story_Splitter.split(reddit_content)` returns or raises `StorySplitError`, `reddit_content` is byte-for-byte equal to a `copy.deepcopy` taken before the call.
    - **Validates: Requirements 1.6**
  
  - [ ] 5.12 Write splitter example unit tests
    - Cover edge cases the property strategies don't reliably reach: `_redistribute_tail` with a single redistribution iteration, with multi-iteration redistribution, and with a successful tail merge fallback (Req 5.3); `pathological_text` driving `StorySplitError(reason="no_valid_boundary")`; `len(thread_post) > max_parts * hard_max_length` driving `StorySplitError(reason="too_many_parts")`; tail merge that would exceed `hard_max_length` driving `StorySplitError(reason="tail_redistribution_failed")`.
    - Test in `tests/test_story_splitter_examples.py`.
    - _Requirements: 4.7, 5.2, 5.3, 8.1_
  
  - [ ] 5.13 Write splitter logging tests for Requirement 12 entry/exit/error paths
    - Test in `tests/test_story_splitter_logging.py`. Capture stdout/stderr (or hook the `print_substep`/logger used by `splitter.py`) and assert: (12.1) on entry, the resolved `mode`, `soft_max_length`, `hard_max_length`, `min_part_length`, `max_parts`, and `subreddit_name` are emitted; (12.2) after producing the plan, the part count, per-part `len(part_raw_post)`, and per-boundary type (paragraph/sentence/line/whitespace) are emitted; (12.3) on `StorySplitError`, the `thread_id`, `reason`, and input `len(thread_post)` are emitted.
    - _Requirements: 12.1, 12.2, 12.3_

- [ ] 6. Checkpoint - Ensure splitter package tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 7. Plumb Subreddit_Name through ingestion
  - [x] 7.1 Add `_RedditPost.subreddit` and `content["subreddit_name"]` in `reddit/subreddit.py`
    - Add `self.subreddit: str = data.get("subreddit", "") or ""` to `_RedditPost.__init__`.
    - In `get_subreddit_threads`, set `content["subreddit_name"] = (submission.subreddit or _first_configured_subreddit()).lower()` where `_first_configured_subreddit()` returns `settings.config["reddit"]["thread"]["subreddit"].split("+")[0].lstrip("r/").strip().lower()`.
    - This is the only change permitted in `reddit/subreddit.py` per Requirement 13.2.
    - _Requirements: 2.1, 13.2 (Glossary "Subreddit_Name")_
  
  - [x] 7.2 Set `content["subreddit_name"]` in `batch.py::build_reddit_object`
    - Mirror the `reddit/subreddit.py` change: in `build_reddit_object(submission)`, add `content["subreddit_name"] = (getattr(submission, "subreddit", "") or _first_configured_subreddit()).lower()`. Reuse the `_first_configured_subreddit` helper (import from `reddit/subreddit.py` or duplicate at module scope to keep `batch.py` standalone).
    - _Requirements: 2.1, 13.2 (Glossary "Subreddit_Name")_
  
  - [ ] 7.3 Write unit tests for subreddit_name resolution
    - Test in `tests/test_story_splitter_subreddit.py`. Cover: (a) submission with a populated `subreddit` field — `subreddit_name` lowercased equals that value; (b) submission with empty `subreddit` and `[reddit.thread] subreddit = "Relationships"` — falls back to `"relationships"`; (c) `[reddit.thread] subreddit = "relationships+confessions"` — falls back to the first configured subreddit; (d) `r/` prefix in the configured value is stripped.
    - _Requirements: 2.1, 13.2_

- [ ] 8. Replace scrape-time length cutoff with per-subreddit ceiling
  - [x] 8.1 Replace the `storymode_max_length` cutoff in `utils/subreddit.py::get_subreddit_undone`
    - Within the `storymode` branch, replace the existing `len(submission.selftext) > storymode_max_length` check with: derive `subreddit_name = (getattr(submission, "subreddit", "") or subreddit).lower()`, build `splitting_cfg = SplittingConfig.from_settings(settings.config, subreddit_name=subreddit_name)`, and reject when `len(submission.selftext) > ceiling` where `ceiling = splitting_cfg.hard_max_length` for `cutoff` mode and `ceiling = splitting_cfg.max_parts * splitting_cfg.hard_max_length` for `split` mode.
    - Preserve the existing `len(selftext) < 200` minimum and all other filter rules unchanged.
    - _Requirements: 2.5, 2.6, 2.7, 11.2_
  
  - [ ] 8.2 Replace the `storymode_max_length` cutoff in `batch.py::is_valid_post`
    - Replace `if len(post.selftext) > max_len: return False` with the same per-subreddit ceiling computed via `SplittingConfig.from_settings(settings.config, subreddit_name=(post.subreddit or "").lower())`. Use `cfg.hard_max_length` for `cutoff` mode and `cfg.max_parts * cfg.hard_max_length` for `split` mode.
    - _Requirements: 2.5, 2.6, 2.7, 11.2_
  
  - [ ] 8.3 Write unit tests for the scrape-time filter under cutoff vs split mode
    - Test in `tests/test_story_splitter_filters.py`. Cover: (a) `cutoff` mode rejects `len > hard_max_length` (Req 2.5, 11.2); (b) `cutoff` mode admits `len <= hard_max_length`; (c) `split` mode admits `len <= max_parts * hard_max_length` (Req 2.6); (d) `split` mode rejects `len > max_parts * hard_max_length` (Req 2.7); (e) per-subreddit override flips behavior between two posts in the same fetch.
    - _Requirements: 2.5, 2.6, 2.7, 11.2_

- [ ] 9. Integrate Story_Splitter into the orchestrator
  - [ ] 9.1 Insert `Story_Splitter`, the per-part loop, and the inside-loop `already_done` check in `main.py::main`
    - After `Translation_Service.translate(...)` and before the existing `posttextparser` / `save_text_to_mp3` calls, instantiate `SplittingConfig.from_settings(settings.config, subreddit_name=reddit_object.get("subreddit_name", ""))` and call `Story_Splitter(splitting_config).split(reddit_object)`.
    - Wrap the splitter call in `try/except StorySplitError` per the design's "Orchestrator integration" pattern: write a `videos.json` skipped record (`reddit_title="skipped:" + e.reason`) via the existing `save_data` helper, log a warning, and `return` so the run loop continues (Req 8.2).
    - Replace the linear `posttextparser → save_text_to_mp3 → ... → make_final_video` block with `for story_part in split_plan:` iterating those stages over `story_part`. Run `posttextparser` *inside* the per-part loop when `storymodemethod == 1` (resolution to design Q2).
    - Add an inside-loop `already_done` guard: load `videos.json` once before the loop, then `if any(v["id"] == story_part["thread_id"] for v in done_videos): continue` so half-finished multi-part runs resume from the next undone part (Req 7.5).
    - Set `reddit_id = extract_id(story_part)` inside the loop so the existing global `reddit_id` reflects the current part for any cleanup hook.
    - Emit per-iteration logging (Req 12.4): `part_number`, `total_parts`, and `part_thread_id`.
    - _Requirements: 1.1, 1.2, 1.4, 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 8.2, 12.4, 13.3_
  
  - [ ] 9.2 Insert the same orchestration changes into `batch.py::make_one_video`
    - Mirror the `main.py::main` change: invoke `Story_Splitter` after `Translation_Service.translate`, catch `StorySplitError` (write the same skipped record and `return False`), iterate `for story_part in split_plan:` over the consumer stages including `posttextparser` when `storymodemethod == 1`, add the inside-loop `already_done` check, and emit Req 12.4 logging.
    - Preserve the existing outer `try/except` cleanup so a failure in any consumer stage of part `k` cleans `assets/temp/{part_thread_id}` and returns `False`; parts `1..k-1` already in `videos.json` remain there.
    - _Requirements: 1.1, 1.4, 7.1, 7.2, 7.3, 7.4, 7.5, 8.2, 12.4, 13.3_
  
  - [ ] 9.3 Write property test for pipeline stage order and per-part argument plumbing
    - **Property 12: Pipeline stage order and per-part argument plumbing**
    - Test in `tests/test_orchestrator_properties.py`. Monkey-patch `get_subreddit_threads`, `Translation_Service.translate`, `Story_Splitter.split`, `posttextparser`, `save_text_to_mp3`, `get_screenshots_of_reddit_posts`, `chop_background`, `make_final_video` to record their call order and arguments. For all `(storymode, storymodemethod, mode, post_length)` combinations, assert: (1) `get_subreddit_threads` precedes `Translation_Service.translate` precedes `Story_Splitter.split`, each called once; (2) consumer stages are each called exactly once per `Story_Part` with `thread_id == part_thread_id`, `thread_title == part_thread_title`, `thread_post == part_thread_post`; (3) when `storymode and storymodemethod == 1`, `posttextparser` is called once per part between `split` and `save_text_to_mp3`.
    - **Validates: Requirements 1.1, 1.4, 7.2, 13.3**
  
  - [ ] 9.4 Write property test for `part_thread_id` derivation and consumer plumbing
    - **Property 13: Per-part thread_id derivation and consumer plumbing**
    - Test in `tests/test_orchestrator_properties.py`. For all `Split_Plan`s, assert every `Story_Part` satisfies `part["part_thread_id"] == thread_id` when `total_parts == 1` and `part["part_thread_id"] == f"{thread_id}-p{part_number}"` when `total_parts >= 2`; further, `extract_id(story_part)` equals `part["part_thread_id"]` for every part.
    - **Validates: Requirements 7.1, 7.3, 7.4, 7.5, 7.6**
  
  - [ ] 9.5 Write orchestrator logging test for Requirement 12.4
    - Test in `tests/test_story_splitter_logging.py`. Run a mocked `main()` with a 2-part `Split_Plan` and capture stdout/stderr; assert each iteration of the per-part loop logs `part_number`, `total_parts`, and `part_thread_id`.
    - _Requirements: 12.4_
  
  - [ ] 9.6 Write `StorySplitError` skip-path integration test
    - Test in `tests/test_story_splitter_integration.py`. Monkey-patch `Story_Splitter.split` to raise `StorySplitError(thread_id="abc", reason="too_many_parts", detail="...")`; assert `main(POST_ID="abc")` returns without raising, `videos.json` gains a record with `id == "abc"`, and a warning naming the reason was logged. Repeat for `batch.py::make_one_video` returning `False` with the same record.
    - _Requirements: 8.1, 8.2_

- [ ] 10. AST/static scope-isolation checks
  - [ ] 10.1 Write AST tests for `utils/story_splitter` scope isolation
    - Test in `tests/test_story_splitter_ast.py`. Walk `utils/story_splitter/*.py` with `ast` and assert: no `import` or `from … import` references to `posttextparser`, `save_text_to_mp3`, `get_screenshots_of_reddit_posts`, `chop_background`, `make_final_video`, `Translation_Service`, `requests`, or `pathlib.Path`; no `open(` calls; no `os.makedirs` / `os.path.exists` calls. The splitter MUST remain a pure function of `(Reddit_Content, SplittingConfig) -> Split_Plan`.
    - _Requirements: 1.5, 1.6, 13.1_
  
  - [ ] 10.2 Write AST tests for `claude-translation` scope isolation
    - Test in `tests/test_story_splitter_ast.py`. Walk `utils/translation/*.py` and assert no symbols from `utils.story_splitter` are imported. Walk `main.py` and `batch.py` and assert the `Translation_Service.translate` call site is unchanged in shape (translation still runs once per run, before the splitter).
    - _Requirements: 13.1, 13.2, 13.3_

- [ ] 11. Smoke and integration tests
  - [ ] 11.1 Write a two-part end-to-end smoke test
    - Test in `tests/test_story_splitter_integration.py`. With every consumer stage (`save_text_to_mp3`, `get_screenshots_of_reddit_posts`, `chop_background`, `make_final_video`, `download_background_video`, `download_background_audio`) replaced by no-op fakes that record their `thread_id` argument, run a real `main()` with a generated 2500-character `thread_post` and `mode = "split"`. Assert two `make_final_video` calls were made with `thread_id`s `"<id>-p1"` and `"<id>-p2"`, and that `videos.json` gained two records with the suffixed IDs.
    - _Requirements: 1.4, 7.1, 7.3, 7.4, 7.5_
  
  - [ ] 11.2 Write a backwards-compatibility smoke test
    - Test in `tests/test_story_splitter_integration.py`. With no `[splitting]` section in the loaded config (and no `[splitting.subreddits.*]` or `[splitting.templates]` tables), run a mocked `main()` with a 500-character `thread_post`. Assert exactly one `make_final_video` call with `thread_id == "<id>"` (no `-p1` suffix), `videos.json` gained exactly one record keyed by the bare `thread_id`, and the `assets/temp/` directory used is `assets/temp/<id>/` (not `assets/temp/<id>-p1/`).
    - _Requirements: 11.1, 11.2, 11.3, 7.6_
  
  - [ ] 11.3 Write a config schema parse test for `utils/.config.template.toml`
    - Test in `tests/test_story_splitter_integration.py`. Parse `utils/.config.template.toml` with `tomllib` (or the project's existing TOML loader) and assert every field added by this spec is present with a documented default: `[splitting] default_mode`, `soft_max_length`, `single_part_tolerance`, `min_part_length`, `max_parts`; `[splitting.templates] title_first_part`, `title_other_part`, `body_prefix_other_part`, `body_suffix_non_final_part`; and that the file documents the `[splitting.subreddits.<subreddit_name>]` override structure.
    - _Requirements: 10.1, 10.3, 10.4_

- [ ] 12. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP. They cover property tests, example unit tests, AST scope checks, logging tests, and smoke / integration tests. The core implementation tasks (no `*`) deliver a working splitter end-to-end.
- Each property test references its property number from the design's "Correctness Properties" section (P1–P17) and the requirement clause(s) it validates (per Requirement 9 and the surrounding observability and configuration requirements).
- All property tests run with at least 100 Hypothesis examples (`@settings(max_examples=100)` or higher) and use the shared strategies in `tests/_strategies.py`.
- Splitting tests are spread across six test files for parallelism: `tests/test_splitting_config_properties.py` (P11, P14), `tests/test_story_splitter_examples.py` (boundary unit tests + splitter examples), `tests/test_templates_properties.py` (P9, P15, P16, P17), `tests/test_story_splitter_properties.py` (P1–P8, P10), `tests/test_orchestrator_properties.py` (P12, P13), and the integration / AST / logging files.
- The orchestrator integration in `main.py` and `batch.py` deliberately mirrors the same per-part loop structure so a single `Story_Part` (cutoff or backwards-compat path) produces byte-for-byte identical artifacts to the pre-feature pipeline (Requirement 11.3).
- `StorySplitError` is the splitter's only domain-level exception and is caught in exactly one place per orchestrator (the `Story_Splitter(...).split(...)` call site); failures inside consumer stages keep the existing `try/except` semantics in each entry point.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "2.1", "2.2", "7.1"] },
    { "id": 1, "tasks": ["1.3", "2.3", "3.1", "4.1", "7.2"] },
    { "id": 2, "tasks": ["2.4", "3.2", "4.2", "5.1", "8.1"] },
    { "id": 3, "tasks": ["2.5", "4.3", "5.2", "5.12", "8.2"] },
    { "id": 4, "tasks": ["4.4", "5.3", "5.13", "7.3", "8.3", "9.1", "9.4", "10.1"] },
    { "id": 5, "tasks": ["4.5", "5.4", "9.2", "10.2"] },
    { "id": 6, "tasks": ["5.5", "9.3", "9.5", "9.6"] },
    { "id": 7, "tasks": ["5.6", "11.1"] },
    { "id": 8, "tasks": ["5.7", "11.2"] },
    { "id": 9, "tasks": ["5.8", "11.3"] },
    { "id": 10, "tasks": ["5.9"] },
    { "id": 11, "tasks": ["5.10"] },
    { "id": 12, "tasks": ["5.11"] }
  ]
}
```
