"""Property-based tests for no wrapper introduction.

**Property 22: Output does not introduce wrappers**
**Validates: Requirements 14.3**

Hypothesis-generate inputs without code fences, surrounding quotes, or HTML
tags, and a mocked client whose translations are also clean and do not collapse
under sanitization; assert no Translatable_Field in the output contains
leading/trailing matched code fences, leading/trailing matched quotes, or HTML
tags absent from the corresponding input.

Requirement 14.3 states:
    THE Translation_Service SHALL NOT introduce HTML tags, markdown fences, or
    surrounding quotation marks into Translatable_Field values that the original
    text did not contain, except (a) when criterion 2 substitutes the original
    value back in, or (b) when the sanitizer has collapsed the translated value
    AND the substitution itself fails.

Test setup:
  - Input Translatable_Fields contain no code fences (```), no surrounding
    matched quotes, and no HTML tags.
  - The mocked client's ``translate`` returns clean text (same constraints).
  - ``utils.voice.sanitize_text`` is patched to return its input unchanged so
    the sanitizer does not collapse any value (no fallback to original).
  - ``force_translate = True`` so detection is skipped and every field is
    translated.
  - ``cache_enabled = False`` so every field goes through the mock client.

Assertions:
  1. No output Translatable_Field starts and ends with matched ``` code fences.
  2. No output Translatable_Field starts and ends with matched ASCII or Unicode
     quotation marks that were not present in the corresponding input.
  3. No output Translatable_Field contains HTML tags (<tag> or </tag>) that
     were absent from the corresponding input.

Note: ``utils.voice`` is injected into ``sys.modules`` as a fake module because
it has a hard dependency on ``cleantext`` which may not be installed in the test
environment. The fake ``sanitize_text`` is the identity function so it does not
interfere with the wrapper assertions.
"""
from __future__ import annotations

import re
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
# Regex helpers for wrapper detection
# ---------------------------------------------------------------------------

# Matches a string that starts AND ends with triple backtick fences.
# e.g. "```hello```" or "```\nhello\n```"
_CODE_FENCE_RE = re.compile(r"^```.*```$", re.DOTALL)

# Matched ASCII quote pairs: "...", '...', and Unicode equivalents.
# We check if the first and last characters form a matched pair.
_QUOTE_PAIRS = {
    '"': '"',
    "'": "'",
    "\u2018": "\u2019",  # ' '
    "\u201c": "\u201d",  # " "
    "\u00ab": "\u00bb",  # « »
    "\u2039": "\u203a",  # ‹ ›
}

# Matches any HTML tag: opening <tag>, closing </tag>, or self-closing <tag/>.
_HTML_TAG_RE = re.compile(r"<[a-zA-Z][^>]*>|</[a-zA-Z][^>]*>")

# Characters that must NOT appear in generated "clean" text.
# We exclude backtick (to avoid accidental fences), angle brackets (HTML),
# and the quote characters used in _QUOTE_PAIRS.
_FORBIDDEN_CHARS = set("`<>\"'\u2018\u2019\u201c\u201d\u00ab\u00bb\u2039\u203a")

# Alphabet for clean text: printable ASCII minus forbidden chars, plus spaces.
_CLEAN_ALPHABET = "".join(
    ch
    for ch in (
        "abcdefghijklmnopqrstuvwxyz"
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        "0123456789"
        " .,!?;:-_()[]{}@#$%^&*+=|~/\\"
    )
    if ch not in _FORBIDDEN_CHARS
)

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

# Text that contains no code fences, no surrounding quotes, and no HTML tags.
_clean_text_strategy = st.text(
    alphabet=_CLEAN_ALPHABET,
    min_size=1,
    max_size=300,
)

# A single comment dict with clean text fields.
_comment_strategy = st.fixed_dictionaries(
    {
        "comment_id": st.text(min_size=1, max_size=32),
        "comment_url": st.text(max_size=200),
        "comment_body": _clean_text_strategy,
        "author": st.text(max_size=64),
    }
)

# Reddit_Content dict where all Translatable_Fields are clean.
_reddit_content_strategy = st.fixed_dictionaries(
    {
        # Translatable fields — clean (no fences, quotes, HTML)
        "thread_title": _clean_text_strategy,
        "thread_post": _clean_text_strategy,
        "comments": st.lists(_comment_strategy, min_size=0, max_size=5),
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

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config() -> TranslationConfig:
    """Build a TranslationConfig with provider='anthropic', force_translate=True,
    and cache disabled so every field goes through the mock client."""
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
    """Return a mock Anthropic_Client whose translate() returns clean text.

    The translation is a simple prefix + original text, which is guaranteed
    to be clean because the original text is clean and the prefix is clean.
    detect_source_language is not called because force_translate=True.
    """
    mock_client = MagicMock()
    # Returns clean text: "translated: " + original (no fences, quotes, HTML)
    mock_client.translate.side_effect = (
        lambda text, target_lang: "translated " + text
    )
    mock_client.detect_source_language.side_effect = AssertionError(
        "detect_source_language must not be called when force_translate=True"
    )
    return mock_client


def _has_code_fence_wrapper(text: str) -> bool:
    """Return True if text starts AND ends with matched ``` code fences."""
    return bool(_CODE_FENCE_RE.match(text))


def _has_surrounding_quote_wrapper(text: str) -> bool:
    """Return True if text starts with an opening quote and ends with the
    corresponding closing quote (matched pair)."""
    if len(text) < 2:
        return False
    first = text[0]
    last = text[-1]
    return _QUOTE_PAIRS.get(first) == last


def _extract_html_tags(text: str) -> set[str]:
    """Return the set of HTML tag strings found in text."""
    return set(_HTML_TAG_RE.findall(text))


def _assert_no_wrappers_introduced(
    field_name: str,
    input_text: str,
    output_text: str,
) -> None:
    """Assert that output_text does not introduce wrappers absent from input_text.

    Checks:
      1. No leading/trailing matched ``` code fences.
      2. No leading/trailing matched quotation marks not present in input.
      3. No HTML tags absent from the input.
    """
    # 1. Code fence check
    assert not _has_code_fence_wrapper(output_text), (
        f"Field '{field_name}': output has leading/trailing code fences "
        f"that were not in the input.\n"
        f"Input:  {input_text!r}\n"
        f"Output: {output_text!r}"
    )

    # 2. Surrounding quote check
    # Only flag if the output has a surrounding quote wrapper AND the input
    # did not have the same surrounding quote wrapper.
    if _has_surrounding_quote_wrapper(output_text):
        assert _has_surrounding_quote_wrapper(input_text), (
            f"Field '{field_name}': output has surrounding matched quotes "
            f"that were not in the input.\n"
            f"Input:  {input_text!r}\n"
            f"Output: {output_text!r}"
        )

    # 3. HTML tag check: no new tags in output that weren't in input
    input_tags = _extract_html_tags(input_text)
    output_tags = _extract_html_tags(output_text)
    new_tags = output_tags - input_tags
    assert not new_tags, (
        f"Field '{field_name}': output contains HTML tags absent from input.\n"
        f"New tags: {new_tags!r}\n"
        f"Input:  {input_text!r}\n"
        f"Output: {output_text!r}"
    )


# ---------------------------------------------------------------------------
# Property 22: Output does not introduce wrappers (Req 14.3)
# ---------------------------------------------------------------------------


@given(content=_reddit_content_strategy)
@settings(max_examples=200)
def test_no_code_fence_wrapper_introduced(content: dict[str, Any]) -> None:
    """**Property 22: Output does not introduce wrappers**
    **Validates: Requirements 14.3**

    When input Translatable_Fields contain no code fences and the mocked
    client returns clean text, no output Translatable_Field shall start and
    end with matched ``` code fences.
    """
    config = _make_config()
    mock_client = _make_mock_client()
    fake_voice = _make_fake_voice_module()

    with (
        patch(
            "utils.translation.service.Translation_Service._build_client",
            return_value=mock_client,
        ),
        patch.dict(sys.modules, {"utils.voice": fake_voice}),
    ):
        service = Translation_Service(config)
        result = service.translate(content)

    # Check thread_title
    assert not _has_code_fence_wrapper(result["thread_title"]), (
        f"thread_title has code fence wrapper.\n"
        f"Input:  {content['thread_title']!r}\n"
        f"Output: {result['thread_title']!r}"
    )

    # Check thread_post
    assert not _has_code_fence_wrapper(result["thread_post"]), (
        f"thread_post has code fence wrapper.\n"
        f"Input:  {content['thread_post']!r}\n"
        f"Output: {result['thread_post']!r}"
    )

    # Check each comment_body
    for i, (in_c, out_c) in enumerate(
        zip(content["comments"], result["comments"])
    ):
        assert not _has_code_fence_wrapper(out_c["comment_body"]), (
            f"comments[{i}].comment_body has code fence wrapper.\n"
            f"Input:  {in_c['comment_body']!r}\n"
            f"Output: {out_c['comment_body']!r}"
        )


@given(content=_reddit_content_strategy)
@settings(max_examples=200)
def test_no_surrounding_quote_wrapper_introduced(content: dict[str, Any]) -> None:
    """**Property 22: Output does not introduce wrappers**
    **Validates: Requirements 14.3**

    When input Translatable_Fields contain no surrounding matched quotes and
    the mocked client returns clean text, no output Translatable_Field shall
    start and end with matched quotation marks that were absent from the input.
    """
    config = _make_config()
    mock_client = _make_mock_client()
    fake_voice = _make_fake_voice_module()

    with (
        patch(
            "utils.translation.service.Translation_Service._build_client",
            return_value=mock_client,
        ),
        patch.dict(sys.modules, {"utils.voice": fake_voice}),
    ):
        service = Translation_Service(config)
        result = service.translate(content)

    # Check thread_title
    if _has_surrounding_quote_wrapper(result["thread_title"]):
        assert _has_surrounding_quote_wrapper(content["thread_title"]), (
            f"thread_title has surrounding quote wrapper not in input.\n"
            f"Input:  {content['thread_title']!r}\n"
            f"Output: {result['thread_title']!r}"
        )

    # Check thread_post
    if _has_surrounding_quote_wrapper(result["thread_post"]):
        assert _has_surrounding_quote_wrapper(content["thread_post"]), (
            f"thread_post has surrounding quote wrapper not in input.\n"
            f"Input:  {content['thread_post']!r}\n"
            f"Output: {result['thread_post']!r}"
        )

    # Check each comment_body
    for i, (in_c, out_c) in enumerate(
        zip(content["comments"], result["comments"])
    ):
        if _has_surrounding_quote_wrapper(out_c["comment_body"]):
            assert _has_surrounding_quote_wrapper(in_c["comment_body"]), (
                f"comments[{i}].comment_body has surrounding quote wrapper "
                f"not in input.\n"
                f"Input:  {in_c['comment_body']!r}\n"
                f"Output: {out_c['comment_body']!r}"
            )


@given(content=_reddit_content_strategy)
@settings(max_examples=200)
def test_no_html_tags_introduced(content: dict[str, Any]) -> None:
    """**Property 22: Output does not introduce wrappers**
    **Validates: Requirements 14.3**

    When input Translatable_Fields contain no HTML tags and the mocked client
    returns clean text, no output Translatable_Field shall contain HTML tags
    absent from the corresponding input.
    """
    config = _make_config()
    mock_client = _make_mock_client()
    fake_voice = _make_fake_voice_module()

    with (
        patch(
            "utils.translation.service.Translation_Service._build_client",
            return_value=mock_client,
        ),
        patch.dict(sys.modules, {"utils.voice": fake_voice}),
    ):
        service = Translation_Service(config)
        result = service.translate(content)

    # Check thread_title
    input_tags = _extract_html_tags(content["thread_title"])
    output_tags = _extract_html_tags(result["thread_title"])
    new_tags = output_tags - input_tags
    assert not new_tags, (
        f"thread_title has new HTML tags: {new_tags!r}\n"
        f"Input:  {content['thread_title']!r}\n"
        f"Output: {result['thread_title']!r}"
    )

    # Check thread_post
    input_tags = _extract_html_tags(content["thread_post"])
    output_tags = _extract_html_tags(result["thread_post"])
    new_tags = output_tags - input_tags
    assert not new_tags, (
        f"thread_post has new HTML tags: {new_tags!r}\n"
        f"Input:  {content['thread_post']!r}\n"
        f"Output: {result['thread_post']!r}"
    )

    # Check each comment_body
    for i, (in_c, out_c) in enumerate(
        zip(content["comments"], result["comments"])
    ):
        input_tags = _extract_html_tags(in_c["comment_body"])
        output_tags = _extract_html_tags(out_c["comment_body"])
        new_tags = output_tags - input_tags
        assert not new_tags, (
            f"comments[{i}].comment_body has new HTML tags: {new_tags!r}\n"
            f"Input:  {in_c['comment_body']!r}\n"
            f"Output: {out_c['comment_body']!r}"
        )


@given(content=_reddit_content_strategy)
@settings(max_examples=300)
def test_no_wrappers_introduced_combined(content: dict[str, Any]) -> None:
    """**Property 22: Output does not introduce wrappers**
    **Validates: Requirements 14.3**

    Combined check: for all three Translatable_Field types simultaneously,
    no output field introduces code fences, surrounding quotes, or HTML tags
    absent from the corresponding input.
    """
    config = _make_config()
    mock_client = _make_mock_client()
    fake_voice = _make_fake_voice_module()

    with (
        patch(
            "utils.translation.service.Translation_Service._build_client",
            return_value=mock_client,
        ),
        patch.dict(sys.modules, {"utils.voice": fake_voice}),
    ):
        service = Translation_Service(config)
        result = service.translate(content)

    # thread_title
    _assert_no_wrappers_introduced(
        "thread_title",
        content["thread_title"],
        result["thread_title"],
    )

    # thread_post
    _assert_no_wrappers_introduced(
        "thread_post",
        content["thread_post"],
        result["thread_post"],
    )

    # comment_body for every comment
    for i, (in_c, out_c) in enumerate(
        zip(content["comments"], result["comments"])
    ):
        _assert_no_wrappers_introduced(
            f"comments[{i}].comment_body",
            in_c["comment_body"],
            out_c["comment_body"],
        )
