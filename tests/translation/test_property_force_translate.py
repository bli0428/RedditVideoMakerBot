"""Property-based tests for force_translate skipping source-language detection.

**Property 6: Force-translate skips detection**
**Validates: Requirements 5.4**

When ``force_translate = True``, ``Translation_Service`` SHALL skip
Source_Language detection entirely and translate every Translatable_Field
without calling ``detect_source_language`` at all.

Strategy:
- Hypothesis-generate ``Reddit_Content`` dicts with non-empty string fields.
- Build a ``TranslationConfig`` with ``force_translate=True``,
  ``provider="anthropic"``, ``target_lang="es"``, and ``cache_enabled=False``.
- Mock ``_build_client`` to return a mock client whose
  ``detect_source_language`` and ``translate`` methods are tracked.
- ``translate`` returns ``"translated: " + text``; ``detect_source_language``
  returns ``"en"``.
- Inject a fake ``utils.voice`` module with an identity ``sanitize_text``.
- Call ``translate(content)`` and assert ``detect_source_language`` was
  called exactly zero times.

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

_comment_strategy = st.fixed_dictionaries(
    {
        "comment_id": st.text(min_size=1, max_size=32),
        "comment_body": st.text(min_size=1, max_size=500),
        "comment_url": st.text(max_size=200),
        "author": st.text(max_size=64),
    }
)

_reddit_content_strategy = st.fixed_dictionaries(
    {
        "thread_title": st.text(min_size=1, max_size=300),
        "thread_post": st.text(min_size=1, max_size=2000),
        "comments": st.lists(_comment_strategy, max_size=5),
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


def _make_force_translate_config() -> TranslationConfig:
    """Build a TranslationConfig with force_translate=True targeting Spanish."""
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
    """Return a mock Anthropic_Client with tracked detect_source_language.

    - ``translate`` returns ``"translated: " + text`` so the result is
      non-empty and sanitize_text won't collapse it.
    - ``detect_source_language`` returns ``"en"`` and is tracked to verify
      it is never called when ``force_translate=True``.
    """
    mock_client = MagicMock()
    # translate returns a non-empty string derived from the input
    mock_client.translate.side_effect = lambda text, target_lang: "translated: " + text
    # detect_source_language is tracked — it should never be called
    mock_client.detect_source_language = MagicMock(return_value="en")
    return mock_client


# ---------------------------------------------------------------------------
# Property 6: force_translate=True → detect_source_language called 0 times
# ---------------------------------------------------------------------------


@given(content=_reddit_content_strategy)
@settings(max_examples=200)
def test_force_translate_skips_detection(content: dict[str, Any]) -> None:
    """**Property 6: Force-translate skips detection**
    **Validates: Requirements 5.4**

    When ``force_translate = True``, ``Translation_Service.translate`` must
    NOT call ``detect_source_language`` on the client, regardless of the
    content or target language.
    """
    config = _make_force_translate_config()
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
        service.translate(content)

    assert mock_client.detect_source_language.call_count == 0, (
        f"Expected detect_source_language to be called 0 times with "
        f"force_translate=True, but it was called "
        f"{mock_client.detect_source_language.call_count} time(s). "
        f"content keys={list(content.keys())!r}"
    )


@given(content=_reddit_content_strategy)
@settings(max_examples=200)
def test_force_translate_still_translates_fields(content: dict[str, Any]) -> None:
    """**Property 6: Force-translate skips detection**
    **Validates: Requirements 5.4**

    Complementary check: with ``force_translate = True``, translation of
    Translatable_Fields still proceeds (i.e., ``translate`` is called on the
    client), confirming that skipping detection does not also skip translation.
    """
    config = _make_force_translate_config()
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
        service.translate(content)

    # At least thread_title must be translated (it is always a Translatable_Field)
    assert mock_client.translate.call_count >= 1, (
        f"Expected at least one translate call with force_translate=True, "
        f"but got {mock_client.translate.call_count} call(s)."
    )
    # detect_source_language must still be zero
    assert mock_client.detect_source_language.call_count == 0, (
        f"detect_source_language was called despite force_translate=True"
    )
