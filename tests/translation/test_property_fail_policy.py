"""Property-based tests for Translation_Service fail-policy propagation.

**Property 11: Failure propagation under fail policy**
**Validates: Requirements 6.2, 6.3**

Hypothesis-generate inputs, ``TranslationError`` subclasses, and
Translatable_Field choices; with ``failure_policy = "fail"``, assert the
raised exception's ``str`` contains both the field name and the error class
name.

The mock client:
  - ``detect_source_language`` returns a language different from ``target_lang``
    so translation always proceeds (``force_translate=True`` is used to skip
    detection entirely and keep the test focused on the fail policy).
  - ``translate`` raises the generated ``TranslationError`` subclass.

``utils.voice`` is injected into ``sys.modules`` as a fake module because it
has a hard dependency on ``cleantext`` which may not be installed in the test
environment.  The fake ``sanitize_text`` is the identity function so it does
not interfere with the exception assertions.
"""
from __future__ import annotations

import sys
import types
from typing import Any, Type
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from utils.translation.config import (
    DEFAULT_MAX_OUTPUT_TOKENS,
    DEFAULT_MODEL,
    TranslationConfig,
)
from utils.translation.errors import (
    TranslationAPIError,
    TranslationAuthError,
    TranslationEmptyResponseError,
    TranslationError,
    TranslationRateLimitError,
    TranslationTimeoutError,
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
        "comment_url": st.text(max_size=200),
        "comment_body": st.text(min_size=1, max_size=500),
        "author": st.text(max_size=64),
    }
)

# Reddit_Content dict with all fields Translation_Service reads.
# thread_title and thread_post are non-empty strings so they are always
# Translatable_Fields that the service will attempt to translate.
_reddit_content_strategy = st.fixed_dictionaries(
    {
        # Translatable fields — non-empty so translation is always attempted
        "thread_title": st.text(min_size=1, max_size=300),
        "thread_post": st.text(min_size=1, max_size=2000),
        "comments": st.lists(_comment_strategy, min_size=1, max_size=5),
        # Structural fields
        "thread_id": st.text(min_size=1, max_size=32),
        "thread_url": st.text(max_size=200),
        "permalink": st.text(max_size=200),
        "author": st.text(max_size=64),
        "avatar_url": st.text(max_size=200),
        "is_nsfw": st.booleans(),
        "subreddit": st.text(max_size=64),
    }
)

# All concrete TranslationError subclasses (including TranslationEmptyResponseError
# per Req 6.3 which must also be treated as a translation error).
_TRANSLATION_ERROR_SUBCLASSES: list[Type[TranslationError]] = [
    TranslationAPIError,
    TranslationAuthError,
    TranslationRateLimitError,
    TranslationTimeoutError,
    TranslationEmptyResponseError,
]

_error_class_strategy = st.sampled_from(_TRANSLATION_ERROR_SUBCLASSES)

# Translatable field names that the service will attempt to translate.
# "thread_title" and "thread_post" are top-level; "comment_body" represents
# any comments[*].comment_body field.
_TRANSLATABLE_FIELD_NAMES = ["thread_title", "thread_post", "comment_body"]
_field_name_strategy = st.sampled_from(_TRANSLATABLE_FIELD_NAMES)

# Target language codes distinct from "en" (the mock detector's return value).
_target_lang_strategy = st.sampled_from(["es", "fr", "de", "ja", "pt-BR", "zh-CN"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fail_config(target_lang: str) -> TranslationConfig:
    """Build a TranslationConfig with failure_policy='fail', provider='anthropic',
    force_translate=True, and cache disabled."""
    return TranslationConfig(
        provider="anthropic",
        effective_provider="anthropic",
        target_lang=target_lang,
        failure_policy="fail",
        cache_enabled=False,
        force_translate=True,  # skip detection; focus on fail policy
        model=DEFAULT_MODEL,
        max_output_tokens=DEFAULT_MAX_OUTPUT_TOKENS,
        api_key="test-key",
    )


def _make_raising_client(error_class: Type[TranslationError]) -> MagicMock:
    """Return a mock Anthropic_Client whose ``translate`` always raises
    an instance of ``error_class`` with a fixed message."""
    mock_client = MagicMock()
    mock_client.detect_source_language.return_value = "en"
    mock_client.translate.side_effect = error_class("mock translation error")
    return mock_client


# ---------------------------------------------------------------------------
# Property 11: Failure propagation under fail policy (Req 6.2, 6.3)
# ---------------------------------------------------------------------------


@given(
    content=_reddit_content_strategy,
    error_class=_error_class_strategy,
    target_lang=_target_lang_strategy,
)
@settings(max_examples=200)
def test_fail_policy_raises_translation_error(
    content: dict[str, Any],
    error_class: Type[TranslationError],
    target_lang: str,
) -> None:
    """**Property 11: Failure propagation under fail policy**
    **Validates: Requirements 6.2, 6.3**

    With ``failure_policy = "fail"`` and a mock client that raises a
    ``TranslationError`` subclass, ``translate(content)`` must raise a
    ``TranslationError`` (or subclass thereof).
    """
    config = _make_fail_config(target_lang=target_lang)
    mock_client = _make_raising_client(error_class)

    with (
        patch(
            "utils.translation.service.Translation_Service._build_client",
            return_value=mock_client,
        ),
        patch.dict(sys.modules, {"utils.voice": _make_fake_voice_module()}),
    ):
        service = Translation_Service(config)
        with pytest.raises(TranslationError):
            service.translate(content)


@given(
    content=_reddit_content_strategy,
    error_class=_error_class_strategy,
    target_lang=_target_lang_strategy,
)
@settings(max_examples=200)
def test_fail_policy_error_message_contains_field_name(
    content: dict[str, Any],
    error_class: Type[TranslationError],
    target_lang: str,
) -> None:
    """**Property 11: Failure propagation under fail policy**
    **Validates: Requirements 6.2, 6.3**

    With ``failure_policy = "fail"``, the raised exception's ``str``
    must contain the name of the field that failed.

    The first Translatable_Field the service encounters is ``thread_title``,
    so the error message must contain ``"thread_title"``.
    """
    config = _make_fail_config(target_lang=target_lang)
    mock_client = _make_raising_client(error_class)

    with (
        patch(
            "utils.translation.service.Translation_Service._build_client",
            return_value=mock_client,
        ),
        patch.dict(sys.modules, {"utils.voice": _make_fake_voice_module()}),
    ):
        service = Translation_Service(config)
        with pytest.raises(TranslationError) as exc_info:
            service.translate(content)

    error_message = str(exc_info.value)
    # The first field attempted is thread_title; its name must appear in the message.
    assert "thread_title" in error_message, (
        f"Expected 'thread_title' in error message, got: {error_message!r}"
    )


@given(
    content=_reddit_content_strategy,
    error_class=_error_class_strategy,
    target_lang=_target_lang_strategy,
)
@settings(max_examples=200)
def test_fail_policy_error_message_contains_error_class_name(
    content: dict[str, Any],
    error_class: Type[TranslationError],
    target_lang: str,
) -> None:
    """**Property 11: Failure propagation under fail policy**
    **Validates: Requirements 6.2, 6.3**

    With ``failure_policy = "fail"``, the raised exception's ``str``
    must contain the name of the underlying error class (e.g.,
    ``"TranslationAPIError"``, ``"TranslationEmptyResponseError"``).
    """
    config = _make_fail_config(target_lang=target_lang)
    mock_client = _make_raising_client(error_class)

    with (
        patch(
            "utils.translation.service.Translation_Service._build_client",
            return_value=mock_client,
        ),
        patch.dict(sys.modules, {"utils.voice": _make_fake_voice_module()}),
    ):
        service = Translation_Service(config)
        with pytest.raises(TranslationError) as exc_info:
            service.translate(content)

    error_message = str(exc_info.value)
    assert error_class.__name__ in error_message, (
        f"Expected {error_class.__name__!r} in error message, got: {error_message!r}"
    )


@given(
    content=_reddit_content_strategy,
    error_class=_error_class_strategy,
    target_lang=_target_lang_strategy,
)
@settings(max_examples=200)
def test_fail_policy_error_message_contains_both_field_and_class(
    content: dict[str, Any],
    error_class: Type[TranslationError],
    target_lang: str,
) -> None:
    """**Property 11: Failure propagation under fail policy**
    **Validates: Requirements 6.2, 6.3**

    Combined assertion: the raised exception's ``str`` must contain BOTH
    the field name AND the error class name, as required by Req 6.2.
    """
    config = _make_fail_config(target_lang=target_lang)
    mock_client = _make_raising_client(error_class)

    with (
        patch(
            "utils.translation.service.Translation_Service._build_client",
            return_value=mock_client,
        ),
        patch.dict(sys.modules, {"utils.voice": _make_fake_voice_module()}),
    ):
        service = Translation_Service(config)
        with pytest.raises(TranslationError) as exc_info:
            service.translate(content)

    error_message = str(exc_info.value)

    assert "thread_title" in error_message, (
        f"Field name 'thread_title' missing from error message: {error_message!r}"
    )
    assert error_class.__name__ in error_message, (
        f"Error class name {error_class.__name__!r} missing from error message: "
        f"{error_message!r}"
    )


@given(
    content=_reddit_content_strategy,
    error_class=_error_class_strategy,
    target_lang=_target_lang_strategy,
)
@settings(max_examples=100)
def test_fail_policy_does_not_swallow_exception(
    content: dict[str, Any],
    error_class: Type[TranslationError],
    target_lang: str,
) -> None:
    """**Property 11: Failure propagation under fail policy**
    **Validates: Requirements 6.2, 6.3**

    With ``failure_policy = "fail"``, ``translate`` must NOT return normally
    when the client raises a ``TranslationError``. The exception must propagate
    to the caller.
    """
    config = _make_fail_config(target_lang=target_lang)
    mock_client = _make_raising_client(error_class)

    raised = False
    with (
        patch(
            "utils.translation.service.Translation_Service._build_client",
            return_value=mock_client,
        ),
        patch.dict(sys.modules, {"utils.voice": _make_fake_voice_module()}),
    ):
        service = Translation_Service(config)
        try:
            service.translate(content)
        except TranslationError:
            raised = True

    assert raised, (
        f"Expected TranslationError to propagate with failure_policy='fail', "
        f"but translate() returned normally. "
        f"error_class={error_class.__name__!r}, target_lang={target_lang!r}"
    )
