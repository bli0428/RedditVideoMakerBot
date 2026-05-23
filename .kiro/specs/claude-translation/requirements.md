# Requirements Document

## Introduction

The Reddit video pipeline currently translates scraped post text using the `translators` library against Google Translate. The translation calls are duplicated across four modules (`video_creation/final_video.py:name_normalize`, `TTS/engine_wrapper.py:process_text`, `video_creation/screenshot_downloader.py`, and the `post_lang` consumer in `TTS/GTTS.py`), each of which independently reads `settings.config["reddit"]["thread"]["post_lang"]` and re-runs the translator. This is opaque, low-quality on idiomatic Reddit prose, and runs a network round-trip even when the source post is already in the target language.

This feature introduces a centralized `Translation_Service` that calls the official Anthropic Python SDK to translate Reddit post content (title, body, comments) into a configured target language while preserving Reddit's casual register, slang, and profanity. Translation runs as a single upstream pre-processing step on the `Reddit_Content` dictionary returned by `get_subreddit_threads`, so every downstream consumer (TTS, screenshots, filename normalization, final video) reads the already-translated text and existing per-call translation invocations can be removed in one place.

This spec also bundles a small but deliberate scraper-decoupling change. The current scraper (`reddit/subreddit.py::get_subreddit_threads`, mirrored in `batch.py`) calls `posttextparser` on `submission.selftext` while building `Reddit_Content` whenever `storymodemethod = 1`, which forces sentence segmentation to run before translation. That ordering would force `Translation_Service` to translate a list of sentences and re-split the result, which complicates the contract and creates a sentence-count drift problem. To avoid that, this spec re-orders the pipeline to **scrape → translate → parse → consume**: the scraper now returns raw `submission.selftext` as a string in `thread_post`, the orchestrator (`main.py::main`) calls `Translation_Service` on the raw string, and only then calls `posttextparser` (when `storymodemethod = 1`) so spaCy segmentation runs over the language the viewer will actually see. `Translation_Service` is therefore "raw text in, raw text out" for both storymode methods and never imports `posttextparser`.

`utils/posttextparser.py` itself is unchanged in this spec: it stays where it is, it stays English-only (spaCy's `en_core_web_sm`), and no per-language model download is added here. The English-only tokenizer is a known quality limitation when `target_lang` is non-English; treating it properly is a separate concern from this ordering change. See Open Questions.

This spec is independent of the in-flight `card-rendering-refactor` spec and SHALL NOT modify any file in that spec's scope (see Requirement 12). Translation completes before any rendering runs, so the two changes commute and can land in either order.

## Glossary

- **Translation_Service**: The new module that translates `Reddit_Content` fields into a target language using Anthropic Claude. The single public entry point for the rest of the pipeline.
- **Anthropic_Client**: The thin wrapper around the official `anthropic` Python SDK used by `Translation_Service`.
- **Reddit_Content**: The dictionary returned by `reddit/subreddit.py::get_subreddit_threads`, with fields including `thread_title`, `thread_post`, `comments[*].comment_body`, `thread_id`, `thread_url`, `permalink`, `author`, `avatar_url`, `is_nsfw`, `subreddit`. After this spec, `thread_post` is always a raw string at the moment `Reddit_Content` leaves the scraper.
- **Translatable_Field**: A `Reddit_Content` field whose value is human-readable prose intended for the viewer (`thread_title`, `thread_post`, each `comments[*].comment_body`).
- **Structural_Field**: A `Reddit_Content` field that identifies, locates, or quantifies the post and is never translated (`thread_id`, `thread_url`, `permalink`, `author`, `avatar_url`, `is_nsfw`, `subreddit`, `comments[*].comment_id`, `comments[*].comment_url`).
- **Target_Language**: The ISO 639-1 (or BCP-47) language code the post is translated into, configured in `[translation] target_lang`.
- **Source_Language**: The detected or declared language of the original post text.
- **Translation_Provider**: The configured backend used for translation. Valid values are `anthropic` (this spec) and `none` (no-op pass-through). The legacy `translators`/Google path is removed (see Requirement 11).
- **Translation_Cache**: An optional on-disk key-value store keyed by `(thread_id, content_hash, target_lang, model_id)` that returns previously-translated text without re-calling Anthropic.
- **Translation_Failure_Policy**: The configured behavior when the Anthropic API returns an error, times out, or is rate-limited. Valid values are `skip` (use original text and warn) and `fail` (raise and abort the run).
- **Pipeline**: The existing video-generation pipeline driven by `main.py::main`.
- **Pipeline_Stage_Order**: The required execution order of pipeline stages within a single run: `get_subreddit_threads` → `Translation_Service` → `posttextparser` (only when `storymodemethod = 1`) → `save_text_to_mp3` / `get_screenshots_of_reddit_posts` / `make_final_video`.
- **Scraper**: The set of functions that build `Reddit_Content` from Reddit's public JSON API: `reddit/subreddit.py::get_subreddit_threads` and the equivalent path in `batch.py`.
- **Orchestrator**: The entry-point function that drives a single video run end-to-end: `main.py::main` (and its `batch.py` counterpart, where applicable). The Orchestrator owns Pipeline_Stage_Order.

## Requirements

### Requirement 1: Centralized Translation Step

**User Story:** As a maintainer, I want translation to happen once at a single integration point, so that downstream modules see consistent translated text without each calling a translator.

#### Acceptance Criteria

1. THE Orchestrator SHALL invoke the Translation_Service exactly once per video run, after `get_subreddit_threads` has returned a `Reddit_Content` dictionary, and before `posttextparser`, `save_text_to_mp3`, `get_screenshots_of_reddit_posts`, and `make_final_video` are called. The "exactly once" constraint applies only after `get_subreddit_threads` has completed; if `get_subreddit_threads` short-circuits the run (e.g., "already done"), the Translation_Service SHALL NOT be invoked.
2. THE Translation_Service SHALL accept a `Reddit_Content` dictionary and return a `Reddit_Content` dictionary with the same keys and the same Structural_Field values.
3. WHERE the Target_Language key is unset (the configuration key is missing or has been assigned `None`), THE Translation_Service SHALL return the input `Reddit_Content` unchanged.
4. WHERE the Target_Language is the empty string, THE Translation_Service SHALL return the input `Reddit_Content` unchanged.
5. THE Translation_Service SHALL be the only call site in the codebase that invokes the Anthropic SDK for post-content translation.
6. WHEN translation is performed for a Translatable_Field (i.e., `provider` is `anthropic`, Target_Language is non-empty, Source_Language differs from Target_Language, and no cache hit applies), THE Translation_Service SHALL perform the translation by invoking the Anthropic_Client. THE Translation_Service SHALL NOT delegate the underlying SDK call to any other module or component.

### Requirement 2: Anthropic SDK Integration

**User Story:** As an operator, I want translation to use the official Anthropic Python library, so that I get a supported, documented client with proper retries and error types.

#### Acceptance Criteria

1. THE Anthropic_Client SHALL use the official `anthropic` Python package as its only HTTP backend for Claude calls.
2. THE Anthropic_Client SHALL send each translation request with `temperature = 0` to make repeated translations of the same input deterministic within a model version.
3. IF the Anthropic_Client is configured (via code or environment) with a `temperature` value other than `0`, THEN THE Anthropic_Client SHALL reject the configuration at startup with an error naming the offending value, rather than silently overriding it.
4. THE Anthropic_Client SHALL pass the configured Claude model identifier with each request.
5. THE Anthropic_Client SHALL include a system prompt that instructs Claude to preserve the original casual Reddit register, slang, and profanity, and to return only the translated text without commentary or surrounding markup.
6. THE Anthropic_Client SHALL pass the configured maximum output token budget with each request.

### Requirement 3: Configuration Schema

**User Story:** As an operator, I want translation settings in `config.toml`, so that I can configure provider, target language, model, and credentials without editing code.

#### Acceptance Criteria

1. THE Pipeline SHALL read translation configuration from a new `[translation]` section in `config.toml` and `utils/.config.template.toml`.
2. THE `[translation]` section SHALL always expose the following fields with default values regardless of whether the section is explicitly present in `config.toml`: `provider` (string, default `none`, options `none` and `anthropic`), `target_lang` (string, default empty), `failure_policy` (string, default `skip`, options `skip` and `fail`), and `cache_enabled` (bool, default `true`).
3. THE `[translation.anthropic]` subsection SHALL always expose the following fields with default values regardless of whether the subsection is explicitly present in `config.toml`: `model` (string, default `claude-3-5-sonnet-latest`), `max_output_tokens` (int, default `4096`), and `api_key` (string, default empty).
4. WHEN the `ANTHROPIC_API_KEY` environment variable is set, THE Anthropic_Client SHALL use the environment variable value as the API key in preference to `[translation.anthropic].api_key`.
5. WHEN both `ANTHROPIC_API_KEY` and `[translation.anthropic].api_key` are unset and `provider` is `anthropic`, THE Translation_Service SHALL defer the error until translation is actually attempted: at the first invocation that would call the Anthropic_Client, THE Translation_Service SHALL apply the configured `failure_policy` with an error that names both configuration sources. Startup itself SHALL NOT abort solely because the API key is missing.
6. THE `[translation]` section SHALL be documented in `utils/.config.template.toml` with explanations and example values for each field.

### Requirement 4: Translatable Field Coverage

**User Story:** As a viewer, I want every visible piece of text in the video translated, so that titles, body text, comments, and on-screen UI strings all read in the target language.

#### Acceptance Criteria

1. WHEN `provider` is `anthropic` and Target_Language is non-empty, THE Translation_Service SHALL translate `thread_title` from Source_Language to Target_Language.
2. WHEN the post is in storymode and `storymodemethod` is `0`, THE Translation_Service SHALL translate the raw `thread_post` string to Target_Language and SHALL return a string in `thread_post`.
3. WHEN the post is in storymode and `storymodemethod` is `1`, THE Translation_Service SHALL translate the raw `thread_post` string to Target_Language and SHALL return a string in `thread_post`. Sentence segmentation of the translated string is the Orchestrator's responsibility (see Requirement 9) and is not performed inside the Translation_Service.
4. WHEN `provider` is `anthropic` and Target_Language is non-empty, THE Translation_Service SHALL translate each `comments[*].comment_body` to Target_Language regardless of whether `storymode` is enabled.
5. THE Translation_Service SHALL NOT modify any Structural_Field listed in the Glossary.
6. THE Translation_Service SHALL treat `thread_post` as a string in both storymode methods and SHALL NOT branch on `storymodemethod` to choose between list handling and string handling.
7. IF `Reddit_Content["thread_post"]` is not a `str` instance when `Translation_Service` reads it (for example, if it has been pre-parsed into a list), THEN `Translation_Service` SHALL raise a `TypeError` naming the field and the actual type, rather than attempting to coerce or join the value.

### Requirement 5: Source Language Handling

**User Story:** As an operator, I want translation skipped when the source post is already in the target language, so that I don't pay for and wait on no-op API calls.

#### Acceptance Criteria

1. THE Translation_Service SHALL accept the joined post text (title + body or title + comments) and ask Anthropic to determine whether the dominant Source_Language matches the configured Target_Language.
2. IF the detected Source_Language matches the Target_Language, THEN THE Translation_Service SHALL return the input `Reddit_Content` with all Translatable_Field values unchanged and SHALL log that translation was skipped.
3. THE Translation_Service SHALL perform Source_Language detection in a single Anthropic call per `Reddit_Content`, not once per Translatable_Field.
4. WHERE the operator sets `[translation] force_translate = true`, THE Translation_Service SHALL skip Source_Language detection entirely and SHALL translate every Translatable_Field.

### Requirement 6: Failure Handling

**User Story:** As an operator, I want a clear policy for what happens when Anthropic is down or rate-limited, so that an outage does not silently corrupt my video output.

#### Acceptance Criteria

1. IF the Anthropic_Client raises an error during translation AND `failure_policy` is `skip`, THEN THE Translation_Service SHALL return the input `Reddit_Content` with all Translatable_Field values unchanged, log a warning that names the failing field and the underlying error class, and SHALL NOT raise.
2. IF the Anthropic_Client raises an error during translation AND `failure_policy` is `fail`, THEN THE Translation_Service SHALL re-raise the error with a message that names the failing field and the underlying error class.
3. IF the Anthropic_Client returns a response that does not contain text, THEN THE Translation_Service SHALL treat the response as a translation error and apply the configured `failure_policy`.
4. THE Translation_Service SHALL preserve every key in the input `Reddit_Content` after any translation-layer failure, regardless of `failure_policy` outcome. THE Translation_Service is permitted to fail key preservation under catastrophic system-level errors (e.g., `MemoryError`, interpreter shutdown, OS-level I/O errors during in-memory copy); under such conditions THE Translation_Service is exempt from the key-preservation guarantee, and these exceptions SHALL be allowed to propagate unchanged and SHALL be documented in the module docstring.

### Requirement 7: Translation Cache

**User Story:** As an operator running the bot many times in development, I want repeated translations of the same post to hit a cache, so that I don't re-pay for identical Anthropic calls.

#### Acceptance Criteria

1. WHERE `cache_enabled` is `true`, THE Translation_Cache SHALL store translated Translatable_Field values keyed by `thread_id`, the SHA-256 hash of the original field text, the Target_Language, and the configured Claude model identifier.
2. WHEN a Translatable_Field is requested for translation and a Translation_Cache entry exists for its key, THE Translation_Service SHALL return the cached translation without calling the Anthropic_Client.
3. WHERE the Translation_Service has determined within the same run that the cache contains no entry for a `(thread_id, target_lang, model_id)` triple, THE Translation_Service MAY skip subsequent cache reads for that triple within the same run.
4. WHEN the Anthropic_Client returns a successful translation, THE Translation_Service SHALL attempt to write the result to the Translation_Cache before returning.
5. IF the Translation_Cache write fails after a successful Anthropic translation, THEN THE Translation_Service SHALL log a warning naming the field and the underlying error class and SHALL return the translated value to the caller.
6. WHERE `cache_enabled` is `false`, THE Translation_Service SHALL NOT read from or write to any Translation_Cache file, regardless of whether existing cache files are present on disk.
7. THE Translation_Cache SHALL be stored under `assets/temp/{thread_id}/translation_cache.json` so cleanup deletes it alongside other per-thread artifacts.

### Requirement 8: Determinism and Idempotence Properties

**User Story:** As a developer, I want Translation_Service to behave predictably, so that I can write property tests that catch regressions.

#### Acceptance Criteria

1. THE Translation_Service SHALL produce the same output `Reddit_Content` when invoked twice on the same input `Reddit_Content` with the same configuration and the same Anthropic model version (determinism property).
2. THE Translation_Service SHALL produce the same output `Reddit_Content` when invoked on its own previous output with the same Target_Language (idempotence property).
3. THE Translation_Service SHALL preserve every Structural_Field value byte-for-byte from input to output regardless of Target_Language, `failure_policy`, or cache state (round-trip property on structural fields).
4. FOR ALL inputs where the detected Source_Language equals the Target_Language, THE Translation_Service SHALL produce an output whose Translatable_Field values equal the input Translatable_Field values (no-op property). For `thread_post` this property is evaluated against the raw string returned by the Scraper, not against a list of sentences.

### Requirement 9: Storymode Sentence Segmentation Runs After Translation

**User Story:** As a viewer of a story-mode video, I want sentence segmentation to run over the translated text, so that spaCy splits the language the video actually displays.

#### Acceptance Criteria

1. WHEN `storymode = true` AND `storymodemethod = 1` AND the Translation_Service has been invoked and returned, THE Orchestrator SHALL call `utils.posttextparser.posttextparser` on `Reddit_Content["thread_post"]` after the Translation_Service has returned and before any TTS, screenshot, or final-video stage runs.
2. IF `storymode = true` AND `storymodemethod = 1` AND the Translation_Service has not been invoked for the current run (for example, because earlier stages short-circuited), THEN THE Orchestrator SHALL NOT call `utils.posttextparser.posttextparser`.
3. WHEN `storymode = true` AND `storymodemethod = 0`, THE Orchestrator SHALL NOT call `utils.posttextparser.posttextparser`, and `Reddit_Content["thread_post"]` SHALL remain a string for downstream consumers.
4. THE Translation_Service SHALL NOT import or call `utils.posttextparser.posttextparser`.

### Requirement 10: Per-Field Adapter Removal at Existing Call Sites

**User Story:** As a maintainer, I want the four scattered `translators.translate_text(...)` call sites collapsed once translation is centralized, so that the codebase has one translation path.

#### Acceptance Criteria

1. WHEN the Translation_Service has run on `Reddit_Content`, THE Pipeline SHALL pass the translated `Reddit_Content` to `posttextparser` (when `storymodemethod = 1`), `save_text_to_mp3`, `get_screenshots_of_reddit_posts`, and `make_final_video` without further translator calls.
2. THE module `TTS/engine_wrapper.py` SHALL NOT import or call `translators.translate_text` for post content after this feature lands.
3. THE module `video_creation/screenshot_downloader.py` SHALL NOT import or call `translators.translate_text` for post content after this feature lands.
4. THE module `video_creation/final_video.py` SHALL NOT import or call `translators.translate_text` for post content after this feature lands.
5. THE module `TTS/GTTS.py` SHALL select the gTTS voice locale by preferring `[translation] target_lang` when it resolves to a non-empty value, falling back to `[reddit.thread] post_lang` when `[translation] target_lang` is empty.
6. IF neither `[reddit.thread] post_lang` nor `[translation] target_lang` resolves to a non-empty value when `TTS/GTTS.py` runs, THEN `TTS/GTTS.py` SHALL fall back to its existing default locale and SHALL log a warning that no translation locale was available, rather than raising an unhandled error.
7. THE module `reddit/subreddit.py` SHALL NOT import or call `utils.posttextparser.posttextparser` after this feature lands.
8. THE module `batch.py` SHALL NOT import or call `utils.posttextparser.posttextparser` after this feature lands.

### Requirement 11: Provider Selection

**User Story:** As an operator, I want to disable translation cleanly during development, so that I can run the bot without Anthropic credentials.

#### Acceptance Criteria

1. WHEN `[translation] provider` is `none`, THE Translation_Service SHALL return its input `Reddit_Content` unchanged regardless of `target_lang`.
2. WHEN `[translation] provider` is `anthropic`, THE Translation_Service SHALL route translation through the Anthropic_Client.
3. IF `[translation] provider` is set to a value other than `none` or `anthropic`, THEN THE Pipeline SHALL log an error naming the offending value and listing the supported providers, SHALL set the in-memory effective provider to `none` for the remainder of the run, and SHALL continue running with translation disabled rather than aborting at startup.

### Requirement 12: Concurrency with `card-rendering-refactor`

**User Story:** As a maintainer, I want this spec and the card-rendering-refactor spec to be mergeable in either order, so that work on the two specs does not block each other.

#### Acceptance Criteria

1. THE Translation_Service SHALL NOT modify `utils/card.py`.
2. THE Translation_Service SHALL NOT modify `test_transition.py` or any file under a future `video_creation/render/` package owned by the card-rendering-refactor spec.
3. THE Translation_Service SHALL NOT modify the per-frame composition logic, the timing engine, or the style-registry surface owned by the card-rendering-refactor spec.
4. THE only edit this spec SHALL make to `video_creation/final_video.py` once the `translators.translate_text` removal in Requirement 10.4 is complete is that single removal, and THE Translation_Service SHALL NOT introduce any other change to `video_creation/final_video.py` after that removal lands; any further coordination with that file SHALL flow through the translated `Reddit_Content`. WHILE the Requirement 10.4 removal is in progress and not yet complete, this spec MAY make additional edits to `video_creation/final_video.py` strictly in service of completing that removal.
5. THE scraper-decoupling and Orchestrator-ordering changes introduced by Requirements 15 and 16 SHALL be confined to `reddit/subreddit.py`, `batch.py`, `main.py`, and the new translation modules. Specifically, those changes SHALL NOT touch `utils/card.py`, `test_transition.py`, or any file under a future `video_creation/render/` package, and SHALL NOT touch `video_creation/final_video.py` beyond the `translators.translate_text` removal already covered by Requirement 10.4.

### Requirement 13: Observability

**User Story:** As an operator, I want to see what translation did during a run, so that I can diagnose cost, cache, and quality issues.

#### Acceptance Criteria

1. THE Translation_Service SHALL log, at the start of each run, the configured `provider`, `target_lang`, `model`, `failure_policy`, and `cache_enabled` values.
2. THE Translation_Service SHALL log, for each Anthropic call, the field name being translated and the input and output character counts.
3. THE Translation_Service SHALL log, for each cache hit, the field name and that the result came from the cache.
4. THE Translation_Service SHALL log, at the end of each run, the total number of Anthropic calls made and the total number of input characters submitted.

### Requirement 14: Sanitization Compatibility

**User Story:** As a developer of the TTS pipeline, I want translated text to remain compatible with the existing sanitizer, so that downstream `sanitize_text` and `process_text` continue to work without changes.

#### Acceptance Criteria

1. THE Translation_Service SHALL apply `utils.voice.sanitize_text` to every Translatable_Field value it returns.
2. WHEN the sanitizer collapses a translated Translatable_Field value to an empty string or whitespace, THE Translation_Service SHALL substitute the original (untranslated) Translatable_Field value verbatim and log a warning naming the field; the substituted original value is preserved as-is even if it contains formatting elements that would otherwise be prohibited by criterion 3.
3. THE Translation_Service SHALL NOT introduce HTML tags, markdown fences, or surrounding quotation marks into Translatable_Field values that the original text did not contain, except (a) when criterion 2 substitutes the original value back in, or (b) when the sanitizer has collapsed the translated value AND the substitution itself fails, in which case THE Translation_Service MAY return any non-collapsed string (including one containing formatting) so the pipeline can continue.

### Requirement 15: Scraper Decoupling

**User Story:** As a maintainer, I want the Reddit scraper to return raw post text, so that translation, sentence segmentation, and other downstream stages can run in any order the Orchestrator chooses.

#### Acceptance Criteria

1. THE function `reddit/subreddit.py::get_subreddit_threads` SHALL set `Reddit_Content["thread_post"]` to `submission.selftext` as a Python `str` whenever `storymode` is enabled, regardless of the value of `storymodemethod`.
2. THE function `reddit/subreddit.py::get_subreddit_threads` SHALL NOT call `utils.posttextparser.posttextparser` on `submission.selftext` or on any other `Reddit_Content` field.
3. THE module `reddit/subreddit.py` SHALL remove the import of `utils.posttextparser.posttextparser`.
4. THE module `batch.py` SHALL set `Reddit_Content["thread_post"]` to `submission.selftext` as a `str` regardless of `storymodemethod`, and `utils.posttextparser.posttextparser` SHALL NOT be called or imported by `batch.py`. This requirement applies regardless of whether `batch.py` currently contains a parallel scraper path; if no such path exists today, this requirement is satisfied as long as `batch.py` does not import or call `utils.posttextparser.posttextparser` and does not assign a parsed list to `Reddit_Content["thread_post"]`.
5. THE structural shape of `Reddit_Content` returned by the Scraper SHALL otherwise be byte-for-byte identical to the pre-change shape: same keys, same Structural_Field values, same comment list shape.

### Requirement 16: Orchestrator-Owned Pipeline Stage Ordering

**User Story:** As a maintainer, I want the entry-point function to own the order in which scrape, translate, parse, and consume stages run, so that the order is explicit, testable, and changeable in one place.

#### Acceptance Criteria

1. THE Orchestrator SHALL invoke pipeline stages in the order defined by Pipeline_Stage_Order: `get_subreddit_threads` → `Translation_Service` → `posttextparser` (only when `storymodemethod = 1` AND the Translation_Service has been invoked) → `save_text_to_mp3` / `get_screenshots_of_reddit_posts` / `make_final_video`. THE Orchestrator SHALL skip a stage when its preconditions are not met (for example, skip `posttextparser` when `storymodemethod ≠ 1` or when the Translation_Service was never invoked, or skip the entire run when an earlier stage signals "already done"); when a stage is skipped, THE Orchestrator SHALL preserve the relative order of all remaining stages.
2. THE Orchestrator SHALL call `Translation_Service` with the raw `Reddit_Content` dictionary returned by `get_subreddit_threads` and SHALL pass the translated `Reddit_Content` to every subsequent stage.
3. WHEN `storymodemethod = 1` AND `Translation_Service` has been invoked and returned for the current run, THE Orchestrator SHALL replace `Reddit_Content["thread_post"]` with the result of `utils.posttextparser.posttextparser(Reddit_Content["thread_post"])` after `Translation_Service` returns and before any consumer stage reads `thread_post`.
4. WHEN `storymodemethod = 0`, THE Orchestrator SHALL leave `Reddit_Content["thread_post"]` as the string returned by `Translation_Service` and SHALL NOT call `utils.posttextparser.posttextparser`.
5. THE Orchestrator SHALL own the overall stage sequence defined by Pipeline_Stage_Order in `main.py::main` (and its `batch.py` counterpart, where applicable). THE Orchestrator MAY delegate sub-sequences to helper functions (for example, a helper that wraps the post-translation `posttextparser` call) provided the helper does not re-order, skip, or insert stages relative to Pipeline_Stage_Order. THE Scraper, the Translation_Service, and consumer stages SHALL NOT control or alter the overall stage sequence.

## Open Questions

1. `utils/posttextparser.py` loads spaCy's `en_core_web_sm` model unconditionally. After this re-ordering, the parser runs over translated (potentially non-English) text when `storymodemethod = 1` and `target_lang` is non-English. The English tokenizer will still produce sentence splits, but segmentation quality on non-Latin scripts is degraded. A follow-up spec should decide whether to (a) load a per-language spaCy model based on `target_lang`, (b) fall back to a regex-based sentence splitter for non-English targets, or (c) document the limitation and accept it. This spec does not add a hard requirement for per-language model selection.
