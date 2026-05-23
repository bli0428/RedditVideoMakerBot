"""Property-based tests for Translation_Service skip-policy failure containment.

**Property 10: Failure containment under skip policy**
**Validates: Requirements 6.1, 6.3, 6.4**

Hypothesis-generate inputs, ``TranslationError`` subclasses (including
``TranslationEmptyResponseError``), and Translatable_Field choices; with
``failure_policy = "skip"`` and the mocked client raising on the chosen field,
assert:

1. No exception propagates from ``translate(content)``.
2. ``output.keys() == input.keys()``.
3. The failed field value equals the original input value.
4. A warning containing both the field name and the error class name is emitted
   (captured via patching ``utils.console.print_substep``).

The mock client:
  - ``detect_source_language`` returns a language different from ``target_lang``
    so translation always proceeds (``force_translate=True`` is used to avoid
    the detection call entirely and keep the test focused on field-level failure).
  - ``translate`` raises the generated ``TranslationError`` subclass for the
    chosen field and returns ``"translated: " + text`` for all other fields.

``utils.voice`` is injected into ``sys.modules`` as a fake module whose
``sanitize_text`` is the identity function, because the real module has a hard
dependency on ``cleantext`` which may not be installed in the test environment.
The lazy ``from utils.voice import sanitize_text`` inside
``Translation_Service._sanitize_or_fallback`` resolves against this fake module.
"""
from __future__ import annotations

import sys
import types
from typing import Any
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
# thread_title and thread_post must be non-empty strings so the service
# actually attempts to translate them (empty strings are still translated,
# but we want to verify the original value is preserved on failure).
_reddit_content_strategy = st.fixed_dictionaries(
    {
        # Translatable fields — non-empty strings so translation is attempted
        "thread_title": st.text(min_size=1, max_size=300),
        "thread_post": st.text(min_size=1, max_size=2000),
        "comments": st.lists(_comment_strategy, min_size=1, max_size=5),
        # Structural fields — must be preserved byte-for-byte
        "thread_id": st.text(min_size=1, max_size=32),
        "thread_url": st.text(max_size=200),
        "permalink": st.text(max_size=200),
        "author": st.text(max_size=64),
        "avatar_url": st.text(max_size=200),
        "is_nsfw": st.booleans(),
        "subreddit": st.text(max_size=64),
    }
)

# All TranslationError subclasses, including TranslationEmptyResponseError (Req 6.3).
_error_classes = [
    TranslationError,
    TranslationAPIError,
    TranslationAuthError,
    TranslationEmptyResponseError,
    TranslationRateLimitError,
    TranslationTimeoutError,
]

_error_class_strategy = st.sampled_from(_error_classes)

# Translatable field choices: thread_title, thread_post, or a comment body.
# We use a string tag and resolve it against the content dict at test time.
_field_tag_strategy = st.sampled_from(["thread_title", "thread_post", "comment_body"])

# Target language codes distinct from "en" so detection (if used) would proceed.
_target_lang_strategy = st.sampled_from(["es", "fr", "de", "ja", "pt-BR", "zh-CN"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_skip_config(target_lang: str) -> TranslationConfig:
    """Build a TranslationConfig with failure_policy='skip', cache disabled,
    force_translate=True (so detection is skipped and we focus on field errors)."""
    return TranslationConfig(
        provider="anthropic",
        effective_provider="anthropic",
        target_lang=target_lang,
        failure_policy="skip",
        cache_enabled=False,
        force_translate=True,
        model=DEFAULT_MODEL,
        max_output_tokens=DEFAULT_MAX_OUTPUT_TOKENS,
        api_key="test-key",
    )


def _make_failing_client(
    content: dict[str, Any],
    field_tag: str,
    error_class: type,
) -> MagicMock:
    """Return a mock Anthropic_Client whose ``translate`` raises ``error_class``
    for the chosen field and returns ``"translated: " + text`` for all others.

    The failing field is identified by matching the text value:
    - "thread_title" → content["thread_title"]
    - "thread_post"  → content["thread_post"]
    - "comment_body" → content["comments"][0]["comment_body"] (first comment)
    """
    if field_tag == "thread_title":
        failing_text = content["thread_title"]
    elif field_tag == "thread_post":
        failing_text = content["thread_post"]
    else:  # "comment_body"
        failing_text = content["comments"][0]["comment_body"]

    error_instance = error_class(f"Simulated {error_class.__name__} for testing")

    def _translate_side_effect(text: str, target_lang: str) -> str:
        if text == failing_text:
            raise error_instance
        return f"translated: {text}"

    mock_client = MagicMock()
    mock_client.detect_source_language.return_value = "en"
    mock_client.translate.side_effect = _translate_side_effect
    return mock_client, failing_text, error_instance


def _get_field_value_from_output(
    output: dict[str, Any],
    field_tag: str,
) -> str:
    """Extract the field value from the output dict for the given field tag."""
    if field_tag == "thread_title":
        return output["thread_title"]
    elif field_tag == "thread_post":
        return output["thread_post"]
    else:  # "comment_body"
        return output["comments"][0]["comment_body"]


def _get_field_name_in_output(
    content: dict[str, Any],
    field_tag: str,
) -> str:
    """Return the field name as it appears in warning messages from the service.

    The service uses:
    - "thread_title" for thread_title
    - "thread_post" for thread_post
    - "comments[0].comment_body" for the first comment body
    """
    if field_tag == "thread_title":
        return "thread_title"
    elif field_tag == "thread_post":
        return "thread_post"
    else:
        return "comments[0].comment_body"


# ---------------------------------------------------------------------------
# Property 10: Failure containment under skip policy (Req 6.1, 6.3, 6.4)
# ---------------------------------------------------------------------------


@given(
    content=_reddit_content_strategy,
    error_class=_error_class_strategy,
    field_tag=_field_tag_strategy,
    target_lang=_target_lang_strategy,
)
@settings(max_examples=200)
def test_skip_policy_no_exception_propagates(
    content: dict[str, Any],
    error_class: type,
    field_tag: str,
    target_lang: str,
) -> None:
    """**Property 10: Failure containment under skip policy**
    **Validates: Requirements 6.1, 6.3, 6.4**

    When ``failure_policy = "skip"`` and the mocked client raises a
    ``TranslationError`` subclass for a chosen field, no exception should
    propagate from ``translate(content)``.
    """
    config = _make_skip_config(target_lang)
    mock_client, failing_text, error_instance = _make_failing_client(
        content, field_tag, error_class
    )

    fake_voice = _make_fake_voice_module()
    with (
        patch(
            "utils.translation.service.Translation_Service._build_client",
            return_value=mock_client,
        ),
        patch.dict(sys.modules, {"utils.voice": fake_voice}),
        patch("utils.translation.service.print_substep"),
    ):
        service = Translation_Service(config)
        # Must not raise — failure_policy="skip" contains the error
        try:
            output = service.translate(content)
        except Exception as exc:
            pytest.fail(
                f"translate() raised {type(exc).__name__} under failure_policy='skip' "
                f"when {error_class.__name__} was raised for field '{field_tag}'. "
                f"Exception: {exc}"
            )


@given(
    content=_reddit_content_strategy,
    error_class=_error_class_strategy,
    field_tag=_field_tag_strategy,
    target_lang=_target_lang_strategy,
)
@settings(max_examples=200)
def test_skip_policy_output_keys_equal_input_keys(
    content: dict[str, Any],
    error_class: type,
    field_tag: str,
    target_lang: str,
) -> None:
    """**Property 10: Failure containment under skip policy**
    **Validates: Requirements 6.1, 6.3, 6.4**

    When ``failure_policy = "skip"`` and a field raises, the output dict must
    have exactly the same keys as the input dict (Req 6.4 key-preservation).
    """
    config = _make_skip_config(target_lang)
    mock_client, failing_text, error_instance = _make_failing_client(
        content, field_tag, error_class
    )

    fake_voice = _make_fake_voice_module()
    with (
        patch(
            "utils.translation.service.Translation_Service._build_client",
            return_value=mock_client,
        ),
        patch.dict(sys.modules, {"utils.voice": fake_voice}),
        patch("utils.translation.service.print_substep"),
    ):
        service = Translation_Service(config)
        output = service.translate(content)

    assert output.keys() == content.keys(), (
        f"Key mismatch under skip policy with {error_class.__name__} on '{field_tag}'. "
        f"Input keys: {set(content.keys())}, Output keys: {set(output.keys())}"
    )


@given(
    content=_reddit_content_strategy,
    error_class=_error_class_strategy,
    field_tag=_field_tag_strategy,
    target_lang=_target_lang_strategy,
)
@settings(max_examples=200)
def test_skip_policy_failed_field_equals_original(
    content: dict[str, Any],
    error_class: type,
    field_tag: str,
    target_lang: str,
) -> None:
    """**Property 10: Failure containment under skip policy**
    **Validates: Requirements 6.1, 6.3, 6.4**

    When ``failure_policy = "skip"`` and a field raises, the failed field's
    value in the output must equal the original input value (Req 6.1, 6.4).
    """
    config = _make_skip_config(target_lang)
    mock_client, failing_text, error_instance = _make_failing_client(
        content, field_tag, error_class
    )

    fake_voice = _make_fake_voice_module()
    with (
        patch(
            "utils.translation.service.Translation_Service._build_client",
            return_value=mock_client,
        ),
        patch.dict(sys.modules, {"utils.voice": fake_voice}),
        patch("utils.translation.service.print_substep"),
    ):
        service = Translation_Service(config)
        output = service.translate(content)

    output_value = _get_field_value_from_output(output, field_tag)
    assert output_value == failing_text, (
        f"Failed field '{field_tag}' was not preserved under skip policy. "
        f"Error class: {error_class.__name__}. "
        f"Expected: {failing_text!r}, Got: {output_value!r}"
    )


@given(
    content=_reddit_content_strategy,
    error_class=_error_class_strategy,
    field_tag=_field_tag_strategy,
    target_lang=_target_lang_strategy,
)
@settings(max_examples=200)
def test_skip_policy_warning_contains_field_and_error_class(
    content: dict[str, Any],
    error_class: type,
    field_tag: str,
    target_lang: str,
) -> None:
    """**Property 10: Failure containment under skip policy**
    **Validates: Requirements 6.1, 6.3, 6.4**

    When ``failure_policy = "skip"`` and a field raises, a warning must be
    emitted via ``utils.console.print_substep`` that contains both the field
    name and the error class name (Req 6.1).
    """
    config = _make_skip_config(target_lang)
    mock_client, failing_text, error_instance = _make_failing_client(
        content, field_tag, error_class
    )
    expected_field_name = _get_field_name_in_output(content, field_tag)

    warning_calls: list[str] = []

    def _capture_print_substep(msg: str, *args: Any, **kwargs: Any) -> None:
        warning_calls.append(msg)

    fake_voice = _make_fake_voice_module()
    with (
        patch(
            "utils.translation.service.Translation_Service._build_client",
            return_value=mock_client,
        ),
        patch.dict(sys.modules, {"utils.voice": fake_voice}),
        patch(
            "utils.translation.service.print_substep",
            side_effect=_capture_print_substep,
        ),
    ):
        service = Translation_Service(config)
        service.translate(content)

    # Find warning messages (those containing "[warn]")
    warning_messages = [msg for msg in warning_calls if "[warn]" in msg]

    assert warning_messages, (
        f"No warning was emitted under skip policy when {error_class.__name__} "
        f"was raised for field '{field_tag}'. "
        f"All print_substep calls: {warning_calls!r}"
    )

    # At least one warning must contain both the field name and the error class name
    matching_warnings = [
        msg
        for msg in warning_messages
        if expected_field_name in msg and error_class.__name__ in msg
    ]

    assert matching_warnings, (
        f"No warning contained both field name '{expected_field_name}' and "
        f"error class '{error_class.__name__}' under skip policy. "
        f"Warning messages found: {warning_messages!r}"
    )


@given(
    content=_reddit_content_strategy,
    error_class=_error_class_strategy,
    field_tag=_field_tag_strategy,
    target_lang=_target_lang_strategy,
)
@settings(max_examples=100)
def test_skip_policy_all_assertions_combined(
    content: dict[str, Any],
    error_class: type,
    field_tag: str,
    target_lang: str,
) -> None:
    """**Property 10: Failure containment under skip policy**
    **Validates: Requirements 6.1, 6.3, 6.4**

    Combined property: all four assertions in one test for efficiency.

    1. No exception propagates.
    2. output.keys() == input.keys().
    3. The failed field value equals the original input value.
    4. A warning containing both field name and error class name is emitted.
    """
    config = _make_skip_config(target_lang)
    mock_client, failing_text, error_instance = _make_failing_client(
        content, field_tag, error_class
    )
    expected_field_name = _get_field_name_in_output(content, field_tag)

    warning_calls: list[str] = []

    def _capture_print_substep(msg: str, *args: Any, **kwargs: Any) -> None:
        warning_calls.append(msg)

    fake_voice = _make_fake_voice_module()
    with (
        patch(
            "utils.translation.service.Translation_Service._build_client",
            return_value=mock_client,
        ),
        patch.dict(sys.modules, {"utils.voice": fake_voice}),
        patch(
            "utils.translation.service.print_substep",
            side_effect=_capture_print_substep,
        ),
    ):
        service = Translation_Service(config)

        # Assertion 1: no exception propagates
        try:
            output = service.translate(content)
        except Exception as exc:
            pytest.fail(
                f"translate() raised {type(exc).__name__} under failure_policy='skip' "
                f"when {error_class.__name__} was raised for field '{field_tag}'. "
                f"Exception: {exc}"
            )

    # Assertion 2: key preservation (Req 6.4)
    assert output.keys() == content.keys(), (
        f"Key mismatch under skip policy with {error_class.__name__} on '{field_tag}'. "
        f"Input keys: {set(content.keys())}, Output keys: {set(output.keys())}"
    )

    # Assertion 3: failed field value equals original (Req 6.1)
    output_value = _get_field_value_from_output(output, field_tag)
    assert output_value == failing_text, (
        f"Failed field '{field_tag}' was not preserved under skip policy. "
        f"Error class: {error_class.__name__}. "
        f"Expected: {failing_text!r}, Got: {output_value!r}"
    )

    # Assertion 4: warning emitted with field name and error class (Req 6.1)
    warning_messages = [msg for msg in warning_calls if "[warn]" in msg]
    assert warning_messages, (
        f"No warning was emitted under skip policy when {error_class.__name__} "
        f"was raised for field '{field_tag}'. "
        f"All print_substep calls: {warning_calls!r}"
    )

    matching_warnings = [
        msg
        for msg in warning_messages
        if expected_field_name in msg and error_class.__name__ in msg
    ]
    assert matching_warnings, (
        f"No warning contained both field name '{expected_field_name}' and "
        f"error class '{error_class.__name__}' under skip policy. "
        f"Warning messages found: {warning_messages!r}"
    )
