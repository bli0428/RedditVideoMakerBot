"""Shared Hypothesis strategies for the story-multi-part-splitting spec.

These strategies are imported by property-test modules throughout the
``tests/`` tree.  They are intentionally kept free of any import from the
production modules so that they can be loaded without side-effects.

Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.8, 9.9, 9.10
"""
from __future__ import annotations

from typing import Any, Dict, List

from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Known template placeholder names (Requirement 6.5)
# ---------------------------------------------------------------------------
_KNOWN_PLACEHOLDERS: List[str] = [
    "title",
    "part_number",
    "total_parts",
    "next_part_number",
    "prev_part_number",
]

# Unknown placeholder names that should be left literal (Requirement 6.7)
_UNKNOWN_PLACEHOLDERS: List[str] = [
    "partname",
    "author",
    "subreddit",
    "date",
    "url",
    "foo",
    "bar",
    "baz",
]


# ---------------------------------------------------------------------------
# multi_paragraph_text
# ---------------------------------------------------------------------------

@st.composite
def multi_paragraph_text(draw, min_size: int = 50, max_size: int = 6000) -> str:
    """Generate realistic multi-paragraph text mixing paragraph breaks,
    sentence terminators, line breaks, and plain words.

    The generated text contains a mix of:
    - ``\\n\\n`` paragraph separators
    - Sentence terminators: ``. ``, ``! ``, ``? ``
    - Single ``\\n`` line breaks
    - Plain word sequences

    The result has at least ``min_size`` and at most ``max_size`` characters.

    Requirements: 9.1, 9.2, 9.8
    """
    # Build a pool of "atoms" — small text fragments — then join them until
    # we reach the desired length range.
    word = st.text(
        alphabet=st.characters(
            whitelist_categories=("Ll", "Lu", "Nd"),
            whitelist_characters="-'",
        ),
        min_size=1,
        max_size=15,
    )

    sentence_terminator = st.sampled_from([". ", "! ", "? "])
    separator = st.sampled_from([" ", "\n", "\n\n"])

    # A "chunk" is a word optionally followed by a separator or terminator.
    @st.composite
    def chunk(draw_inner) -> str:
        w = draw_inner(word)
        suffix = draw_inner(
            st.one_of(
                st.just(" "),
                sentence_terminator,
                separator,
            )
        )
        return w + suffix

    # Draw chunks until we have enough characters.
    parts: List[str] = []
    total = 0
    # We need at least min_size chars; draw up to a generous upper bound.
    max_chunks = max(max_size // 3, 10)
    chunks = draw(st.lists(chunk(), min_size=1, max_size=max_chunks))
    for c in chunks:
        parts.append(c)
        total += len(c)
        if total >= max_size:
            break

    text = "".join(parts)

    # Trim to max_size
    if len(text) > max_size:
        text = text[:max_size]

    # Pad to min_size with simple word content if too short
    while len(text) < min_size:
        extra = draw(word)
        text = text + " " + extra

    return text


# ---------------------------------------------------------------------------
# pathological_text
# ---------------------------------------------------------------------------

@st.composite
def pathological_text(draw, length: int = 500) -> str:
    """Generate a string of exactly ``length`` non-whitespace characters with
    no punctuation.

    This is the worst-case input for the boundary search: no paragraph breaks,
    no sentence terminators, no line breaks, and no whitespace at all.  The
    splitter must either find a whitespace fallback (impossible here) or raise
    ``StorySplitError(reason="no_valid_boundary")``.

    Requirements: 9.8
    """
    # Use only lowercase ASCII letters and digits — no whitespace, no punctuation.
    alphabet = st.characters(
        whitelist_categories=("Ll", "Lu", "Nd"),
    )
    text = draw(
        st.text(alphabet=alphabet, min_size=length, max_size=length)
    )
    return text


# ---------------------------------------------------------------------------
# splitting_config  /  degenerate_config
# ---------------------------------------------------------------------------

@st.composite
def splitting_config(draw) -> Dict[str, Any]:
    """Generate a valid ``SplittingConfig``-compatible settings dict.

    Covers the valid parameter ranges:
    - ``soft_max_length`` in ``[100, 5000]``
    - ``single_part_tolerance`` in ``[1.0, 3.0]``
    - ``min_part_length`` in ``[1, soft_max_length // 2]``
    - ``max_parts`` in ``[1, 10]``

    Returns a ``settings.config``-shaped dict (i.e., the dict that would be
    passed to ``SplittingConfig.from_settings``).

    Requirements: 9.3, 9.4, 9.5, 9.9
    """
    soft_max_length = draw(st.integers(min_value=100, max_value=5000))
    single_part_tolerance = draw(
        st.floats(min_value=1.0, max_value=3.0, allow_nan=False, allow_infinity=False)
    )
    # min_part_length must be at least 1 and at most soft_max_length // 2
    max_min_part = max(1, soft_max_length // 2)
    min_part_length = draw(st.integers(min_value=1, max_value=max_min_part))
    max_parts = draw(st.integers(min_value=1, max_value=10))
    mode = draw(st.sampled_from(["cutoff", "split"]))

    return {
        "splitting": {
            "default_mode": mode,
            "soft_max_length": soft_max_length,
            "single_part_tolerance": single_part_tolerance,
            "min_part_length": min_part_length,
            "max_parts": max_parts,
        }
    }


@st.composite
def degenerate_config(draw) -> Dict[str, Any]:
    """Generate a ``settings.config``-shaped dict that exercises the clamping
    and fallback paths in ``SplittingConfig.from_settings``.

    Covers:
    - ``single_part_tolerance < 1.0`` → clamped to ``1.0``
    - ``soft_max_length < 1`` → falls back to ``1000``
    - ``min_part_length < 1`` → clamped to ``1``
    - ``max_parts < 1`` → clamped to ``1``
    - ``default_mode`` set to an invalid value → falls back to ``"cutoff"``

    Requirements: 9.3, 9.4
    """
    # Each field independently may be degenerate or valid.
    soft_max_length = draw(
        st.one_of(
            st.integers(min_value=-100, max_value=0),   # degenerate: < 1
            st.integers(min_value=1, max_value=5000),   # valid
        )
    )
    single_part_tolerance = draw(
        st.one_of(
            st.floats(
                min_value=-2.0, max_value=0.9999,
                allow_nan=False, allow_infinity=False,
            ),  # degenerate: < 1.0
            st.floats(
                min_value=1.0, max_value=3.0,
                allow_nan=False, allow_infinity=False,
            ),  # valid
        )
    )
    min_part_length = draw(
        st.one_of(
            st.integers(min_value=-10, max_value=0),  # degenerate: < 1
            st.integers(min_value=1, max_value=500),  # valid
        )
    )
    max_parts = draw(
        st.one_of(
            st.integers(min_value=-5, max_value=0),  # degenerate: < 1
            st.integers(min_value=1, max_value=10),  # valid
        )
    )
    mode = draw(
        st.one_of(
            st.sampled_from(["cutoff", "split"]),          # valid
            st.text(min_size=1, max_size=20).filter(       # invalid
                lambda s: s not in ("cutoff", "split")
            ),
        )
    )

    return {
        "splitting": {
            "default_mode": mode,
            "soft_max_length": soft_max_length,
            "single_part_tolerance": single_part_tolerance,
            "min_part_length": min_part_length,
            "max_parts": max_parts,
        }
    }


# ---------------------------------------------------------------------------
# template_string
# ---------------------------------------------------------------------------

@st.composite
def template_string(draw) -> str:
    """Generate a template string mixing known and unknown placeholder names.

    The result is a string that may contain:
    - Known placeholders: ``{title}``, ``{part_number}``, ``{total_parts}``,
      ``{next_part_number}``, ``{prev_part_number}``
    - Unknown placeholders: ``{partname}``, ``{author}``, etc.
    - Plain text (no placeholders)

    Requirements: 9.10
    """
    # Build a list of fragments: plain text and/or placeholder references.
    plain_text = st.text(
        alphabet=st.characters(
            blacklist_characters="{}",
            blacklist_categories=("Cs",),
        ),
        min_size=0,
        max_size=30,
    )

    known_placeholder = st.sampled_from(
        ["{" + p + "}" for p in _KNOWN_PLACEHOLDERS]
    )
    unknown_placeholder = st.sampled_from(
        ["{" + p + "}" for p in _UNKNOWN_PLACEHOLDERS]
    )

    fragment = st.one_of(plain_text, known_placeholder, unknown_placeholder)
    fragments = draw(st.lists(fragment, min_size=1, max_size=8))
    return "".join(fragments)


# ---------------------------------------------------------------------------
# reddit_content
# ---------------------------------------------------------------------------

@st.composite
def reddit_content(draw, thread_post: st.SearchStrategy[str] | None = None) -> Dict[str, Any]:
    """Generate a ``Reddit_Content``-shaped dict suitable for passing to
    ``Story_Splitter.split``.

    Fields produced:
    - ``thread_id``       — alphanumeric string, 4–12 chars
    - ``thread_title``    — short text, 5–80 chars
    - ``thread_post``     — drawn from ``thread_post`` strategy if provided,
                            else from ``multi_paragraph_text()``
    - ``comments``        — list of 0–5 comment dicts (each with ``comment_body``)
    - ``is_nsfw``         — bool
    - ``author``          — alphanumeric string, 3–20 chars
    - ``subreddit_name``  — lowercase alphanumeric, 3–21 chars

    Requirements: 9.1, 9.2, 9.5
    """
    thread_id = draw(
        st.text(
            alphabet="abcdefghijklmnopqrstuvwxyz0123456789",
            min_size=4,
            max_size=12,
        )
    )
    thread_title = draw(
        st.text(
            alphabet=st.characters(
                blacklist_categories=("Cs",),
                blacklist_characters="\x00",
            ),
            min_size=5,
            max_size=80,
        )
    )

    if thread_post is None:
        post_text = draw(multi_paragraph_text(min_size=50, max_size=6000))
    else:
        post_text = draw(thread_post)

    # Generate 0–5 comment dicts
    comment_body_strategy = st.text(
        alphabet=st.characters(blacklist_categories=("Cs",)),
        min_size=1,
        max_size=200,
    )
    comments = draw(
        st.lists(
            st.fixed_dictionaries({"comment_body": comment_body_strategy}),
            min_size=0,
            max_size=5,
        )
    )

    is_nsfw = draw(st.booleans())

    author = draw(
        st.text(
            alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-",
            min_size=3,
            max_size=20,
        )
    )

    subreddit_name = draw(
        st.text(
            alphabet="abcdefghijklmnopqrstuvwxyz0123456789_",
            min_size=3,
            max_size=21,
        )
    )

    return {
        "thread_id": thread_id,
        "thread_title": thread_title,
        "thread_post": post_text,
        "comments": comments,
        "is_nsfw": is_nsfw,
        "author": author,
        "subreddit_name": subreddit_name,
    }
