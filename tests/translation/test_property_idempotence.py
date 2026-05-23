"""Property-based test for idempotence under same target language.

**Property 2: Idempotence under same target language**
**Validates: Requirements 8.2**

Hypothesis-generate ``Reddit_Content`` dicts and configs with non-empty
``target_lang``; assert ``translate(translate(input)) == translate(input)``.

The mock client always returns ``"translated_text"`` regardless of input, and
``detect_source_language`` always returns ``"en"`` (different from target
``"es"``). This means:

- First call: each Translatable_Field is translated to ``"translated_text"``.
- Second call: each Translatable_Field (already ``"translated_text"``) is
  translated again — but the mock returns ``"translated_text"`` again.
- Therefore ``translate(translate(input)) == translate(input)``.

The fake ``utils.voice`` module provides an identity ``sanitize_text`` so the
real module (which requires ``cleantext``) is never imported, and sanitizer
side-effects do not interfere with the idempotence check.
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

_comment_strategy = st.fixed_dictionaries(
    {
        "comment_id": st.text(min_size=1, max_size=32),
        "comment_url": st.text(max_size=200),
        "comment_body": st.text(max_size=500),
        "author": st.text(max_size=64),
    }
)

_reddit_content_strategy = st.fixed_dictionaries(
    {
        # Translatable fields
        "thread_title": st.text(max_size=300),
        "thread_post": st.one_of(st.none(), st.text(max_size=2000)),
        "comments": st.lists(_comment_strategy, max_size=10),
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

# Non-empty target language codes distinct from the "en" the mock detector
# returns, so translation always proceeds.
_target_lang_strategy = st.sampled_from(["es", "fr", "de", "ja", "pt-BR", "zh-CN"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(target_lang: str, force_translate: bool = True) -> TranslationConfig:
    """Build a TranslationConfig with provider=anthropic and cache disabled."""
    return TranslationConfig(
        provider="anthropic",
        effective_provider="anthropic",
        target_lang=target_lang,
        failure_policy="skip",
        cache_enabled=False,
        force_translate=force_translate,
        model=DEFAULT_MODEL,
        max_output_tokens=DEFAULT_MAX_OUTPUT_TOKENS,
        api_key="test-key",
    )


def _make_mock_client() -> MagicMock:
    """Return a mock Anthropic_Client that always returns 'translated_text'.

    - ``translate(text, target_lang)`` always returns ``"translated_text"``
      regardless of input, making the mock idempotent.
    - ``detect_source_language(sample)`` always returns ``"en"``.
    """
    mock_client = MagicMock()
    mock_client.translate.return_value = "translated_text"
    mock_client.detect_source_language.return_value = "en"
    return mock_client


# ---------------------------------------------------------------------------
# Property 2: Idempotence under same target language (Req 8.2)
# ---------------------------------------------------------------------------


@given(
    content=_reddit_content_strategy,
    target_lang=_target_lang_strategy,
)
@settings(max_examples=200)
def test_idempotence_translate_twice_equals_translate_once(
    content: dict[str, Any],
    target_lang: str,
) -> None:
    """**Property 2: Idempotence under same target language**
    **Validates: Requirements 8.2**

    Translating an already-translated Reddit_Content with the same target
    language must produce the same result as translating it once.

    That is: ``translate(translate(input)) == translate(input)``

    The mock client always returns ``"translated_text"`` for any input, so
    the second translation of an already-translated dict produces the same
    output as the first translation.
    """
    config = _make_config(target_lang, force_translate=True)
    mock_client = _make_mock_client()
    fake_voice = _make_fake_voice_module()

    with (
        patch.object(Translation_Service, "_build_client", return_value=mock_client),
        patch.dict(sys.modules, {"utils.voice": fake_voice}),
    ):
        service = Translation_Service(config)

        # First translation: translate(input)
        output1 = service.translate(content)

        # Second translation: translate(translate(input))
        output2 = service.translate(output1)

    assert output1 == output2, (
        f"Idempotence violated: translate(translate(input)) != translate(input).\n"
        f"output1={output1!r}\n"
        f"output2={output2!r}"
    )


@given(
    content=_reddit_content_strategy,
    target_lang=_target_lang_strategy,
)
@settings(max_examples=200)
def test_idempotence_structural_fields_preserved_across_both_calls(
    content: dict[str, Any],
    target_lang: str,
) -> None:
    """**Property 2: Idempotence under same target language**
    **Validates: Requirements 8.2**

    Structural fields must be preserved byte-for-byte through both translation
    calls, confirming that idempotence holds for the full dict including
    non-translatable fields.
    """
    _STRUCTURAL_FIELDS = (
        "thread_id",
        "thread_url",
        "permalink",
        "author",
        "avatar_url",
        "is_nsfw",
        "subreddit",
    )
    _COMMENT_STRUCTURAL_FIELDS = ("comment_id", "comment_url")

    config = _make_config(target_lang, force_translate=True)
    mock_client = _make_mock_client()
    fake_voice = _make_fake_voice_module()

    with (
        patch.object(Translation_Service, "_build_client", return_value=mock_client),
        patch.dict(sys.modules, {"utils.voice": fake_voice}),
    ):
        service = Translation_Service(config)
        output1 = service.translate(content)
        output2 = service.translate(output1)

    # Keys must be identical across all three dicts.
    assert output1.keys() == content.keys(), (
        f"output1 keys differ from input keys: "
        f"{set(output1.keys())} vs {set(content.keys())}"
    )
    assert output2.keys() == content.keys(), (
        f"output2 keys differ from input keys: "
        f"{set(output2.keys())} vs {set(content.keys())}"
    )

    # Top-level structural fields must be byte-for-byte identical.
    for field in _STRUCTURAL_FIELDS:
        if field in content:
            assert output1[field] == content[field], (
                f"output1: structural field '{field}' was modified. "
                f"input={content[field]!r}, output1={output1[field]!r}"
            )
            assert output2[field] == content[field], (
                f"output2: structural field '{field}' was modified. "
                f"input={content[field]!r}, output2={output2[field]!r}"
            )

    # Per-comment structural fields must be byte-for-byte identical.
    input_comments = content.get("comments", [])
    output1_comments = output1.get("comments", [])
    output2_comments = output2.get("comments", [])

    assert len(output1_comments) == len(input_comments)
    assert len(output2_comments) == len(input_comments)

    for i, (in_c, out1_c, out2_c) in enumerate(
        zip(input_comments, output1_comments, output2_comments)
    ):
        for field in _COMMENT_STRUCTURAL_FIELDS:
            if field in in_c:
                assert out1_c[field] == in_c[field], (
                    f"output1: comments[{i}].{field} was modified. "
                    f"input={in_c[field]!r}, output1={out1_c[field]!r}"
                )
                assert out2_c[field] == in_c[field], (
                    f"output2: comments[{i}].{field} was modified. "
                    f"input={in_c[field]!r}, output2={out2_c[field]!r}"
                )


@given(
    content=_reddit_content_strategy,
    target_lang=_target_lang_strategy,
)
@settings(max_examples=100)
def test_idempotence_with_force_translate_false_and_source_differs(
    content: dict[str, Any],
    target_lang: str,
) -> None:
    """**Property 2: Idempotence under same target language**
    **Validates: Requirements 8.2**

    Idempotence also holds when ``force_translate=False`` and the mock
    detector returns a source language different from the target. The second
    call on the already-translated output must produce the same result.
    """
    # Use force_translate=False; mock detect returns "en", target is e.g. "es"
    # so translation proceeds on both calls.
    config = _make_config(target_lang, force_translate=False)
    mock_client = _make_mock_client()
    # Ensure detected language never matches target so translation always runs.
    mock_client.detect_source_language.return_value = "en"
    fake_voice = _make_fake_voice_module()

    with (
        patch.object(Translation_Service, "_build_client", return_value=mock_client),
        patch.dict(sys.modules, {"utils.voice": fake_voice}),
    ):
        service = Translation_Service(config)
        output1 = service.translate(content)
        output2 = service.translate(output1)

    assert output1 == output2, (
        f"Idempotence violated with force_translate=False: "
        f"translate(translate(input)) != translate(input).\n"
        f"output1={output1!r}\n"
        f"output2={output2!r}"
    )
