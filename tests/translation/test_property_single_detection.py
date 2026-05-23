"""Property-based test for single-call source-language detection.

**Property 7: Detection is single-call per Reddit_Content**
**Validates: Requirements 5.3**

Hypothesis-generate inputs with ``force_translate = False`` and source != target;
assert ``detect_source_language`` is called exactly once regardless of the
number of Translatable_Fields (i.e., regardless of comment count).

Requirement 5.3:
    THE Translation_Service SHALL perform Source_Language detection in a single
    Anthropic call per Reddit_Content, not once per Translatable_Field.

``utils.voice`` is injected into ``sys.modules`` because it has a hard
dependency on ``cleantext`` which may not be installed in the test environment.
"""
from __future__ import annotations

import sys
import types
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
# Fake utils.voice module
# ---------------------------------------------------------------------------


def _make_fake_voice_module() -> types.ModuleType:
    """Return a fake ``utils.voice`` module whose ``sanitize_text`` is the
    identity function.  Injected into ``sys.modules`` so the lazy
    ``from utils.voice import sanitize_text`` inside
    ``Translation_Service._sanitize_or_fallback`` resolves without importing
    the real module (which requires ``cleantext``).
    """
    mod = types.ModuleType("utils.voice")
    mod.sanitize_text = lambda text: text  # type: ignore[attr-defined]
    return mod


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# A single comment dict with the required fields.
_comment_strategy = st.fixed_dictionaries(
    {
        "comment_id": st.text(min_size=1, max_size=32),
        "comment_body": st.text(min_size=1, max_size=500),
        "comment_url": st.text(max_size=200),
        "author": st.text(max_size=64),
    }
)

# Reddit_Content with a variable number of comments (0–10).
_reddit_content_strategy = st.fixed_dictionaries(
    {
        "thread_title": st.text(min_size=1, max_size=300),
        "thread_post": st.text(min_size=1, max_size=2000),
        "comments": st.lists(_comment_strategy, min_size=0, max_size=10),
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

def _make_config(*, force_translate: bool = False) -> TranslationConfig:
    """Build a TranslationConfig for the anthropic provider targeting Spanish."""
    return TranslationConfig(
        provider="anthropic",
        effective_provider="anthropic",
        target_lang="es",
        failure_policy="skip",
        cache_enabled=False,
        force_translate=force_translate,
        model=DEFAULT_MODEL,
        max_output_tokens=DEFAULT_MAX_OUTPUT_TOKENS,
        api_key="test-key",
    )


def _make_mock_client(detected_lang: str = "en") -> MagicMock:
    """Return a mock Anthropic_Client.

    - ``detect_source_language`` returns ``detected_lang`` (default "en",
      which differs from the target "es" so translation proceeds).
    - ``translate`` returns a non-empty string so sanitize_text won't collapse it.
    """
    mock_client = MagicMock()
    mock_client.detect_source_language.return_value = detected_lang
    mock_client.translate.return_value = "translated text"
    return mock_client


# ---------------------------------------------------------------------------
# Property 7: detect_source_language called exactly once per Reddit_Content
# ---------------------------------------------------------------------------


@given(content=_reddit_content_strategy)
@settings(max_examples=200)
def test_detect_source_language_called_exactly_once(content: dict[str, Any]) -> None:
    """**Property 7: Detection is single-call per Reddit_Content**
    **Validates: Requirements 5.3**

    Regardless of how many comments (Translatable_Fields) are present in the
    Reddit_Content, ``detect_source_language`` must be called exactly once per
    ``translate()`` invocation when ``force_translate=False`` and the detected
    source language differs from the target language.
    """
    config = _make_config(force_translate=False)
    mock_client = _make_mock_client(detected_lang="en")  # "en" != "es" → translation runs
    fake_voice = _make_fake_voice_module()

    with (
        patch(
            "utils.translation.service.Translation_Service._build_client",
            return_value=mock_client,
        ),
        patch.dict(sys.modules, {"utils.voice": fake_voice}),
    ):
        service = Translation_Service(config)
        service.translate(content)

    detect_call_count = mock_client.detect_source_language.call_count
    assert detect_call_count == 1, (
        f"Expected detect_source_language to be called exactly once, "
        f"but it was called {detect_call_count} time(s). "
        f"comment_count={len(content['comments'])}, "
        f"content={content!r}"
    )


@given(
    content=_reddit_content_strategy,
    num_comments=st.integers(min_value=0, max_value=10),
)
@settings(max_examples=200)
def test_detect_call_count_independent_of_comment_count(
    content: dict[str, Any],
    num_comments: int,
) -> None:
    """**Property 7: Detection is single-call per Reddit_Content**
    **Validates: Requirements 5.3**

    Explicitly vary the number of comments and assert that the detection call
    count is always exactly 1, independent of the number of Translatable_Fields.
    """
    # Build a comment list of the requested length.
    comments = [
        {
            "comment_id": f"c{i}",
            "comment_body": f"comment body {i}",
            "comment_url": f"https://reddit.com/c{i}",
            "author": f"user{i}",
        }
        for i in range(num_comments)
    ]
    content_with_n_comments = {**content, "comments": comments}

    config = _make_config(force_translate=False)
    mock_client = _make_mock_client(detected_lang="en")  # "en" != "es"
    fake_voice = _make_fake_voice_module()

    with (
        patch(
            "utils.translation.service.Translation_Service._build_client",
            return_value=mock_client,
        ),
        patch.dict(sys.modules, {"utils.voice": fake_voice}),
    ):
        service = Translation_Service(config)
        service.translate(content_with_n_comments)

    detect_call_count = mock_client.detect_source_language.call_count
    assert detect_call_count == 1, (
        f"Expected detect_source_language to be called exactly once, "
        f"but it was called {detect_call_count} time(s) "
        f"with {num_comments} comment(s)."
    )


@given(content=_reddit_content_strategy)
@settings(max_examples=100)
def test_force_translate_skips_detection_entirely(content: dict[str, Any]) -> None:
    """**Property 7: Detection is single-call per Reddit_Content**
    **Validates: Requirements 5.3, 5.4**

    Complementary check: when ``force_translate=True``, detection is skipped
    entirely (0 calls), confirming the single-call invariant is specific to
    the non-forced path.
    """
    config = _make_config(force_translate=True)
    mock_client = _make_mock_client(detected_lang="en")
    fake_voice = _make_fake_voice_module()

    with (
        patch(
            "utils.translation.service.Translation_Service._build_client",
            return_value=mock_client,
        ),
        patch.dict(sys.modules, {"utils.voice": fake_voice}),
    ):
        service = Translation_Service(config)
        service.translate(content)

    detect_call_count = mock_client.detect_source_language.call_count
    assert detect_call_count == 0, (
        f"Expected detect_source_language to be called 0 times when "
        f"force_translate=True, but it was called {detect_call_count} time(s)."
    )


@given(
    content=_reddit_content_strategy,
    comment_count=st.integers(min_value=0, max_value=10),
)
@settings(max_examples=150)
def test_translate_call_count_equals_translatable_field_count(
    content: dict[str, Any],
    comment_count: int,
) -> None:
    """**Property 7: Detection is single-call per Reddit_Content**
    **Validates: Requirements 5.3**

    Sanity check: while detection is called once, ``translate`` is called once
    per Translatable_Field (thread_title + thread_post + each comment_body).
    This confirms the single-detection invariant is not achieved by skipping
    translation calls.
    """
    comments = [
        {
            "comment_id": f"c{i}",
            "comment_body": f"comment body {i}",
            "comment_url": f"https://reddit.com/c{i}",
            "author": f"user{i}",
        }
        for i in range(comment_count)
    ]
    content_with_n_comments = {**content, "comments": comments}

    config = _make_config(force_translate=False)
    mock_client = _make_mock_client(detected_lang="en")  # "en" != "es"
    fake_voice = _make_fake_voice_module()

    with (
        patch(
            "utils.translation.service.Translation_Service._build_client",
            return_value=mock_client,
        ),
        patch.dict(sys.modules, {"utils.voice": fake_voice}),
    ):
        service = Translation_Service(config)
        service.translate(content_with_n_comments)

    # Detection: exactly 1 call.
    assert mock_client.detect_source_language.call_count == 1, (
        f"Expected exactly 1 detect call, "
        f"got {mock_client.detect_source_language.call_count}."
    )

    # Translation: 1 (thread_title) + 1 (thread_post, always str here) + comment_count.
    expected_translate_calls = 2 + comment_count
    actual_translate_calls = mock_client.translate.call_count
    assert actual_translate_calls == expected_translate_calls, (
        f"Expected {expected_translate_calls} translate call(s) "
        f"(thread_title + thread_post + {comment_count} comment(s)), "
        f"but got {actual_translate_calls}."
    )
