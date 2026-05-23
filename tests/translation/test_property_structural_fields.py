"""Property test: Structural-Field byte-equality through the no-op path.

**Property 3: Structural-Field byte-equality (no-op flavor)**
**Validates: Requirements 1.2, 4.5, 6.4, 8.3, 15.5**

Hypothesis-generate Reddit_Content dicts; with a no-op config, assert:
  1. output.keys() == input.keys()
  2. Every Structural_Field value is preserved byte-for-byte in the output
  3. For each comment, comment_id and comment_url are preserved byte-for-byte

Structural fields (never translated):
  thread_id, thread_url, permalink, author, avatar_url, is_nsfw, subreddit,
  comments[*].comment_id, comments[*].comment_url
"""
from __future__ import annotations

from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from utils.translation.config import (
    DEFAULT_MAX_OUTPUT_TOKENS,
    DEFAULT_MODEL,
    TranslationConfig,
)
from utils.translation.service import Translation_Service

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Strategy for a single comment dict including all structural and translatable fields.
comment_strategy = st.fixed_dictionaries(
    {
        "comment_id": st.text(min_size=1, max_size=32),
        "comment_url": st.text(max_size=200),
        "comment_body": st.text(max_size=500),
        "author": st.text(max_size=64),
    }
)

# Strategy for a full Reddit_Content dict with all structural fields present.
reddit_content_strategy = st.fixed_dictionaries(
    {
        # Translatable fields
        "thread_title": st.text(max_size=300),
        "thread_post": st.one_of(st.none(), st.text(max_size=2000)),
        "comments": st.lists(comment_strategy, max_size=10),
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

# No-op configs: either provider="none" or target_lang=""
_NOOP_CONFIGS = [
    TranslationConfig(
        provider="none",
        effective_provider="none",
        target_lang="es",
        failure_policy="skip",
        cache_enabled=False,
        force_translate=False,
        model=DEFAULT_MODEL,
        max_output_tokens=DEFAULT_MAX_OUTPUT_TOKENS,
        api_key="",
    ),
    TranslationConfig(
        provider="anthropic",
        effective_provider="anthropic",
        target_lang="",
        failure_policy="skip",
        cache_enabled=False,
        force_translate=False,
        model=DEFAULT_MODEL,
        max_output_tokens=DEFAULT_MAX_OUTPUT_TOKENS,
        api_key="",
    ),
]

# Structural field names at the top level of Reddit_Content.
_TOP_LEVEL_STRUCTURAL_FIELDS = (
    "thread_id",
    "thread_url",
    "permalink",
    "author",
    "avatar_url",
    "is_nsfw",
    "subreddit",
)

# Structural field names inside each comment dict.
_COMMENT_STRUCTURAL_FIELDS = (
    "comment_id",
    "comment_url",
)


# ---------------------------------------------------------------------------
# Property 3a: output.keys() == input.keys() (no-op path, provider="none")
# ---------------------------------------------------------------------------


@given(content=reddit_content_strategy)
@settings(max_examples=200)
def test_noop_provider_none_preserves_all_keys(content: dict[str, Any]) -> None:
    """**Property 3: Structural-Field byte-equality (no-op flavor)**
    **Validates: Requirements 1.2, 4.5, 6.4, 8.3, 15.5**

    When effective_provider == "none", the output dict must have exactly the
    same keys as the input dict — no keys added, removed, or renamed.
    """
    config = _NOOP_CONFIGS[0]  # provider="none"
    service = Translation_Service(config)
    result = service.translate(content)

    assert result.keys() == content.keys(), (
        f"Key mismatch with provider='none'. "
        f"Input keys: {set(content.keys())}, "
        f"Output keys: {set(result.keys())}"
    )


@given(content=reddit_content_strategy)
@settings(max_examples=200)
def test_noop_empty_target_lang_preserves_all_keys(content: dict[str, Any]) -> None:
    """**Property 3: Structural-Field byte-equality (no-op flavor)**
    **Validates: Requirements 1.2, 4.5, 6.4, 8.3, 15.5**

    When target_lang == "", the output dict must have exactly the same keys
    as the input dict.
    """
    config = _NOOP_CONFIGS[1]  # target_lang=""
    service = Translation_Service(config)
    result = service.translate(content)

    assert result.keys() == content.keys(), (
        f"Key mismatch with target_lang=''. "
        f"Input keys: {set(content.keys())}, "
        f"Output keys: {set(result.keys())}"
    )


# ---------------------------------------------------------------------------
# Property 3b: Top-level structural fields are byte-for-byte identical
# ---------------------------------------------------------------------------


@given(content=reddit_content_strategy)
@settings(max_examples=200)
def test_noop_provider_none_preserves_top_level_structural_fields(
    content: dict[str, Any],
) -> None:
    """**Property 3: Structural-Field byte-equality (no-op flavor)**
    **Validates: Requirements 1.2, 4.5, 6.4, 8.3, 15.5**

    When effective_provider == "none", every top-level Structural_Field value
    must be byte-for-byte identical in the output.
    """
    config = _NOOP_CONFIGS[0]  # provider="none"
    service = Translation_Service(config)
    result = service.translate(content)

    for field in _TOP_LEVEL_STRUCTURAL_FIELDS:
        if field in content:
            assert result[field] == content[field], (
                f"Structural field '{field}' was modified under provider='none'. "
                f"Input: {content[field]!r}, Output: {result[field]!r}"
            )
            # For string fields, also verify byte-level identity via is/==
            if isinstance(content[field], str):
                assert result[field] is content[field] or result[field] == content[field], (
                    f"String structural field '{field}' changed value under provider='none'."
                )


@given(content=reddit_content_strategy)
@settings(max_examples=200)
def test_noop_empty_target_lang_preserves_top_level_structural_fields(
    content: dict[str, Any],
) -> None:
    """**Property 3: Structural-Field byte-equality (no-op flavor)**
    **Validates: Requirements 1.2, 4.5, 6.4, 8.3, 15.5**

    When target_lang == "", every top-level Structural_Field value must be
    byte-for-byte identical in the output.
    """
    config = _NOOP_CONFIGS[1]  # target_lang=""
    service = Translation_Service(config)
    result = service.translate(content)

    for field in _TOP_LEVEL_STRUCTURAL_FIELDS:
        if field in content:
            assert result[field] == content[field], (
                f"Structural field '{field}' was modified under target_lang=''. "
                f"Input: {content[field]!r}, Output: {result[field]!r}"
            )


# ---------------------------------------------------------------------------
# Property 3c: Per-comment structural fields (comment_id, comment_url)
#              are byte-for-byte identical
# ---------------------------------------------------------------------------


@given(content=reddit_content_strategy)
@settings(max_examples=200)
def test_noop_provider_none_preserves_comment_structural_fields(
    content: dict[str, Any],
) -> None:
    """**Property 3: Structural-Field byte-equality (no-op flavor)**
    **Validates: Requirements 1.2, 4.5, 6.4, 8.3, 15.5**

    When effective_provider == "none", every comment's comment_id and
    comment_url must be byte-for-byte identical in the output.
    """
    config = _NOOP_CONFIGS[0]  # provider="none"
    service = Translation_Service(config)
    result = service.translate(content)

    input_comments = content.get("comments", [])
    output_comments = result.get("comments", [])

    assert len(output_comments) == len(input_comments), (
        f"Comment list length changed under provider='none'. "
        f"Input: {len(input_comments)}, Output: {len(output_comments)}"
    )

    for i, (in_comment, out_comment) in enumerate(
        zip(input_comments, output_comments)
    ):
        for field in _COMMENT_STRUCTURAL_FIELDS:
            if field in in_comment:
                assert out_comment[field] == in_comment[field], (
                    f"Comment structural field 'comments[{i}].{field}' was modified "
                    f"under provider='none'. "
                    f"Input: {in_comment[field]!r}, Output: {out_comment[field]!r}"
                )


@given(content=reddit_content_strategy)
@settings(max_examples=200)
def test_noop_empty_target_lang_preserves_comment_structural_fields(
    content: dict[str, Any],
) -> None:
    """**Property 3: Structural-Field byte-equality (no-op flavor)**
    **Validates: Requirements 1.2, 4.5, 6.4, 8.3, 15.5**

    When target_lang == "", every comment's comment_id and comment_url must
    be byte-for-byte identical in the output.
    """
    config = _NOOP_CONFIGS[1]  # target_lang=""
    service = Translation_Service(config)
    result = service.translate(content)

    input_comments = content.get("comments", [])
    output_comments = result.get("comments", [])

    assert len(output_comments) == len(input_comments), (
        f"Comment list length changed under target_lang=''. "
        f"Input: {len(input_comments)}, Output: {len(output_comments)}"
    )

    for i, (in_comment, out_comment) in enumerate(
        zip(input_comments, output_comments)
    ):
        for field in _COMMENT_STRUCTURAL_FIELDS:
            if field in in_comment:
                assert out_comment[field] == in_comment[field], (
                    f"Comment structural field 'comments[{i}].{field}' was modified "
                    f"under target_lang=''. "
                    f"Input: {in_comment[field]!r}, Output: {out_comment[field]!r}"
                )


# ---------------------------------------------------------------------------
# Property 3d: Combined — all structural fields across both no-op triggers
# ---------------------------------------------------------------------------


@given(
    content=reddit_content_strategy,
    use_provider_none=st.booleans(),
)
@settings(max_examples=300)
def test_all_structural_fields_preserved_across_noop_configs(
    content: dict[str, Any],
    use_provider_none: bool,
) -> None:
    """**Property 3: Structural-Field byte-equality (no-op flavor)**
    **Validates: Requirements 1.2, 4.5, 6.4, 8.3, 15.5**

    Comprehensive check: for both no-op triggers (provider="none" and
    target_lang=""), all top-level and per-comment structural fields must be
    preserved byte-for-byte, and output.keys() must equal input.keys().
    """
    config = _NOOP_CONFIGS[0] if use_provider_none else _NOOP_CONFIGS[1]
    service = Translation_Service(config)
    result = service.translate(content)

    # 1. Key set must be identical
    assert result.keys() == content.keys(), (
        f"Key mismatch. Config: {'provider=none' if use_provider_none else 'target_lang=empty'}. "
        f"Input keys: {set(content.keys())}, Output keys: {set(result.keys())}"
    )

    # 2. Top-level structural fields must be byte-for-byte identical
    for field in _TOP_LEVEL_STRUCTURAL_FIELDS:
        if field in content:
            assert result[field] == content[field], (
                f"Top-level structural field '{field}' was modified. "
                f"Config: {'provider=none' if use_provider_none else 'target_lang=empty'}. "
                f"Input: {content[field]!r}, Output: {result[field]!r}"
            )

    # 3. Per-comment structural fields must be byte-for-byte identical
    input_comments = content.get("comments", [])
    output_comments = result.get("comments", [])

    assert len(output_comments) == len(input_comments), (
        f"Comment list length changed. "
        f"Config: {'provider=none' if use_provider_none else 'target_lang=empty'}. "
        f"Input: {len(input_comments)}, Output: {len(output_comments)}"
    )

    for i, (in_comment, out_comment) in enumerate(
        zip(input_comments, output_comments)
    ):
        for field in _COMMENT_STRUCTURAL_FIELDS:
            if field in in_comment:
                assert out_comment[field] == in_comment[field], (
                    f"Comment structural field 'comments[{i}].{field}' was modified. "
                    f"Config: {'provider=none' if use_provider_none else 'target_lang=empty'}. "
                    f"Input: {in_comment[field]!r}, Output: {out_comment[field]!r}"
                )
