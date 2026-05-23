"""Property test for karaoke chunking math.

# Feature: card-rendering-refactor, Property 9

Property 9: Karaoke chunking splits lines by chunk_size
Validates: Requirements 7.4

For any line definition with n words and any chunk_size = k > 0,
TimingEngine.compute emits exactly ceil(n / k) LineTiming entries for that
line, the entries' text.split() lengths sum to n, and the first floor(n / k)
entries each have exactly k words.
"""

from __future__ import annotations

import math

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from video_creation.render.timing.engine import TimingEngine
from video_creation.render.timing.models import LineDefinition, WordTimestamp


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# A single non-empty word (no whitespace so split() is predictable)
_word = st.text(
    alphabet=st.characters(
        whitelist_categories=("Lu", "Ll", "Nd"),
        whitelist_characters="-'",
    ),
    min_size=1,
    max_size=12,
)


@st.composite
def word_list_and_timestamps(draw):
    """Draw a list of words and matching WordTimestamp objects with
    non-decreasing, non-overlapping times."""
    words = draw(st.lists(_word, min_size=1, max_size=30))
    n = len(words)

    # Build monotonically non-decreasing timestamps.
    # Each word occupies a 0.1-second slot; gaps between words are 0–0.05 s.
    timestamps = []
    t = 0.0
    for w in words:
        start = t
        end = start + 0.1
        timestamps.append(WordTimestamp(word=w, start=start, end=end))
        t = end + draw(st.floats(min_value=0.0, max_value=0.05))

    return words, timestamps


# ---------------------------------------------------------------------------
# Property 9
# ---------------------------------------------------------------------------

@given(
    wl_ts=word_list_and_timestamps(),
    chunk_size=st.integers(min_value=1, max_value=10),
)
@settings(max_examples=200)
def test_karaoke_chunking_math(wl_ts, chunk_size):
    """Property 9: Karaoke chunking splits lines by chunk_size.

    Validates: Requirements 7.4
    """
    words, timestamps = wl_ts
    n = len(words)
    k = chunk_size

    # Build a single LineDefinition whose text matches the word list.
    line_text = " ".join(words)
    line_def = LineDefinition(
        text=line_text,
        word_count=n,
        y_top=0,
        y_bottom=100,
        page_index=0,
    )

    result = TimingEngine().compute(
        words=tuple(timestamps),
        line_definitions=(line_def,),
        chunk_size=k,
        audio_speed=1.0,
        title_duration=0.0,
    )

    # All entries should be for line_index=0 (the only line).
    line_entries = [e for e in result.entries if e.line_index == 0]

    # 1. Exactly ceil(n / k) entries for this line.
    expected_chunks = math.ceil(n / k)
    assert len(line_entries) == expected_chunks, (
        f"Expected {expected_chunks} chunks for n={n}, k={k}, "
        f"got {len(line_entries)}"
    )

    # 2. The entries' text.split() lengths sum to n.
    total_words_in_entries = sum(len(e.text.split()) for e in line_entries)
    assert total_words_in_entries == n, (
        f"Word count across chunks ({total_words_in_entries}) != n ({n})"
    )

    # 3. The first floor(n / k) entries each have exactly k words.
    full_chunks = math.floor(n / k)
    for i in range(full_chunks):
        chunk_word_count = len(line_entries[i].text.split())
        assert chunk_word_count == k, (
            f"Chunk {i} has {chunk_word_count} words, expected {k} "
            f"(n={n}, k={k})"
        )
