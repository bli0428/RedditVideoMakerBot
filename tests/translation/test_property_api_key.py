"""Property test for API-key environment precedence.

**Property 15: API-key environment precedence**
**Validates: Requirements 3.4**

Hypothesis-generate (env_value, config_value) pairs of strings, set/unset
ANTHROPIC_API_KEY accordingly, and assert resolve_api_key() returns env when
non-empty, then config_value, and raises TranslationConfigError naming both
sources when both are empty.
"""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from utils.translation.config import TranslationConfig
from utils.translation.errors import TranslationConfigError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Strategy for non-empty strings (printable ASCII, no null bytes)
_nonempty_str = st.text(
    alphabet=st.characters(
        whitelist_categories=("Lu", "Ll", "Nd", "Pc", "Pd"),
        whitelist_characters="._-",
    ),
    min_size=1,
    max_size=64,
)

# Strategy for possibly-empty strings (empty string represents "not set")
_maybe_empty_str = st.one_of(st.just(""), _nonempty_str)


def _make_config(api_key: str) -> TranslationConfig:
    """Build a minimal TranslationConfig with the given api_key field."""
    return TranslationConfig(
        provider="anthropic",
        effective_provider="anthropic",
        target_lang="es",
        failure_policy="skip",
        cache_enabled=True,
        force_translate=False,
        model="claude-3-5-sonnet-latest",
        max_output_tokens=4096,
        api_key=api_key,
    )


# ---------------------------------------------------------------------------
# Property 15: API-key environment precedence
# ---------------------------------------------------------------------------


@given(
    env_value=_nonempty_str,
    config_value=_maybe_empty_str,
)
@settings(max_examples=100)
def test_env_key_takes_precedence_over_config(env_value: str, config_value: str) -> None:
    """When ANTHROPIC_API_KEY env var is non-empty, resolve_api_key() returns it
    regardless of the config api_key value (Req 3.4).
    """
    config = _make_config(config_value)
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": env_value}, clear=False):
        result = config.resolve_api_key()
    assert result == env_value, (
        f"Expected env value {env_value!r} but got {result!r} "
        f"(config_value={config_value!r})"
    )


@given(
    config_value=_nonempty_str,
)
@settings(max_examples=100)
def test_config_key_used_when_env_absent(config_value: str) -> None:
    """When ANTHROPIC_API_KEY is unset (or empty), resolve_api_key() returns
    the config api_key when it is non-empty (Req 3.4).
    """
    config = _make_config(config_value)
    # Remove the env var entirely so only the config value is available
    env_without_key = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
    with patch.dict(os.environ, env_without_key, clear=True):
        result = config.resolve_api_key()
    assert result == config_value, (
        f"Expected config value {config_value!r} but got {result!r}"
    )


@given(
    config_value=_nonempty_str,
)
@settings(max_examples=50)
def test_empty_env_falls_back_to_config(config_value: str) -> None:
    """When ANTHROPIC_API_KEY is set to the empty string, resolve_api_key()
    falls back to the config api_key (Req 3.4 — env must be non-empty to win).
    """
    config = _make_config(config_value)
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}, clear=False):
        result = config.resolve_api_key()
    assert result == config_value, (
        f"Expected config value {config_value!r} but got {result!r} "
        f"when env is empty string"
    )


@settings(max_examples=1)
@given(st.just(None))  # single-case: both sources empty
def test_both_empty_raises_translation_config_error(_: None) -> None:
    """When both ANTHROPIC_API_KEY and config api_key are empty/absent,
    resolve_api_key() raises TranslationConfigError whose message names both
    configuration sources (Req 3.4, 3.5).
    """
    config = _make_config("")
    env_without_key = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
    with patch.dict(os.environ, env_without_key, clear=True):
        with pytest.raises(TranslationConfigError) as exc_info:
            config.resolve_api_key()

    message = str(exc_info.value)
    # The error message must name both configuration sources so the operator
    # knows where to look (Req 3.4 / 3.5).
    assert "ANTHROPIC_API_KEY" in message, (
        f"Error message should mention ANTHROPIC_API_KEY env var; got: {message!r}"
    )
    assert "api_key" in message or "config" in message.lower(), (
        f"Error message should mention the config api_key source; got: {message!r}"
    )


@given(
    env_value=_nonempty_str,
    config_value=_nonempty_str,
)
@settings(max_examples=100)
def test_env_wins_when_both_set(env_value: str, config_value: str) -> None:
    """When both ANTHROPIC_API_KEY and config api_key are non-empty, the env
    var wins (Req 3.4 — env takes precedence).
    """
    config = _make_config(config_value)
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": env_value}, clear=False):
        result = config.resolve_api_key()
    assert result == env_value, (
        f"Env var {env_value!r} should win over config {config_value!r}; "
        f"got {result!r}"
    )
