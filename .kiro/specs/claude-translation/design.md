# Design Document

## Overview

This feature replaces the four scattered `translators.translate_text(...)` invocations with a single `Translation_Service` that runs once per video on the `Reddit_Content` dictionary returned by `get_subreddit_threads`. The service uses the official `anthropic` Python SDK with `temperature = 0` to translate `thread_title`, `thread_post`, and every `comments[*].comment_body` into the configured target language while preserving Reddit's casual register, slang, and profanity.

The change also re-orders the pipeline. Today the scraper calls `posttextparser` on `submission.selftext` whenever `storymodemethod = 1`, which forces sentence segmentation to run before translation and would force the translator to operate on a list of sentences. After this feature lands, the scraper always returns raw `submission.selftext` as a string in `thread_post`, the orchestrator (`main.py::main`, `batch.py::make_one_video`) calls `Translation_Service` on that raw string, and only then calls `posttextparser` (when `storymodemethod = 1`) so spaCy segmentation runs on the language the viewer will see. `Translation_Service` is "raw text in, raw text out" for both storymode methods and never imports `posttextparser`.

`utils/posttextparser.py` itself is untouched. It stays English-only; the per-language tokenizer question is deferred to a follow-up spec (see Open Questions in requirements.md).

The four legacy `translators.translate_text` call sites are removed in a single migration phase, and `TTS/GTTS.py` is updated to prefer `[translation] target_lang` for its locale, falling back to `[reddit.thread] post_lang` for backward compatibility.

This spec is independent of the in-flight `card-rendering-refactor` spec. The only edit shared between them is the single-line removal of `translators.translate_text` from `video_creation/final_video.py::name_normalize` (Requirement 10.4); no other file owned by the rendering refactor (`utils/card.py`, `test_transition.py`, future `video_creation/render/`) is touched here.

### Goals

- One module owns translation; downstream consumers see already-translated `Reddit_Content` (Req 1, 10).
- Translation uses the official Anthropic SDK with `temperature = 0` for determinism within a model version (Req 2, 8.1).
- Source-language detection is one Anthropic call per `Reddit_Content`, not per field (Req 5).
- A persistent on-disk cache keyed by `(thread_id, sha256(text), target_lang, model_id)` makes repeated runs free (Req 7).
- Failure policy is configurable: `skip` warns and returns originals; `fail` re-raises (Req 6).
- The orchestrator owns stage order; the scraper returns raw text only (Req 9, 15, 16).
- Universal properties (determinism, idempotence, structural-field round-trip, source==target no-op) hold across all valid inputs (Req 8).

### Non-Goals

- Per-language spaCy model selection. `posttextparser` stays English-only (deferred per Open Questions).
- Streaming translation, batching multiple posts in one Anthropic call, or background pre-translation.
- Translating UI strings outside `Reddit_Content` (channel names, watermark, button labels).
- Translating audio, image text overlays, or anything not in `Reddit_Content`.
- Changing the structural shape of `Reddit_Content` returned by the scraper beyond the `thread_post`-as-`str` invariant (Req 15.5).
- Touching the card-rendering-refactor scope (`utils/card.py`, `test_transition.py`, `video_creation/render/`, or `final_video.py` beyond the single `translators.translate_text` removal).

## Architecture

### Package Layout

A new package `utils/translation/` owns this feature. Placing it under `utils/` matches the existing convention (`utils/voice.py`, `utils/posttextparser.py`, `utils/cleanup.py`) and keeps it close to the sibling modules it cooperates with (`sanitize_text`, `posttextparser`).

```
utils/
  translation/
    __init__.py          # public API: Translation_Service, TranslationConfig, errors
    service.py           # Translation_Service: orchestrates detect + translate + cache + sanitize
    anthropic_client.py  # Anthropic_Client: thin wrapper over the official SDK
    cache.py             # Translation_Cache: per-thread JSON read/write with atomic writes
    config.py            # TranslationConfig dataclass + parsing/validation from settings.config
    errors.py            # TranslationError hierarchy
    prompts.py           # System and user prompt templates for detect + translate
```

`utils/posttextparser.py` is unchanged. `reddit/subreddit.py`, `batch.py`, `main.py`, `TTS/engine_wrapper.py`, `TTS/GTTS.py`, `video_creation/screenshot_downloader.py`, and `video_creation/final_video.py` are edited but no new files are added outside `utils/translation/`.

### Boundaries

- **Pure (no SDK / I/O)**: `prompts.py`, the public dataclass surface in `config.py`, the `errors.py` hierarchy, the key derivation in `cache.py`.
- **SDK only**: `anthropic_client.py` is the only module that imports `anthropic`.
- **I/O only**: `cache.py` is the only module that reads or writes `assets/temp/{thread_id}/translation_cache.json`.
- **Orchestration**: `service.py` composes the detector, translator, cache, and sanitizer. It does not import the Anthropic SDK directly — it calls `Anthropic_Client` — and it never touches `posttextparser` (Req 9.4).

The orchestrator (`main.py`, `batch.py`) imports only the public surface in `utils.translation.__init__`. Downstream consumers (`save_text_to_mp3`, `get_screenshots_of_reddit_posts`, `make_final_video`) do not import from `utils.translation` at all — they receive the already-translated `Reddit_Content` and never know translation happened.

### High-Level Flow

```mermaid
flowchart TD
    A[main.py::main] --> B[get_subreddit_threads&#40;POST_ID&#41;]
    B --> C{provider == anthropic AND target_lang non-empty?}
    C -->|no| C2[Translation_Service no-op pass-through]
    C -->|yes| D[Translation_Service.translate&#40;reddit_content, config&#41;]
    D --> E{force_translate?}
    E -->|yes| H[translate every Translatable_Field]
    E -->|no| F[Anthropic_Client.detect_source_language&#40;sample&#41;]
    F --> G{source == target?}
    G -->|yes| G2[return reddit_content unchanged + log skip]
    G -->|no| H
    H --> I{Translation_Cache hit?}
    I -->|yes| J[use cached translation]
    I -->|no| K[Anthropic_Client.translate&#40;text&#41;]
    K --> L[Translation_Cache.write]
    J --> M[sanitize_text]
    L --> M
    M --> N[translated Reddit_Content]
    C2 --> O[reddit_content]
    G2 --> O
    N --> O
    O --> P{storymodemethod == 1?}
    P -->|yes| Q[posttextparser&#40;reddit_content[thread_post]&#41;]
    P -->|no| R[downstream consumers]
    Q --> R
    R --> S[save_text_to_mp3 / get_screenshots / make_final_video]
```

### Pipeline Stage Order (Req 16)

The orchestrator owns the sequence. The current sequence is:

```
get_subreddit_threads -> save_text_to_mp3 -> get_screenshots_of_reddit_posts -> make_final_video
```

After this spec lands:

```
get_subreddit_threads
    -> Translation_Service.translate (always; no-op when provider=none or target_lang empty)
    -> posttextparser (only when storymodemethod == 1)
    -> save_text_to_mp3
    -> get_screenshots_of_reddit_posts
    -> make_final_video
```

`posttextparser` is invoked by `main.py::main` (and `batch.py::make_one_video`), not inside `get_subreddit_threads`, not inside `Translation_Service`, and not inside any consumer stage.

## Components and Interfaces

### `Translation_Service` (service.py)

Public, stateless surface. One method.

```python
# utils/translation/service.py
"""Translation_Service public API.

Documented exemptions to the key-preservation guarantee in Req 6.4:
catastrophic system-level errors (MemoryError, KeyboardInterrupt during
in-memory copy, OS-level I/O errors raised by the cache write path) are
allowed to propagate unchanged and are NOT caught by failure_policy.
"""
from __future__ import annotations
from typing import Any

from utils.translation.config import TranslationConfig
from utils.translation.errors import TranslationError


class Translation_Service:
    """Translates a Reddit_Content dict into config.target_lang.

    Stateless: one instance per run is fine, but the class holds no per-run
    mutable state outside the cache read-miss bloom set (see cache.py).
    """

    def __init__(self, config: TranslationConfig) -> None: ...

    def translate(self, reddit_content: dict[str, Any]) -> dict[str, Any]:
        """Return a new Reddit_Content dict with Translatable_Field values
        translated into config.target_lang.

        Inputs:
            reddit_content: dict produced by reddit/subreddit.py::get_subreddit_threads.
                Must contain string values for thread_title and thread_post,
                and a list of dicts under "comments" each with "comment_body".

        Outputs:
            dict with the same keys, same Structural_Field values byte-for-byte,
            and translated Translatable_Field values.

        Behavior:
            - If config.provider == "none", returns input unchanged (Req 11.1).
            - If config.target_lang is None or "", returns input unchanged (Req 1.3, 1.4).
            - If config.force_translate is False and detected source ==
              target, returns input unchanged with a log line (Req 5.2, 5.4).
            - Otherwise translates each Translatable_Field, consulting the
              cache before and writing to the cache after each Anthropic call.
            - Sanitizes every translated value via utils.voice.sanitize_text;
              if the sanitizer collapses the result to empty/whitespace,
              substitutes the original value back in and warns (Req 14.2).

        Errors:
            - Raises TypeError if reddit_content["thread_post"] is not a str
              (Req 4.7). Message names the field and the actual type.
            - Raises TranslationConfigError on first translation attempt if
              provider == "anthropic" and no API key resolves (Req 3.5).
            - Under config.failure_policy == "fail":
                propagates TranslationError subclasses raised by Anthropic_Client.
            - Under config.failure_policy == "skip":
                catches TranslationError, logs a warning naming the field and
                the underlying error class, and substitutes the original
                Translatable_Field value (Req 6.1, 6.4).
            - Catastrophic system-level errors (MemoryError, KeyboardInterrupt,
              OSError raised before any field has been substituted) propagate
              unchanged (Req 6.4 exemption clause).
        """
```

The implementation is straightforward composition:

```python
def translate(self, reddit_content):
    # Type discipline (Req 4.7)
    post = reddit_content.get("thread_post")
    if post is not None and not isinstance(post, str):
        raise TypeError(
            f"Translation_Service expected thread_post to be str, "
            f"got {type(post).__name__}"
        )

    # Provider gating (Req 11.1, 1.3, 1.4)
    if self.config.effective_provider == "none":
        return reddit_content
    if not self.config.target_lang:
        return reddit_content

    # Lazy API key check (Req 3.5)
    if not self.config.has_api_key():
        return self._apply_failure_policy(
            reddit_content, field="<startup>",
            error=TranslationConfigError(
                "No Anthropic API key found. Set ANTHROPIC_API_KEY or "
                "[translation.anthropic].api_key."
            ),
        )

    # Source-language detection (Req 5)
    if not self.config.force_translate:
        sample = self._build_detection_sample(reddit_content)
        try:
            src = self._client.detect_source_language(sample)
        except TranslationError as e:
            return self._apply_failure_policy(reddit_content, field="<detect>", error=e)
        if self._lang_matches(src, self.config.target_lang):
            print_substep(
                f"Source language ({src}) matches target ({self.config.target_lang}); "
                f"skipping translation."
            )
            return reddit_content

    # Translate each Translatable_Field (Req 4)
    out = dict(reddit_content)
    out["thread_title"] = self._translate_field("thread_title", reddit_content["thread_title"])
    if isinstance(reddit_content.get("thread_post"), str):
        out["thread_post"] = self._translate_field("thread_post", reddit_content["thread_post"])
    out["comments"] = [
        {**c, "comment_body": self._translate_field(
            f"comments[{i}].comment_body", c["comment_body"]
        )}
        for i, c in enumerate(reddit_content.get("comments", []))
    ]
    self._log_run_summary()
    return out
```

`_translate_field` is the cache + Anthropic + sanitize + failure-policy unit:

```python
def _translate_field(self, field_name: str, text: str) -> str:
    # Cache read (Req 7.2)
    if self.config.cache_enabled:
        cached = self._cache.get(
            thread_id=self._thread_id,
            text=text,
            target_lang=self.config.target_lang,
            model_id=self.config.model,
        )
        if cached is not None:
            print_substep(f"[cache hit] {field_name}")
            self._stats.cache_hits += 1
            return self._sanitize_or_fallback(field_name, cached, text)

    # Anthropic call (Req 6.1, 6.2)
    try:
        translated = self._client.translate(text, target_lang=self.config.target_lang)
    except TranslationError as e:
        return self._apply_field_failure_policy(field_name, text, e)

    # Cache write (Req 7.4, 7.5)
    if self.config.cache_enabled:
        try:
            self._cache.put(
                thread_id=self._thread_id,
                text=text,
                target_lang=self.config.target_lang,
                model_id=self.config.model,
                translation=translated,
            )
        except OSError as e:
            print_substep(
                f"[warn] cache write failed for {field_name}: "
                f"{type(e).__name__}: {e}",
                style="yellow",
            )

    self._stats.calls += 1
    self._stats.input_chars += len(text)
    print_substep(f"[translated] {field_name}: {len(text)} -> {len(translated)} chars")
    return self._sanitize_or_fallback(field_name, translated, text)
```

`_sanitize_or_fallback` applies `utils.voice.sanitize_text` and substitutes the original on collapse (Req 14.1, 14.2). `_apply_field_failure_policy` consults `config.failure_policy` and either re-raises with a wrapped message (Req 6.2) or returns the original text (Req 6.1, 6.4).

### `Anthropic_Client` (anthropic_client.py)

Thin wrapper over the official SDK. Two methods.

```python
# utils/translation/anthropic_client.py
from __future__ import annotations
from typing import TYPE_CHECKING

from utils.translation.errors import (
    TranslationAPIError, TranslationAuthError, TranslationEmptyResponseError,
    TranslationRateLimitError, TranslationTimeoutError,
)
from utils.translation.prompts import (
    SYSTEM_PROMPT_DETECT, SYSTEM_PROMPT_TRANSLATE,
    user_prompt_detect, user_prompt_translate,
)

if TYPE_CHECKING:
    import anthropic


class Anthropic_Client:
    """Thin wrapper around the anthropic Python SDK.

    Owns:
        - SDK client construction (api_key, base URL).
        - Request building (system prompt, max_output_tokens, model, temperature=0).
        - Response parsing (extract first text block; treat empty as failure).
        - SDK-exception-to-TranslationError mapping.

    Does NOT own:
        - failure_policy decisions (lives in Translation_Service).
        - Caching (lives in Translation_Cache).
        - Sanitization (lives in Translation_Service via utils.voice.sanitize_text).
    """

    def __init__(
        self,
        api_key: str,
        model: str,
        max_output_tokens: int,
        temperature: float = 0.0,
    ) -> None:
        if temperature != 0.0:
            raise TranslationConfigError(
                f"Anthropic_Client requires temperature=0 for determinism; "
                f"got temperature={temperature!r}"
            )
        import anthropic
        self._sdk = anthropic
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model
        self._max_output_tokens = max_output_tokens

    def detect_source_language(self, sample: str) -> str:
        """Return a BCP-47 / ISO 639-1 tag, e.g. 'en', 'es', 'pt-BR'.

        One Anthropic call. The sample is the joined detection sample from
        Translation_Service (title + body excerpt + first N comments).
        """
        response = self._call(
            system=SYSTEM_PROMPT_DETECT,
            user=user_prompt_detect(sample),
        )
        return response.strip().lower()

    def translate(self, text: str, target_lang: str) -> str:
        """Translate text into target_lang. One Anthropic call per call."""
        response = self._call(
            system=SYSTEM_PROMPT_TRANSLATE,
            user=user_prompt_translate(text=text, target_lang=target_lang),
        )
        return response

    # ---- internals -------------------------------------------------------

    def _call(self, system: str, user: str) -> str:
        try:
            msg = self._client.messages.create(
                model=self._model,
                max_tokens=self._max_output_tokens,
                temperature=0.0,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
        except self._sdk.AuthenticationError as e:
            raise TranslationAuthError(str(e)) from e
        except self._sdk.RateLimitError as e:
            raise TranslationRateLimitError(str(e)) from e
        except self._sdk.APITimeoutError as e:
            raise TranslationTimeoutError(str(e)) from e
        except self._sdk.APIError as e:
            raise TranslationAPIError(str(e)) from e

        text = self._extract_text(msg)
        if not text or not text.strip():
            raise TranslationEmptyResponseError(
                f"Anthropic response contained no text (model={self._model})"
            )
        return text

    @staticmethod
    def _extract_text(msg) -> str:
        """Extract the first text block from an SDK Message.

        SDK responses have msg.content as a list of ContentBlock objects;
        each has a .type ('text', 'tool_use', etc.). We only consume 'text'
        blocks and concatenate them.
        """
        out = []
        for block in getattr(msg, "content", []) or []:
            if getattr(block, "type", None) == "text":
                out.append(getattr(block, "text", "") or "")
        return "".join(out)
```

The SDK-exception-to-`TranslationError` mapping is:

| SDK exception | Mapped to | Notes |
|---|---|---|
| `anthropic.AuthenticationError` | `TranslationAuthError` | Bad/missing API key, propagates under both policies |
| `anthropic.RateLimitError` | `TranslationRateLimitError` | 429s |
| `anthropic.APITimeoutError` | `TranslationTimeoutError` | Network timeouts |
| `anthropic.APIError` | `TranslationAPIError` | 4xx/5xx other than the above |
| (custom) empty `content` | `TranslationEmptyResponseError` | Req 6.3 |

All five are subclasses of `TranslationError`. The mapping lets `Translation_Service`'s `failure_policy` operate on a single hierarchy without importing the SDK exception types.

### `Translation_Cache` (cache.py)

```python
# utils/translation/cache.py
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Optional


class Translation_Cache:
    """Per-thread JSON cache under assets/temp/{thread_id}/translation_cache.json.

    Key: SHA-256 hex digest of:
        f"{thread_id}|{sha256(text_utf8)}|{target_lang}|{model_id}"
    Value: the translated string.

    Writes are atomic (temp file + os.replace). Reads tolerate missing files
    and corrupt JSON (treated as empty cache). The cache stores no metadata
    about translation success or failure; only successful translations are
    written (Req 7.4).
    """

    _CACHE_FILENAME = "translation_cache.json"

    def __init__(self, base_dir: str = "assets/temp") -> None:
        self._base = Path(base_dir)
        # In-memory miss bloom set per (thread_id, target_lang, model_id) tuple
        # so we don't re-read the cache once we've established it's empty
        # for a given triple within a run (Req 7.3).
        self._known_empty: set[tuple[str, str, str]] = set()

    @staticmethod
    def _hash_text(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    @staticmethod
    def _cache_key(thread_id: str, text: str, target_lang: str, model_id: str) -> str:
        composite = f"{thread_id}|{Translation_Cache._hash_text(text)}|{target_lang}|{model_id}"
        return hashlib.sha256(composite.encode("utf-8")).hexdigest()

    def _path(self, thread_id: str) -> Path:
        return self._base / thread_id / self._CACHE_FILENAME

    def _read(self, thread_id: str) -> dict:
        p = self._path(thread_id)
        if not p.exists():
            return {}
        try:
            with p.open("r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}

    def get(self, *, thread_id: str, text: str, target_lang: str, model_id: str) -> Optional[str]:
        triple = (thread_id, target_lang, model_id)
        if triple in self._known_empty:
            return None
        data = self._read(thread_id)
        if not data:
            self._known_empty.add(triple)
            return None
        key = self._cache_key(thread_id, text, target_lang, model_id)
        return data.get(key)

    def put(self, *, thread_id: str, text: str, target_lang: str, model_id: str, translation: str) -> None:
        """Atomic write: read-modify-tempfile-rename.

        Raises OSError on persistent I/O failure; Translation_Service catches
        and warns (Req 7.5).
        """
        path = self._path(thread_id)
        path.parent.mkdir(parents=True, exist_ok=True)

        data = self._read(thread_id)
        key = self._cache_key(thread_id, text, target_lang, model_id)
        data[key] = translation

        # Atomic write
        fd, tmp_path = tempfile.mkstemp(prefix=".trcache.", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as tmp:
                json.dump(data, tmp, ensure_ascii=False, indent=2)
            os.replace(tmp_path, path)
        except OSError:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

        # Once we've written, the triple is no longer "known empty"
        self._known_empty.discard((thread_id, target_lang, model_id))
```

Cache file shape (`assets/temp/{thread_id}/translation_cache.json`):

```json
{
  "<sha256-of-thread_id|sha256-of-text|target_lang|model_id>": "translated text...",
  "<sha256-of-thread_id|sha256-of-different-text|target_lang|model_id>": "another translated text..."
}
```

Example:

```json
{
  "5fbc1c2a8b3a...c9f1": "Mi gato se subió al tejado anoche.",
  "9aa07e34b1d3...12b8": "no manches eso es brutal"
}
```

Storing the cache under `assets/temp/{thread_id}/` ensures the existing `cleanup(reddit_id)` path in `main.py::shutdown` removes it alongside other per-thread artifacts (Req 7.7).

The detection result is **not** persisted to disk. It is held in process memory for the duration of one `Translation_Service.translate()` call only — the next run re-detects (Req 5.3 says one call per `Reddit_Content`, not per process).

### `TranslationConfig` (config.py)

```python
# utils/translation/config.py
from __future__ import annotations
import os
from dataclasses import dataclass
from typing import Mapping

from utils.translation.errors import TranslationConfigError

VALID_PROVIDERS = ("none", "anthropic")
VALID_FAILURE_POLICIES = ("skip", "fail")
DEFAULT_MODEL = "claude-3-5-sonnet-latest"
DEFAULT_MAX_OUTPUT_TOKENS = 4096


@dataclass(frozen=True)
class TranslationConfig:
    """Parsed and validated [translation] section of config.toml.

    `provider` is the as-configured value. `effective_provider` is the value
    after Req 11.3 degradation (unknown -> "none" with a warning).
    """
    provider: str
    effective_provider: str
    target_lang: str
    failure_policy: str
    cache_enabled: bool
    force_translate: bool
    # Anthropic-specific
    model: str
    max_output_tokens: int
    api_key: str  # may be empty; resolved lazily in has_api_key()

    def has_api_key(self) -> bool:
        """Resolve API key with environment precedence (Req 3.4).

        Returns True if either ANTHROPIC_API_KEY env var is set OR
        [translation.anthropic].api_key is non-empty. Lazy: never called at
        startup, only on first translation attempt (Req 3.5).
        """
        env = os.environ.get("ANTHROPIC_API_KEY", "")
        return bool(env) or bool(self.api_key)

    def resolve_api_key(self) -> str:
        """Return the API key in effect. Env var wins (Req 3.4).
        Raises TranslationConfigError if neither is set."""
        env = os.environ.get("ANTHROPIC_API_KEY", "")
        if env:
            return env
        if self.api_key:
            return self.api_key
        raise TranslationConfigError(
            "No Anthropic API key. Set ANTHROPIC_API_KEY env var or "
            "[translation.anthropic].api_key in config.toml."
        )

    @classmethod
    def from_settings(cls, settings_config: Mapping) -> "TranslationConfig":
        """Parse settings.config and return a validated TranslationConfig.

        Defaults apply per Req 3.2 / 3.3 even when [translation] is absent.
        """
        section = settings_config.get("translation", {}) or {}
        anthropic_section = section.get("anthropic", {}) or {}

        provider_raw = section.get("provider", "none")
        if provider_raw not in VALID_PROVIDERS:
            # Req 11.3: log + degrade to "none", do not abort startup.
            from utils.console import print_substep
            print_substep(
                f"[warn] Unknown translation.provider {provider_raw!r}; "
                f"valid: {VALID_PROVIDERS}. Disabling translation for this run.",
                style="yellow",
            )
            effective = "none"
        else:
            effective = provider_raw

        failure_policy = section.get("failure_policy", "skip")
        if failure_policy not in VALID_FAILURE_POLICIES:
            raise TranslationConfigError(
                f"Invalid failure_policy {failure_policy!r}; "
                f"valid: {VALID_FAILURE_POLICIES}"
            )

        return cls(
            provider=provider_raw,
            effective_provider=effective,
            target_lang=str(section.get("target_lang", "") or ""),
            failure_policy=failure_policy,
            cache_enabled=bool(section.get("cache_enabled", True)),
            force_translate=bool(section.get("force_translate", False)),
            model=str(anthropic_section.get("model", DEFAULT_MODEL)),
            max_output_tokens=int(anthropic_section.get("max_output_tokens", DEFAULT_MAX_OUTPUT_TOKENS)),
            api_key=str(anthropic_section.get("api_key", "") or ""),
        )
```

### Configuration TOML Shape

`config.toml` and `utils/.config.template.toml` gain:

```toml
# config.toml — new section
[translation]
provider = "anthropic"          # "none" or "anthropic"; unknown -> "none" + warn
target_lang = "es"              # ISO 639-1 / BCP-47; empty disables translation
failure_policy = "skip"         # "skip" warns + uses original, "fail" re-raises
cache_enabled = true            # cache translations under assets/temp/{thread_id}/
force_translate = false         # skip source detection and translate every field

[translation.anthropic]
model = "claude-3-5-sonnet-latest"
max_output_tokens = 4096
api_key = ""                    # ANTHROPIC_API_KEY env var takes precedence
```

`utils/.config.template.toml` ships these as documented dict-form entries with `optional`, `default`, `options`, and `explanation` keys, matching the existing template style (Req 3.6). Example for `provider`:

```toml
[translation]
provider = { optional = true, default = "none", options = ["none", "anthropic"], explanation = "Translation backend. 'none' disables translation; 'anthropic' uses Claude via the Anthropic SDK." }
target_lang = { optional = true, default = "", explanation = "ISO 639-1 / BCP-47 target language code. Empty disables translation. Examples: 'es', 'pt-BR', 'ja'." }
failure_policy = { optional = true, default = "skip", options = ["skip", "fail"], explanation = "What to do when Anthropic raises an error: 'skip' uses the original text and warns; 'fail' re-raises." }
cache_enabled = { optional = true, type = "bool", default = true, options = [true, false], explanation = "Cache translations under assets/temp/{thread_id}/translation_cache.json so repeated runs don't re-call Anthropic." }
force_translate = { optional = true, type = "bool", default = false, options = [true, false], explanation = "Skip source-language detection and translate every field unconditionally." }

[translation.anthropic]
model = { optional = true, default = "claude-3-5-sonnet-latest", explanation = "Claude model identifier passed with each request." }
max_output_tokens = { optional = true, type = "int", default = 4096, nmin = 1, explanation = "Maximum output tokens per Anthropic request." }
api_key = { optional = true, default = "", explanation = "Anthropic API key. The ANTHROPIC_API_KEY environment variable takes precedence over this value." }
```

### Prompts (prompts.py)

Two system prompts and two user-prompt builders. Treated as data so snapshot tests can pin the exact strings.

```python
# utils/translation/prompts.py

SYSTEM_PROMPT_DETECT = """You are a language detector for short Reddit excerpts.

The user will send you a single string consisting of a Reddit post title,
followed by a snippet of the post body, followed by up to a few short
comments, separated by ' | '. Some excerpts mix languages, contain slang,
or contain profanity.

Your job:
- Identify the dominant language of the excerpt.
- Reply with ONE language tag and nothing else. Use BCP-47 / ISO 639-1
  codes (e.g. 'en', 'es', 'pt-BR', 'ja', 'zh-CN').
- Do NOT include explanations, punctuation, quotes, or markdown.
- Do NOT prefix your answer with 'Language:' or any other label.
- If the excerpt is too short or ambiguous to detect, reply 'und'.
"""

SYSTEM_PROMPT_TRANSLATE = """You translate Reddit posts and comments.

Rules:
- Translate the user's text into the target language they specify.
- Preserve the original casual register: keep slang, profanity, internet
  shorthand, and tone exactly as forceful or casual as the source.
- Preserve line breaks and paragraph structure.
- Do NOT add commentary, notes, summaries, or warnings.
- Do NOT wrap your output in quotation marks, code fences, or markdown.
- Do NOT translate proper nouns, usernames, or URLs.
- Output ONLY the translated text, raw, ready to be displayed verbatim.
- If the input is empty or whitespace-only, output the input unchanged.
"""

def user_prompt_detect(sample: str) -> str:
    return f"Detect the dominant language of the following Reddit excerpt:\n\n{sample}"

def user_prompt_translate(*, text: str, target_lang: str) -> str:
    return (
        f"Translate the following text into the language with code "
        f"{target_lang!r}. Output only the translation, no quotes, no "
        f"markdown, no commentary.\n\n---\n{text}\n---"
    )
```

The `---` fences in the user prompt are deliberate: they let the model recognize the input boundaries without us asking it to repeat them. The system prompt explicitly instructs against echoing them in output (Req 14.3). The translate prompt repeats "no quotes, no markdown, no commentary" twice (system + user) to bias the output toward raw text.

### Source-Language Detection Sample (Req 5.1, 5.3)

`Translation_Service._build_detection_sample` produces a single string from one `Reddit_Content`:

```
TITLE: <thread_title>
BODY: <thread_post truncated to 500 chars>
COMMENT 1: <comments[0].comment_body truncated to 200 chars>
COMMENT 2: <comments[1].comment_body truncated to 200 chars>
COMMENT 3: <comments[2].comment_body truncated to 200 chars>
```

Truncation rules:
- Title: full (titles are short, max ~300 chars on Reddit).
- Body: first 500 characters, ending on a word boundary if possible.
- Comments: up to the first three non-empty comments, each truncated to 200 characters on a word boundary.

If `thread_post` is empty (link post, no selftext) and there are no comments, the sample is just the title. The sample stays under ~1.5 KB regardless of post size, keeping the detection call cheap.

The detection sample is built and sent **once per `Reddit_Content`** (Req 5.3). The result lives in a local variable in `Translation_Service.translate()` and is not persisted (`Translation_Cache` only stores translations, not detections).

### Orchestrator Integration (Req 16)

#### `main.py::main` — full diff

```python
# Before
def main(POST_ID=None) -> None:
    global reddit_id, reddit_object
    reddit_object = get_subreddit_threads(POST_ID)
    reddit_id = extract_id(reddit_object)
    print_substep(f"Thread ID is {reddit_id}", style="bold blue")
    length, number_of_comments = save_text_to_mp3(reddit_object)
    length = math.ceil(length)
    get_screenshots_of_reddit_posts(reddit_object, number_of_comments)
    bg_config = {...}
    download_background_video(bg_config["video"])
    download_background_audio(bg_config["audio"])
    chop_background(bg_config, length, reddit_object)
    make_final_video(number_of_comments, length, reddit_object, bg_config)
```

```python
# After
from utils.translation import Translation_Service, TranslationConfig
from utils.posttextparser import posttextparser

def main(POST_ID=None) -> None:
    global reddit_id, reddit_object

    # Stage 1: scrape (Req 16.1)
    reddit_object = get_subreddit_threads(POST_ID)
    reddit_id = extract_id(reddit_object)
    print_substep(f"Thread ID is {reddit_id}", style="bold blue")

    # Stage 2: translate (Req 1.1, 16.2). Always called; no-op when
    # provider=none or target_lang empty.
    translation_config = TranslationConfig.from_settings(settings.config)
    reddit_object = Translation_Service(translation_config).translate(reddit_object)

    # Stage 3: parse (Req 9.1, 16.3). Only when storymodemethod=1.
    if (
        settings.config["settings"]["storymode"]
        and settings.config["settings"]["storymodemethod"] == 1
    ):
        reddit_object["thread_post"] = posttextparser(reddit_object["thread_post"])

    # Stages 4-7: consume (unchanged)
    length, number_of_comments = save_text_to_mp3(reddit_object)
    length = math.ceil(length)
    get_screenshots_of_reddit_posts(reddit_object, number_of_comments)
    bg_config = {...}
    download_background_video(bg_config["video"])
    download_background_audio(bg_config["audio"])
    chop_background(bg_config, length, reddit_object)
    make_final_video(number_of_comments, length, reddit_object, bg_config)
```

Helper extraction (optional, allowed by Req 16.5): the translate+parse block can move into `utils/translation/__init__.py::translate_and_parse(reddit_object, settings_config) -> dict` so the helper is unit-testable without monkey-patching `main.py`. The helper does not re-order stages; it executes the two-step sequence as a single named operation.

#### `batch.py::make_one_video` — diff

```python
# Before
def make_one_video(submission, video_num):
    reddit_object = build_reddit_object(submission)  # calls posttextparser internally
    reddit_id = extract_id(reddit_object)
    length, number_of_clips = save_text_to_mp3(reddit_object)
    ...

def build_reddit_object(submission):
    content = {...}
    if settings.config["settings"]["storymode"]:
        if settings.config["settings"]["storymodemethod"] == 1:
            content["thread_post"] = posttextparser(submission.selftext)
        else:
            content["thread_post"] = submission.selftext
    return content
```

```python
# After
from utils.translation import Translation_Service, TranslationConfig

def make_one_video(submission, video_num):
    reddit_object = build_reddit_object(submission)  # always raw str in thread_post
    reddit_id = extract_id(reddit_object)

    translation_config = TranslationConfig.from_settings(settings.config)
    reddit_object = Translation_Service(translation_config).translate(reddit_object)

    if (
        settings.config["settings"]["storymode"]
        and settings.config["settings"]["storymodemethod"] == 1
    ):
        reddit_object["thread_post"] = posttextparser(reddit_object["thread_post"])

    length, number_of_clips = save_text_to_mp3(reddit_object)
    ...

def build_reddit_object(submission):
    content = {...}
    if settings.config["settings"]["storymode"]:
        content["thread_post"] = submission.selftext  # always str (Req 15.4)
    return content
```

The `posttextparser` import is removed from `batch.py` (Req 15.4, 10.8).

#### `reddit/subreddit.py::get_subreddit_threads` — diff (Req 15)

```python
# Before
from utils.posttextparser import posttextparser
...
if settings.config["settings"]["storymode"]:
    if settings.config["settings"]["storymodemethod"] == 1:
        content["thread_post"] = posttextparser(submission.selftext)
    else:
        content["thread_post"] = submission.selftext
```

```python
# After
# (import removed: Req 15.3, 10.7)
...
if settings.config["settings"]["storymode"]:
    content["thread_post"] = submission.selftext  # always str (Req 15.1)
```

### gTTS Locale Resolution (Req 10.5, 10.6)

`TTS/GTTS.py` becomes:

```python
# After
import random

from gtts import gTTS

from utils import settings
from utils.console import print_substep

DEFAULT_LOCALE = "en"


class GTTS:
    def __init__(self):
        self.max_chars = 5000
        self.voices = []

    def run(self, text, filepath, random_voice: bool = False):
        lang = (
            settings.config.get("translation", {}).get("target_lang", "")
            or settings.config["reddit"]["thread"].get("post_lang", "")
        )
        if not lang:
            print_substep(
                f"[warn] No translation locale available; gTTS falling back "
                f"to {DEFAULT_LOCALE!r}.",
                style="yellow",
            )
            lang = DEFAULT_LOCALE
        tts = gTTS(text=text, lang=lang, slow=False)
        tts.save(filepath)
```

### Adapter Removal Plan (Req 10)

The four current call sites and their replacements:

| Site | Line | Current | Replacement |
|---|---|---|---|
| `video_creation/final_video.py::name_normalize` | 65–77 | Calls `translators.translate_text(name, ..., to_language=lang)` if `post_lang` set | Strip the `lang` block entirely. The function returns the cleaned filename string in the original Latin transliteration. **Behavior change is intentional**: `name_normalize` now produces a stable, ASCII-safe filename derived from `thread_title` regardless of target language. The viewer never sees the filename, so loss of translated filename is acceptable. |
| `TTS/engine_wrapper.py::process_text` | 199–206 | Calls `translators.translate_text(...)` if `post_lang` set | Strip translation entirely. `process_text` becomes `sanitize_text(text) if clean else text`. The text is already translated by `Translation_Service`. |
| `video_creation/screenshot_downloader.py::get_screenshots_of_reddit_posts` | 137–157 | Calls `translators.translate_text(reddit_object["thread_title"])` and overwrites the H1 in the page DOM via `page.evaluate` | Replace the call with `translated_title = reddit_object["thread_title"]` (already translated by `Translation_Service`). The DOM-rewrite block is preserved when `lang` is non-empty so the screenshot still shows the translated text. The `translate_text` inner helper and the `import translators` at module top are removed. |
| `TTS/GTTS.py` | 16 | `lang=settings.config["reddit"]["thread"]["post_lang"] or "en"` | Use the locale-resolution helper above (`[translation] target_lang` first, `[reddit.thread] post_lang` fallback, `"en"` default with warning). |

After the removals, `import translators` lines are deleted from:
- `video_creation/final_video.py:12`
- `TTS/engine_wrapper.py:7`
- `video_creation/screenshot_downloader.py:6`

Static AST-based test (see Testing Strategy) confirms none of these four files import `translators` after the migration.

## Data Models

### `Reddit_Content` (input/output of `Translation_Service`)

The shape is unchanged from the current scraper output, with one tightening:

```python
Reddit_Content = TypedDict("Reddit_Content", {
    "thread_title": str,
    "thread_post": str,                       # always str, both storymode methods (Req 4.7, 15.1)
    "thread_id": str,
    "thread_url": str,
    "is_nsfw": bool,
    "author": str,
    "avatar_url": str,
    "comments": list[dict[str, str]],         # each: comment_body, comment_url, comment_id
    # ...other Structural_Fields preserved byte-for-byte
})
```

`Translation_Service` returns a dict with the same key set (Req 1.2, 6.4) and the same Structural_Field values byte-for-byte (Req 8.3, 15.5). The output of `Translation_Service` may be mutated by the orchestrator (e.g., `posttextparser` later replaces `thread_post` with a `list[str]` when `storymodemethod=1`), but `Translation_Service` itself never returns a non-`str` `thread_post`.

### `TranslationConfig`

See config.py above. Frozen dataclass. Validated once at the top of `main` (Req 11.3 degradation happens here, not at startup of the program).

### `TranslationStats` (in-process, for observability)

```python
@dataclass
class TranslationStats:
    calls: int = 0          # total Anthropic API calls
    cache_hits: int = 0
    input_chars: int = 0    # total characters submitted to Anthropic
```

Logged at the end of each run (Req 13.4).

### Cache File Schema

See `Translation_Cache` above. Single flat dict, key = SHA-256 hex of the composite tuple, value = translated string. No metadata, no versioning. Cache files are always cleaned by the existing `cleanup(reddit_id)` path because they live under `assets/temp/{thread_id}/`.

## Migration Plan

The migration is staged so `main.py` runs cleanly at every checkpoint.

### Phase 1: Package skeleton, no-op provider

- Add `utils/translation/` package with `__init__.py`, `errors.py`, `config.py`, `service.py` containing the no-op pass-through path only.
- `service.py` only handles `provider == "none"` and the `target_lang == ""` short-circuit.
- Add `[translation]` section to `config.toml` with `provider = "none"`.
- Add `[translation]` documentation to `utils/.config.template.toml`.
- Property tests for the no-op path: `translate(x) == x` when provider is none.
- `main.py` imports and calls `Translation_Service`, but the service returns the input unchanged.
- **Behavior unchanged.**

### Phase 2: Scraper decoupling + orchestrator re-ordering (Req 15, 16)

- Remove `posttextparser` import and call from `reddit/subreddit.py`. Always set `content["thread_post"] = submission.selftext`.
- Remove `posttextparser` import and call from `batch.py::build_reddit_object`. Always set `content["thread_post"] = submission.selftext`.
- Add the conditional `posttextparser` call to `main.py::main` after `Translation_Service` (still no-op).
- Add the same conditional `posttextparser` call to `batch.py::make_one_video` after `Translation_Service`.
- **Behavior unchanged**: both storymode methods now flow through the new stage order; the `storymodemethod=1` path produces a `list[str]` `thread_post` exactly as before, just at a different point in the pipeline.

### Phase 3: Anthropic SDK integration

- Add `anthropic` to `requirements.txt`.
- Add `anthropic_client.py`, `cache.py`, `prompts.py`.
- Implement `Translation_Service.translate` for the `provider == "anthropic"` branch: detection sample, source-detection call, per-field translate-or-cache loop, sanitize-or-fallback, failure-policy application.
- Implement `Translation_Cache` with atomic writes.
- Add log lines per Req 13.
- Snapshot tests on `prompts.py`.
- Property tests for determinism, idempotence, structural-field round-trip, source==target no-op, cache hit equivalence, failure containment under `skip`.
- Operator opts in by setting `[translation].provider = "anthropic"` and `target_lang` in `config.toml`. With `provider = "none"` the path is unchanged.

### Phase 4: Adapter removal (Req 10)

- Remove `import translators` and the `translate_text` block from `video_creation/final_video.py::name_normalize`.
- Remove `import translators` and the translation block from `TTS/engine_wrapper.py::process_text`.
- Remove `import translators` and the `translate_text` helper (but keep the DOM-rewrite block) from `video_creation/screenshot_downloader.py`.
- Update `TTS/GTTS.py` to prefer `[translation] target_lang` over `[reddit.thread] post_lang`.
- AST-based tests confirm no `translators` import in the four target files.
- After this phase, the four `translators.translate_text` call sites are gone; translation flows exclusively through `Translation_Service`.

### Phase 5: Cleanup and docs

- Remove the legacy `post_lang` field from the example in `config.toml` (the field stays in `.config.template.toml` for backward compatibility — `GTTS.py` still reads it as fallback).
- Add a short section to `README.md` describing the new `[translation]` block.
- Verify the `translators` package can be removed from `requirements.txt` if no other module uses it (`grep_search` for `import translators` should find zero hits after Phase 4).

Each phase is independently committable and `main.py` runs cleanly between phases.

<!-- Correctness Properties section continues after prework. -->

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

The properties below are derived from the prework analysis and consolidated to remove redundancy. Each property tests YOUR code's logic — `Translation_Service`, `Anthropic_Client`, `Translation_Cache`, `TranslationConfig`, and the orchestrator wiring — and benefits from running 100+ iterations across generated `Reddit_Content` inputs and varied configurations. Items classified as SMOKE in the prework (architectural / static AST checks) and EXAMPLE (specific log strings, prompt snapshots) are covered by the Testing Strategy section below, not as universal properties.

The Anthropic SDK is mocked in every property test. The properties test our code's contract; they do not test Claude's translation quality.

### Property 1: Determinism under fixed model and config

*For any* `Reddit_Content` input and *any* `TranslationConfig` with `provider = "anthropic"`, calling `Translation_Service(config).translate(input)` twice in succession with a deterministic mocked `Anthropic_Client` SHALL produce two output dicts that are equal under value equality.

**Validates: Requirements 8.1**

### Property 2: Idempotence under same target language

*For any* `Reddit_Content` input and *any* `TranslationConfig` with non-empty `target_lang`, if `y = Translation_Service(config).translate(input)` and `z = Translation_Service(config).translate(y)`, then `y == z`.

**Validates: Requirements 8.2**

### Property 3: Structural-Field byte-equality

*For any* `Reddit_Content` input, *any* `TranslationConfig`, *any* `failure_policy`, and *any* cache state (cold, populated, or disabled), the output of `Translation_Service.translate(input)` SHALL have the same key set as `input` and SHALL preserve the value of every Structural_Field (`thread_id`, `thread_url`, `permalink`, `author`, `avatar_url`, `is_nsfw`, `subreddit`, and each `comments[*].comment_id`, `comments[*].comment_url`) byte-for-byte from `input`.

**Validates: Requirements 1.2, 4.5, 6.4, 8.3, 15.5**

### Property 4: Pass-through when translation is disabled

*For any* `Reddit_Content` input, if `config.effective_provider == "none"` *or* `config.target_lang in (None, "")`, then `Translation_Service(config).translate(input) == input` and no Anthropic call is made.

**Validates: Requirements 1.3, 1.4, 11.1**

### Property 5: Source==target no-op

*For any* `Reddit_Content` input and *any* `TranslationConfig` with `provider = "anthropic"`, `target_lang` non-empty, and `force_translate = False`, if the mocked detector returns a tag whose lowercase form equals `target_lang.lower()`, then no `Anthropic_Client.translate` call is made and every Translatable_Field value in the output equals the corresponding Translatable_Field value in the input.

**Validates: Requirements 5.2, 8.4**

### Property 6: Force-translate skips detection

*For any* `Reddit_Content` input and *any* `TranslationConfig` with `force_translate = True`, the mocked `Anthropic_Client.detect_source_language` SHALL be called zero times during `Translation_Service.translate(input)`.

**Validates: Requirements 5.4**

### Property 7: Detection is single-call per Reddit_Content

*For any* `Reddit_Content` input and *any* `TranslationConfig` with `force_translate = False` and source != target (mocked), `Anthropic_Client.detect_source_language` SHALL be called exactly once per `Translation_Service.translate(input)` invocation, regardless of the number of Translatable_Fields.

**Validates: Requirements 5.3**

### Property 8: All Translatable_Fields are translated

*For any* `Reddit_Content` input with non-empty `thread_title`, string `thread_post`, and a non-empty `comments` list, and *any* `TranslationConfig` that triggers translation (`provider = "anthropic"`, `target_lang` non-empty, source != target, cache cold), each of `output["thread_title"]`, `output["thread_post"]`, and every `output["comments"][i]["comment_body"]` SHALL equal `sanitize_text(mocked_client.translate(corresponding_input_value))`. The translated `output["thread_post"]` SHALL be a `str`, never a `list`.

**Validates: Requirements 4.1, 4.2, 4.3, 4.4, 14.1**

### Property 9: TypeError on non-string thread_post

*For any* `Reddit_Content` input where `input["thread_post"]` is not a `str` (list, int, dict, bytes, ...) and not `None`, `Translation_Service.translate(input)` SHALL raise `TypeError` whose message contains the string `"thread_post"` and the actual type name.

**Validates: Requirements 4.7**

### Property 10: Failure containment under skip policy

*For any* `Reddit_Content` input, *any* `TranslationError` subclass `E` (including `TranslationEmptyResponseError`), and *any* Translatable_Field `f` chosen as the injection point, with `failure_policy = "skip"` and the mocked `Anthropic_Client` raising `E()` when translating `f`, the result of `Translation_Service.translate(input)` SHALL satisfy:
- no exception propagates,
- `output.keys() == input.keys()`,
- every Translatable_Field value in `output` equals the corresponding value in `input` for the field that failed; other fields' values may be translated or original (the property is failure containment, not all-or-nothing rollback),
- a warning containing `f` and `E.__name__` is emitted.

**Validates: Requirements 6.1, 6.3, 6.4**

### Property 11: Failure propagation under fail policy

*For any* `Reddit_Content` input, *any* `TranslationError` subclass `E`, and *any* Translatable_Field `f`, with `failure_policy = "fail"` and the mocked `Anthropic_Client` raising `E()` on `f`, `Translation_Service.translate(input)` SHALL raise an exception whose `str(exception)` contains both `f` and `E.__name__`.

**Validates: Requirements 6.2, 6.3**

### Property 12: Anthropic request shape

*For any* `TranslationConfig` (model `M`, max_output_tokens `N`) and *any* `Reddit_Content` input that triggers at least one translate call, every captured kwargs of `mocked_anthropic.messages.create` SHALL satisfy `kwargs["model"] == M`, `kwargs["max_tokens"] == N`, and `kwargs["temperature"] == 0`.

**Validates: Requirements 2.2, 2.4, 2.6**

### Property 13: Temperature != 0 rejection

*For any* float `t` with `t != 0.0`, constructing `Anthropic_Client(api_key=..., model=..., max_output_tokens=..., temperature=t)` SHALL raise `TranslationConfigError` whose message contains the literal repr of `t`.

**Validates: Requirements 2.3**

### Property 14: Config defaults applied for missing keys

*For any* `settings.config` mapping where the `[translation]` section is absent or omits some of the documented keys, `TranslationConfig.from_settings(settings_config)` SHALL return a `TranslationConfig` whose missing-key values equal the documented defaults: `provider = "none"`, `target_lang = ""`, `failure_policy = "skip"`, `cache_enabled = True`, `force_translate = False`, `model = "claude-3-5-sonnet-latest"`, `max_output_tokens = 4096`, `api_key = ""`.

**Validates: Requirements 3.2, 3.3**

### Property 15: API-key environment precedence

*For any* `TranslationConfig` and *any* `(env_value, config_value)` pair of strings, with `os.environ["ANTHROPIC_API_KEY"]` set to `env_value`, `config.resolve_api_key()` SHALL return `env_value` when `env_value` is non-empty, and `config_value` otherwise. If both are empty, `resolve_api_key()` SHALL raise `TranslationConfigError` whose message names both sources.

**Validates: Requirements 3.4**

### Property 16: Unknown provider degrades to none

*For any* string `s` not in `{"none", "anthropic"}`, `TranslationConfig.from_settings({"translation": {"provider": s, ...}})` SHALL return a config with `effective_provider == "none"`, SHALL NOT raise, and SHALL emit a warning containing `s` and the valid provider list.

**Validates: Requirements 11.3**

### Property 17: Cache key derivation is deterministic and tuple-sensitive

*For any* tuple `(thread_id, text, target_lang, model_id)`, `Translation_Cache._cache_key(...)` SHALL return the same value on repeat calls (determinism). For *any* two tuples that differ in at least one component, the returned cache keys SHALL differ. The cache file path for `thread_id` SHALL equal `Path("assets/temp") / thread_id / "translation_cache.json"`.

**Validates: Requirements 7.1, 7.7**

### Property 18: Cache hit short-circuits Anthropic_Client

*For any* `Reddit_Content` input and *any* `TranslationConfig` with `cache_enabled = True` triggering translation, calling `Translation_Service(config).translate(input)` twice on a fresh temp cache directory SHALL satisfy:
- the second call invokes `mocked_anthropic_client.translate` zero times,
- the second call invokes `mocked_anthropic_client.detect_source_language` exactly once (detection is not cached),
- the two output dicts are equal under value equality.

**Validates: Requirements 7.2**

### Property 19: Cache write occurs after successful Anthropic translation

*For any* `Reddit_Content` input that triggers at least one translation under a fresh temp cache directory with `cache_enabled = True`, after `Translation_Service.translate(input)` returns successfully, the file at `assets/temp/{thread_id}/translation_cache.json` SHALL exist and SHALL contain the cache key derived from each translated `(text, target_lang, model_id)` tuple.

**Validates: Requirements 7.4**

### Property 20: cache_enabled=False disables all cache I/O

*For any* `Reddit_Content` input with `cache_enabled = False` and a populated `assets/temp/{thread_id}/translation_cache.json` file on disk, `Translation_Cache.get` and `Translation_Cache.put` SHALL be invoked zero times during `Translation_Service.translate(input)`, and the on-disk cache file SHALL remain unchanged.

**Validates: Requirements 7.6**

### Property 21: Sanitizer collapse triggers original substitution

*For any* `Reddit_Content` input and *any* Translatable_Field `f`, if the mocked `Anthropic_Client.translate` for `f` returns a value `v` such that `sanitize_text(v).strip() == ""`, then `output[f]` SHALL equal `input[f]` and a warning containing `f` SHALL be emitted.

**Validates: Requirements 14.2**

### Property 22: Output does not introduce wrappers

*For any* `Reddit_Content` input where no Translatable_Field value contains code fences, surrounding quotation marks, or HTML tags, and *any* mocked `Anthropic_Client` whose translations also contain none of those markers (and that does not collapse under sanitization), every Translatable_Field value in the output SHALL contain none of: leading/trailing matched code-fence pairs (` ``` `), leading/trailing matched ASCII or Unicode quotation marks, or HTML tags (`<…>`) absent from the corresponding input.

**Validates: Requirements 14.3**

### Property 23: Pipeline stage order

*For any* `settings.config` flag combination (`storymode in {True, False}`, `storymodemethod in {0, 1}`, translation provider in `{"none", "anthropic"}`, `target_lang in {"", "<non-empty>"}`), and a fully mocked stage set (mocked `get_subreddit_threads`, `Translation_Service.translate`, `posttextparser`, `save_text_to_mp3`, `get_screenshots_of_reddit_posts`, `make_final_video`), running `main.py::main` SHALL produce a call sequence that is a subsequence of:

```
get_subreddit_threads, Translation_Service.translate, posttextparser,
save_text_to_mp3, get_screenshots_of_reddit_posts, make_final_video
```

with the following preconditions: `Translation_Service.translate` is called exactly once iff `get_subreddit_threads` returned (Req 1.1); `posttextparser` is called iff `Translation_Service.translate` was called *and* `storymode == True` *and* `storymodemethod == 1` (Req 9.1, 9.2, 9.3); each consumer stage receives the dict produced by the most recent stage in the sequence (Req 16.2).

**Validates: Requirements 1.1, 9.1, 9.2, 9.3, 16.1, 16.2, 16.3, 16.4**

### Property 24: Scraper returns raw string thread_post

*For any* mocked `submission` with `selftext` of any string value and *any* `(storymode, storymodemethod)` setting with `storymode = True`, calling `get_subreddit_threads` SHALL produce `content["thread_post"]` that is a `str` and equals `submission.selftext`. The same property SHALL hold for `batch.build_reddit_object(submission)`.

**Validates: Requirements 15.1, 15.4**

### Property 25: gTTS locale precedence

*For any* `(target_lang, post_lang)` pair of strings, the locale resolved by `TTS/GTTS.py::GTTS.run` SHALL equal:
- `target_lang` when `target_lang` is non-empty,
- `post_lang` when `target_lang` is empty and `post_lang` is non-empty,
- `"en"` (the default) when both are empty, with a warning emitted.

**Validates: Requirements 10.5, 10.6**

## Error Handling

### `TranslationError` Hierarchy (errors.py)

```python
# utils/translation/errors.py
class TranslationError(Exception):
    """Base class for translation-layer errors. All errors raised by
    Anthropic_Client and Translation_Service inherit from this."""

class TranslationConfigError(TranslationError):
    """Raised for misconfiguration: invalid temperature, missing API key,
    invalid failure_policy. Always propagates regardless of failure_policy
    because misconfiguration cannot be 'skipped past' meaningfully."""

class TranslationAPIError(TranslationError):
    """Generic Anthropic API error (non-auth, non-rate-limit, non-timeout,
    non-empty-response). Maps anthropic.APIError."""

class TranslationAuthError(TranslationError):
    """Anthropic authentication failure. Maps anthropic.AuthenticationError."""

class TranslationRateLimitError(TranslationError):
    """Anthropic rate limit hit. Maps anthropic.RateLimitError."""

class TranslationTimeoutError(TranslationError):
    """Anthropic request timed out. Maps anthropic.APITimeoutError."""

class TranslationEmptyResponseError(TranslationError):
    """Anthropic returned a Message with no text content (Req 6.3)."""
```

### Propagation Matrix

| Error class | `failure_policy = skip` | `failure_policy = fail` |
|---|---|---|
| `TranslationConfigError` | propagates (cannot be skipped — see Req 3.5; though Req 6.1 makes the field-level skip handle this when raised mid-translate) | propagates |
| `TranslationAuthError` | caught, warns, falls back to original | wrapped + re-raised with field name |
| `TranslationRateLimitError` | caught, warns, falls back to original | wrapped + re-raised with field name |
| `TranslationTimeoutError` | caught, warns, falls back to original | wrapped + re-raised with field name |
| `TranslationAPIError` | caught, warns, falls back to original | wrapped + re-raised with field name |
| `TranslationEmptyResponseError` | caught, warns, falls back to original | wrapped + re-raised with field name |
| `OSError` from `Translation_Cache.put` | caught, warns, returns translated value (Req 7.5) | caught, warns, returns translated value (cache write failure should not abort the run regardless of policy) |
| `MemoryError`, `KeyboardInterrupt`, `SystemExit` | propagates (Req 6.4 exemption) | propagates |
| `TypeError` (non-string `thread_post`) | propagates (Req 4.7 — type discipline is unconditional) | propagates |

The `TranslationConfigError` row deserves attention. Per Req 3.5, the error is **deferred** to first translation attempt. When a missing API key is detected lazily inside `_translate_field`, `Translation_Service` constructs a `TranslationConfigError` and routes it through the same `failure_policy` path as any other `TranslationError`. Under `skip`, every Translatable_Field falls back to the original (which is the intended behavior — the run continues with untranslated text). Under `fail`, the error propagates and aborts the run.

`TypeError` for non-string `thread_post` is **always** propagated regardless of `failure_policy`. This is a programmer error, not a translation-layer failure (Req 4.7).

### Wrapped Re-raise Format

Under `failure_policy = "fail"`, the wrapped re-raise message is:

```
Translation failed for {field_name}: {ErrorClass.__name__}: {original_message}
```

Example:

```
TranslationRateLimitError: Translation failed for comments[3].comment_body:
RateLimitError: 429 Too Many Requests
```

The wrapped error preserves `__cause__` from the original SDK exception via `raise ... from sdk_exception`.

## Testing Strategy

### PBT Applicability Assessment

This feature is **suitable for property-based testing**. `Translation_Service` is a pure-ish function: input `Reddit_Content` + `TranslationConfig` -> output `Reddit_Content`, with the only side effects being log lines and atomic cache writes. The Anthropic SDK is the only external dependency, and it is mocked in every property test (we don't test Claude's translation quality; we test our wiring around it).

`Translation_Cache` is filesystem-bound but small enough to test against a `tempfile.TemporaryDirectory` per test case. `TranslationConfig.from_settings` is a pure function. The pipeline-order property runs against fully mocked stages and is trivially fast (no I/O).

### Test Layout

```
tests/
  unit/
    translation/
      test_config.py            # property: defaults, env precedence, unknown-provider degradation
      test_cache.py             # property: key determinism, atomic writes, get/put, gating
      test_anthropic_client.py  # property: request shape, temperature rejection, response parsing
      test_service.py           # property: 1-22 above (the bulk of PBT here)
      test_prompts.py           # snapshot tests on prompts.py
      test_imports.py           # AST scans (SMOKE invariants)
  integration/
    test_pipeline_order.py      # Property 23: full main.py wiring with mocked stages
    test_scraper_decoupling.py  # Property 24: get_subreddit_threads + batch.build_reddit_object
    test_gtts_locale.py         # Property 25: locale precedence
    test_anthropic_recorded.py  # 1-2 recorded-cassette tests against the real SDK shape
```

### Property-Based Test Library

Python ecosystem standard: **Hypothesis**. Each property test runs **at minimum 100 iterations** per Hypothesis configuration. Tests are tagged with a comment referencing the design property, e.g.:

```python
# Feature: claude-translation, Property 3: Structural-Field byte-equality
@given(reddit_content=reddit_content_strategy(), config=translation_config_strategy())
@settings(max_examples=200)
def test_structural_fields_preserved(reddit_content, config):
    out = Translation_Service(config).translate(reddit_content)
    assert out.keys() == reddit_content.keys()
    for f in STRUCTURAL_FIELDS:
        assert out[f] == reddit_content[f]
    for i, c in enumerate(reddit_content.get("comments", [])):
        assert out["comments"][i]["comment_id"] == c["comment_id"]
        assert out["comments"][i]["comment_url"] == c["comment_url"]
```

A shared `reddit_content_strategy()` Hypothesis strategy generates valid `Reddit_Content` dicts: random `thread_id`, `thread_url`, `thread_title`, `thread_post` (string), and a list of comment dicts with `comment_body`, `comment_id`, `comment_url`. Edge cases included automatically by Hypothesis: empty strings, whitespace-only strings, very long strings, unicode, null bytes (filtered out where invalid).

A shared `translation_config_strategy()` generates valid `TranslationConfig` instances by varying provider, target_lang, failure_policy, cache_enabled, force_translate, model, and max_output_tokens.

A shared `MockAnthropicClient` returns deterministic fake translations of the form `f"<{target_lang}>{text}</{target_lang}>"` so the property tests can verify specific transformations without hitting the network.

### Snapshot Tests on Prompts

`test_prompts.py` pins the exact `SYSTEM_PROMPT_DETECT` and `SYSTEM_PROMPT_TRANSLATE` strings via Python string equality against committed expected strings. This catches accidental edits to prompt wording. The `user_prompt_translate` and `user_prompt_detect` builders are tested by example: a fixed input produces a fixed output.

### AST-Based Static Tests (SMOKE)

`test_imports.py` walks the codebase with `ast` and asserts:

```python
# Req 10.2-10.4: no translators import in the four target files
for path in [
    "TTS/engine_wrapper.py",
    "video_creation/screenshot_downloader.py",
    "video_creation/final_video.py",
    "TTS/GTTS.py",
]:
    tree = ast.parse(open(path).read())
    assert "translators" not in collect_imports(tree), \
        f"{path} still imports translators"

# Req 9.4: Translation_Service does not import posttextparser
for path in glob("utils/translation/**/*.py", recursive=True):
    tree = ast.parse(open(path).read())
    assert "posttextparser" not in collect_module_names(tree), \
        f"{path} references posttextparser"

# Req 10.7, 15.2, 15.3: reddit/subreddit.py does not import posttextparser
tree = ast.parse(open("reddit/subreddit.py").read())
assert "posttextparser" not in collect_imports(tree)

# Req 10.8: batch.py does not import posttextparser
tree = ast.parse(open("batch.py").read())
assert "posttextparser" not in collect_imports(tree)

# Req 1.5, 1.6, 2.1: anthropic SDK imported only in utils/translation/anthropic_client.py
for path in glob("**/*.py", recursive=True):
    if path == "utils/translation/anthropic_client.py":
        continue
    if path.startswith("venv/") or path.startswith(".git/"):
        continue
    tree = ast.parse(open(path).read())
    assert "anthropic" not in collect_imports(tree), \
        f"{path} imports anthropic SDK directly"

# Req 4.6: Translation_Service does not branch on storymodemethod
tree = ast.parse(open("utils/translation/service.py").read())
for node in ast.walk(tree):
    if isinstance(node, ast.Attribute) and node.attr == "storymodemethod":
        raise AssertionError("Translation_Service references storymodemethod")
```

These tests run in CI and fail fast on any regression that re-introduces a `translators` import, a `posttextparser` import in the wrong file, or a direct `anthropic` SDK import outside `Anthropic_Client`.

### Integration Tests

Two integration tests cover the end-to-end Anthropic SDK contract:

1. **Recorded-cassette test** (`test_anthropic_recorded.py`): Uses `pytest-vcr` or a similar HTTP-cassette library to record a single real Anthropic call once, then replay it on every CI run. Verifies that `Anthropic_Client._extract_text` correctly parses the real SDK's `Message` shape.

2. **Pipeline-order integration test** (`test_pipeline_order.py`): Property 23. Imports `main.main` with all six stages monkey-patched to record their call order in a shared list. Hypothesis generates `settings.config` flag combinations; the test asserts each call sequence is a valid subsequence of the documented stage order.

### Test Coverage Summary

| Property | Test File | Iterations |
|---|---|---|
| 1 Determinism | `test_service.py` | 200 |
| 2 Idempotence | `test_service.py` | 200 |
| 3 Structural-Field byte-equality | `test_service.py` | 500 (core invariant) |
| 4 Pass-through when disabled | `test_service.py` | 200 |
| 5 Source==target no-op | `test_service.py` | 200 |
| 6 force_translate skips detection | `test_service.py` | 100 |
| 7 Detection is single-call | `test_service.py` | 100 |
| 8 All Translatable_Fields translated | `test_service.py` | 200 |
| 9 TypeError on non-string thread_post | `test_service.py` | 100 |
| 10 Skip-policy containment | `test_service.py` | 200 |
| 11 Fail-policy propagation | `test_service.py` | 200 |
| 12 Anthropic request shape | `test_anthropic_client.py` | 200 |
| 13 Temperature != 0 rejection | `test_anthropic_client.py` | 100 |
| 14 Config defaults | `test_config.py` | 200 |
| 15 API-key env precedence | `test_config.py` | 100 |
| 16 Unknown provider degradation | `test_config.py` | 100 |
| 17 Cache key determinism | `test_cache.py` | 500 |
| 18 Cache hit short-circuit | `test_cache.py` | 200 |
| 19 Cache write after Anthropic | `test_cache.py` | 100 |
| 20 cache_enabled=false disables I/O | `test_cache.py` | 100 |
| 21 Sanitizer collapse substitution | `test_service.py` | 100 |
| 22 No wrapper introduction | `test_service.py` | 200 |
| 23 Pipeline stage order | `test_pipeline_order.py` | 200 |
| 24 Scraper returns raw str | `test_scraper_decoupling.py` | 200 |
| 25 gTTS locale precedence | `test_gtts_locale.py` | 200 |

Plus AST-based SMOKE tests (single execution each) for the architectural invariants in Reqs 1.5, 1.6, 2.1, 4.6, 9.4, 10.2-10.4, 10.7, 10.8, 15.2, 15.3, 16.5.

Plus snapshot tests on `SYSTEM_PROMPT_DETECT`, `SYSTEM_PROMPT_TRANSLATE` (Req 2.5), and the example-based tests for Req 3.5 (deferred API-key error), 13.1 (start-of-run log line), 13.4 (end-of-run summary).

## Observability

Per Requirement 13, `Translation_Service` emits log lines via the existing `print_step` / `print_substep` helpers from `utils.console` to match the surrounding pipeline's logging style.

### Log Lines

| Event | Severity | Helper | Format |
|---|---|---|---|
| Start of run (Req 13.1) | info | `print_step` | `Translation: provider={provider} target_lang={target_lang} model={model} failure_policy={failure_policy} cache_enabled={cache_enabled}` |
| Per Anthropic translate call (Req 13.2) | info | `print_substep` | `[translated] {field_name}: {input_chars} -> {output_chars} chars` |
| Per cache hit (Req 13.3) | info | `print_substep` | `[cache hit] {field_name}` |
| End of run summary (Req 13.4) | info | `print_substep` | `Translation summary: {calls} Anthropic calls, {input_chars} input chars submitted, {cache_hits} cache hits` |
| Source==target skip (Req 5.2) | info | `print_substep` | `Source language ({src}) matches target ({target}); skipping translation.` |
| Sanitizer collapse fallback (Req 14.2) | warning (yellow) | `print_substep(..., style="yellow")` | `[warn] Sanitizer collapsed translation of {field_name}; using original.` |
| Cache write failure (Req 7.5) | warning (yellow) | `print_substep(..., style="yellow")` | `[warn] cache write failed for {field_name}: {ErrorClass.__name__}: {message}` |
| Failure-policy=skip caught error (Req 6.1) | warning (yellow) | `print_substep(..., style="yellow")` | `[warn] Translation failed for {field_name} ({ErrorClass.__name__}: {message}); using original.` |
| Unknown provider degradation (Req 11.3) | warning (yellow) | `print_substep(..., style="yellow")` | `[warn] Unknown translation.provider {value!r}; valid: ('none', 'anthropic'). Disabling translation for this run.` |
| gTTS locale fallback to default (Req 10.6) | warning (yellow) | `print_substep(..., style="yellow")` | `[warn] No translation locale available; gTTS falling back to 'en'.` |

The start-of-run line uses `print_step` (the bolder section header); per-field events use `print_substep` (the indented sub-line). Warnings use `print_substep(..., style="yellow")` to match the `print_substep("Failed: ...", style="bold red")` pattern already used by `batch.py`.

### Sample Run Log

```
══ Translation: provider=anthropic target_lang=es model=claude-3-5-sonnet-latest failure_policy=skip cache_enabled=true
   [detect] sample_chars=872 detected=en
   [translated] thread_title: 64 -> 71 chars
   [cache hit] thread_post
   [translated] comments[0].comment_body: 187 -> 203 chars
   [translated] comments[1].comment_body: 142 -> 159 chars
   [warn] Translation failed for comments[2].comment_body (TranslationRateLimitError: 429 Too Many Requests); using original.
   [translated] comments[3].comment_body: 89 -> 95 chars
   Translation summary: 4 Anthropic calls, 482 input chars submitted, 1 cache hit
```

The `[detect]` line is an additional informational line tied to Req 5.1 — it shows the detection sample size and result so operators can spot detection problems without enabling debug logging.

### What Is NOT Logged

- The full prompt text (could leak post content into logs at scale).
- The translated text (same reason).
- The API key (always redacted, even if it's the empty string).
- The cache file path on every read (only on write failure).
