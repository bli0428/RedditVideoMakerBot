"""TranslationConfig: parsed and validated [translation] section of config.toml.

Provides a frozen dataclass with all translation settings, including defaults
per Req 3.2/3.3 and unknown-provider degradation per Req 11.3.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

from utils.translation.errors import TranslationConfigError

VALID_PROVIDERS = ("none", "anthropic")
VALID_FAILURE_POLICIES = ("skip", "fail")
DEFAULT_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_MAX_OUTPUT_TOKENS = 4096


@dataclass(frozen=True)
class TranslationConfig:
    """Parsed and validated [translation] section of config.toml.

    `provider` is the as-configured value. `effective_provider` is the value
    after Req 11.3 degradation (unknown -> "none" with a warning).
    """

    provider: str
    effective_provider: str
    target_lang: str
    failure_policy: str
    cache_enabled: bool
    force_translate: bool
    # Anthropic-specific
    model: str
    max_output_tokens: int
    api_key: str  # may be empty; resolved lazily in has_api_key()

    def has_api_key(self) -> bool:
        """Resolve API key with environment precedence (Req 3.4).

        Returns True if either ANTHROPIC_API_KEY env var is set OR
        [translation.anthropic].api_key is non-empty. Lazy: never called at
        startup, only on first translation attempt (Req 3.5).
        """
        env = os.environ.get("ANTHROPIC_API_KEY", "")
        return bool(env) or bool(self.api_key)

    def resolve_api_key(self) -> str:
        """Return the API key in effect. Env var wins (Req 3.4).

        Raises TranslationConfigError if neither ANTHROPIC_API_KEY env var
        nor [translation.anthropic].api_key is set.
        """
        env = os.environ.get("ANTHROPIC_API_KEY", "")
        if env:
            return env
        if self.api_key:
            return self.api_key
        raise TranslationConfigError(
            "No Anthropic API key. Set ANTHROPIC_API_KEY env var or "
            "[translation.anthropic].api_key in config.toml."
        )

    @classmethod
    def from_settings(cls, settings_config: Mapping) -> "TranslationConfig":
        """Parse settings.config and return a validated TranslationConfig.

        Defaults apply per Req 3.2 / 3.3 even when [translation] is absent.
        Unknown provider logs a warning and sets effective_provider = "none"
        without aborting (Req 11.3).
        """
        section = settings_config.get("translation", {}) or {}
        anthropic_section = section.get("anthropic", {}) or {}

        provider_raw = section.get("provider", "none")
        if provider_raw not in VALID_PROVIDERS:
            # Req 11.3: log + degrade to "none", do not abort startup.
            from utils.console import print_substep

            print_substep(
                f"[warn] Unknown translation.provider {provider_raw!r}; "
                f"valid: {VALID_PROVIDERS}. Disabling translation for this run.",
                style="yellow",
            )
            effective = "none"
        else:
            effective = provider_raw

        failure_policy = section.get("failure_policy", "skip")
        if failure_policy not in VALID_FAILURE_POLICIES:
            raise TranslationConfigError(
                f"Invalid failure_policy {failure_policy!r}; "
                f"valid: {VALID_FAILURE_POLICIES}"
            )

        return cls(
            provider=provider_raw,
            effective_provider=effective,
            target_lang=str(section.get("target_lang", "") or ""),
            failure_policy=failure_policy,
            cache_enabled=bool(section.get("cache_enabled", True)),
            force_translate=bool(section.get("force_translate", False)),
            model=str(anthropic_section.get("model", DEFAULT_MODEL)),
            max_output_tokens=int(
                anthropic_section.get("max_output_tokens", DEFAULT_MAX_OUTPUT_TOKENS)
            ),
            api_key=str(anthropic_section.get("api_key", "") or ""),
        )
