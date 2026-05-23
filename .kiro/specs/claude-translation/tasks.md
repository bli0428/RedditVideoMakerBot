# Implementation Plan: Claude Translation

## Overview

Convert the feature design into a series of prompts for a code-generation LLM that will implement each step with incremental progress. Make sure that each prompt builds on the previous prompts, and ends with wiring things together. There should be no hanging or orphaned code that isn't integrated into a previous step. Focus ONLY on tasks that involve writing, modifying, or testing code.

This plan follows the design's five-phase migration so `main.py` runs cleanly between every checkpoint:

1. **Phase 1** — package skeleton + no-op provider wired through `main.py`.
2. **Phase 2** — scraper decoupling + orchestrator re-ordering (raw `str` `thread_post`, `posttextparser` runs after `Translation_Service`).
3. **Phase 3** — Anthropic SDK integration (real `anthropic` provider, cache, prompts, failure policy).
4. **Phase 4** — adapter removal at the four legacy `translators.translate_text` call sites + gTTS locale precedence.
5. **Phase 5** — cleanup and docs.

Implementation language: Python (matches the existing codebase and the design document, which uses concrete Python throughout).

## Tasks

### Phase 1 — Package skeleton and no-op provider

- [x] 1. Scaffold `utils/translation/` package with errors, config, and no-op service
  - [x] 1.1 Create `utils/translation/__init__.py`, `utils/translation/errors.py`, `utils/translation/config.py`, `utils/translation/service.py`
    - In `errors.py`, define the `TranslationError` hierarchy: `TranslationError`, `TranslationConfigError`, `TranslationAPIError`, `TranslationAuthError`, `TranslationRateLimitError`, `TranslationTimeoutError`, `TranslationEmptyResponseError`
    - In `config.py`, define the frozen `TranslationConfig` dataclass with fields `provider`, `effective_provider`, `target_lang`, `failure_policy`, `cache_enabled`, `force_translate`, `model`, `max_output_tokens`, `api_key`, plus `VALID_PROVIDERS`, `VALID_FAILURE_POLICIES`, `DEFAULT_MODEL`, `DEFAULT_MAX_OUTPUT_TOKENS`
    - Implement `TranslationConfig.from_settings(settings_config)` honoring defaults from Req 3.2/3.3 and the unknown-provider degradation from Req 11.3 (warn + `effective_provider = "none"`, never abort)
    - Implement `TranslationConfig.has_api_key()` and `TranslationConfig.resolve_api_key()` with environment precedence per Req 3.4
    - In `service.py`, define `Translation_Service` with `__init__(config)` and a `translate(reddit_content)` method that, in this phase, only handles the no-op short-circuits: `effective_provider == "none"` (Req 11.1), empty `target_lang` (Req 1.3, 1.4), and the non-string `thread_post` `TypeError` (Req 4.7)
    - In `__init__.py`, re-export `Translation_Service`, `TranslationConfig`, and the `TranslationError` hierarchy as the public API
    - Add a module docstring to `service.py` documenting the catastrophic-error exemption from Req 6.4
    - _Requirements: 1.2, 1.3, 1.4, 3.2, 3.3, 3.4, 3.5, 4.7, 6.4, 11.1, 11.3, 12.1, 12.2, 12.3_

  - [x] 1.2 Write property test for no-op pass-through and config defaults
    - **Property 4: Pass-through when translation is disabled**
    - **Validates: Requirements 1.3, 1.4, 11.1**
    - Hypothesis-generate `Reddit_Content` dicts and configs where `effective_provider == "none"` or `target_lang in (None, "")`; assert `Translation_Service(config).translate(input) == input` and that no Anthropic_Client is constructed (the service is not yet wired to the SDK, so this is a structural assertion that the no-op branch returns early)
    - _Requirements: 1.3, 1.4, 11.1_

  - [x] 1.3 Write property test for `TranslationConfig` defaults
    - **Property 14: Config defaults applied for missing keys**
    - **Validates: Requirements 3.2, 3.3**
    - Hypothesis-generate `settings.config` mappings where the `[translation]` section is absent or omits subsets of keys; assert each missing key resolves to the documented default
    - _Requirements: 3.2, 3.3_

  - [x] 1.4 Write property test for API-key environment precedence
    - **Property 15: API-key environment precedence**
    - **Validates: Requirements 3.4**
    - Hypothesis-generate `(env_value, config_value)` pairs of strings, set/unset `ANTHROPIC_API_KEY` accordingly, and assert `resolve_api_key()` returns env when non-empty, then config_value, and raises `TranslationConfigError` naming both sources when both are empty
    - _Requirements: 3.4_

  - [x] 1.5 Write property test for unknown-provider degradation
    - **Property 16: Unknown provider degrades to none**
    - **Validates: Requirements 11.3**
    - Hypothesis-generate strings outside `{"none", "anthropic"}` for `provider`; assert `from_settings` returns `effective_provider == "none"`, does not raise, and emits a warning containing both the offending value and the valid provider list
    - _Requirements: 11.3_

  - [x] 1.6 Write property test for structural-field byte-equality through the no-op path
    - **Property 3: Structural-Field byte-equality (no-op flavor)**
    - **Validates: Requirements 1.2, 4.5, 6.4, 8.3, 15.5**
    - Hypothesis-generate `Reddit_Content` dicts; with a no-op config, assert `output.keys() == input.keys()` and every Structural_Field value (including `comments[*].comment_id`, `comments[*].comment_url`) is preserved byte-for-byte
    - _Requirements: 1.2, 4.5, 6.4, 8.3, 15.5_

- [x] 2. Add `[translation]` configuration to `config.toml` and `utils/.config.template.toml`
  - [x] 2.1 Append `[translation]` and `[translation.anthropic]` sections to `config.toml`
    - Use `provider = "none"` so behavior remains unchanged at the end of Phase 1
    - Include `target_lang = ""`, `failure_policy = "skip"`, `cache_enabled = true`, `force_translate = false`
    - Under `[translation.anthropic]`: `model = "claude-3-5-sonnet-latest"`, `max_output_tokens = 4096`, `api_key = ""`
    - _Requirements: 3.1, 3.2, 3.3, 11.1_

  - [x] 2.2 Document the `[translation]` section in `utils/.config.template.toml`
    - Use the existing dict-form template style: `{ optional = true, default = ..., options = [...], explanation = "..." }` for each field
    - Cover `provider`, `target_lang`, `failure_policy`, `cache_enabled`, `force_translate`, and the `[translation.anthropic]` keys `model`, `max_output_tokens`, `api_key`
    - Note in the `api_key` explanation that `ANTHROPIC_API_KEY` env var takes precedence
    - _Requirements: 3.1, 3.6_

- [x] 3. Wire `Translation_Service` into `main.py::main` as a no-op
  - [x] 3.1 Import `Translation_Service` and `TranslationConfig` from `utils.translation` in `main.py`
    - After `reddit_object = get_subreddit_threads(POST_ID)` and before `save_text_to_mp3`, call `TranslationConfig.from_settings(settings.config)` and `Translation_Service(translation_config).translate(reddit_object)`, reassigning to `reddit_object`
    - With `provider = "none"` from Phase 1, the call is a no-op and the rest of `main` is unchanged
    - Do not yet add the conditional `posttextparser` call to `main.py` (that lands in Phase 2)
    - _Requirements: 1.1, 16.1, 16.2_

- [x] 4. Phase 1 checkpoint
  - Ensure all tests pass, ask the user if questions arise.

### Phase 2 — Scraper decoupling and orchestrator re-ordering

- [x] 5. Decouple the scraper so `thread_post` is always a raw `str`
  - [x] 5.1 Edit `reddit/subreddit.py::get_subreddit_threads` to remove `posttextparser`
    - Remove the line `from utils.posttextparser import posttextparser`
    - Replace the `storymodemethod == 1` branch so `content["thread_post"] = submission.selftext` unconditionally whenever `storymode` is enabled
    - Leave every other Structural_Field assignment byte-identical to the pre-change shape
    - _Requirements: 10.7, 15.1, 15.2, 15.3, 15.5_

  - [x] 5.2 Edit `batch.py::build_reddit_object` to remove `posttextparser` and always set `thread_post` to `submission.selftext`
    - Remove the `from utils.posttextparser import posttextparser` import (if present)
    - Set `content["thread_post"] = submission.selftext` whenever `storymode` is enabled, regardless of `storymodemethod`
    - If `batch.py` does not currently contain a parallel scraper path that imports `posttextparser`, satisfy this by ensuring no such import or call exists after the edit (Req 15.4 explicit allowance)
    - _Requirements: 10.8, 15.4, 15.5_

- [x] 6. Move `posttextparser` invocation into the orchestrator
  - [x] 6.1 Add the conditional `posttextparser` call to `main.py::main` after `Translation_Service` returns
    - Import `from utils.posttextparser import posttextparser` in `main.py`
    - After the `Translation_Service` call (still no-op in this phase), if `settings.config["settings"]["storymode"]` and `settings.config["settings"]["storymodemethod"] == 1`, replace `reddit_object["thread_post"]` with `posttextparser(reddit_object["thread_post"])` before the consumer stages run
    - Do not invoke `posttextparser` when `storymodemethod == 0` (Req 9.3, 16.4)
    - Do not invoke `posttextparser` when `Translation_Service` was not invoked for the current run (Req 9.2); since `Translation_Service` is always invoked when `get_subreddit_threads` returns, satisfy this by guarding the parser block within the same control flow that wraps the translate call
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 16.1, 16.2, 16.3, 16.4, 16.5_

  - [x] 6.2 Add the same conditional `posttextparser` call to `batch.py::make_one_video` after `Translation_Service` returns
    - Mirror the helper structure used in `main.py::main` so both orchestrator entry points produce the same Pipeline_Stage_Order
    - Wire `Translation_Service` into `make_one_video` in the same position relative to scrape and consumer stages
    - _Requirements: 9.1, 9.2, 9.3, 16.1, 16.2, 16.3, 16.4, 16.5_

  - [x] 6.3 Write property test for pipeline stage order
    - **Property 23: Pipeline stage order**
    - **Validates: Requirements 1.1, 9.1, 9.2, 9.3, 16.1, 16.2, 16.3, 16.4**
    - Hypothesis-generate `(storymode, storymodemethod, provider, target_lang)` flag combinations; monkey-patch `get_subreddit_threads`, `Translation_Service.translate`, `posttextparser`, `save_text_to_mp3`, `get_screenshots_of_reddit_posts`, and `make_final_video` with recorders and assert each call sequence is a subsequence of the documented order with the per-flag preconditions
    - _Requirements: 1.1, 9.1, 9.2, 9.3, 16.1, 16.2, 16.3, 16.4_

  - [x] 6.4 Write property test for raw-string `thread_post` from the scraper
    - **Property 24: Scraper returns raw string thread_post**
    - **Validates: Requirements 15.1, 15.4**
    - Hypothesis-generate mocked `submission` objects with arbitrary `selftext` strings; for both `storymodemethod` values, assert `get_subreddit_threads` and `batch.build_reddit_object` produce `content["thread_post"]` that is a `str` and equals `submission.selftext`
    - _Requirements: 15.1, 15.4_

- [x] 7. Phase 2 checkpoint
  - Ensure all tests pass, ask the user if questions arise.

### Phase 3 — Anthropic SDK integration

- [x] 8. Add Anthropic SDK dependency
  - [x] 8.1 Add `anthropic` to `requirements.txt`
    - Pin a compatible version per the design's expected SDK exception types (`AuthenticationError`, `RateLimitError`, `APITimeoutError`, `APIError`)
    - _Requirements: 2.1_

- [x] 9. Implement prompts module
  - [x] 9.1 Create `utils/translation/prompts.py` with `SYSTEM_PROMPT_DETECT`, `SYSTEM_PROMPT_TRANSLATE`, `user_prompt_detect(sample)`, and `user_prompt_translate(*, text, target_lang)`
    - Use the exact strings from the design's prompts section so snapshot tests can pin them
    - System prompt for translation must instruct Claude to preserve casual register, slang, and profanity, and to return raw text only (Req 2.5)
    - _Requirements: 2.5_

  - [x] 9.2 Snapshot tests on `prompts.py`
    - Pin `SYSTEM_PROMPT_DETECT` and `SYSTEM_PROMPT_TRANSLATE` byte-for-byte against committed expected strings
    - Example-based tests for `user_prompt_detect("hello")` and `user_prompt_translate(text="hi", target_lang="es")`
    - _Requirements: 2.5, 14.3_

- [x] 10. Implement `Translation_Cache`
  - [x] 10.1 Create `utils/translation/cache.py` with `Translation_Cache`
    - SHA-256 key derivation over `f"{thread_id}|{sha256(text_utf8)}|{target_lang}|{model_id}"`
    - Cache file at `assets/temp/{thread_id}/translation_cache.json`
    - Atomic writes via `tempfile.mkstemp` + `os.replace`; tolerate missing files and `json.JSONDecodeError`/`OSError` on read
    - In-memory `_known_empty` bloom set keyed by `(thread_id, target_lang, model_id)` so subsequent reads short-circuit per Req 7.3
    - `get` returns `None` on miss; `put` raises `OSError` on persistent I/O failure for the service to catch
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.7_

  - [x] 10.2 Write property test for cache key derivation
    - **Property 17: Cache key derivation is deterministic and tuple-sensitive**
    - **Validates: Requirements 7.1, 7.7**
    - Hypothesis-generate `(thread_id, text, target_lang, model_id)` tuples; assert repeat calls produce the same key; assert any single-component change produces a different key; assert the cache file path equals `Path("assets/temp") / thread_id / "translation_cache.json"`
    - _Requirements: 7.1, 7.7_

- [x] 11. Implement `Anthropic_Client`
  - [x] 11.1 Create `utils/translation/anthropic_client.py` with `Anthropic_Client`
    - Constructor validates `temperature == 0.0` and raises `TranslationConfigError` otherwise (Req 2.3)
    - Lazy-import the `anthropic` SDK inside the constructor; store `self._sdk` and `self._client`
    - `detect_source_language(sample)` and `translate(text, target_lang)` each call `self._call(system, user)` and return the parsed text
    - `_call` builds `messages.create(model, max_tokens, temperature=0.0, system, messages=[{"role":"user","content":user}])` and maps `anthropic.AuthenticationError -> TranslationAuthError`, `RateLimitError -> TranslationRateLimitError`, `APITimeoutError -> TranslationTimeoutError`, `APIError -> TranslationAPIError`
    - `_extract_text(msg)` walks `msg.content`, concatenates blocks where `block.type == "text"`, and raises `TranslationEmptyResponseError` when the result is empty/whitespace
    - `Anthropic_Client` is the only module that imports the `anthropic` SDK (Req 1.5, 1.6, 2.1)
    - _Requirements: 1.5, 1.6, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 6.3_

  - [x] 11.2 Write property test for Anthropic request shape
    - **Property 12: Anthropic request shape**
    - **Validates: Requirements 2.2, 2.4, 2.6**
    - Hypothesis-generate `(model, max_output_tokens)` configs and `Reddit_Content` inputs that trigger at least one translate call; capture every `messages.create` kwargs invocation and assert `model`, `max_tokens`, and `temperature == 0` match
    - _Requirements: 2.2, 2.4, 2.6_

  - [x] 11.3 Write property test for temperature rejection
    - **Property 13: Temperature != 0 rejection**
    - **Validates: Requirements 2.3**
    - Hypothesis-generate floats `t != 0.0`; assert `Anthropic_Client(api_key=..., model=..., max_output_tokens=..., temperature=t)` raises `TranslationConfigError` whose message contains `repr(t)`
    - _Requirements: 2.3_

- [x] 12. Extend `Translation_Service` to handle the `provider == "anthropic"` branch
  - [x] 12.1 Update `utils/translation/service.py` to integrate the cache, client, and failure policy
    - Construct `Anthropic_Client` lazily on first translation attempt (Req 3.5) using `config.resolve_api_key()` so a missing key is reported only when translation is actually needed
    - Build the source-language detection sample (`TITLE: ... BODY: <500 chars> COMMENT 1..3: <200 chars>`) and call `detect_source_language` exactly once per `Reddit_Content` (Req 5.1, 5.3)
    - When `force_translate == False` and the detected source matches `target_lang` (lowercase compare), short-circuit and return the input (Req 5.2, 5.4)
    - Translate `thread_title`, `thread_post` (when `str`), and every `comments[*].comment_body` via `_translate_field` which (a) reads cache, (b) calls `Anthropic_Client.translate`, (c) writes cache, (d) sanitizes via `utils.voice.sanitize_text`, (e) substitutes original on collapse with a warning (Req 14.2)
    - Apply `failure_policy` per `_apply_field_failure_policy`: under `skip`, catch `TranslationError`, warn with field name and error class, return original (Req 6.1); under `fail`, re-raise wrapped with field name (Req 6.2)
    - Treat empty Anthropic responses as `TranslationEmptyResponseError` (Req 6.3)
    - Catch `OSError` from cache writes, warn, and continue with the translated value (Req 7.5)
    - Emit the start-of-run, per-call, per-cache-hit, and end-of-run summary log lines (Req 13.1–13.4)
    - Preserve every key in the input dict regardless of failure path (Req 6.4); document the catastrophic-error exemption in the docstring already present from Phase 1
    - _Requirements: 1.1, 1.2, 1.5, 1.6, 2.1, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 5.1, 5.2, 5.3, 5.4, 6.1, 6.2, 6.3, 6.4, 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 11.2, 13.1, 13.2, 13.3, 13.4, 14.1, 14.2, 14.3_

  - [x] 12.2 Write property test for determinism
    - **Property 1: Determinism under fixed model and config**
    - **Validates: Requirements 8.1**
    - Hypothesis-generate `Reddit_Content` and `TranslationConfig` with `provider = "anthropic"`; with a deterministic mocked `Anthropic_Client`, call `translate` twice and assert value equality
    - _Requirements: 8.1_

  - [x] 12.3 Write property test for idempotence
    - **Property 2: Idempotence under same target language**
    - **Validates: Requirements 8.2**
    - Hypothesis-generate `Reddit_Content` and configs with non-empty `target_lang`; assert `translate(translate(input)) == translate(input)`
    - _Requirements: 8.2_

  - [x] 12.4 Write property test for structural-field byte-equality (full)
    - **Property 3: Structural-Field byte-equality**
    - **Validates: Requirements 1.2, 4.5, 6.4, 8.3, 15.5**
    - Hypothesis-generate inputs across all combinations of `failure_policy`, cache state, and provider; assert `output.keys() == input.keys()` and every Structural_Field value (including `comments[*].comment_id` and `comments[*].comment_url`) is preserved byte-for-byte
    - _Requirements: 1.2, 4.5, 6.4, 8.3, 15.5_

  - [x] 12.5 Write property test for source==target no-op
    - **Property 5: Source==target no-op**
    - **Validates: Requirements 5.2, 8.4**
    - Hypothesis-generate inputs with `force_translate = False`; mock the detector to return a tag matching `target_lang.lower()`; assert no `Anthropic_Client.translate` call is made and Translatable_Field values equal the input values
    - _Requirements: 5.2, 8.4_

  - [x] 12.6 Write property test for `force_translate` skipping detection
    - **Property 6: Force-translate skips detection**
    - **Validates: Requirements 5.4**
    - Hypothesis-generate inputs with `force_translate = True`; assert the mocked `detect_source_language` is called zero times
    - _Requirements: 5.4_

  - [x] 12.7 Write property test for single-call detection
    - **Property 7: Detection is single-call per Reddit_Content**
    - **Validates: Requirements 5.3**
    - Hypothesis-generate inputs with `force_translate = False` and source != target; assert `detect_source_language` is called exactly once regardless of the number of Translatable_Fields
    - _Requirements: 5.3_

  - [x] 12.8 Write property test for full Translatable_Field coverage
    - **Property 8: All Translatable_Fields are translated**
    - **Validates: Requirements 4.1, 4.2, 4.3, 4.4, 14.1**
    - Hypothesis-generate inputs with non-empty `thread_title`, string `thread_post`, and a non-empty `comments` list; assert each translated value equals `sanitize_text(mocked_client.translate(corresponding_input))` and that `output["thread_post"]` is a `str`
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 14.1_

  - [x] 12.9 Write property test for `TypeError` on non-string `thread_post`
    - **Property 9: TypeError on non-string thread_post**
    - **Validates: Requirements 4.7**
    - Hypothesis-generate non-`str`, non-`None` values (list, int, dict, bytes); assert `translate` raises `TypeError` whose message contains `"thread_post"` and the actual type name
    - _Requirements: 4.7_

  - [x] 12.10 Write property test for skip-policy failure containment
    - **Property 10: Failure containment under skip policy**
    - **Validates: Requirements 6.1, 6.3, 6.4**
    - Hypothesis-generate inputs, `TranslationError` subclasses (including `TranslationEmptyResponseError`), and Translatable_Field choices; with `failure_policy = "skip"` and the mocked client raising on the chosen field, assert no exception propagates, `output.keys() == input.keys()`, the failed field equals its input value, and a warning containing both field and error class is emitted
    - _Requirements: 6.1, 6.3, 6.4_

  - [x] 12.11 Write property test for fail-policy propagation
    - **Property 11: Failure propagation under fail policy**
    - **Validates: Requirements 6.2, 6.3**
    - Hypothesis-generate inputs, `TranslationError` subclasses, and Translatable_Field choices; with `failure_policy = "fail"`, assert the raised exception's `str` contains both the field name and the error class name
    - _Requirements: 6.2, 6.3_

  - [x] 12.12 Write property test for cache hit short-circuit
    - **Property 18: Cache hit short-circuits Anthropic_Client**
    - **Validates: Requirements 7.2**
    - Use a `tempfile.TemporaryDirectory` cache root; run `translate` twice on the same input with `cache_enabled = True`; assert the second call invokes `mocked_anthropic_client.translate` zero times and `detect_source_language` exactly once, and the two outputs are equal
    - _Requirements: 7.2_

  - [x] 12.13 Write property test for cache write after Anthropic translation
    - **Property 19: Cache write occurs after successful Anthropic translation**
    - **Validates: Requirements 7.4**
    - Use a fresh temp cache directory; assert that after `translate` returns successfully, `assets/temp/{thread_id}/translation_cache.json` exists and contains the expected key for each translated `(text, target_lang, model_id)` tuple
    - _Requirements: 7.4_

  - [x] 12.14 Write property test for `cache_enabled = False` disabling I/O
    - **Property 20: cache_enabled=False disables all cache I/O**
    - **Validates: Requirements 7.6**
    - Pre-populate `assets/temp/{thread_id}/translation_cache.json`; with `cache_enabled = False`, monkey-patch `Translation_Cache.get`/`put` to count invocations; assert both counts are zero and the on-disk file is byte-unchanged
    - _Requirements: 7.6_

  - [x] 12.15 Write property test for sanitizer-collapse substitution
    - **Property 21: Sanitizer collapse triggers original substitution**
    - **Validates: Requirements 14.2**
    - Hypothesis-generate inputs and pick a Translatable_Field; configure the mocked client to return a value that collapses under `sanitize_text`; assert `output[field] == input[field]` and a warning containing the field name is emitted
    - _Requirements: 14.2_

  - [x] 12.16 Write property test for no wrapper introduction
    - **Property 22: Output does not introduce wrappers**
    - **Validates: Requirements 14.3**
    - Hypothesis-generate inputs without code fences, surrounding quotes, or HTML tags, and a mocked client whose translations are also clean and do not collapse under sanitization; assert no Translatable_Field in the output contains leading/trailing matched code fences, leading/trailing matched quotes, or HTML tags absent from the corresponding input
    - _Requirements: 14.3_

- [x] 13. Phase 3 checkpoint
  - Ensure all tests pass, ask the user if questions arise.

### Phase 4 — Adapter removal at legacy call sites

- [x] 14. Remove `translators.translate_text` from the four legacy call sites
  - [x] 14.1 Edit `video_creation/final_video.py::name_normalize` to drop the `translators` block
    - Remove `import translators` from `video_creation/final_video.py`
    - Strip the `lang` block in `name_normalize` so the function returns the cleaned filename string in the original Latin transliteration
    - Make no other change to `final_video.py` (Req 12.4)
    - _Requirements: 10.1, 10.4, 12.4_

  - [x] 14.2 Edit `TTS/engine_wrapper.py::process_text` to drop the `translators` block
    - Remove `import translators` from `TTS/engine_wrapper.py`
    - Reduce `process_text` to `sanitize_text(text) if clean else text`; the text is already translated by `Translation_Service`
    - _Requirements: 10.1, 10.2_

  - [x] 14.3 Edit `video_creation/screenshot_downloader.py` to drop `translators` while preserving the DOM rewrite
    - Remove `import translators` and the inner `translate_text` helper
    - When `lang` is non-empty, replace the translator call with `translated_title = reddit_object["thread_title"]` (already translated by `Translation_Service`) and keep the existing `page.evaluate` DOM-rewrite block so the screenshot still shows the translated text
    - _Requirements: 10.1, 10.3_

- [x] 15. Update `TTS/GTTS.py` to prefer `[translation] target_lang` for the gTTS locale
  - [x] 15.1 Edit `TTS/GTTS.py` to resolve the locale with the documented precedence and default
    - Resolve `lang` as: `[translation] target_lang` if non-empty, else `[reddit.thread] post_lang` if non-empty, else `"en"` with a warning
    - Use `settings.config.get("translation", {}).get("target_lang", "")` so missing sections do not raise
    - _Requirements: 10.5, 10.6_

  - [x] 15.2 Write property test for gTTS locale precedence
    - **Property 25: gTTS locale precedence**
    - **Validates: Requirements 10.5, 10.6**
    - Hypothesis-generate `(target_lang, post_lang)` string pairs; monkey-patch `settings.config` and `gtts.gTTS`; assert the resolved locale equals `target_lang` when non-empty, else `post_lang` when non-empty, else `"en"` with a warning emitted
    - _Requirements: 10.5, 10.6_

- [x] 16. Add AST-based static tests for the import-removal invariants
  - [x] 16.1 Write static AST tests asserting the architectural invariants
    - Walk `TTS/engine_wrapper.py`, `video_creation/screenshot_downloader.py`, `video_creation/final_video.py`, and `TTS/GTTS.py` with `ast` and assert none of them imports `translators` (Req 10.2, 10.3, 10.4)
    - Walk `reddit/subreddit.py` and `batch.py` and assert neither imports `posttextparser` (Req 10.7, 10.8, 15.2, 15.3)
    - Walk every `*.py` under `utils/translation/` and assert none references `posttextparser` (Req 9.4)
    - Walk every project `*.py` outside `utils/translation/anthropic_client.py` (excluding `venv/`, `.git/`) and assert none imports the `anthropic` SDK (Req 1.5, 1.6, 2.1)
    - Walk `utils/translation/service.py` and assert no `Attribute` node has `attr == "storymodemethod"` (Req 4.6)
    - _Requirements: 1.5, 1.6, 2.1, 4.6, 9.4, 10.2, 10.3, 10.4, 10.7, 10.8, 15.2, 15.3, 16.5_

- [x] 17. Phase 4 checkpoint
  - Ensure all tests pass, ask the user if questions arise.

### Phase 5 — Cleanup and docs

- [x] 18. Add a README section describing the `[translation]` block
  - [x] 18.1 Append a `Translation` section to `README.md`
    - Document the `[translation]` and `[translation.anthropic]` keys with the same defaults as `utils/.config.template.toml`
    - Note that `ANTHROPIC_API_KEY` env var takes precedence over `[translation.anthropic].api_key` (Req 3.4)
    - Note that `provider = "none"` disables translation entirely and that unknown providers degrade to `"none"` with a warning (Req 11.1, 11.3)
    - Note that translations are cached per-thread under `assets/temp/{thread_id}/translation_cache.json` and cleaned alongside other per-thread artifacts (Req 7.7)
    - _Requirements: 3.1, 3.6_

- [x] 19. Verify the legacy `translators` package is removable
  - [x] 19.1 Grep the codebase for residual `translators` imports and remove the dependency if none remain
    - Run a repository-wide search for `import translators` and `from translators` (excluding `venv/`, `.git/`, build caches) and confirm zero hits across non-test source
    - If the search confirms no remaining usage, remove `translators` from `requirements.txt`
    - If any non-test usage remains, leave `translators` in `requirements.txt` and add a code comment in the offending file referencing this task so the dependency can be revisited
    - _Requirements: 10.2, 10.3, 10.4_

- [x] 20. Final checkpoint
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional (test sub-tasks) and can be skipped for a faster MVP. Core implementation sub-tasks are never optional.
- Each task references specific requirements for traceability. Property test sub-tasks additionally cite the design's property numbers and the requirements they validate.
- Phase ordering matches the design's Migration Plan so `main.py` runs cleanly between every checkpoint: Phase 1 leaves behavior unchanged (no-op `Translation_Service`), Phase 2 re-orders the pipeline without changing observable output, Phase 3 enables real translation behind the `provider = "anthropic"` opt-in, Phase 4 removes the legacy adapter call sites, and Phase 5 finalizes docs and cleans up dependencies.
- Same-file conflicts that drive the wave layout below: `utils/translation/service.py` is touched in Phases 1 and 3; `main.py` is touched in Phases 1 and 2; `batch.py` is touched twice in Phase 2 (decoupling and orchestrator wiring).

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "2.1", "2.2"] },
    { "id": 1, "tasks": ["1.2", "1.3", "1.4", "1.5", "1.6", "3.1"] },
    { "id": 2, "tasks": ["5.1", "5.2", "8.1", "9.1", "10.1", "11.1"] },
    { "id": 3, "tasks": ["6.1", "6.2", "9.2", "10.2", "11.2", "11.3"] },
    { "id": 4, "tasks": ["6.3", "6.4", "12.1"] },
    { "id": 5, "tasks": ["14.1", "14.2", "14.3", "15.1"] },
    { "id": 6, "tasks": ["12.2", "12.3", "12.4", "12.5", "12.6", "12.7", "12.8", "12.9", "12.10", "12.11", "12.12", "12.13", "12.14", "12.15", "12.16", "15.2", "16.1", "18.1"] },
    { "id": 7, "tasks": ["19.1"] }
  ]
}
```
