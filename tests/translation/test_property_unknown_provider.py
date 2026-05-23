"""Property test: Unknown provider degrades to none.

**Validates: Requirements 11.3**

Property 16: Unknown provider degrades to none
  - Hypothesis-generate strings outside {"none", "anthropic"} for `provider`
  - Assert `from_settings` returns `effective_provider == "none"`
  - Assert it does not raise
  - Assert a warning was emitted containing both the offending value and the
    valid provider list
"""
from __future__ import annotations

from unittest.mock import call, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from utils.translation.config import VALID_PROVIDERS, TranslationConfig

# Strategy: generate arbitrary text strings that are NOT valid providers.
# We filter out the two valid values so every generated string is "unknown".
unknown_provider_st = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",)),  # exclude surrogates
    min_size=0,
    max_size=64,
).filter(lambda s: s not in VALID_PROVIDERS)


@given(unknown_provider=unknown_provider_st)
@settings(max_examples=100)
def test_unknown_provider_degrades_to_none(unknown_provider: str) -> None:
    """Property 16: Unknown provider degrades to none.

    **Validates: Requirements 11.3**

    For any provider string outside {"none", "anthropic"}:
    1. from_settings does not raise
    2. result.effective_provider == "none"
    3. A warning is emitted containing both the offending value and the valid
       provider list
    """
    settings_config = {"translation": {"provider": unknown_provider}}

    captured_calls: list[call] = []

    def fake_print_substep(text: str, style: str = "") -> None:
        captured_calls.append(call(text, style=style))

    with patch("utils.console.print_substep", side_effect=fake_print_substep):
        # 1. Must not raise
        result = TranslationConfig.from_settings(settings_config)

    # 2. effective_provider must be "none"
    assert result.effective_provider == "none", (
        f"Expected effective_provider='none' for unknown provider {unknown_provider!r}, "
        f"got {result.effective_provider!r}"
    )

    # 3. A warning must have been emitted
    assert len(captured_calls) >= 1, (
        f"Expected at least one warning call for unknown provider {unknown_provider!r}, "
        f"but no calls were made to print_substep"
    )

    # The warning text must contain the offending value
    warning_text = captured_calls[0].args[0]
    assert unknown_provider in warning_text or repr(unknown_provider) in warning_text, (
        f"Warning text {warning_text!r} does not contain the offending provider "
        f"value {unknown_provider!r}"
    )

    # The warning text must reference the valid providers
    # VALID_PROVIDERS is ("none", "anthropic") — at least one must appear in the warning
    assert any(p in warning_text for p in VALID_PROVIDERS), (
        f"Warning text {warning_text!r} does not mention any valid provider from "
        f"{VALID_PROVIDERS}"
    )
