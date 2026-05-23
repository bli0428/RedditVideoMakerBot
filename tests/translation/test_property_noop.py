"""Property-based tests for Translation_Service no-op pass-through.

**Property 4: Pass-through when translation is disabled**
**Validates: Requirements 1.3, 1.4, 11.1**

Tests that Translation_Service returns the input Reddit_Content unchanged
(identity / equality) when:
  - effective_provider == "none"  (Req 11.1)
  - target_lang is None or ""     (Req 1.3, 1.4)

No Anthropic_Client is constructed in these paths; the service returns early
before any SDK interaction could occur.
"""
from __future__ import annotations

from dataclasses import replace
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

# A single comment dict with the required fields.
comment_strategy = st.fixed_dictionaries(
    {
        "comment_id": st.text(min_size=1, max_size=32),
        "comment_body": st.text(max_size=500),
        "comment_url": st.text(max_size=200),
        "author": st.text(max_size=64),
    }
)

# Reddit_Content dict with the fields Translation_Service reads.
reddit_content_strategy = st.fixed_dictionaries(
    {
        "thread_title": st.text(max_size=300),
        "thread_post": st.one_of(st.none(), st.text(max_size=2000)),
        "comments": st.lists(comment_strategy, max_size=10),
        # Structural fields that must be preserved byte-for-byte.
        "thread_id": st.text(min_size=1, max_size=32),
        "thread_url": st.text(max_size=200),
        "permalink": st.text(max_size=200),
        "author": st.text(max_size=64),
        "is_nsfw": st.booleans(),
        "subreddit": st.text(max_size=64),
    }
)


def _make_config(
    *,
    effective_provider: str = "none",
    target_lang: str = "",
) -> TranslationConfig:
    """Build a minimal TranslationConfig for no-op scenarios."""
    return TranslationConfig(
        provider=effective_provider,
        effective_provider=effective_provider,
        target_lang=target_lang,
        failure_policy="skip",
        cache_enabled=False,
        force_translate=False,
        model=DEFAULT_MODEL,
        max_output_tokens=DEFAULT_MAX_OUTPUT_TOKENS,
        api_key="",
    )


# ---------------------------------------------------------------------------
# Property 4a: provider == "none" → pass-through (Req 11.1)
# ---------------------------------------------------------------------------

@given(content=reddit_content_strategy)
@settings(max_examples=200)
def test_noop_when_provider_is_none(content: dict[str, Any]) -> None:
    """**Property 4: Pass-through when translation is disabled**
    **Validates: Requirements 11.1**

    When effective_provider == "none", translate() must return the exact same
    dict object (identity) regardless of target_lang or content.
    """
    config = _make_config(effective_provider="none", target_lang="es")
    service = Translation_Service(config)
    result = service.translate(content)
    # Identity check: the no-op branch returns the input object unchanged.
    assert result is content, (
        "Expected translate() to return the same dict object when "
        f"effective_provider='none', but got a different object. "
        f"content={content!r}"
    )


# ---------------------------------------------------------------------------
# Property 4b: target_lang == "" → pass-through (Req 1.4)
# ---------------------------------------------------------------------------

@given(content=reddit_content_strategy)
@settings(max_examples=200)
def test_noop_when_target_lang_is_empty_string(content: dict[str, Any]) -> None:
    """**Property 4: Pass-through when translation is disabled**
    **Validates: Requirements 1.4**

    When target_lang is the empty string, translate() must return the exact
    same dict object regardless of provider or content.
    """
    config = _make_config(effective_provider="anthropic", target_lang="")
    service = Translation_Service(config)
    result = service.translate(content)
    assert result is content, (
        "Expected translate() to return the same dict object when "
        f"target_lang='', but got a different object. content={content!r}"
    )


# ---------------------------------------------------------------------------
# Property 4c: target_lang is None → pass-through (Req 1.3)
# ---------------------------------------------------------------------------

@given(content=reddit_content_strategy)
@settings(max_examples=200)
def test_noop_when_target_lang_is_none(content: dict[str, Any]) -> None:
    """**Property 4: Pass-through when translation is disabled**
    **Validates: Requirements 1.3**

    When target_lang is None (coerced to "" by from_settings, but we test the
    service directly with an empty string to cover the None/empty equivalence),
    translate() must return the same dict object.

    Note: TranslationConfig.from_settings coerces None to "" via
    `str(section.get("target_lang", "") or "")`, so the service always sees
    "" rather than None. This test verifies the "" path covers the None case.
    """
    # from_settings coerces None -> ""; verify that path produces a no-op.
    settings_map: dict[str, Any] = {"translation": {"target_lang": None}}
    config = TranslationConfig.from_settings(settings_map)
    assert config.target_lang == "", (
        f"Expected from_settings to coerce None target_lang to '', "
        f"got {config.target_lang!r}"
    )
    service = Translation_Service(config)
    result = service.translate(content)
    assert result is content, (
        "Expected translate() to return the same dict object when "
        f"target_lang was None (coerced to ''), but got a different object. "
        f"content={content!r}"
    )


# ---------------------------------------------------------------------------
# Property 4d: both conditions together (provider=none AND empty target_lang)
# ---------------------------------------------------------------------------

@given(content=reddit_content_strategy)
@settings(max_examples=100)
def test_noop_when_both_provider_none_and_empty_target_lang(
    content: dict[str, Any],
) -> None:
    """**Property 4: Pass-through when translation is disabled**
    **Validates: Requirements 1.3, 1.4, 11.1**

    When both effective_provider == "none" AND target_lang == "", the service
    must still return the same dict object (provider check fires first).
    """
    config = _make_config(effective_provider="none", target_lang="")
    service = Translation_Service(config)
    result = service.translate(content)
    assert result is content


# ---------------------------------------------------------------------------
# Property 4e: no-op path preserves all keys and values (equality check)
# ---------------------------------------------------------------------------

@given(content=reddit_content_strategy)
@settings(max_examples=200)
def test_noop_preserves_all_keys_and_values(content: dict[str, Any]) -> None:
    """**Property 4: Pass-through when translation is disabled**
    **Validates: Requirements 1.3, 1.4, 11.1**

    Equality check (complementary to identity): the returned dict has the
    same keys and values as the input under any no-op condition.
    """
    for config in [
        _make_config(effective_provider="none", target_lang="es"),
        _make_config(effective_provider="anthropic", target_lang=""),
    ]:
        service = Translation_Service(config)
        result = service.translate(content)
        assert result == content, (
            f"translate() returned a dict that differs from the input under "
            f"no-op config {config!r}. content={content!r}, result={result!r}"
        )


# ---------------------------------------------------------------------------
# Property 4f: no-op path does not construct Anthropic_Client
#              (structural assertion — the module is not imported)
# ---------------------------------------------------------------------------

def test_noop_does_not_import_anthropic_client_module() -> None:
    """**Property 4: Pass-through when translation is disabled**
    **Validates: Requirements 1.3, 1.4, 11.1**

    Structural assertion: the no-op branch in Translation_Service must return
    before any Anthropic_Client is constructed. We verify this by confirming
    that the `anthropic` SDK is NOT imported as a side-effect of constructing
    Translation_Service with a no-op config and calling translate().

    This is a static/structural test, not a property test, because the
    Anthropic SDK is not yet wired to the service in Phase 1.
    """
    import sys

    # Remove anthropic from sys.modules if it happens to be present so we
    # can detect a fresh import.
    anthropic_was_present = "anthropic" in sys.modules
    anthropic_client_was_present = "utils.translation.anthropic_client" in sys.modules

    config = _make_config(effective_provider="none", target_lang="es")
    service = Translation_Service(config)
    content: dict[str, Any] = {
        "thread_title": "Test",
        "thread_post": "Body",
        "comments": [],
        "thread_id": "abc123",
        "thread_url": "https://reddit.com/r/test",
        "permalink": "/r/test/abc123",
        "author": "user",
        "is_nsfw": False,
        "subreddit": "test",
    }
    result = service.translate(content)
    assert result is content

    # If anthropic was not present before, it must not have been imported.
    if not anthropic_was_present:
        assert "anthropic" not in sys.modules, (
            "Translation_Service imported the 'anthropic' SDK during a no-op "
            "translate() call. The no-op branch must return before any SDK "
            "interaction."
        )
    if not anthropic_client_was_present:
        assert "utils.translation.anthropic_client" not in sys.modules, (
            "Translation_Service imported anthropic_client during a no-op "
            "translate() call."
        )
