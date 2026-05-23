"""Property test for cache key derivation.

**Property 17: Cache key derivation is deterministic and tuple-sensitive**
**Validates: Requirements 7.1, 7.7**

Hypothesis-generate (thread_id, text, target_lang, model_id) tuples; assert
repeat calls produce the same key; assert any single-component change produces
a different key; assert the cache file path equals
Path("assets/temp") / thread_id / "translation_cache.json".
"""
from __future__ import annotations

from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from utils.translation.cache import Translation_Cache

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Non-empty printable text — covers ASCII, Unicode, and edge-case characters.
_text_str = st.text(min_size=1, max_size=200)

# Non-empty identifiers for thread_id, target_lang, model_id.
_id_str = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="-_"),
    min_size=1,
    max_size=64,
)


# ---------------------------------------------------------------------------
# Property 17a: Determinism — same inputs produce the same key
# ---------------------------------------------------------------------------


@given(
    thread_id=_id_str,
    text=_text_str,
    target_lang=_id_str,
    model_id=_id_str,
)
@settings(max_examples=200)
def test_cache_key_is_deterministic(
    thread_id: str, text: str, target_lang: str, model_id: str
) -> None:
    """Calling _cache_key twice with identical arguments returns the same hex
    digest (Req 7.1 — deterministic keying).
    """
    key1 = Translation_Cache._cache_key(thread_id, text, target_lang, model_id)
    key2 = Translation_Cache._cache_key(thread_id, text, target_lang, model_id)
    assert key1 == key2, (
        f"_cache_key is not deterministic for inputs "
        f"({thread_id!r}, {text!r}, {target_lang!r}, {model_id!r}): "
        f"got {key1!r} then {key2!r}"
    )
    # Keys must be non-empty hex strings (SHA-256 produces 64 hex chars)
    assert len(key1) == 64, f"Expected 64-char hex digest, got {len(key1)}: {key1!r}"
    assert all(c in "0123456789abcdef" for c in key1), (
        f"Key is not a lowercase hex string: {key1!r}"
    )


# ---------------------------------------------------------------------------
# Property 17b: Sensitivity — changing thread_id changes the key
# ---------------------------------------------------------------------------


@given(
    thread_id=_id_str,
    other_thread_id=_id_str,
    text=_text_str,
    target_lang=_id_str,
    model_id=_id_str,
)
@settings(max_examples=200)
def test_cache_key_sensitive_to_thread_id(
    thread_id: str,
    other_thread_id: str,
    text: str,
    target_lang: str,
    model_id: str,
) -> None:
    """When thread_id differs, the cache key must differ (Req 7.1 — tuple-sensitive)."""
    if thread_id == other_thread_id:
        return  # trivially equal inputs; skip

    key1 = Translation_Cache._cache_key(thread_id, text, target_lang, model_id)
    key2 = Translation_Cache._cache_key(other_thread_id, text, target_lang, model_id)
    assert key1 != key2, (
        f"Different thread_ids {thread_id!r} vs {other_thread_id!r} produced "
        f"the same cache key {key1!r}"
    )


# ---------------------------------------------------------------------------
# Property 17c: Sensitivity — changing text changes the key
# ---------------------------------------------------------------------------


@given(
    thread_id=_id_str,
    text=_text_str,
    other_text=_text_str,
    target_lang=_id_str,
    model_id=_id_str,
)
@settings(max_examples=200)
def test_cache_key_sensitive_to_text(
    thread_id: str,
    text: str,
    other_text: str,
    target_lang: str,
    model_id: str,
) -> None:
    """When text differs, the cache key must differ (Req 7.1 — tuple-sensitive)."""
    if text == other_text:
        return  # trivially equal inputs; skip

    key1 = Translation_Cache._cache_key(thread_id, text, target_lang, model_id)
    key2 = Translation_Cache._cache_key(thread_id, other_text, target_lang, model_id)
    assert key1 != key2, (
        f"Different texts produced the same cache key {key1!r} "
        f"(thread_id={thread_id!r}, target_lang={target_lang!r}, model_id={model_id!r})"
    )


# ---------------------------------------------------------------------------
# Property 17d: Sensitivity — changing target_lang changes the key
# ---------------------------------------------------------------------------


@given(
    thread_id=_id_str,
    text=_text_str,
    target_lang=_id_str,
    other_target_lang=_id_str,
    model_id=_id_str,
)
@settings(max_examples=200)
def test_cache_key_sensitive_to_target_lang(
    thread_id: str,
    text: str,
    target_lang: str,
    other_target_lang: str,
    model_id: str,
) -> None:
    """When target_lang differs, the cache key must differ (Req 7.1 — tuple-sensitive)."""
    if target_lang == other_target_lang:
        return  # trivially equal inputs; skip

    key1 = Translation_Cache._cache_key(thread_id, text, target_lang, model_id)
    key2 = Translation_Cache._cache_key(thread_id, text, other_target_lang, model_id)
    assert key1 != key2, (
        f"Different target_langs {target_lang!r} vs {other_target_lang!r} produced "
        f"the same cache key {key1!r}"
    )


# ---------------------------------------------------------------------------
# Property 17e: Sensitivity — changing model_id changes the key
# ---------------------------------------------------------------------------


@given(
    thread_id=_id_str,
    text=_text_str,
    target_lang=_id_str,
    model_id=_id_str,
    other_model_id=_id_str,
)
@settings(max_examples=200)
def test_cache_key_sensitive_to_model_id(
    thread_id: str,
    text: str,
    target_lang: str,
    model_id: str,
    other_model_id: str,
) -> None:
    """When model_id differs, the cache key must differ (Req 7.1 — tuple-sensitive)."""
    if model_id == other_model_id:
        return  # trivially equal inputs; skip

    key1 = Translation_Cache._cache_key(thread_id, text, target_lang, model_id)
    key2 = Translation_Cache._cache_key(thread_id, text, target_lang, other_model_id)
    assert key1 != key2, (
        f"Different model_ids {model_id!r} vs {other_model_id!r} produced "
        f"the same cache key {key1!r}"
    )


# ---------------------------------------------------------------------------
# Property 17f: Path — cache._path(thread_id) matches the documented location
# ---------------------------------------------------------------------------


@given(thread_id=_id_str)
@settings(max_examples=200)
def test_cache_path_matches_documented_location(thread_id: str) -> None:
    """The cache file path must equal Path("assets/temp") / thread_id /
    "translation_cache.json" (Req 7.7 — stored under assets/temp/{thread_id}/).
    """
    cache = Translation_Cache()  # default base_dir="assets/temp"
    expected = Path("assets/temp") / thread_id / "translation_cache.json"
    actual = cache._path(thread_id)
    assert actual == expected, (
        f"_path({thread_id!r}) returned {actual!r}, expected {expected!r}"
    )
