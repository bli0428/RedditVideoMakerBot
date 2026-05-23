"""Property-based tests for Translation_Service determinism.

**Property 1: Determinism under fixed model and config**
**Validates: Requirements 8.1**

Hypothesis-generate ``Reddit_Content`` and ``TranslationConfig`` with
``provider = "anthropic"``; with a deterministic mocked ``Anthropic_Client``,
call ``translate`` twice and assert value equality.

The mock client:
  - ``detect_source_language`` returns a language different from ``target_lang``
    so translation always proceeds.
  - ``translate`` returns ``"translated: " + original`` deterministically.

``utils.voice.sanitize_text`` is patched to return its input unchanged so
sanitizer side-effects do not interfere with the equality assertion.
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
        "comment_url": st.text(max_size=200),
        "comment_body": st.text(max_size=500),
        "author": st.text(max_size=64),
    }
)

# Reddit_Content dict with all fields Translation_Service reads.
_reddit_content_strategy = st.fixed_dictionaries(
    {
        # Translatable fields
        "thread_title": st.text(min_size=1, max_size=300),
        "thread_post": st.text(max_size=2000),  # str only — non-str raises TypeError
        "comments": st.lists(_comment_strategy, max_size=5),
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

# Target language codes that are distinct from the source language the mock
# detector will return ("en"), so translation always proceeds.
_target_lang_strategy = st.sampled_from(["es", "fr", "de", "ja", "pt-BR", "zh-CN"])

# Model identifiers: non-empty strings without whitespace.
_model_strategy = st.text(
    alphabet=st.characters(
        whitelist_categories=("Lu", "Ll", "Nd", "Pc", "Pd"),
        whitelist_characters=".-_",
    ),
    min_size=1,
    max_size=64,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(target_lang: str, model: str = DEFAULT_MODEL) -> TranslationConfig:
    """Build a TranslationConfig with provider='anthropic' and cache disabled."""
    return TranslationConfig(
        provider="anthropic",
        effective_provider="anthropic",
        target_lang=target_lang,
        failure_policy="skip",
        cache_enabled=False,
        force_translate=False,
        model=model,
        max_output_tokens=DEFAULT_MAX_OUTPUT_TOKENS,
        api_key="test-key",
    )


def _make_mock_client() -> MagicMock:
    """Return a deterministic mock Anthropic_Client.

    - ``detect_source_language`` always returns ``"en"`` (different from any
      target_lang in ``_target_lang_strategy``), so translation always proceeds.
    - ``translate(text, target_lang)`` returns ``"translated: " + text``
      deterministically.
    """
    mock_client = MagicMock()
    mock_client.detect_source_language.return_value = "en"
    mock_client.translate.side_effect = lambda text, target_lang: f"translated: {text}"
    return mock_client


# ---------------------------------------------------------------------------
# Property 1: Determinism under fixed model and config (Req 8.1)
# ---------------------------------------------------------------------------


@given(
    content=_reddit_content_strategy,
    target_lang=_target_lang_strategy,
)
@settings(max_examples=200)
def test_determinism_same_output_on_two_calls(
    content: dict[str, Any],
    target_lang: str,
) -> None:
    """**Property 1: Determinism under fixed model and config**
    **Validates: Requirements 8.1**

    Calling ``Translation_Service(config).translate(content)`` twice with the
    same input and a deterministic mock client must produce equal outputs.

    Both calls share the same ``Translation_Service`` instance (and therefore
    the same injected mock client) to mirror the real scenario where the same
    model and config are used for both invocations.
    """
    config = _make_config(target_lang=target_lang)
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
        result1 = service.translate(content)
        result2 = service.translate(content)

    assert result1 == result2, (
        f"translate() produced different outputs on two calls with the same "
        f"input and deterministic mock client.\n"
        f"result1={result1!r}\n"
        f"result2={result2!r}"
    )


@given(
    content=_reddit_content_strategy,
    target_lang=_target_lang_strategy,
)
@settings(max_examples=200)
def test_determinism_separate_service_instances(
    content: dict[str, Any],
    target_lang: str,
) -> None:
    """**Property 1: Determinism under fixed model and config**
    **Validates: Requirements 8.1**

    Two separate ``Translation_Service`` instances with the same config and
    the same deterministic mock client must produce equal outputs for the same
    input.  This verifies that no instance-level mutable state (other than the
    injected client) affects the output.
    """
    config = _make_config(target_lang=target_lang)
    mock_client = _make_mock_client()

    fake_voice = _make_fake_voice_module()
    with (
        patch(
            "utils.translation.service.Translation_Service._build_client",
            return_value=mock_client,
        ),
        patch.dict(sys.modules, {"utils.voice": fake_voice}),
    ):
        service1 = Translation_Service(config)
        result1 = service1.translate(content)

        service2 = Translation_Service(config)
        result2 = service2.translate(content)

    assert result1 == result2, (
        f"Two separate Translation_Service instances with the same config "
        f"produced different outputs for the same input.\n"
        f"result1={result1!r}\n"
        f"result2={result2!r}"
    )


@given(
    content=_reddit_content_strategy,
    target_lang=_target_lang_strategy,
    model=_model_strategy,
)
@settings(max_examples=200)
def test_determinism_across_model_variants(
    content: dict[str, Any],
    target_lang: str,
    model: str,
) -> None:
    """**Property 1: Determinism under fixed model and config**
    **Validates: Requirements 8.1**

    For any model identifier, two calls with the same config and deterministic
    mock client must produce equal outputs.  This ensures the model field does
    not introduce non-determinism in the service layer.
    """
    config = _make_config(target_lang=target_lang, model=model)
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
        result1 = service.translate(content)
        result2 = service.translate(content)

    assert result1 == result2, (
        f"translate() produced different outputs on two calls with model={model!r}.\n"
        f"result1={result1!r}\n"
        f"result2={result2!r}"
    )
