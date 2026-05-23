"""Property-based test for cache_enabled=False disabling all cache I/O.

**Property 20: cache_enabled=False disables all cache I/O**
**Validates: Requirements 7.6**

Pre-populate ``assets/temp/{thread_id}/translation_cache.json``; with
``cache_enabled = False``, monkey-patch ``Translation_Cache.get``/``put`` to
count invocations; assert both counts are zero and the on-disk file is
byte-unchanged.

When ``cache_enabled=False``, ``Translation_Service.__init__`` sets
``self._cache = None``, so ``Translation_Cache`` is never instantiated and
its ``get``/``put`` methods are never called.  The pre-populated cache file
must remain byte-identical after the run.
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

_target_lang_strategy = st.sampled_from(["es", "fr", "de", "ja", "pt-BR", "zh-CN"])

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_cache_disabled_config(target_lang: str) -> TranslationConfig:
    """Build a TranslationConfig with cache_enabled=False and provider='anthropic'."""
    return TranslationConfig(
        provider="anthropic",
        effective_provider="anthropic",
        target_lang=target_lang,
        failure_policy="skip",
        cache_enabled=False,
        force_translate=True,  # skip detection so we always reach translation
        model=DEFAULT_MODEL,
        max_output_tokens=DEFAULT_MAX_OUTPUT_TOKENS,
        api_key="test-key",
    )


def _make_mock_client() -> MagicMock:
    """Return a mock Anthropic_Client that returns non-empty translations."""
    mock_client = MagicMock()
    mock_client.detect_source_language.return_value = "en"
    mock_client.translate.side_effect = lambda text, target_lang: f"translated: {text}"
    return mock_client


def _pre_populate_cache(cache_dir: Path, thread_id: str) -> bytes:
    """Write a pre-populated cache file and return its raw bytes.

    The file contains a sentinel entry so we can verify it is unchanged
    after the run.
    """
    thread_dir = cache_dir / thread_id
    thread_dir.mkdir(parents=True, exist_ok=True)
    cache_path = thread_dir / "translation_cache.json"

    sentinel_data = {
        "pre_existing_key_aabbccdd": "pre-existing translation value",
        "another_sentinel_key_1234": "another pre-existing value",
    }
    raw = json.dumps(sentinel_data, ensure_ascii=False, indent=2).encode("utf-8")
    cache_path.write_bytes(raw)
    return raw


# ---------------------------------------------------------------------------
# Property 20: cache_enabled=False disables all cache I/O
# ---------------------------------------------------------------------------


@given(
    content=_reddit_content_strategy,
    target_lang=_target_lang_strategy,
)
@settings(max_examples=50)
def test_cache_disabled_no_get_calls(
    content: dict[str, Any],
    target_lang: str,
) -> None:
    """**Property 20: cache_enabled=False disables all cache I/O**
    **Validates: Requirements 7.6**

    With ``cache_enabled=False``, ``Translation_Cache.get`` must never be
    called, even when a cache file is pre-populated on disk.
    """
    get_call_count = 0
    put_call_count = 0

    original_get = Translation_Cache.get
    original_put = Translation_Cache.put

    def counting_get(self, **kwargs):
        nonlocal get_call_count
        get_call_count += 1
        return original_get(self, **kwargs)

    def counting_put(self, **kwargs):
        nonlocal put_call_count
        put_call_count += 1
        return original_put(self, **kwargs)

    config = _make_cache_disabled_config(target_lang)
    mock_client = _make_mock_client()

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        thread_id = content["thread_id"]
        _pre_populate_cache(tmp_path, thread_id)

        with (
            patch.object(Translation_Cache, "get", counting_get),
            patch.object(Translation_Cache, "put", counting_put),
            patch(
                "utils.translation.service.Translation_Service._build_client",
                return_value=mock_client,
            ),
            patch.dict(sys.modules, {"utils.voice": _make_fake_voice_module()}),
        ):
            service = Translation_Service(config)
            service.translate(content)

    assert get_call_count == 0, (
        f"Translation_Cache.get was called {get_call_count} time(s) with "
        f"cache_enabled=False. Expected 0 calls. "
        f"target_lang={target_lang!r}, thread_id={thread_id!r}"
    )


@given(
    content=_reddit_content_strategy,
    target_lang=_target_lang_strategy,
)
@settings(max_examples=50)
def test_cache_disabled_no_put_calls(
    content: dict[str, Any],
    target_lang: str,
) -> None:
    """**Property 20: cache_enabled=False disables all cache I/O**
    **Validates: Requirements 7.6**

    With ``cache_enabled=False``, ``Translation_Cache.put`` must never be
    called after a successful Anthropic translation.
    """
    get_call_count = 0
    put_call_count = 0

    original_get = Translation_Cache.get
    original_put = Translation_Cache.put

    def counting_get(self, **kwargs):
        nonlocal get_call_count
        get_call_count += 1
        return original_get(self, **kwargs)

    def counting_put(self, **kwargs):
        nonlocal put_call_count
        put_call_count += 1
        return original_put(self, **kwargs)

    config = _make_cache_disabled_config(target_lang)
    mock_client = _make_mock_client()

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        thread_id = content["thread_id"]
        _pre_populate_cache(tmp_path, thread_id)

        with (
            patch.object(Translation_Cache, "get", counting_get),
            patch.object(Translation_Cache, "put", counting_put),
            patch(
                "utils.translation.service.Translation_Service._build_client",
                return_value=mock_client,
            ),
            patch.dict(sys.modules, {"utils.voice": _make_fake_voice_module()}),
        ):
            service = Translation_Service(config)
            service.translate(content)

    assert put_call_count == 0, (
        f"Translation_Cache.put was called {put_call_count} time(s) with "
        f"cache_enabled=False. Expected 0 calls. "
        f"target_lang={target_lang!r}, thread_id={thread_id!r}"
    )


@given(
    content=_reddit_content_strategy,
    target_lang=_target_lang_strategy,
)
@settings(max_examples=50)
def test_cache_disabled_file_byte_unchanged(
    content: dict[str, Any],
    target_lang: str,
) -> None:
    """**Property 20: cache_enabled=False disables all cache I/O**
    **Validates: Requirements 7.6**

    With ``cache_enabled=False``, the pre-populated cache file on disk must
    be byte-identical after ``translate`` returns.  No write (atomic or
    otherwise) should touch the file.
    """
    config = _make_cache_disabled_config(target_lang)
    mock_client = _make_mock_client()

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        thread_id = content["thread_id"]
        original_bytes = _pre_populate_cache(tmp_path, thread_id)
        cache_file = tmp_path / thread_id / "translation_cache.json"

        # Patch Translation_Cache to use our temp dir as base
        with (
            patch(
                "utils.translation.service.Translation_Service._build_client",
                return_value=mock_client,
            ),
            patch.dict(sys.modules, {"utils.voice": _make_fake_voice_module()}),
        ):
            service = Translation_Service(config)
            service.translate(content)

        # The file must still exist and be byte-identical
        assert cache_file.exists(), (
            f"Pre-populated cache file was deleted by translate() with "
            f"cache_enabled=False. thread_id={thread_id!r}"
        )
        after_bytes = cache_file.read_bytes()
        assert after_bytes == original_bytes, (
            f"Cache file was modified by translate() with cache_enabled=False.\n"
            f"thread_id={thread_id!r}, target_lang={target_lang!r}\n"
            f"Before ({len(original_bytes)} bytes): {original_bytes[:200]!r}\n"
            f"After  ({len(after_bytes)} bytes):  {after_bytes[:200]!r}"
        )


@given(
    content=_reddit_content_strategy,
    target_lang=_target_lang_strategy,
)
@settings(max_examples=50)
def test_cache_disabled_combined_assertions(
    content: dict[str, Any],
    target_lang: str,
) -> None:
    """**Property 20: cache_enabled=False disables all cache I/O**
    **Validates: Requirements 7.6**

    Combined assertion: with ``cache_enabled=False``, both ``get`` and ``put``
    call counts are zero AND the pre-populated cache file is byte-unchanged.
    This is the canonical single-test form of Property 20.
    """
    get_call_count = 0
    put_call_count = 0

    original_get = Translation_Cache.get
    original_put = Translation_Cache.put

    def counting_get(self, **kwargs):
        nonlocal get_call_count
        get_call_count += 1
        return original_get(self, **kwargs)

    def counting_put(self, **kwargs):
        nonlocal put_call_count
        put_call_count += 1
        return original_put(self, **kwargs)

    config = _make_cache_disabled_config(target_lang)
    mock_client = _make_mock_client()

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        thread_id = content["thread_id"]
        original_bytes = _pre_populate_cache(tmp_path, thread_id)
        cache_file = tmp_path / thread_id / "translation_cache.json"

        with (
            patch.object(Translation_Cache, "get", counting_get),
            patch.object(Translation_Cache, "put", counting_put),
            patch(
                "utils.translation.service.Translation_Service._build_client",
                return_value=mock_client,
            ),
            patch.dict(sys.modules, {"utils.voice": _make_fake_voice_module()}),
        ):
            service = Translation_Service(config)
            service.translate(content)

        # Assert both counts are zero
        assert get_call_count == 0, (
            f"Translation_Cache.get was called {get_call_count} time(s) with "
            f"cache_enabled=False. Expected 0 calls. "
            f"target_lang={target_lang!r}, thread_id={thread_id!r}"
        )
        assert put_call_count == 0, (
            f"Translation_Cache.put was called {put_call_count} time(s) with "
            f"cache_enabled=False. Expected 0 calls. "
            f"target_lang={target_lang!r}, thread_id={thread_id!r}"
        )

        # Assert the on-disk file is byte-unchanged
        assert cache_file.exists(), (
            f"Pre-populated cache file was deleted by translate() with "
            f"cache_enabled=False. thread_id={thread_id!r}"
        )
        after_bytes = cache_file.read_bytes()
        assert after_bytes == original_bytes, (
            f"Cache file was modified by translate() with cache_enabled=False.\n"
            f"thread_id={thread_id!r}, target_lang={target_lang!r}\n"
            f"Before ({len(original_bytes)} bytes): {original_bytes[:200]!r}\n"
            f"After  ({len(after_bytes)} bytes):  {after_bytes[:200]!r}"
        )
