"""Property-based tests for cache hit short-circuiting Anthropic_Client.

**Property 18: Cache hit short-circuits Anthropic_Client**
**Validates: Requirements 7.2**

When ``cache_enabled = True``, a second call to ``translate`` with the same
input must:
  - NOT invoke ``client.translate`` at all (all fields are served from cache).
  - Invoke ``detect_source_language`` exactly once on the second call
    (detection is not cached to disk, but the second call still runs detection
    before consulting the field-level cache).
  - Return an output equal to the first call's output.

Strategy:
- Use a ``tempfile.TemporaryDirectory`` as the cache base directory so each
  test run starts with a clean, isolated cache.
- Inject a ``Translation_Cache`` backed by the temp dir into the service by
  setting ``service._cache`` directly after construction.
- Mock ``_build_client`` to return a tracked mock client.
- First call: ``translate(content)`` — client.translate is called for each
  Translatable_Field and results are written to the temp cache.
- Second call: ``translate(content)`` — all fields are cache hits, so
  client.translate is called zero times.
- Assert both outputs are equal.
- Assert ``detect_source_language`` was called exactly once on the second call
  (detection runs once per translate() invocation per Req 5.3; the cache only
  short-circuits the per-field translate calls, not detection).

Note on sanitize_text:
  ``utils.voice`` requires the ``cleantext`` package which may not be
  installed in the test environment. We mock the entire ``utils.voice`` module
  in ``sys.modules`` so the local import inside
  ``Translation_Service._sanitize_or_fallback`` resolves to our mock, making
  ``sanitize_text`` the identity function for these tests.
"""
from __future__ import annotations

import sys
import tempfile
from typing import Any
from unittest.mock import MagicMock, patch

from hypothesis import given, settings
from hypothesis import strategies as st

from utils.translation.cache import Translation_Cache
from utils.translation.config import (
    DEFAULT_MAX_OUTPUT_TOKENS,
    DEFAULT_MODEL,
    TranslationConfig,
)
from utils.translation.service import Translation_Service

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_comment_strategy = st.fixed_dictionaries(
    {
        "comment_id": st.text(min_size=1, max_size=32),
        "comment_body": st.text(min_size=1, max_size=200),
        "comment_url": st.text(max_size=200),
        "author": st.text(max_size=64),
    }
)

_reddit_content_strategy = st.fixed_dictionaries(
    {
        # Translatable fields — must be non-empty strings so translation proceeds
        "thread_title": st.text(min_size=1, max_size=200),
        "thread_post": st.text(min_size=1, max_size=500),
        "comments": st.lists(_comment_strategy, min_size=0, max_size=3),
        # Structural fields
        "thread_id": st.text(
            alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd")),
            min_size=1,
            max_size=32,
        ),
        "thread_url": st.text(max_size=200),
        "permalink": st.text(max_size=200),
        "author": st.text(max_size=64),
        "is_nsfw": st.booleans(),
        "subreddit": st.text(max_size=64),
    }
)

_target_lang_strategy = st.sampled_from(["es", "fr", "de", "ja", "pt-BR", "zh-CN"])

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(target_lang: str, cache_enabled: bool = True) -> TranslationConfig:
    """Build a TranslationConfig with provider='anthropic' and cache enabled."""
    return TranslationConfig(
        provider="anthropic",
        effective_provider="anthropic",
        target_lang=target_lang,
        failure_policy="skip",
        cache_enabled=cache_enabled,
        force_translate=False,
        model=DEFAULT_MODEL,
        max_output_tokens=DEFAULT_MAX_OUTPUT_TOKENS,
        api_key="test-key",
    )


def _make_mock_client() -> MagicMock:
    """Return a mock Anthropic_Client with tracked calls.

    - ``detect_source_language`` returns ``"en"`` (different from any
      target_lang in ``_target_lang_strategy``), so translation always proceeds.
    - ``translate(text, target_lang)`` returns ``"translated: " + text``
      deterministically so the cache can store and retrieve it.
    """
    mock_client = MagicMock()
    mock_client.detect_source_language.return_value = "en"
    mock_client.translate.side_effect = lambda text, target_lang: f"translated: {text}"
    return mock_client


def _make_mock_voice_module() -> MagicMock:
    """Return a mock utils.voice module with sanitize_text as the identity function.

    ``utils.voice`` requires ``cleantext`` which may not be installed in the
    test environment. We mock the whole module so the local import inside
    ``Translation_Service._sanitize_or_fallback`` resolves without error.
    """
    mock_voice = MagicMock()
    mock_voice.sanitize_text.side_effect = lambda text: text
    return mock_voice


# ---------------------------------------------------------------------------
# Property 18: Cache hit short-circuits Anthropic_Client (Req 7.2)
# ---------------------------------------------------------------------------


@given(
    content=_reddit_content_strategy,
    target_lang=_target_lang_strategy,
)
@settings(max_examples=50)
def test_cache_hit_short_circuits_client_translate(
    content: dict[str, Any],
    target_lang: str,
) -> None:
    """**Property 18: Cache hit short-circuits Anthropic_Client**
    **Validates: Requirements 7.2**

    After a first ``translate`` call populates the cache, a second call with
    the same input must NOT invoke ``client.translate`` at all (every field is
    served from the on-disk cache).

    Both outputs must be equal.
    """
    config = _make_config(target_lang=target_lang, cache_enabled=True)
    mock_voice = _make_mock_voice_module()

    with tempfile.TemporaryDirectory() as tmp_dir:
        # Build a cache backed by the temp directory
        cache = Translation_Cache(base_dir=tmp_dir)
        mock_client = _make_mock_client()

        # Patch _build_client so the service uses our mock, inject the
        # temp-dir-backed cache directly, and mock utils.voice so the local
        # import inside _sanitize_or_fallback resolves without cleantext.
        with patch.dict(sys.modules, {"utils.voice": mock_voice}), patch(
            "utils.translation.service.Translation_Service._build_client",
            return_value=mock_client,
        ):
            service = Translation_Service(config)
            # Inject the temp-dir cache, overriding the default one
            service._cache = cache

            # First call: populates the cache
            result1 = service.translate(content)

            # Record how many translate calls happened on the first pass
            first_call_translate_count = mock_client.translate.call_count

            # Reset the call counts so we can measure the second call in isolation
            mock_client.translate.reset_mock()
            mock_client.detect_source_language.reset_mock()

            # Second call: all fields should be cache hits
            result2 = service.translate(content)

            second_call_translate_count = mock_client.translate.call_count
            second_call_detect_count = mock_client.detect_source_language.call_count

    # The first call must have translated at least thread_title
    assert first_call_translate_count >= 1, (
        f"Expected at least one client.translate call on the first pass, "
        f"got {first_call_translate_count}. "
        f"target_lang={target_lang!r}"
    )

    # The second call must NOT invoke client.translate (all cache hits)
    assert second_call_translate_count == 0, (
        f"Expected client.translate to be called 0 times on the second pass "
        f"(all fields should be cache hits), but it was called "
        f"{second_call_translate_count} time(s). "
        f"target_lang={target_lang!r}, thread_id={content.get('thread_id')!r}"
    )

    # detect_source_language is called once per translate() invocation
    # (Req 5.3); the second call still detects but then hits the cache for
    # every field.
    assert second_call_detect_count == 1, (
        f"Expected detect_source_language to be called exactly once on the "
        f"second pass, but it was called {second_call_detect_count} time(s). "
        f"target_lang={target_lang!r}"
    )

    # Both outputs must be equal
    assert result1 == result2, (
        f"First and second translate() calls produced different outputs.\n"
        f"result1={result1!r}\n"
        f"result2={result2!r}"
    )


@given(
    content=_reddit_content_strategy,
    target_lang=_target_lang_strategy,
)
@settings(max_examples=30)
def test_cache_hit_total_detect_calls_across_two_invocations(
    content: dict[str, Any],
    target_lang: str,
) -> None:
    """**Property 18: Cache hit short-circuits Anthropic_Client**
    **Validates: Requirements 7.2**

    Complementary check: across both ``translate`` calls combined,
    ``detect_source_language`` is called exactly twice (once per invocation),
    confirming that detection is not skipped on the second call but that
    field-level translation IS skipped via the cache.
    """
    config = _make_config(target_lang=target_lang, cache_enabled=True)
    mock_voice = _make_mock_voice_module()

    with tempfile.TemporaryDirectory() as tmp_dir:
        cache = Translation_Cache(base_dir=tmp_dir)
        mock_client = _make_mock_client()

        with patch.dict(sys.modules, {"utils.voice": mock_voice}), patch(
            "utils.translation.service.Translation_Service._build_client",
            return_value=mock_client,
        ):
            service = Translation_Service(config)
            service._cache = cache

            service.translate(content)
            first_call_translate_count = mock_client.translate.call_count

            service.translate(content)
            total_detect_calls = mock_client.detect_source_language.call_count
            total_translate_calls = mock_client.translate.call_count

    # Detection runs once per translate() call → 2 total
    assert total_detect_calls == 2, (
        f"Expected detect_source_language to be called exactly 2 times total "
        f"(once per translate() invocation), but got {total_detect_calls}. "
        f"target_lang={target_lang!r}"
    )

    # All translate calls happen on the first pass; second pass is all cache hits.
    # The second call must not add any new translate calls beyond the first pass.
    assert total_translate_calls == first_call_translate_count, (
        f"Expected client.translate to be called exactly {first_call_translate_count} times "
        f"total (all on the first pass, zero on the second), but got "
        f"{total_translate_calls}. "
        f"target_lang={target_lang!r}, "
        f"comments={len(content.get('comments', []))}"
    )
