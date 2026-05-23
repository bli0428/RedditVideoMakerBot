"""Property-based tests for sanitizer-collapse substitution.

**Property 21: Sanitizer collapse triggers original substitution**
**Validates: Requirements 14.2**

For any ``Reddit_Content`` input and any Translatable_Field ``f``, if the
mocked ``Anthropic_Client.translate`` for ``f`` returns a value ``v`` such
that ``sanitize_text(v).strip() == ""``, then ``output[f]`` SHALL equal
``input[f]`` and a warning containing ``f`` SHALL be emitted.

The key insight: when ``translate`` returns ``""`` and ``sanitize_text("")``
returns ``""`` (identity for empty), the service should substitute the
original value back in and emit a warning (Req 14.2).

Setup:
- Generate ``Reddit_Content`` dicts with non-empty ``thread_title`` using
  Hypothesis.
- Use config with ``provider="anthropic"``, ``target_lang="es"``,
  ``force_translate=True``, ``cache_enabled=False``.
- Mock ``_build_client`` to return a client where ``translate`` returns ``""``
  (empty string) for the chosen field and a non-empty string for all others.
- Inject a fake ``utils.voice`` module where ``sanitize_text`` returns ``""``
  when given ``""`` (identity for empty), so the collapse path is triggered.
- Assert ``output[field] == input[field]`` (original substituted back).
- Assert a warning was emitted (captured via patching
  ``utils.translation.service.print_substep``).
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
from utils.translation.service import Translation_Service


# ---------------------------------------------------------------------------
# Fake utils.voice module
# ---------------------------------------------------------------------------


def _make_fake_voice_module() -> types.ModuleType:
    """Return a fake ``utils.voice`` module whose ``sanitize_text`` is the
    identity function (returns the input unchanged, including empty strings).

    Injected into ``sys.modules`` so the lazy
    ``from utils.voice import sanitize_text`` inside
    ``Translation_Service._sanitize_or_fallback`` resolves without importing
    the real module (which requires ``cleantext``).

    When ``translate`` returns ``""`` and ``sanitize_text("")`` returns ``""``,
    the collapse condition ``not result or not result.strip()`` is True, so
    the service substitutes the original value back in and emits a warning.
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
# thread_title must be non-empty (the task requirement).
# thread_post and comment_body must also be non-empty so the service
# actually attempts to translate them and we can verify original substitution.
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

# Translatable field choices: thread_title, thread_post, or a comment body.
_field_tag_strategy = st.sampled_from(["thread_title", "thread_post", "comment_body"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config() -> TranslationConfig:
    """Build a TranslationConfig with force_translate=True, cache disabled."""
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


def _make_collapsing_client(
    content: dict[str, Any],
    field_tag: str,
) -> MagicMock:
    """Return a mock Anthropic_Client whose ``translate`` returns ``""``
    (empty string) for the chosen field and ``"translated: " + text`` for
    all other fields.

    When ``sanitize_text("")`` returns ``""`` (via the identity fake module),
    the collapse condition is triggered and the service substitutes the
    original value back in.

    The failing field is identified by matching the text value:
    - "thread_title" → content["thread_title"]
    - "thread_post"  → content["thread_post"]
    - "comment_body" → content["comments"][0]["comment_body"] (first comment)
    """
    if field_tag == "thread_title":
        collapsing_text = content["thread_title"]
    elif field_tag == "thread_post":
        collapsing_text = content["thread_post"]
    else:  # "comment_body"
        collapsing_text = content["comments"][0]["comment_body"]

    def _translate_side_effect(text: str, target_lang: str) -> str:
        if text == collapsing_text:
            return ""  # This will collapse under sanitize_text (identity returns "")
        return f"translated: {text}"

    mock_client = MagicMock()
    mock_client.translate.side_effect = _translate_side_effect
    return mock_client, collapsing_text


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


def _get_field_name_in_warning(field_tag: str) -> str:
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
# Property 21: Sanitizer collapse triggers original substitution (Req 14.2)
# ---------------------------------------------------------------------------


@given(
    content=_reddit_content_strategy,
    field_tag=_field_tag_strategy,
)
@settings(max_examples=100)
def test_sanitizer_collapse_substitutes_original(
    content: dict[str, Any],
    field_tag: str,
) -> None:
    """**Property 21: Sanitizer collapse triggers original substitution**
    **Validates: Requirements 14.2**

    When ``translate`` returns ``""`` and ``sanitize_text("")`` returns ``""``
    (identity for empty), the service should substitute the original value
    back in and emit a warning.

    Asserts:
    1. ``output[field] == input[field]`` (original substituted back).
    2. A warning was emitted via ``utils.translation.service.print_substep``
       containing the field name.
    """
    config = _make_config()
    mock_client, collapsing_text = _make_collapsing_client(content, field_tag)
    expected_field_name = _get_field_name_in_warning(field_tag)

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
        output = service.translate(content)

    # Assertion 1: original value substituted back (Req 14.2)
    output_value = _get_field_value_from_output(output, field_tag)
    assert output_value == collapsing_text, (
        f"Sanitizer-collapsed field '{field_tag}' was not substituted with "
        f"the original value. "
        f"Expected: {collapsing_text!r}, Got: {output_value!r}"
    )

    # Assertion 2: warning was emitted containing the field name (Req 14.2)
    warning_messages = [msg for msg in warning_calls if "[warn]" in msg]
    assert warning_messages, (
        f"No warning was emitted when sanitizer collapsed field '{field_tag}'. "
        f"All print_substep calls: {warning_calls!r}"
    )

    matching_warnings = [
        msg for msg in warning_messages if expected_field_name in msg
    ]
    assert matching_warnings, (
        f"No warning contained the field name '{expected_field_name}' after "
        f"sanitizer collapse. "
        f"Warning messages found: {warning_messages!r}"
    )
