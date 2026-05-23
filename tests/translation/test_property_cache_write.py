"""Property-based test for cache write after successful Anthropic translation.

**Property 19: Cache write occurs after successful Anthropic translation**
**Validates: Requirements 7.4**

After ``translate(content)`` returns with ``cache_enabled=True`` and
``force_translate=True``, the cache file must exist on disk and contain at
least one entry (the translated ``thread_title``).

Strategy:
- Use a ``tempfile.TemporaryDirectory`` as the cache base directory so each
  test run starts with a clean, isolated cache.
- Mock ``_build_client`` to return a client where ``translate`` returns
  ``"TRANSLATED:" + text`` and ``detect_source_language`` returns ``"en"``.
- Inject a fake ``utils.voice`` module with identity ``sanitize_text``.
- Inject the temp dir by setting ``service._cache = Translation_Cache(base_dir=tmp_dir)``
  after construction.
- Call ``translate(content)`` with ``cache_enabled=True``, ``force_translate=True``,
  ``target_lang="es"``.
- Assert the cache file exists at ``{temp_dir}/{thread_id}/translation_cache.json``.
- Assert the cache file contains at least one entry (the translated thread_title).
"""
from __future__ import annotations

import json
import sys
import tempfile
import types
from pathlib import Path
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
# Strategies
# ---------------------------------------------------------------------------

_comment_strategy = st.fixed_dictionaries(
    {
        "comment_id": st.text(min_size=1, max_size=32),
        "comment_body": st.text(min_size=1, max_size=200),
        "comment_url": st.text(max_size=200),
        "author": st.text(max_size=64),
    }
)

_reddit_content_strategy = st.fixed_dictionaries(
    {
        # Translatable fields — must be non-empty strings so translation proceeds
        "thread_title": st.text(min_size=1, max_size=200),
        "thread_post": st.text(min_size=1, max_size=500),
        "comments": st.lists(_comment_strategy, min_size=0, max_size=3),
        # Structural fields
        "thread_id": st.text(
            alphabet=st.characters(
                whitelist_categories=("Lu", "Ll", "Nd"),
                whitelist_characters="-_",
            ),
            min_size=1,
            max_size=32,
        ),
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


def _make_config() -> TranslationConfig:
    """Build a TranslationConfig with cache_enabled=True, force_translate=True,
    provider='anthropic', and target_lang='es'."""
    return TranslationConfig(
        provider="anthropic",
        effective_provider="anthropic",
        target_lang="es",
        failure_policy="skip",
        cache_enabled=True,
        force_translate=True,  # skip detection so we always reach translation
        model=DEFAULT_MODEL,
        max_output_tokens=DEFAULT_MAX_OUTPUT_TOKENS,
        api_key="test-key",
    )


def _make_mock_client() -> MagicMock:
    """Return a mock Anthropic_Client that returns 'TRANSLATED:' + text."""
    mock_client = MagicMock()
    mock_client.detect_source_language.return_value = "en"
    mock_client.translate.side_effect = lambda text, target_lang: f"TRANSLATED:{text}"
    return mock_client


def _make_fake_voice_module() -> types.ModuleType:
    """Return a fake ``utils.voice`` module whose ``sanitize_text`` is the
    identity function. Injected into ``sys.modules`` so the lazy
    ``from utils.voice import sanitize_text`` inside
    ``Translation_Service._sanitize_or_fallback`` resolves without importing
    the real module (which requires ``cleantext``).
    """
    mod = types.ModuleType("utils.voice")
    mod.sanitize_text = lambda text: text  # type: ignore[attr-defined]
    return mod


# ---------------------------------------------------------------------------
# Property 19: Cache write occurs after successful Anthropic translation
# ---------------------------------------------------------------------------


@given(content=_reddit_content_strategy)
@settings(max_examples=50)
def test_cache_file_exists_after_translation(content: dict[str, Any]) -> None:
    """**Property 19: Cache write occurs after successful Anthropic translation**
    **Validates: Requirements 7.4**

    After a successful ``translate`` call with ``cache_enabled=True`` and
    ``force_translate=True``, the cache file must exist on disk at
    ``{temp_dir}/{thread_id}/translation_cache.json``.
    """
    config = _make_config()
    mock_client = _make_mock_client()
    fake_voice = _make_fake_voice_module()

    with tempfile.TemporaryDirectory() as tmp_dir:
        thread_id = content["thread_id"]
        expected_cache_path = Path(tmp_dir) / thread_id / "translation_cache.json"

        with patch.dict(sys.modules, {"utils.voice": fake_voice}), patch(
            "utils.translation.service.Translation_Service._build_client",
            return_value=mock_client,
        ):
            service = Translation_Service(config)
            # Inject the temp-dir-backed cache
            service._cache = Translation_Cache(base_dir=tmp_dir)

            service.translate(content)

        assert expected_cache_path.exists(), (
            f"Cache file was not created after successful translation.\n"
            f"Expected path: {expected_cache_path}\n"
            f"thread_id={thread_id!r}"
        )


@given(content=_reddit_content_strategy)
@settings(max_examples=50)
def test_cache_file_contains_at_least_one_entry(content: dict[str, Any]) -> None:
    """**Property 19: Cache write occurs after successful Anthropic translation**
    **Validates: Requirements 7.4**

    After a successful ``translate`` call with ``cache_enabled=True`` and
    ``force_translate=True``, the cache file must contain at least one entry
    (the translated ``thread_title`` is always written).
    """
    config = _make_config()
    mock_client = _make_mock_client()
    fake_voice = _make_fake_voice_module()

    with tempfile.TemporaryDirectory() as tmp_dir:
        thread_id = content["thread_id"]
        cache_path = Path(tmp_dir) / thread_id / "translation_cache.json"

        with patch.dict(sys.modules, {"utils.voice": fake_voice}), patch(
            "utils.translation.service.Translation_Service._build_client",
            return_value=mock_client,
        ):
            service = Translation_Service(config)
            # Inject the temp-dir-backed cache
            service._cache = Translation_Cache(base_dir=tmp_dir)

            service.translate(content)

        assert cache_path.exists(), (
            f"Cache file was not created after successful translation.\n"
            f"Expected path: {cache_path}\n"
            f"thread_id={thread_id!r}"
        )

        with cache_path.open("r", encoding="utf-8") as f:
            cache_data = json.load(f)

        assert len(cache_data) >= 1, (
            f"Cache file exists but contains no entries after translation.\n"
            f"cache_data={cache_data!r}\n"
            f"thread_id={thread_id!r}, thread_title={content['thread_title']!r}"
        )
