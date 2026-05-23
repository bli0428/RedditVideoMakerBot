"""Property-based tests for source==target no-op behaviour.

**Property 5: Source==target no-op**
**Validates: Requirements 5.2, 8.4**

When ``force_translate=False`` and the detector returns a language tag that
matches ``target_lang`` (case-insensitive), ``Translation_Service.translate``
must:

1. Never call ``Anthropic_Client.translate`` (no translation work is done).
2. Return a dict whose Translatable_Field values are identical to the input
   values (thread_title, thread_post, comments[*].comment_body).

The mock strategy:
- ``_build_client`` on ``Translation_Service`` is patched to return a
  ``MagicMock`` whose ``detect_source_language`` returns a tag equal to
  ``target_lang.lower()``.
- ``translate`` on that mock is tracked so we can assert it is never called.
"""
from __future__ import annotations

import sys
from typing import Any
from unittest.mock import MagicMock, patch

from hypothesis import given, settings
from hypothesis import strategies as st

from utils.translation.config import (
    DEFAULT_MAX_OUTPUT_TOKENS,
    DEFAULT_MODEL,
    TranslationConfig,
)
from utils.translation.service import Translation_Service

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Non-empty target language codes (BCP-47 / ISO 639-1 style).
_target_lang_strategy = st.sampled_from(["es", "fr", "de", "ja", "pt-BR", "zh-CN", "EN", "Es"])

# A single comment dict with non-empty body so the service iterates over it.
_comment_strategy = st.fixed_dictionaries(
    {
        "comment_id": st.text(min_size=1, max_size=32),
        "comment_body": st.text(min_size=1, max_size=500),
        "comment_url": st.text(max_size=200),
        "author": st.text(max_size=64),
    }
)

# Reddit_Content with non-empty thread_title, string thread_post, and comments.
_reddit_content_strategy = st.fixed_dictionaries(
    {
        "thread_title": st.text(min_size=1, max_size=300),
        "thread_post": st.text(min_size=1, max_size=2000),
        "comments": st.lists(_comment_strategy, min_size=1, max_size=5),
        # Structural fields
        "thread_id": st.text(min_size=1, max_size=32),
        "thread_url": st.text(max_size=200),
        "permalink": st.text(max_size=200),
        "author": st.text(max_size=64),
        "is_nsfw": st.booleans(),
        "subreddit": st.text(max_size=64),
    }
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(target_lang: str) -> TranslationConfig:
    """Build a TranslationConfig with provider='anthropic', force_translate=False."""
    return TranslationConfig(
        provider="anthropic",
        effective_provider="anthropic",
        target_lang=target_lang,
        failure_policy="skip",
        cache_enabled=False,
        force_translate=False,
        model=DEFAULT_MODEL,
        max_output_tokens=DEFAULT_MAX_OUTPUT_TOKENS,
        api_key="test-key",
    )


def _make_mock_client(detected_lang: str) -> MagicMock:
    """Return a mock Anthropic_Client whose detect_source_language returns
    ``detected_lang`` and whose translate method is tracked."""
    mock_client = MagicMock()
    mock_client.detect_source_language.return_value = detected_lang
    return mock_client


# ---------------------------------------------------------------------------
# Property 5a: translate() is never called when source == target (Req 5.2)
# ---------------------------------------------------------------------------


@given(
    content=_reddit_content_strategy,
    target_lang=_target_lang_strategy,
)
@settings(max_examples=200)
def test_translate_not_called_when_source_matches_target(
    content: dict[str, Any],
    target_lang: str,
) -> None:
    """**Property 5: Source==target no-op**
    **Validates: Requirements 5.2, 8.4**

    When the detector returns a tag equal to ``target_lang.lower()``,
    ``Anthropic_Client.translate`` must never be called.
    """
    config = _make_config(target_lang)
    # The detected language matches the target (case-insensitive).
    detected = target_lang.lower()
    mock_client = _make_mock_client(detected)

    service = Translation_Service(config)
    # Inject the mock client directly so _build_client is never called.
    service._client = mock_client

    service.translate(content)

    mock_client.translate.assert_not_called(), (
        f"Expected Anthropic_Client.translate to never be called when "
        f"detected language {detected!r} matches target_lang {target_lang!r}, "
        f"but it was called {mock_client.translate.call_count} time(s)."
    )


# ---------------------------------------------------------------------------
# Property 5b: Translatable_Field values equal input values (Req 8.4)
# ---------------------------------------------------------------------------


@given(
    content=_reddit_content_strategy,
    target_lang=_target_lang_strategy,
)
@settings(max_examples=200)
def test_translatable_fields_unchanged_when_source_matches_target(
    content: dict[str, Any],
    target_lang: str,
) -> None:
    """**Property 5: Source==target no-op**
    **Validates: Requirements 5.2, 8.4**

    When source == target, the output Translatable_Field values must equal
    the input values: thread_title, thread_post, and every
    comments[*].comment_body.
    """
    config = _make_config(target_lang)
    detected = target_lang.lower()
    mock_client = _make_mock_client(detected)

    service = Translation_Service(config)
    service._client = mock_client

    result = service.translate(content)

    # thread_title must be unchanged
    assert result["thread_title"] == content["thread_title"], (
        f"thread_title changed in source==target no-op. "
        f"Input: {content['thread_title']!r}, Output: {result['thread_title']!r}"
    )

    # thread_post must be unchanged
    assert result["thread_post"] == content["thread_post"], (
        f"thread_post changed in source==target no-op. "
        f"Input: {content['thread_post']!r}, Output: {result['thread_post']!r}"
    )

    # Every comment_body must be unchanged
    input_comments = content.get("comments", [])
    output_comments = result.get("comments", [])
    assert len(output_comments) == len(input_comments), (
        f"Comment list length changed in source==target no-op. "
        f"Input: {len(input_comments)}, Output: {len(output_comments)}"
    )
    for i, (in_c, out_c) in enumerate(zip(input_comments, output_comments)):
        assert out_c["comment_body"] == in_c["comment_body"], (
            f"comments[{i}].comment_body changed in source==target no-op. "
            f"Input: {in_c['comment_body']!r}, Output: {out_c['comment_body']!r}"
        )


# ---------------------------------------------------------------------------
# Property 5c: Combined — no translate call AND values unchanged (Req 5.2, 8.4)
# ---------------------------------------------------------------------------


@given(
    content=_reddit_content_strategy,
    target_lang=_target_lang_strategy,
)
@settings(max_examples=300)
def test_source_target_noop_combined(
    content: dict[str, Any],
    target_lang: str,
) -> None:
    """**Property 5: Source==target no-op**
    **Validates: Requirements 5.2, 8.4**

    Combined assertion: when source == target (case-insensitive), both
    invariants hold simultaneously:
    1. ``Anthropic_Client.translate`` is never called.
    2. All Translatable_Field values in the output equal the input values.
    """
    config = _make_config(target_lang)
    detected = target_lang.lower()
    mock_client = _make_mock_client(detected)

    service = Translation_Service(config)
    service._client = mock_client

    result = service.translate(content)

    # Invariant 1: translate never called
    assert mock_client.translate.call_count == 0, (
        f"Anthropic_Client.translate was called {mock_client.translate.call_count} "
        f"time(s) when source ({detected!r}) == target ({target_lang!r})."
    )

    # Invariant 2: Translatable_Field values unchanged
    assert result["thread_title"] == content["thread_title"], (
        f"thread_title changed. Input: {content['thread_title']!r}, "
        f"Output: {result['thread_title']!r}"
    )
    assert result["thread_post"] == content["thread_post"], (
        f"thread_post changed. Input: {content['thread_post']!r}, "
        f"Output: {result['thread_post']!r}"
    )
    for i, (in_c, out_c) in enumerate(
        zip(content.get("comments", []), result.get("comments", []))
    ):
        assert out_c["comment_body"] == in_c["comment_body"], (
            f"comments[{i}].comment_body changed. "
            f"Input: {in_c['comment_body']!r}, Output: {out_c['comment_body']!r}"
        )


# ---------------------------------------------------------------------------
# Property 5d: Case-insensitive match — uppercase/mixed-case target_lang
#              still triggers the no-op (Req 5.2)
# ---------------------------------------------------------------------------


@given(
    content=_reddit_content_strategy,
    base_lang=st.sampled_from(["es", "fr", "de", "ja", "en"]),
)
@settings(max_examples=150)
def test_case_insensitive_match_triggers_noop(
    content: dict[str, Any],
    base_lang: str,
) -> None:
    """**Property 5: Source==target no-op**
    **Validates: Requirements 5.2**

    The source==target comparison is case-insensitive (Req 5.2 / _lang_matches).
    When the detector returns ``base_lang.lower()`` and target_lang is the
    same string in any case variant, translate must not be called.
    """
    # Use the uppercase variant as target_lang to exercise case-insensitivity.
    target_lang = base_lang.upper()
    detected = base_lang.lower()  # detector always returns lowercase

    config = _make_config(target_lang)
    mock_client = _make_mock_client(detected)

    service = Translation_Service(config)
    service._client = mock_client

    result = service.translate(content)

    assert mock_client.translate.call_count == 0, (
        f"translate was called despite case-insensitive match: "
        f"detected={detected!r}, target_lang={target_lang!r}"
    )
    assert result["thread_title"] == content["thread_title"]
    assert result["thread_post"] == content["thread_post"]


# ---------------------------------------------------------------------------
# Property 5e: _build_client path — patch _build_client to inject mock
#              (verifies the service wires the mock correctly via _build_client)
# ---------------------------------------------------------------------------


@given(
    content=_reddit_content_strategy,
    target_lang=_target_lang_strategy,
)
@settings(max_examples=100)
def test_source_target_noop_via_build_client_patch(
    content: dict[str, Any],
    target_lang: str,
) -> None:
    """**Property 5: Source==target no-op**
    **Validates: Requirements 5.2, 8.4**

    Same invariants as Property 5c, but the mock is injected via patching
    ``Translation_Service._build_client`` rather than setting ``_client``
    directly, to exercise the lazy-construction path.
    """
    config = _make_config(target_lang)
    detected = target_lang.lower()
    mock_client = _make_mock_client(detected)

    service = Translation_Service(config)

    with patch.object(service, "_build_client", return_value=mock_client):
        result = service.translate(content)

    assert mock_client.translate.call_count == 0, (
        f"translate was called {mock_client.translate.call_count} time(s) "
        f"when source ({detected!r}) == target ({target_lang!r})."
    )
    assert result["thread_title"] == content["thread_title"]
    assert result["thread_post"] == content["thread_post"]
    for i, (in_c, out_c) in enumerate(
        zip(content.get("comments", []), result.get("comments", []))
    ):
        assert out_c["comment_body"] == in_c["comment_body"], (
            f"comments[{i}].comment_body changed via _build_client patch path."
        )
