"""Property test for TranslationConfig defaults.

**Property 14: Config defaults applied for missing keys**
**Validates: Requirements 3.2, 3.3**

Hypothesis-generates settings.config mappings where the [translation] section
is absent or omits subsets of keys; asserts each missing key resolves to the
documented default.
"""
from __future__ import annotations

from typing import Any, Dict

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from utils.translation.config import (
    DEFAULT_MAX_OUTPUT_TOKENS,
    DEFAULT_MODEL,
    TranslationConfig,
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# All valid keys in [translation] and their documented defaults
_TRANSLATION_KEYS = {
    "provider": "none",
    "target_lang": "",
    "failure_policy": "skip",
    "cache_enabled": True,
    "force_translate": False,
}

# All valid keys in [translation.anthropic] and their documented defaults
_ANTHROPIC_KEYS = {
    "model": DEFAULT_MODEL,
    "max_output_tokens": DEFAULT_MAX_OUTPUT_TOKENS,
    "api_key": "",
}

# Strategy: generate a subset of [translation] keys with valid values
_translation_values = st.fixed_dictionaries(
    {},
    optional={
        "provider": st.just("none"),
        "target_lang": st.just(""),
        "failure_policy": st.just("skip"),
        "cache_enabled": st.booleans(),
        "force_translate": st.booleans(),
    },
)

# Strategy: generate a subset of [translation.anthropic] keys with valid values
_anthropic_values = st.fixed_dictionaries(
    {},
    optional={
        "model": st.just(DEFAULT_MODEL),
        "max_output_tokens": st.integers(min_value=1, max_value=8192),
        "api_key": st.just(""),
    },
)


@st.composite
def settings_config_with_partial_translation(draw) -> Dict[str, Any]:
    """Generate a settings.config dict where [translation] may be absent or
    have a subset of keys, and [translation.anthropic] may be absent or have
    a subset of keys."""
    include_translation = draw(st.booleans())
    if not include_translation:
        return {}

    translation_section = draw(_translation_values)

    include_anthropic = draw(st.booleans())
    if include_anthropic:
        translation_section["anthropic"] = draw(_anthropic_values)

    return {"translation": translation_section}


# ---------------------------------------------------------------------------
# Property 14: Config defaults applied for missing keys
# ---------------------------------------------------------------------------


@given(settings_config=settings_config_with_partial_translation())
@settings(max_examples=200)
def test_provider_default_when_absent(settings_config: Dict[str, Any]) -> None:
    """When 'provider' is absent from [translation], it defaults to 'none'.

    **Property 14: Config defaults applied for missing keys**
    **Validates: Requirements 3.2, 3.3**
    """
    # Remove provider from the translation section if present, to test the default
    translation = settings_config.get("translation", {})
    translation.pop("provider", None)
    if translation is not None:
        settings_config = dict(settings_config)
        settings_config["translation"] = translation

    cfg = TranslationConfig.from_settings(settings_config)
    assert cfg.provider == "none", (
        f"Expected provider default 'none', got {cfg.provider!r}"
    )


@given(settings_config=settings_config_with_partial_translation())
@settings(max_examples=200)
def test_target_lang_default_when_absent(settings_config: Dict[str, Any]) -> None:
    """When 'target_lang' is absent from [translation], it defaults to ''.

    **Property 14: Config defaults applied for missing keys**
    **Validates: Requirements 3.2, 3.3**
    """
    translation = dict(settings_config.get("translation", {}))
    translation.pop("target_lang", None)
    settings_config = dict(settings_config)
    settings_config["translation"] = translation

    cfg = TranslationConfig.from_settings(settings_config)
    assert cfg.target_lang == "", (
        f"Expected target_lang default '', got {cfg.target_lang!r}"
    )


@given(settings_config=settings_config_with_partial_translation())
@settings(max_examples=200)
def test_failure_policy_default_when_absent(settings_config: Dict[str, Any]) -> None:
    """When 'failure_policy' is absent from [translation], it defaults to 'skip'.

    **Property 14: Config defaults applied for missing keys**
    **Validates: Requirements 3.2, 3.3**
    """
    translation = dict(settings_config.get("translation", {}))
    translation.pop("failure_policy", None)
    settings_config = dict(settings_config)
    settings_config["translation"] = translation

    cfg = TranslationConfig.from_settings(settings_config)
    assert cfg.failure_policy == "skip", (
        f"Expected failure_policy default 'skip', got {cfg.failure_policy!r}"
    )


@given(settings_config=settings_config_with_partial_translation())
@settings(max_examples=200)
def test_cache_enabled_default_when_absent(settings_config: Dict[str, Any]) -> None:
    """When 'cache_enabled' is absent from [translation], it defaults to True.

    **Property 14: Config defaults applied for missing keys**
    **Validates: Requirements 3.2, 3.3**
    """
    translation = dict(settings_config.get("translation", {}))
    translation.pop("cache_enabled", None)
    settings_config = dict(settings_config)
    settings_config["translation"] = translation

    cfg = TranslationConfig.from_settings(settings_config)
    assert cfg.cache_enabled is True, (
        f"Expected cache_enabled default True, got {cfg.cache_enabled!r}"
    )


@given(settings_config=settings_config_with_partial_translation())
@settings(max_examples=200)
def test_force_translate_default_when_absent(settings_config: Dict[str, Any]) -> None:
    """When 'force_translate' is absent from [translation], it defaults to False.

    **Property 14: Config defaults applied for missing keys**
    **Validates: Requirements 3.2, 3.3**
    """
    translation = dict(settings_config.get("translation", {}))
    translation.pop("force_translate", None)
    settings_config = dict(settings_config)
    settings_config["translation"] = translation

    cfg = TranslationConfig.from_settings(settings_config)
    assert cfg.force_translate is False, (
        f"Expected force_translate default False, got {cfg.force_translate!r}"
    )


@given(settings_config=settings_config_with_partial_translation())
@settings(max_examples=200)
def test_model_default_when_absent(settings_config: Dict[str, Any]) -> None:
    """When 'model' is absent from [translation.anthropic], it defaults to DEFAULT_MODEL.

    **Property 14: Config defaults applied for missing keys**
    **Validates: Requirements 3.2, 3.3**
    """
    settings_config = dict(settings_config)
    translation = dict(settings_config.get("translation", {}))
    anthropic_section = dict(translation.get("anthropic", {}))
    anthropic_section.pop("model", None)
    translation["anthropic"] = anthropic_section
    settings_config["translation"] = translation

    cfg = TranslationConfig.from_settings(settings_config)
    assert cfg.model == DEFAULT_MODEL, (
        f"Expected model default {DEFAULT_MODEL!r}, got {cfg.model!r}"
    )


@given(settings_config=settings_config_with_partial_translation())
@settings(max_examples=200)
def test_max_output_tokens_default_when_absent(settings_config: Dict[str, Any]) -> None:
    """When 'max_output_tokens' is absent from [translation.anthropic], it defaults to 4096.

    **Property 14: Config defaults applied for missing keys**
    **Validates: Requirements 3.2, 3.3**
    """
    settings_config = dict(settings_config)
    translation = dict(settings_config.get("translation", {}))
    anthropic_section = dict(translation.get("anthropic", {}))
    anthropic_section.pop("max_output_tokens", None)
    translation["anthropic"] = anthropic_section
    settings_config["translation"] = translation

    cfg = TranslationConfig.from_settings(settings_config)
    assert cfg.max_output_tokens == DEFAULT_MAX_OUTPUT_TOKENS, (
        f"Expected max_output_tokens default {DEFAULT_MAX_OUTPUT_TOKENS}, "
        f"got {cfg.max_output_tokens!r}"
    )


@given(settings_config=settings_config_with_partial_translation())
@settings(max_examples=200)
def test_api_key_default_when_absent(settings_config: Dict[str, Any]) -> None:
    """When 'api_key' is absent from [translation.anthropic], it defaults to ''.

    **Property 14: Config defaults applied for missing keys**
    **Validates: Requirements 3.2, 3.3**
    """
    settings_config = dict(settings_config)
    translation = dict(settings_config.get("translation", {}))
    anthropic_section = dict(translation.get("anthropic", {}))
    anthropic_section.pop("api_key", None)
    translation["anthropic"] = anthropic_section
    settings_config["translation"] = translation

    cfg = TranslationConfig.from_settings(settings_config)
    assert cfg.api_key == "", (
        f"Expected api_key default '', got {cfg.api_key!r}"
    )


@given(settings_config=settings_config_with_partial_translation())
@settings(max_examples=200)
def test_all_defaults_when_translation_section_absent(settings_config: Dict[str, Any]) -> None:
    """When the entire [translation] section is absent, all keys resolve to their defaults.

    **Property 14: Config defaults applied for missing keys**
    **Validates: Requirements 3.2, 3.3**
    """
    # Completely remove the translation section
    settings_config = {k: v for k, v in settings_config.items() if k != "translation"}

    cfg = TranslationConfig.from_settings(settings_config)

    assert cfg.provider == "none", f"provider default: got {cfg.provider!r}"
    assert cfg.target_lang == "", f"target_lang default: got {cfg.target_lang!r}"
    assert cfg.failure_policy == "skip", f"failure_policy default: got {cfg.failure_policy!r}"
    assert cfg.cache_enabled is True, f"cache_enabled default: got {cfg.cache_enabled!r}"
    assert cfg.force_translate is False, f"force_translate default: got {cfg.force_translate!r}"
    assert cfg.model == DEFAULT_MODEL, f"model default: got {cfg.model!r}"
    assert cfg.max_output_tokens == DEFAULT_MAX_OUTPUT_TOKENS, (
        f"max_output_tokens default: got {cfg.max_output_tokens!r}"
    )
    assert cfg.api_key == "", f"api_key default: got {cfg.api_key!r}"


def test_all_defaults_empty_dict() -> None:
    """Concrete example: from_settings({}) returns all documented defaults.

    **Property 14: Config defaults applied for missing keys**
    **Validates: Requirements 3.2, 3.3**
    """
    cfg = TranslationConfig.from_settings({})

    assert cfg.provider == "none"
    assert cfg.effective_provider == "none"
    assert cfg.target_lang == ""
    assert cfg.failure_policy == "skip"
    assert cfg.cache_enabled is True
    assert cfg.force_translate is False
    assert cfg.model == DEFAULT_MODEL
    assert cfg.max_output_tokens == DEFAULT_MAX_OUTPUT_TOKENS
    assert cfg.api_key == ""


def test_all_defaults_empty_translation_section() -> None:
    """Concrete example: from_settings({'translation': {}}) returns all documented defaults.

    **Property 14: Config defaults applied for missing keys**
    **Validates: Requirements 3.2, 3.3**
    """
    cfg = TranslationConfig.from_settings({"translation": {}})

    assert cfg.provider == "none"
    assert cfg.effective_provider == "none"
    assert cfg.target_lang == ""
    assert cfg.failure_policy == "skip"
    assert cfg.cache_enabled is True
    assert cfg.force_translate is False
    assert cfg.model == DEFAULT_MODEL
    assert cfg.max_output_tokens == DEFAULT_MAX_OUTPUT_TOKENS
    assert cfg.api_key == ""


def test_all_defaults_empty_anthropic_subsection() -> None:
    """Concrete example: from_settings({'translation': {'anthropic': {}}}) returns anthropic defaults.

    **Property 14: Config defaults applied for missing keys**
    **Validates: Requirements 3.2, 3.3**
    """
    cfg = TranslationConfig.from_settings({"translation": {"anthropic": {}}})

    assert cfg.model == DEFAULT_MODEL
    assert cfg.max_output_tokens == DEFAULT_MAX_OUTPUT_TOKENS
    assert cfg.api_key == ""
