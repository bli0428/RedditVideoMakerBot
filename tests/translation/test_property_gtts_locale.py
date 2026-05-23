"""Property-based tests for gTTS locale precedence in TTS/GTTS.py.

**Property 25: gTTS locale precedence**
**Validates: Requirements 10.5, 10.6**

Hypothesis-generate ``(target_lang, post_lang)`` string pairs; monkey-patch
``settings.config`` and ``gtts.gTTS``; assert the resolved locale equals
``target_lang`` when non-empty, else ``post_lang`` when non-empty, else
``"en"`` with a warning emitted.
"""
from __future__ import annotations

import sys
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Language codes: either empty string or a short non-empty code like "es", "pt-BR"
_lang_code = st.one_of(
    st.just(""),
    st.from_regex(r"[a-z]{2}(-[A-Z]{2})?", fullmatch=True).filter(lambda s: len(s) >= 2),
)

# Pairs of (target_lang, post_lang)
_lang_pair = st.tuples(_lang_code, _lang_code)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_settings_config(target_lang: str, post_lang: str) -> dict[str, Any]:
    """Build a minimal settings.config dict for the GTTS.run() call."""
    return {
        "translation": {
            "target_lang": target_lang,
        },
        "reddit": {
            "thread": {
                "post_lang": post_lang,
            }
        },
    }


def _run_gtts_and_capture_lang(target_lang: str, post_lang: str) -> tuple[str, list[str]]:
    """
    Invoke GTTS().run() with the given locale config and return
    (lang_passed_to_gTTS, list_of_warning_messages_emitted).
    """
    config = _build_settings_config(target_lang, post_lang)

    captured_lang: list[str] = []
    warnings_emitted: list[str] = []

    # Mock gTTS so it captures the lang argument without making network calls.
    mock_tts_instance = MagicMock()
    mock_tts_instance.save = MagicMock()

    def fake_gtts(**kwargs):
        captured_lang.append(kwargs.get("lang", ""))
        return mock_tts_instance

    # Capture warnings emitted via print_substep with style="yellow".
    original_print_substep = None

    def fake_print_substep(text, style=""):
        if style == "yellow":
            warnings_emitted.append(text)

    # We need to reload GTTS module to ensure fresh patching each time.
    # Instead, we patch at the module level where GTTS.py imports them.
    with patch("TTS.GTTS.settings") as mock_settings, \
         patch("TTS.GTTS.gTTS", side_effect=fake_gtts), \
         patch("TTS.GTTS.print_substep", side_effect=fake_print_substep):

        mock_settings.config = config

        # Import here to ensure the module is loaded after patches are applied.
        from TTS.GTTS import GTTS
        gtts_instance = GTTS()
        gtts_instance.run("test text", "test.mp3")

    assert len(captured_lang) == 1, (
        f"Expected gTTS to be called exactly once, got {len(captured_lang)} calls. "
        f"target_lang={target_lang!r}, post_lang={post_lang!r}"
    )
    return captured_lang[0], warnings_emitted


# ---------------------------------------------------------------------------
# Property 25a: target_lang non-empty → use target_lang (Req 10.5)
# ---------------------------------------------------------------------------

@given(
    target_lang=st.from_regex(r"[a-z]{2}(-[A-Z]{2})?", fullmatch=True).filter(
        lambda s: len(s) >= 2
    ),
    post_lang=_lang_code,
)
@settings(max_examples=100)
def test_gtts_uses_target_lang_when_non_empty(
    target_lang: str, post_lang: str
) -> None:
    """**Property 25: gTTS locale precedence**
    **Validates: Requirements 10.5**

    When ``[translation] target_lang`` is non-empty, gTTS MUST receive that
    value as its ``lang`` argument, regardless of ``post_lang``.
    """
    resolved_lang, warnings = _run_gtts_and_capture_lang(target_lang, post_lang)
    assert resolved_lang == target_lang, (
        f"Expected gTTS lang={target_lang!r} (from target_lang), "
        f"but got lang={resolved_lang!r}. "
        f"target_lang={target_lang!r}, post_lang={post_lang!r}"
    )
    # No warning should be emitted when a valid locale is resolved.
    assert not warnings, (
        f"Unexpected warning(s) emitted when target_lang={target_lang!r}: {warnings}"
    )


# ---------------------------------------------------------------------------
# Property 25b: target_lang empty, post_lang non-empty → use post_lang (Req 10.5)
# ---------------------------------------------------------------------------

@given(
    post_lang=st.from_regex(r"[a-z]{2}(-[A-Z]{2})?", fullmatch=True).filter(
        lambda s: len(s) >= 2
    ),
)
@settings(max_examples=100)
def test_gtts_falls_back_to_post_lang_when_target_lang_empty(
    post_lang: str,
) -> None:
    """**Property 25: gTTS locale precedence**
    **Validates: Requirements 10.5**

    When ``[translation] target_lang`` is empty and ``[reddit.thread] post_lang``
    is non-empty, gTTS MUST receive ``post_lang`` as its ``lang`` argument.
    """
    resolved_lang, warnings = _run_gtts_and_capture_lang("", post_lang)
    assert resolved_lang == post_lang, (
        f"Expected gTTS lang={post_lang!r} (from post_lang fallback), "
        f"but got lang={resolved_lang!r}. "
        f"target_lang='', post_lang={post_lang!r}"
    )
    # No warning should be emitted when a valid locale is resolved.
    assert not warnings, (
        f"Unexpected warning(s) emitted when post_lang={post_lang!r}: {warnings}"
    )


# ---------------------------------------------------------------------------
# Property 25c: both empty → "en" with a warning (Req 10.6)
# ---------------------------------------------------------------------------

@settings(max_examples=1)
@given(st.just(("", "")))
def test_gtts_falls_back_to_en_with_warning_when_both_empty(
    lang_pair: tuple[str, str],
) -> None:
    """**Property 25: gTTS locale precedence**
    **Validates: Requirements 10.6**

    When both ``[translation] target_lang`` and ``[reddit.thread] post_lang``
    are empty, gTTS MUST receive ``"en"`` as its ``lang`` argument AND a
    warning MUST be emitted.
    """
    target_lang, post_lang = lang_pair
    resolved_lang, warnings = _run_gtts_and_capture_lang(target_lang, post_lang)
    assert resolved_lang == "en", (
        f"Expected gTTS lang='en' when both locales are empty, "
        f"but got lang={resolved_lang!r}."
    )
    assert warnings, (
        "Expected a warning to be emitted when both target_lang and post_lang "
        "are empty, but no warning was captured."
    )


# ---------------------------------------------------------------------------
# Property 25d: precedence ordering across all combinations (Req 10.5, 10.6)
# ---------------------------------------------------------------------------

@given(lang_pair=_lang_pair)
@settings(max_examples=200)
def test_gtts_locale_precedence_property(lang_pair: tuple[str, str]) -> None:
    """**Property 25: gTTS locale precedence**
    **Validates: Requirements 10.5, 10.6**

    For any ``(target_lang, post_lang)`` pair, the resolved locale MUST equal:
    - ``target_lang`` if non-empty
    - ``post_lang`` if ``target_lang`` is empty and ``post_lang`` is non-empty
    - ``"en"`` if both are empty (and a warning MUST be emitted)
    """
    target_lang, post_lang = lang_pair
    resolved_lang, warnings = _run_gtts_and_capture_lang(target_lang, post_lang)

    if target_lang:
        expected = target_lang
        assert resolved_lang == expected, (
            f"Precedence violation: target_lang={target_lang!r} is non-empty "
            f"but gTTS received lang={resolved_lang!r}. "
            f"post_lang={post_lang!r}"
        )
        assert not warnings, (
            f"Unexpected warning when target_lang={target_lang!r} is non-empty: {warnings}"
        )
    elif post_lang:
        expected = post_lang
        assert resolved_lang == expected, (
            f"Precedence violation: target_lang is empty, post_lang={post_lang!r} "
            f"is non-empty, but gTTS received lang={resolved_lang!r}."
        )
        assert not warnings, (
            f"Unexpected warning when post_lang={post_lang!r} is non-empty: {warnings}"
        )
    else:
        # Both empty → must fall back to "en" with a warning.
        assert resolved_lang == "en", (
            f"Expected gTTS lang='en' when both locales are empty, "
            f"but got lang={resolved_lang!r}."
        )
        assert warnings, (
            "Expected a warning when both target_lang and post_lang are empty, "
            "but none was emitted."
        )
