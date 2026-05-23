"""Property-based tests for TypeError on non-string thread_post.

**Property 9: TypeError on non-string thread_post**
**Validates: Requirements 4.7**

Hypothesis-generate non-str, non-None values (list, int, dict, bytes, float);
assert translate() raises TypeError whose message contains "thread_post" and
the actual type name.

Per Req 4.7, the TypeError is raised before any short-circuit (provider=none,
empty target_lang), so the check fires regardless of config.
"""
from __future__ import annotations

from typing import Any

import pytest
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

# Non-str, non-None values that should trigger TypeError.
non_str_non_none_strategy = st.one_of(
    st.lists(st.text(), max_size=5),          # list
    st.integers(),                             # int
    st.floats(allow_nan=False),               # float
    st.binary(max_size=32),                   # bytes
    st.dictionaries(st.text(max_size=10), st.text(max_size=10), max_size=5),  # dict
)

# A single comment dict with the required fields.
comment_strategy = st.fixed_dictionaries(
    {
        "comment_id": st.text(min_size=1, max_size=32),
        "comment_body": st.text(max_size=500),
        "comment_url": st.text(max_size=200),
        "author": st.text(max_size=64),
    }
)


def _make_reddit_content(thread_post_value: Any) -> dict[str, Any]:
    """Build a minimal Reddit_Content dict with the given thread_post value."""
    return {
        "thread_title": "Test title",
        "thread_post": thread_post_value,
        "comments": [],
        "thread_id": "abc123",
        "thread_url": "https://reddit.com/r/test/abc123",
        "permalink": "/r/test/abc123",
        "author": "testuser",
        "is_nsfw": False,
        "subreddit": "test",
    }


def _make_config(*, effective_provider: str = "none") -> TranslationConfig:
    """Build a minimal TranslationConfig."""
    return TranslationConfig(
        provider=effective_provider,
        effective_provider=effective_provider,
        target_lang="es",
        failure_policy="skip",
        cache_enabled=False,
        force_translate=False,
        model=DEFAULT_MODEL,
        max_output_tokens=DEFAULT_MAX_OUTPUT_TOKENS,
        api_key="",
    )


# ---------------------------------------------------------------------------
# Property 9a: TypeError fires with provider="none" (before short-circuit)
# ---------------------------------------------------------------------------

@given(bad_value=non_str_non_none_strategy)
@settings(max_examples=200)
def test_type_error_fires_before_provider_none_short_circuit(
    bad_value: Any,
) -> None:
    """**Property 9: TypeError on non-string thread_post**
    **Validates: Requirements 4.7**

    Even when effective_provider == "none" (which would normally short-circuit
    and return the input unchanged), a non-str, non-None thread_post must
    raise TypeError before the short-circuit executes.

    The error message must contain "thread_post" and the actual type name.
    """
    content = _make_reddit_content(bad_value)
    config = _make_config(effective_provider="none")
    service = Translation_Service(config)

    with pytest.raises(TypeError) as exc_info:
        service.translate(content)

    error_msg = str(exc_info.value)
    actual_type_name = type(bad_value).__name__

    assert "thread_post" in error_msg, (
        f"TypeError message must contain 'thread_post', got: {error_msg!r}"
    )
    assert actual_type_name in error_msg, (
        f"TypeError message must contain the actual type name {actual_type_name!r}, "
        f"got: {error_msg!r}"
    )


# ---------------------------------------------------------------------------
# Property 9b: TypeError fires with provider="anthropic" and non-empty target_lang
# ---------------------------------------------------------------------------

@given(bad_value=non_str_non_none_strategy)
@settings(max_examples=200)
def test_type_error_fires_with_anthropic_provider(
    bad_value: Any,
) -> None:
    """**Property 9: TypeError on non-string thread_post**
    **Validates: Requirements 4.7**

    With provider="anthropic" and a non-empty target_lang, a non-str,
    non-None thread_post must raise TypeError before any API call is made.

    The error message must contain "thread_post" and the actual type name.
    """
    content = _make_reddit_content(bad_value)
    config = _make_config(effective_provider="anthropic")
    service = Translation_Service(config)

    with pytest.raises(TypeError) as exc_info:
        service.translate(content)

    error_msg = str(exc_info.value)
    actual_type_name = type(bad_value).__name__

    assert "thread_post" in error_msg, (
        f"TypeError message must contain 'thread_post', got: {error_msg!r}"
    )
    assert actual_type_name in error_msg, (
        f"TypeError message must contain the actual type name {actual_type_name!r}, "
        f"got: {error_msg!r}"
    )


# ---------------------------------------------------------------------------
# Property 9c: TypeError fires with empty target_lang (before that short-circuit)
# ---------------------------------------------------------------------------

@given(bad_value=non_str_non_none_strategy)
@settings(max_examples=200)
def test_type_error_fires_before_empty_target_lang_short_circuit(
    bad_value: Any,
) -> None:
    """**Property 9: TypeError on non-string thread_post**
    **Validates: Requirements 4.7**

    Even when target_lang == "" (which would normally short-circuit), a
    non-str, non-None thread_post must raise TypeError before the short-circuit.

    The error message must contain "thread_post" and the actual type name.
    """
    content = _make_reddit_content(bad_value)
    # Use anthropic provider with empty target_lang to hit the target_lang
    # short-circuit path — TypeError must still fire first.
    config = TranslationConfig(
        provider="anthropic",
        effective_provider="anthropic",
        target_lang="",
        failure_policy="skip",
        cache_enabled=False,
        force_translate=False,
        model=DEFAULT_MODEL,
        max_output_tokens=DEFAULT_MAX_OUTPUT_TOKENS,
        api_key="",
    )
    service = Translation_Service(config)

    with pytest.raises(TypeError) as exc_info:
        service.translate(content)

    error_msg = str(exc_info.value)
    actual_type_name = type(bad_value).__name__

    assert "thread_post" in error_msg, (
        f"TypeError message must contain 'thread_post', got: {error_msg!r}"
    )
    assert actual_type_name in error_msg, (
        f"TypeError message must contain the actual type name {actual_type_name!r}, "
        f"got: {error_msg!r}"
    )


# ---------------------------------------------------------------------------
# Property 9d: Specific type coverage — list, int, dict, bytes, float
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "bad_value",
    [
        ["sentence one", "sentence two"],   # list (pre-parsed)
        42,                                  # int
        {"key": "value"},                    # dict
        b"raw bytes",                        # bytes
        3.14,                                # float
    ],
)
def test_type_error_for_specific_non_str_types(bad_value: Any) -> None:
    """**Property 9: TypeError on non-string thread_post**
    **Validates: Requirements 4.7**

    Explicit parametrized coverage for the five types called out in the spec:
    list, int, dict, bytes, float. Each must raise TypeError with the correct
    field name and type name in the message.
    """
    content = _make_reddit_content(bad_value)
    config = _make_config(effective_provider="none")
    service = Translation_Service(config)

    with pytest.raises(TypeError) as exc_info:
        service.translate(content)

    error_msg = str(exc_info.value)
    actual_type_name = type(bad_value).__name__

    assert "thread_post" in error_msg, (
        f"TypeError message must contain 'thread_post' for type "
        f"{actual_type_name!r}, got: {error_msg!r}"
    )
    assert actual_type_name in error_msg, (
        f"TypeError message must contain {actual_type_name!r}, "
        f"got: {error_msg!r}"
    )


# ---------------------------------------------------------------------------
# Sanity: str and None values do NOT raise TypeError
# ---------------------------------------------------------------------------

@given(
    thread_post=st.one_of(st.none(), st.text(max_size=500)),
)
@settings(max_examples=100)
def test_no_type_error_for_str_or_none(thread_post: Any) -> None:
    """**Property 9: TypeError on non-string thread_post**
    **Validates: Requirements 4.7**

    Sanity check: str and None values must NOT raise TypeError.
    (None is the legitimate absent-post sentinel; str is the valid type.)
    """
    content = _make_reddit_content(thread_post)
    config = _make_config(effective_provider="none")
    service = Translation_Service(config)

    # Should not raise TypeError — may return normally (no-op path).
    try:
        result = service.translate(content)
        # No-op path: result should be the same object.
        assert result is content
    except TypeError:
        pytest.fail(
            f"translate() raised TypeError for thread_post={thread_post!r} "
            f"(type={type(thread_post).__name__}), but str and None are valid."
        )
