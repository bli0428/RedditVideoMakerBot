"""Property test for TimingEngine well-formedness and determinism.

# Feature: card-rendering-refactor, Property 8

**Validates: Requirements 6.1**

Property 8: TimingEngine output is well-formed and deterministic.

For any sequence of word timestamps (monotonically non-decreasing starts,
start <= end per word) and any sequence of line definitions whose total
word_count equals len(words), TimingEngine.compute(...) SHALL return a
TimingResult such that:
  - entries are ordered by start (each entry's start <= next entry's start),
  - each entry's start <= end,
  - the multiset of words consumed across all entries equals the input words,
  - calling compute twice with the same inputs returns equal TimingResults.
"""

from __future__ import annotations

from collections import Counter

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from video_creation.render.timing.engine import TimingEngine
from video_creation.render.timing.models import LineDefinition, WordTimestamp


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------


def word_timestamps_strategy(words: list[str]):
    """Given a list of words, generate a monotonically non-decreasing
    sequence of WordTimestamp objects with start <= end per word.
    """

    @st.composite
    def _build(draw, words=words):
        n = len(words)
        if n == 0:
            return ()

        # Generate n non-negative gaps between consecutive starts (deltas).
        # Each delta >= 0 ensures monotonically non-decreasing starts.
        deltas = draw(
            st.lists(
                st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
                min_size=n,
                max_size=n,
            )
        )
        # Each word has a duration >= 0 (end - start).
        durations = draw(
            st.lists(
                st.floats(min_value=0.0, max_value=0.5, allow_nan=False, allow_infinity=False),
                min_size=n,
                max_size=n,
            )
        )

        timestamps = []
        current_start = 0.0
        for i, word in enumerate(words):
            start = current_start
            end = start + durations[i]
            timestamps.append(WordTimestamp(word=word, start=start, end=end))
            current_start = start + deltas[i]

        return tuple(timestamps)

    return _build()


@st.composite
def words_and_line_definitions(draw):
    """Generate a consistent (words, line_definitions) pair where the sum of
    word_counts in line_definitions equals len(words).
    """
    # Generate a flat list of word strings.
    words_list = draw(
        st.lists(
            st.text(
                alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd")),
                min_size=1,
                max_size=10,
            ),
            min_size=0,
            max_size=20,
        )
    )

    n = len(words_list)

    # Generate word counts per line that sum to n.
    if n == 0:
        line_word_counts = [0]  # one zero-word line
    else:
        # Build a partition of n into chunks of 1..5 words each.
        counts = []
        remaining = n
        while remaining > 0:
            chunk = draw(st.integers(min_value=1, max_value=min(5, remaining)))
            counts.append(chunk)
            remaining -= chunk
        line_word_counts = counts

    # Build LineDefinition objects.
    word_cursor = 0
    line_defs = []
    for i, wc in enumerate(line_word_counts):
        line_text = " ".join(words_list[word_cursor : word_cursor + wc])
        line_defs.append(
            LineDefinition(
                text=line_text,
                word_count=wc,
                y_top=i * 30,
                y_bottom=i * 30 + 28,
                page_index=i // 5,
            )
        )
        word_cursor += wc

    # Build WordTimestamp objects from the flat word list.
    word_timestamps = draw(word_timestamps_strategy(words_list))

    return tuple(word_timestamps), tuple(line_defs)


# ---------------------------------------------------------------------------
# Property test
# ---------------------------------------------------------------------------


@given(inputs=words_and_line_definitions())
@settings(max_examples=100)
def test_timing_engine_well_formed_and_deterministic(inputs):
    """Property 8: TimingEngine output is well-formed and deterministic.

    **Validates: Requirements 6.1**
    """
    words, line_definitions = inputs

    engine = TimingEngine()

    result = engine.compute(
        words=words,
        line_definitions=line_definitions,
        chunk_size=0,  # no chunking — one LineTiming per LineDefinition
        audio_speed=1.0,
        title_duration=0.0,
    )

    entries = result.entries

    # 1. Entries are ordered by start (non-decreasing).
    for i in range(len(entries) - 1):
        assert entries[i].start <= entries[i + 1].start, (
            f"Entry {i} start={entries[i].start} > entry {i+1} start={entries[i+1].start}"
        )

    # 2. Each entry's start <= end.
    for i, entry in enumerate(entries):
        assert entry.start <= entry.end, (
            f"Entry {i} has start={entry.start} > end={entry.end}"
        )

    # 3. The multiset of words consumed across all entries equals the input words.
    #    Each entry's text is the full line text; split to recover individual words.
    consumed_words = []
    for entry in entries:
        consumed_words.extend(entry.text.split())

    input_words = [w.word for w in words]
    assert Counter(consumed_words) == Counter(input_words), (
        f"Consumed words {Counter(consumed_words)} != input words {Counter(input_words)}"
    )

    # 4. Two compute calls with the same inputs return equal TimingResults.
    result2 = engine.compute(
        words=words,
        line_definitions=line_definitions,
        chunk_size=0,
        audio_speed=1.0,
        title_duration=0.0,
    )
    assert result == result2, "TimingEngine.compute is not deterministic"
