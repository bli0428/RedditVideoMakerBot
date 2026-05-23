"""Property-based tests for full Translatable_Field coverage.

**Property 8: All Translatable_Fields are translated**
**Validates: Requirements 4.1, 4.2, 4.3, 4.4, 14.1**

Hypothesis-generate inputs with non-empty ``thread_title``, string
``thread_post``, and a non-empty ``comments`` list; assert each translated
value equals ``sanitize_text(mocked_client.translate(corresponding_input))``
and that ``output["thread_post"]`` is a ``str``.

The mock client:
  - ``translate(text, target_lang)`` returns ``"TRANSLATED:" + text``
  - ``detect_source_language`` is not called (``force_translate=True``)

``utils.voice.sanitize_text`` is patched to return its input unchanged so
the expected value is simply ``"TRANSLATED:" + original_text``.
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
# Strategies
# ---------------------------------------------------------------------------

# A single comment dict — comment_body must be non-empty so it is translated.
_comment_strategy = st.fixed_dictionaries(
    {
        "comment_id": st.text(min_size=1, max_size=32),
        "comment_url": st.text(max_size=200),
        "comment_body": st.text(min_size=1, max_size=500),
        "author": st.text(max_size=64),
    }
)

# Reddit_Content dict with non-empty translatable fields and at least one comment.
_reddit_content_strategy = st.fixed_dictionaries(
    {
        # Translatable fields — all non-empty so translation is exercised.
        "thread_title": st.text(min_size=1, max_size=300),
        "thread_post": st.text(min_size=1, max_size=2000),  # str only (Req 4.7)
        "comments": st.lists(_comment_strategy, min_size=1, max_size=5),
        # Structural fields — preserved byte-for-byte.
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


def _make_config() -> TranslationConfig:
    """Build a TranslationConfig with provider='anthropic', force_translate=True,
    and cache disabled so every field goes through the Anthropic_Client mock."""
    return TranslationConfig(
        provider="anthropic",
        effective_provider="anthropic",
        target_lang="es",
        failure_policy="skip",
        cache_enabled=False,
        force_translate=True,
        model=DEFAULT_MODEL,
        max_output_tokens=DEFAULT_MAX_OUTPUT_TOKENS,
        api_key="test-key",
    )


def _make_mock_client() -> MagicMock:
    """Return a mock Anthropic_Client whose translate() prepends 'TRANSLATED:'.

    detect_source_language is not called because force_translate=True, but we
    configure it anyway to catch unexpected calls.
    """
    mock_client = MagicMock()
    mock_client.translate.side_effect = lambda text, target_lang: "TRANSLATED:" + text
    mock_client.detect_source_language.side_effect = AssertionError(
        "detect_source_language must not be called when force_translate=True"
    )
    return mock_client


def _make_fake_voice_module() -> types.ModuleType:
    """Return a lightweight fake ``utils.voice`` module with identity sanitize_text.

    ``utils.voice`` imports ``cleantext`` which may not be installed in the test
    environment. We inject a stub module into ``sys.modules`` so the lazy import
    inside ``_sanitize_or_fallback`` resolves without touching the real file.
    """
    mod = types.ModuleType("utils.voice")
    mod.sanitize_text = lambda text: text  # identity — return input unchanged
    return mod


# ---------------------------------------------------------------------------
# Property 8a: thread_title is translated (Req 4.1)
# ---------------------------------------------------------------------------


@given(content=_reddit_content_strategy)
@settings(max_examples=150)
def test_thread_title_is_translated(content: dict[str, Any]) -> None:
    """**Property 8: All Translatable_Fields are translated**
    **Validates: Requirements 4.1, 14.1**

    ``output["thread_title"]`` must equal ``"TRANSLATED:" + input["thread_title"]``
    after sanitize_text (which is patched to be identity here).
    """
    config = _make_config()
    mock_client = _make_mock_client()
    fake_voice = _make_fake_voice_module()

    with (
        patch.dict(sys.modules, {"utils.voice": fake_voice}),
        patch(
            "utils.translation.service.Translation_Service._build_client",
            return_value=mock_client,
        ),
    ):
        service = Translation_Service(config)
        result = service.translate(content)

    expected = "TRANSLATED:" + content["thread_title"]
    assert result["thread_title"] == expected, (
        f"thread_title not translated correctly.\n"
        f"Input:    {content['thread_title']!r}\n"
        f"Expected: {expected!r}\n"
        f"Got:      {result['thread_title']!r}"
    )


# ---------------------------------------------------------------------------
# Property 8b: thread_post is translated and remains a str (Req 4.2, 4.4)
# ---------------------------------------------------------------------------


@given(content=_reddit_content_strategy)
@settings(max_examples=150)
def test_thread_post_is_translated_and_is_str(content: dict[str, Any]) -> None:
    """**Property 8: All Translatable_Fields are translated**
    **Validates: Requirements 4.2, 4.4, 14.1**

    ``output["thread_post"]`` must equal ``"TRANSLATED:" + input["thread_post"]``
    and must be a ``str``.
    """
    config = _make_config()
    mock_client = _make_mock_client()
    fake_voice = _make_fake_voice_module()

    with (
        patch.dict(sys.modules, {"utils.voice": fake_voice}),
        patch(
            "utils.translation.service.Translation_Service._build_client",
            return_value=mock_client,
        ),
    ):
        service = Translation_Service(config)
        result = service.translate(content)

    expected = "TRANSLATED:" + content["thread_post"]
    assert isinstance(result["thread_post"], str), (
        f"output['thread_post'] must be a str, "
        f"got {type(result['thread_post']).__name__!r}"
    )
    assert result["thread_post"] == expected, (
        f"thread_post not translated correctly.\n"
        f"Input:    {content['thread_post']!r}\n"
        f"Expected: {expected!r}\n"
        f"Got:      {result['thread_post']!r}"
    )


# ---------------------------------------------------------------------------
# Property 8c: every comment_body is translated (Req 4.3)
# ---------------------------------------------------------------------------


@given(content=_reddit_content_strategy)
@settings(max_examples=150)
def test_all_comment_bodies_are_translated(content: dict[str, Any]) -> None:
    """**Property 8: All Translatable_Fields are translated**
    **Validates: Requirements 4.3, 14.1**

    For every comment in the input, ``output_comment["comment_body"]`` must
    equal ``"TRANSLATED:" + input_comment["comment_body"]``.
    """
    config = _make_config()
    mock_client = _make_mock_client()
    fake_voice = _make_fake_voice_module()

    with (
        patch.dict(sys.modules, {"utils.voice": fake_voice}),
        patch(
            "utils.translation.service.Translation_Service._build_client",
            return_value=mock_client,
        ),
    ):
        service = Translation_Service(config)
        result = service.translate(content)

    input_comments = content["comments"]
    output_comments = result["comments"]

    assert len(output_comments) == len(input_comments), (
        f"Comment list length changed: "
        f"input={len(input_comments)}, output={len(output_comments)}"
    )

    for i, (in_c, out_c) in enumerate(zip(input_comments, output_comments)):
        expected_body = "TRANSLATED:" + in_c["comment_body"]
        assert out_c["comment_body"] == expected_body, (
            f"comments[{i}].comment_body not translated correctly.\n"
            f"Input:    {in_c['comment_body']!r}\n"
            f"Expected: {expected_body!r}\n"
            f"Got:      {out_c['comment_body']!r}"
        )


# ---------------------------------------------------------------------------
# Property 8d: all three Translatable_Fields translated simultaneously (Req 4.1–4.4)
# ---------------------------------------------------------------------------


@given(content=_reddit_content_strategy)
@settings(max_examples=200)
def test_all_translatable_fields_translated_simultaneously(
    content: dict[str, Any],
) -> None:
    """**Property 8: All Translatable_Fields are translated**
    **Validates: Requirements 4.1, 4.2, 4.3, 4.4, 14.1**

    Comprehensive check: thread_title, thread_post, and every comment_body
    are all translated in a single translate() call, and thread_post remains
    a str.
    """
    config = _make_config()
    mock_client = _make_mock_client()
    fake_voice = _make_fake_voice_module()

    with (
        patch.dict(sys.modules, {"utils.voice": fake_voice}),
        patch(
            "utils.translation.service.Translation_Service._build_client",
            return_value=mock_client,
        ),
    ):
        service = Translation_Service(config)
        result = service.translate(content)

    # thread_title (Req 4.1)
    assert result["thread_title"] == "TRANSLATED:" + content["thread_title"], (
        f"thread_title mismatch: expected 'TRANSLATED:{content['thread_title']}', "
        f"got {result['thread_title']!r}"
    )

    # thread_post (Req 4.2, 4.4)
    assert isinstance(result["thread_post"], str), (
        f"output['thread_post'] must be str, got {type(result['thread_post']).__name__}"
    )
    assert result["thread_post"] == "TRANSLATED:" + content["thread_post"], (
        f"thread_post mismatch: expected 'TRANSLATED:{content['thread_post']}', "
        f"got {result['thread_post']!r}"
    )

    # comment_body for every comment (Req 4.3)
    assert len(result["comments"]) == len(content["comments"]), (
        f"Comment count changed: {len(content['comments'])} -> {len(result['comments'])}"
    )
    for i, (in_c, out_c) in enumerate(zip(content["comments"], result["comments"])):
        expected_body = "TRANSLATED:" + in_c["comment_body"]
        assert out_c["comment_body"] == expected_body, (
            f"comments[{i}].comment_body mismatch: "
            f"expected {expected_body!r}, got {out_c['comment_body']!r}"
        )


# ---------------------------------------------------------------------------
# Property 8e: translate() is called exactly once per Translatable_Field
# ---------------------------------------------------------------------------


@given(content=_reddit_content_strategy)
@settings(max_examples=100)
def test_translate_called_once_per_translatable_field(
    content: dict[str, Any],
) -> None:
    """**Property 8: All Translatable_Fields are translated**
    **Validates: Requirements 4.1, 4.2, 4.3**

    The mock client's ``translate`` method must be called exactly
    ``2 + len(comments)`` times: once for thread_title, once for thread_post,
    and once per comment_body.
    """
    config = _make_config()
    mock_client = _make_mock_client()
    fake_voice = _make_fake_voice_module()

    with (
        patch.dict(sys.modules, {"utils.voice": fake_voice}),
        patch(
            "utils.translation.service.Translation_Service._build_client",
            return_value=mock_client,
        ),
    ):
        service = Translation_Service(config)
        service.translate(content)

    expected_calls = 2 + len(content["comments"])  # title + post + N comments
    assert mock_client.translate.call_count == expected_calls, (
        f"Expected {expected_calls} translate() calls "
        f"(1 title + 1 post + {len(content['comments'])} comments), "
        f"got {mock_client.translate.call_count}"
    )
