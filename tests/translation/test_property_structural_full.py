"""Property test: Structural-Field byte-equality (full).

**Property 3: Structural-Field byte-equality**
**Validates: Requirements 1.2, 4.5, 6.4, 8.3, 15.5**

Hypothesis-generate inputs across all combinations of ``failure_policy``,
cache state, and provider; assert ``output.keys() == input.keys()`` and every
Structural_Field value (including ``comments[*].comment_id`` and
``comments[*].comment_url``) is preserved byte-for-byte.

Structural fields (never translated):
    thread_id, thread_url, permalink, author, avatar_url, is_nsfw, subreddit,
    comments[*].comment_id, comments[*].comment_url

Test matrix:
    failure_policy  in ["skip", "fail"]
    cache_enabled   in [True, False]
    provider        in ["none", "anthropic"]

With a mocked client (detect returns "en", translate returns "translated: " + text).
``utils.voice.sanitize_text`` is injected as an identity function via a fake
``utils.voice`` module in sys.modules.
"""
from __future__ import annotations

import sys
import tempfile
import types
from typing import Any
from unittest.mock import MagicMock, patch

from hypothesis import given, settings
from hypothesis import strategies as st

from utils.translation.cache import Translation_Cache
from utils.translation.config import (
    DEFAULT_MAX_OUTPUT_TOKENS,
    DEFAULT_MODEL,
    TranslationConfig,
)
from utils.translation.service import Translation_Service

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_TOP_LEVEL_STRUCTURAL_FIELDS = (
    "thread_id",
    "thread_url",
    "permalink",
    "author",
    "avatar_url",
    "is_nsfw",
    "subreddit",
)

_COMMENT_STRUCTURAL_FIELDS = (
    "comment_id",
    "comment_url",
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# A single comment dict with all structural and translatable fields.
_comment_strategy = st.fixed_dictionaries(
    {
        "comment_id": st.text(min_size=1, max_size=32),
        "comment_url": st.text(max_size=200),
        "comment_body": st.text(min_size=1, max_size=500),
        "author": st.text(max_size=64),
    }
)

# Full Reddit_Content dict with all structural fields present.
_reddit_content_strategy = st.fixed_dictionaries(
    {
        # Translatable fields — may be modified by the service
        "thread_title": st.text(min_size=1, max_size=300),
        "thread_post": st.one_of(st.none(), st.text(min_size=1, max_size=2000)),
        "comments": st.lists(_comment_strategy, min_size=0, max_size=10),
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

# Sampled from the full test matrix dimensions.
_failure_policy_strategy = st.sampled_from(["skip", "fail"])
_cache_enabled_strategy = st.booleans()
_provider_strategy = st.sampled_from(["none", "anthropic"])


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


def _make_mock_client() -> MagicMock:
    """Return a mock Anthropic_Client.

    - ``detect_source_language`` returns ``"en"`` (different from target "es"),
      so translation always proceeds.
    - ``translate(text, target_lang)`` returns ``"translated: " + text``
      deterministically.
    """
    mock_client = MagicMock()
    mock_client.detect_source_language.return_value = "en"
    mock_client.translate.side_effect = lambda text, target_lang: f"translated: {text}"
    return mock_client


def _make_fake_voice_module() -> types.ModuleType:
    """Return a lightweight fake ``utils.voice`` module.

    The service does ``from utils.voice import sanitize_text`` lazily inside
    ``_sanitize_or_fallback``. Because ``utils.voice`` imports ``cleantext``
    (not installed in the test environment) we inject a stub module into
    ``sys.modules`` so the lazy import resolves without touching the real file.
    The stub's ``sanitize_text`` is the identity function.
    """
    mod = types.ModuleType("utils.voice")
    mod.sanitize_text = lambda text: text  # identity — return input unchanged
    return mod


def _make_config(
    *,
    provider: str,
    failure_policy: str,
    cache_enabled: bool,
) -> TranslationConfig:
    """Build a TranslationConfig for the given test-matrix cell."""
    return TranslationConfig(
        provider=provider,
        effective_provider=provider,
        target_lang="es",  # non-empty so the anthropic path is entered
        failure_policy=failure_policy,
        cache_enabled=cache_enabled,
        force_translate=False,  # allow detection so we exercise the detect path
        model=DEFAULT_MODEL,
        max_output_tokens=DEFAULT_MAX_OUTPUT_TOKENS,
        api_key="test-key",
    )


# ---------------------------------------------------------------------------
# Assertion helper
# ---------------------------------------------------------------------------


def _assert_structural_fields_preserved(
    content: dict[str, Any],
    result: dict[str, Any],
    label: str,
) -> None:
    """Assert all structural fields are byte-for-byte identical in result."""
    # 1. Key set must be identical.
    assert result.keys() == content.keys(), (
        f"[{label}] Key mismatch. "
        f"Input keys: {set(content.keys())}, "
        f"Output keys: {set(result.keys())}"
    )

    # 2. Top-level structural fields must be byte-for-byte identical.
    for field in _TOP_LEVEL_STRUCTURAL_FIELDS:
        if field in content:
            assert result[field] == content[field], (
                f"[{label}] Top-level structural field '{field}' was modified. "
                f"Input: {content[field]!r}, Output: {result[field]!r}"
            )

    # 3. Per-comment structural fields must be byte-for-byte identical.
    input_comments = content.get("comments", [])
    output_comments = result.get("comments", [])

    assert len(output_comments) == len(input_comments), (
        f"[{label}] Comment list length changed. "
        f"Input: {len(input_comments)}, Output: {len(output_comments)}"
    )

    for i, (in_c, out_c) in enumerate(zip(input_comments, output_comments)):
        for field in _COMMENT_STRUCTURAL_FIELDS:
            if field in in_c:
                assert out_c[field] == in_c[field], (
                    f"[{label}] Comment structural field "
                    f"'comments[{i}].{field}' was modified. "
                    f"Input: {in_c[field]!r}, Output: {out_c[field]!r}"
                )


# ---------------------------------------------------------------------------
# Property 3 (full): structural fields preserved across all matrix cells
# ---------------------------------------------------------------------------


@given(
    content=_reddit_content_strategy,
    failure_policy=_failure_policy_strategy,
    cache_enabled=_cache_enabled_strategy,
    provider=_provider_strategy,
)
@settings(max_examples=200)
def test_structural_fields_preserved_full_matrix(
    content: dict[str, Any],
    failure_policy: str,
    cache_enabled: bool,
    provider: str,
) -> None:
    """**Property 3: Structural-Field byte-equality**
    **Validates: Requirements 1.2, 4.5, 6.4, 8.3, 15.5**

    Across all combinations of failure_policy, cache_enabled, and provider,
    the output dict must:
      1. Have exactly the same keys as the input.
      2. Preserve every top-level Structural_Field value byte-for-byte.
      3. Preserve every comment's comment_id and comment_url byte-for-byte.

    The mocked client returns "en" for detect and "translated: " + text for
    translate. sanitize_text is injected as the identity function.
    """
    label = (
        f"provider={provider!r} failure_policy={failure_policy!r} "
        f"cache_enabled={cache_enabled}"
    )

    config = _make_config(
        provider=provider,
        failure_policy=failure_policy,
        cache_enabled=cache_enabled,
    )

    fake_voice = _make_fake_voice_module()
    mock_client = _make_mock_client()

    with tempfile.TemporaryDirectory() as tmp_dir:
        cache = Translation_Cache(base_dir=tmp_dir)

        with patch.dict(sys.modules, {"utils.voice": fake_voice}), patch(
            "utils.translation.service.Translation_Service._build_client",
            return_value=mock_client,
        ):
            service = Translation_Service(config)
            # Inject the temp-dir-backed cache so cache I/O is isolated
            if cache_enabled:
                service._cache = cache

            result = service.translate(content)

    _assert_structural_fields_preserved(content, result, label)


# ---------------------------------------------------------------------------
# Property 3 (explicit per-provider): one test per provider for clear failures
# ---------------------------------------------------------------------------


@given(
    content=_reddit_content_strategy,
    failure_policy=_failure_policy_strategy,
    cache_enabled=_cache_enabled_strategy,
)
@settings(max_examples=200)
def test_structural_fields_preserved_provider_none(
    content: dict[str, Any],
    failure_policy: str,
    cache_enabled: bool,
) -> None:
    """**Property 3: Structural-Field byte-equality**
    **Validates: Requirements 1.2, 4.5, 6.4, 8.3, 15.5**

    With provider="none", the service returns the input unchanged (no-op).
    All structural fields must be preserved byte-for-byte.
    No mocking is needed since the no-op path never reaches the client or
    sanitizer.
    """
    label = (
        f"provider='none' failure_policy={failure_policy!r} "
        f"cache_enabled={cache_enabled}"
    )
    config = _make_config(
        provider="none",
        failure_policy=failure_policy,
        cache_enabled=cache_enabled,
    )
    service = Translation_Service(config)
    result = service.translate(content)
    _assert_structural_fields_preserved(content, result, label)


@given(
    content=_reddit_content_strategy,
    failure_policy=_failure_policy_strategy,
    cache_enabled=_cache_enabled_strategy,
)
@settings(max_examples=200)
def test_structural_fields_preserved_provider_anthropic(
    content: dict[str, Any],
    failure_policy: str,
    cache_enabled: bool,
) -> None:
    """**Property 3: Structural-Field byte-equality**
    **Validates: Requirements 1.2, 4.5, 6.4, 8.3, 15.5**

    With provider="anthropic" and a mocked client (detect returns "en",
    translate returns "translated: " + text), the service translates
    Translatable_Fields but must leave all Structural_Fields byte-for-byte
    identical across all failure_policy and cache_enabled combinations.
    """
    label = (
        f"provider='anthropic' failure_policy={failure_policy!r} "
        f"cache_enabled={cache_enabled}"
    )

    config = _make_config(
        provider="anthropic",
        failure_policy=failure_policy,
        cache_enabled=cache_enabled,
    )

    fake_voice = _make_fake_voice_module()
    mock_client = _make_mock_client()

    with tempfile.TemporaryDirectory() as tmp_dir:
        cache = Translation_Cache(base_dir=tmp_dir)

        with patch.dict(sys.modules, {"utils.voice": fake_voice}), patch(
            "utils.translation.service.Translation_Service._build_client",
            return_value=mock_client,
        ):
            service = Translation_Service(config)
            if cache_enabled:
                service._cache = cache

            result = service.translate(content)

    _assert_structural_fields_preserved(content, result, label)
