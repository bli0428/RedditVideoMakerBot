"""Translation_Service public API.

This module provides the Translation_Service class, which translates a
Reddit_Content dictionary into a configured target language using the
Anthropic Claude API.

Key-preservation guarantee (Req 6.4):
    Translation_Service preserves every key in the input Reddit_Content
    after any translation-layer failure, regardless of failure_policy outcome.

    Documented exemptions to the key-preservation guarantee:
    Catastrophic system-level errors (MemoryError, KeyboardInterrupt during
    in-memory copy, OS-level I/O errors raised by the cache write path before
    any field has been substituted) are allowed to propagate unchanged and are
    NOT caught by failure_policy. These exceptions SHALL be allowed to
    propagate unchanged and are documented here per Req 6.4.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

from utils.console import print_substep
from utils.translation.config import TranslationConfig
from utils.translation.errors import TranslationConfigError, TranslationError

# ---------------------------------------------------------------------------
# Post-translation abbreviation fix table
# ---------------------------------------------------------------------------
# Maps source-language abbreviations that the LLM may leave untranslated to
# their English equivalents.  Applied deterministically after translation on
# thread_title (full string) and the last sentence of thread_post.
#
# Keys are compiled as whole-word, case-insensitive patterns.
# Add new entries here as needed.
# ---------------------------------------------------------------------------
_ABBREV_FIXES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r'\bSTB\b', re.IGNORECASE), 'AITA'),
    (re.compile(r'\bJNSP\b', re.IGNORECASE), 'IDK'),
]


@dataclass
class _TranslationStats:
    """In-process stats for observability (Req 13.4)."""

    calls: int = 0
    cache_hits: int = 0
    input_chars: int = 0


class Translation_Service:
    """Translates a Reddit_Content dict into config.target_lang.

    Stateless: one instance per run is fine, but the class holds no per-run
    mutable state outside the cache read-miss bloom set (see cache.py).
    """

    def __init__(self, config: TranslationConfig) -> None:
        self.config = config
        # Lazy-initialized on first translation attempt (Req 3.5)
        self._client: Optional[Any] = None
        # Cache is initialized once if cache_enabled; None otherwise
        if config.cache_enabled:
            from utils.translation.cache import Translation_Cache

            self._cache: Optional[Any] = Translation_Cache()
        else:
            self._cache = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

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
        # Type discipline (Req 4.7): check before any short-circuit so the
        # TypeError is raised regardless of provider or target_lang.
        post = reddit_content.get("thread_post")
        if post is not None and not isinstance(post, str):
            raise TypeError(
                f"Translation_Service expected thread_post to be str, "
                f"got {type(post).__name__}"
            )

        # Provider gating (Req 11.1)
        if self.config.effective_provider == "none":
            return reddit_content

        # Empty target_lang short-circuit (Req 1.3, 1.4)
        if not self.config.target_lang:
            return reddit_content

        # Start-of-run log (Req 13.1)
        print_substep(
            f"[translation] provider={self.config.effective_provider!r} "
            f"target_lang={self.config.target_lang!r} "
            f"model={self.config.model!r} "
            f"failure_policy={self.config.failure_policy!r} "
            f"cache_enabled={self.config.cache_enabled}"
        )

        # Lazy API key check (Req 3.5)
        if not self.config.has_api_key():
            return self._apply_top_level_failure_policy(
                reddit_content,
                field="<startup>",
                error=TranslationConfigError(
                    "No Anthropic API key found. Set ANTHROPIC_API_KEY or "
                    "[translation.anthropic].api_key."
                ),
            )

        # Lazy client construction (Req 3.5)
        if self._client is None:
            self._client = self._build_client()

        # Per-run stats (Req 13.4)
        stats = _TranslationStats()

        # Extract thread_id for cache keying (Req 7.1)
        thread_id = str(reddit_content.get("thread_id", ""))

        # Metadata detection: language + author gender in one call (Req 5.1, 5.3)
        title = reddit_content.get("thread_title", "") or ""
        body = reddit_content.get("thread_post", "") or ""
        if isinstance(body, list):
            body = " ".join(body)

        try:
            metadata = self._client.detect_post_metadata(title=title, body=body)
        except TranslationError as e:
            return self._apply_top_level_failure_policy(
                reddit_content, field="<detect>", error=e
            )

        src = metadata.get("language", "und")
        author_gender = metadata.get("author_gender", "unknown")
        print_substep(
            f"[translation] detected language={src!r} author_gender={author_gender!r}"
        )

        if not self.config.force_translate:
            if self._lang_matches(src, self.config.target_lang):
                print_substep(
                    f"[translation] Source language ({src!r}) matches target "
                    f"({self.config.target_lang!r}); skipping translation."
                )
                out = dict(reddit_content)
                out["author_gender"] = author_gender
                return out

        # Translate each Translatable_Field (Req 4.1–4.4)
        out = dict(reddit_content)

        out["thread_title"] = self._translate_field(
            "thread_title",
            reddit_content["thread_title"],
            thread_id=thread_id,
            stats=stats,
        )
        out["thread_title"] = self._apply_abbreviation_fixes(out["thread_title"])

        if isinstance(reddit_content.get("thread_post"), str):
            out["thread_post"] = self._translate_field(
                "thread_post",
                reddit_content["thread_post"],
                thread_id=thread_id,
                stats=stats,
            )
            out["thread_post"] = self._apply_abbreviation_fixes(
                out["thread_post"], last_sentence_only=True
            )

        out["comments"] = [
            {
                **c,
                "comment_body": self._translate_field(
                    f"comments[{i}].comment_body",
                    c["comment_body"],
                    thread_id=thread_id,
                    stats=stats,
                ),
            }
            for i, c in enumerate(reddit_content.get("comments", []))
        ]

        out["author_gender"] = author_gender

        # End-of-run summary (Req 13.4)
        print_substep(
            f"[translation] done — "
            f"anthropic_calls={stats.calls} "
            f"cache_hits={stats.cache_hits} "
            f"input_chars={stats.input_chars}"
        )

        return out

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_client(self) -> Any:
        """Construct Anthropic_Client using the resolved API key."""
        from utils.translation.anthropic_client import Anthropic_Client

        return Anthropic_Client(
            api_key=self.config.resolve_api_key(),
            model=self.config.model,
            max_output_tokens=self.config.max_output_tokens,
        )

    def _translate_field(
        self,
        field_name: str,
        text: str,
        *,
        thread_id: str,
        stats: _TranslationStats,
    ) -> str:
        """Translate a single field: cache → Anthropic → cache write → sanitize.

        Args:
            field_name: Human-readable field identifier for logging/errors.
            text: Source text to translate.
            thread_id: Thread identifier for cache keying.
            stats: Mutable stats object updated in-place.

        Returns:
            Translated (and sanitized) text, or original on failure under
            ``skip`` policy.
        """
        # Cache read (Req 7.2)
        if self._cache is not None:
            cached = self._cache.get(
                thread_id=thread_id,
                text=text,
                target_lang=self.config.target_lang,
                model_id=self.config.model,
            )
            if cached is not None:
                # Per-cache-hit log (Req 13.3)
                print_substep(f"[translation] cache hit: {field_name}")
                stats.cache_hits += 1
                return self._sanitize_or_fallback(field_name, cached, text)

        # Anthropic call (Req 6.1, 6.2)
        try:
            translated = self._client.translate(text, target_lang=self.config.target_lang)
        except TranslationError as e:
            return self._apply_field_failure_policy(field_name, text, e)

        # Cache write (Req 7.4, 7.5)
        if self._cache is not None:
            try:
                self._cache.put(
                    thread_id=thread_id,
                    text=text,
                    target_lang=self.config.target_lang,
                    model_id=self.config.model,
                    translation=translated,
                )
            except OSError as e:
                print_substep(
                    f"[translation] [warn] cache write failed for {field_name}: "
                    f"{type(e).__name__}: {e}",
                    style="yellow",
                )

        # Per-call log (Req 13.2)
        stats.calls += 1
        stats.input_chars += len(text)
        print_substep(
            f"[translation] translated {field_name}: "
            f"{len(text)} -> {len(translated)} chars"
        )

        return self._sanitize_or_fallback(field_name, translated, text)

    def _apply_field_failure_policy(
        self, field_name: str, original: str, error: TranslationError
    ) -> str:
        """Apply failure_policy for a single-field translation error.

        Under ``skip``: warn and return original (Req 6.1, 6.4).
        Under ``fail``: re-raise with field name and error class (Req 6.2).
        """
        if self.config.failure_policy == "skip":
            print_substep(
                f"[translation] [warn] skipping {field_name}: "
                f"{type(error).__name__}: {error}",
                style="yellow",
            )
            return original
        else:
            raise type(error)(
                f"Translation failed for field {field_name!r}: "
                f"{type(error).__name__}: {error}"
            ) from error

    def _apply_top_level_failure_policy(
        self,
        reddit_content: dict[str, Any],
        field: str,
        error: TranslationError,
    ) -> dict[str, Any]:
        """Apply failure_policy for top-level errors (API key missing, detect failure).

        Under ``skip``: warn and return input unchanged (Req 6.1, 6.4).
        Under ``fail``: re-raise (Req 6.2).
        """
        if self.config.failure_policy == "skip":
            print_substep(
                f"[translation] [warn] skipping translation ({field}): "
                f"{type(error).__name__}: {error}",
                style="yellow",
            )
            return reddit_content
        else:
            raise type(error)(
                f"Translation failed ({field}): "
                f"{type(error).__name__}: {error}"
            ) from error

    def _build_detection_sample(self, reddit_content: dict[str, Any]) -> str:
        """Build a compact sample string for source-language detection (Req 5.1, 5.3).

        Format:
            TITLE: <thread_title>
            BODY: <thread_post truncated to 500 chars>
            COMMENT 1: <comments[0].comment_body truncated to 200 chars>
            COMMENT 2: <comments[1].comment_body truncated to 200 chars>
            COMMENT 3: <comments[2].comment_body truncated to 200 chars>

        Returns:
            A single string under ~1.5 KB suitable for one detection call.
        """
        parts: list[str] = []

        title = reddit_content.get("thread_title", "") or ""
        parts.append(f"TITLE: {title}")

        body = reddit_content.get("thread_post", "") or ""
        if isinstance(body, str) and body:
            truncated_body = self._truncate_on_word_boundary(body, 500)
            parts.append(f"BODY: {truncated_body}")

        comments = reddit_content.get("comments", []) or []
        comment_count = 0
        for c in comments:
            if comment_count >= 3:
                break
            body_text = (c.get("comment_body", "") or "").strip()
            if not body_text:
                continue
            truncated = self._truncate_on_word_boundary(body_text, 200)
            comment_count += 1
            parts.append(f"COMMENT {comment_count}: {truncated}")

        return "\n".join(parts)

    @staticmethod
    def _truncate_on_word_boundary(text: str, max_chars: int) -> str:
        """Truncate text to at most max_chars, preferring a word boundary."""
        if len(text) <= max_chars:
            return text
        truncated = text[:max_chars]
        # Try to end on a word boundary
        last_space = truncated.rfind(" ")
        if last_space > max_chars // 2:
            return truncated[:last_space]
        return truncated

    @staticmethod
    def _lang_matches(src: str, target: str) -> bool:
        """Return True if src and target represent the same language (Req 5.2).

        Comparison is case-insensitive.
        """
        return src.lower() == target.lower()

    @staticmethod
    def _apply_abbreviation_fixes(text: str, *, last_sentence_only: bool = False) -> str:
        """Replace known untranslated abbreviations with their English equivalents.

        When *last_sentence_only* is True, only the final sentence of *text* is
        processed; the rest is returned unchanged.  This is used for
        ``thread_post`` where only the closing verdict line matters.

        The fix table is ``_ABBREV_FIXES`` at module level — add entries there.
        """
        if not text:
            return text

        if last_sentence_only:
            # Find the last sentence boundary: a sentence-ending char (. ! ?)
            # followed by whitespace and a non-whitespace char.  We want the
            # *last* such boundary so we iterate all matches.
            boundaries = list(re.finditer(r'(?<=[.!?])\s+(?=\S)', text))
            if boundaries:
                last = boundaries[-1]
                prefix = text[:last.end()]   # everything up to and including the whitespace
                sentence = text[last.end():]  # the final sentence
                fixed = sentence
                for pattern, replacement in _ABBREV_FIXES:
                    fixed = pattern.sub(replacement, fixed)
                return prefix + fixed
            # No sentence boundary — fix the whole string

        result = text
        for pattern, replacement in _ABBREV_FIXES:
            result = pattern.sub(replacement, result)
        return result

    def _sanitize_or_fallback(
        self, field_name: str, translated: str, original: str
    ) -> str:
        """Apply sanitize_text; substitute original on collapse (Req 14.1, 14.2).

        Args:
            field_name: Field identifier for warning messages.
            translated: The translated text to sanitize.
            original: The original (pre-translation) text to fall back to.

        Returns:
            Sanitized translated text, or original if sanitization collapses
            the result to empty/whitespace.
        """
        from utils.voice import sanitize_text

        result = sanitize_text(translated)
        if not result or not result.strip():
            print_substep(
                f"[translation] [warn] sanitizer collapsed {field_name}; "
                f"substituting original",
                style="yellow",
            )
            return original
        return result
