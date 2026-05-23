"""Property test for fake-timing synthesizer math.

# Feature: card-rendering-refactor, Property 16

Validates: Requirements 10.4

For any list of words and any wps > 0:
- synth_word_timestamps returns exactly len(words) entries
- each end - start == 1.0 / wps
- timestamps are contiguous (entry[i].end == entry[i+1].start)
- total span == len(words) / wps
"""

from __future__ import annotations

import math

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from video_creation.render.preview.fake_timings import synth_word_timestamps


@given(
    words=st.lists(st.text(min_size=1, max_size=10), min_size=0, max_size=30),
    wps=st.floats(min_value=0.1, max_value=20.0, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=200)
def test_synth_word_timestamps_math(words, wps):
    """Property: synth_word_timestamps produces contiguous, correctly-spaced timestamps."""
    result = synth_word_timestamps(words, wps=wps)

    # Correct count
    assert len(result) == len(words)

    if not words:
        return

    slot = 1.0 / wps

    for i, ts in enumerate(result):
        # Each slot has the right duration
        assert math.isclose(ts.end - ts.start, slot, rel_tol=1e-9), (
            f"Entry {i}: end-start={ts.end - ts.start}, expected {slot}"
        )
        # start == i * slot
        assert math.isclose(ts.start, i * slot, rel_tol=1e-9), (
            f"Entry {i}: start={ts.start}, expected {i * slot}"
        )

    # Contiguous: each end == next start
    for i in range(len(result) - 1):
        assert math.isclose(result[i].end, result[i + 1].start, rel_tol=1e-9)

    # Total span
    expected_span = len(words) / wps
    actual_span = result[-1].end - result[0].start
    assert math.isclose(actual_span, expected_span, rel_tol=1e-9)


def test_synth_word_timestamps_empty():
    assert synth_word_timestamps([], wps=3.0) == ()


def test_synth_word_timestamps_invalid_wps():
    with pytest.raises(ValueError):
        synth_word_timestamps(["hello"], wps=0)
    with pytest.raises(ValueError):
        synth_word_timestamps(["hello"], wps=-1.0)
