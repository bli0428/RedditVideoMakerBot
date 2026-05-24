"""
Concrete example-based unit tests for boundary search helpers.

Tests cover:
- Each boundary type independently (_find_paragraph_break, _find_sentence_terminator,
  _find_line_break, _find_whitespace)
- Priority ordering: paragraph > sentence > line > whitespace
- "Closest from below" preference (largest offset <= target wins)
- Fallback to above-target when nothing fits below
- Empty-window case (min_part_length > hard_max_length)
- _advance_past_whitespace on each boundary type

Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6
"""
from __future__ import annotations

import pytest

from utils.story_splitter.boundaries import (
    _advance_past_whitespace,
    _find_boundary,
    _find_line_break,
    _find_paragraph_break,
    _find_sentence_terminator,
    _find_whitespace,
)


# ---------------------------------------------------------------------------
# _find_paragraph_break
# ---------------------------------------------------------------------------


class TestFindParagraphBreak:
    """Tests for _find_paragraph_break — Requirement 4.1"""

    def test_unix_double_newline_basic(self) -> None:
        """Boundary at first \\n of \\n\\n sequence."""
        text = "Hello world\n\nNext paragraph"
        # \n\n starts at index 11; boundary = 11 (first \n)
        result = _find_paragraph_break(text, start=0, stop=len(text), target=15)
        assert result == 11

    def test_crlf_double_newline(self) -> None:
        """Boundary at first \\n of \\r\\n\\r\\n sequence."""
        text = "Hello world\r\n\r\nNext paragraph"
        # \r\n\r\n starts at index 11; first \n is at index 12
        result = _find_paragraph_break(text, start=0, stop=len(text), target=15)
        assert result == 12

    def test_closest_from_below_preferred(self) -> None:
        """When multiple paragraph breaks exist, the one closest to target from below wins."""
        # "Hello\n\nWorld\n\nFoo bar baz"
        # First \n\n: first \n at index 5
        # Second \n\n: first \n at index 12
        text = "Hello\n\nWorld\n\nFoo bar baz"
        # target=14 → breaks at 5 and 12 are both below; 12 is closer to 14
        result = _find_paragraph_break(text, start=0, stop=len(text), target=14)
        assert result == 12

    def test_fallback_to_above_target(self) -> None:
        """When no break is at or below target, return the lowest one above target."""
        text = "Hello world\n\nNext paragraph"
        # break at index 11; target=5 (below the break)
        result = _find_paragraph_break(text, start=0, stop=len(text), target=5)
        assert result == 11

    def test_no_paragraph_break_returns_none(self) -> None:
        """Returns None when no paragraph break exists in the window."""
        text = "Hello world. No paragraph breaks here."
        result = _find_paragraph_break(text, start=0, stop=len(text), target=10)
        assert result is None

    def test_break_outside_window_returns_none(self) -> None:
        """Returns None when the paragraph break is outside [start, stop)."""
        text = "Hello\n\nWorld"
        # break at index 5; window is [7, 12) — break is outside
        result = _find_paragraph_break(text, start=7, stop=12, target=9)
        assert result is None

    def test_break_at_start_of_window(self) -> None:
        """Break exactly at start of window is included."""
        text = "Hello\n\nWorld"
        # break at index 5; window starts at 5
        result = _find_paragraph_break(text, start=5, stop=12, target=6)
        assert result == 5

    def test_break_at_stop_minus_one(self) -> None:
        """Break at stop-1 is included (window is half-open [start, stop))."""
        text = "Hello world\n\nX"
        # break at index 11; stop=12 → index 11 is in [0, 12)
        result = _find_paragraph_break(text, start=0, stop=12, target=5)
        assert result == 11

    def test_multiple_breaks_below_target_picks_largest(self) -> None:
        """Among breaks at or below target, the largest (closest) is returned."""
        text = "A\n\nB\n\nC\n\nD"
        # breaks at 1, 4, 7; target=6 → candidates below: 1, 4; largest = 4
        result = _find_paragraph_break(text, start=0, stop=len(text), target=6)
        assert result == 4


# ---------------------------------------------------------------------------
# _find_sentence_terminator
# ---------------------------------------------------------------------------


class TestFindSentenceTerminator:
    """Tests for _find_sentence_terminator — Requirement 4.2"""

    def test_period_followed_by_space(self) -> None:
        """Boundary immediately after period when followed by space."""
        text = "Hello world. Next sentence."
        # period at index 11; boundary = 12 (after the period)
        result = _find_sentence_terminator(text, start=0, stop=len(text), target=15)
        assert result == 12

    def test_exclamation_followed_by_space(self) -> None:
        """Boundary immediately after exclamation mark."""
        text = "Hello world! Next sentence."
        result = _find_sentence_terminator(text, start=0, stop=len(text), target=15)
        assert result == 12

    def test_question_mark_followed_by_space(self) -> None:
        """Boundary immediately after question mark."""
        text = "Hello world? Next sentence."
        result = _find_sentence_terminator(text, start=0, stop=len(text), target=15)
        assert result == 12

    def test_period_at_end_of_string(self) -> None:
        """Boundary after period at end of string (followed by end-of-string)."""
        text = "Hello world."
        # period at index 11; boundary = 12 (= len(text))
        result = _find_sentence_terminator(text, start=0, stop=len(text) + 1, target=10)
        assert result == 12

    def test_period_not_followed_by_whitespace_ignored(self) -> None:
        """Period not followed by whitespace or end-of-string is not a boundary."""
        text = "Hello 3.14 world. End."
        # "3.14" — the period at index 7 is not followed by whitespace
        # "world." at index 16 is followed by space → boundary at 17
        # "End." at index 21 is at end → boundary at 22
        result = _find_sentence_terminator(text, start=0, stop=len(text) + 1, target=10)
        assert result == 17

    def test_closest_from_below_preferred(self) -> None:
        """Among terminators at or below target, the largest is returned."""
        text = "First. Second. Third."
        # boundaries at 6, 14, 21; target=13 → candidates below: 6; largest = 6
        result = _find_sentence_terminator(text, start=0, stop=len(text) + 1, target=13)
        assert result == 6

    def test_fallback_to_above_target(self) -> None:
        """When no terminator is at or below target, return the lowest one above."""
        text = "Hello world. Next."
        # boundary at 12; target=5 → no candidates below; fallback = 12
        result = _find_sentence_terminator(text, start=0, stop=len(text) + 1, target=5)
        assert result == 12

    def test_no_sentence_terminator_returns_none(self) -> None:
        """Returns None when no sentence terminator exists in the window."""
        text = "Hello world no punctuation here"
        result = _find_sentence_terminator(text, start=0, stop=len(text), target=10)
        assert result is None

    def test_terminator_outside_window_returns_none(self) -> None:
        """Returns None when the terminator is outside [start, stop)."""
        text = "Hello world. Next."
        # boundary at 12; window is [0, 10) — boundary is outside
        result = _find_sentence_terminator(text, start=0, stop=10, target=5)
        assert result is None


# ---------------------------------------------------------------------------
# _find_line_break
# ---------------------------------------------------------------------------


class TestFindLineBreak:
    """Tests for _find_line_break — Requirement 4.3"""

    def test_single_newline_basic(self) -> None:
        """Boundary at single \\n not part of a paragraph break."""
        text = "Hello world\nNext line"
        # single \n at index 11
        result = _find_line_break(text, start=0, stop=len(text), target=15)
        assert result == 11

    def test_double_newline_not_a_line_break(self) -> None:
        """\\n\\n is a paragraph break, not a line break."""
        text = "Hello world\n\nNext paragraph"
        # \n\n at index 11 — neither \n should be a line break
        result = _find_line_break(text, start=0, stop=len(text), target=15)
        assert result is None

    def test_single_newline_among_paragraph_break(self) -> None:
        """Only the single \\n (not part of \\n\\n) is returned."""
        text = "Hello\nWorld\n\nParagraph"
        # single \n at index 5; \n\n at index 11 (not a line break)
        result = _find_line_break(text, start=0, stop=len(text), target=10)
        assert result == 5

    def test_closest_from_below_preferred(self) -> None:
        """Among line breaks at or below target, the largest is returned."""
        text = "A\nB\nC\nD"
        # line breaks at 1, 3, 5; target=4 → candidates below: 1, 3; largest = 3
        result = _find_line_break(text, start=0, stop=len(text), target=4)
        assert result == 3

    def test_fallback_to_above_target(self) -> None:
        """When no line break is at or below target, return the lowest one above."""
        text = "Hello world\nNext line"
        # line break at 11; target=5 → no candidates below; fallback = 11
        result = _find_line_break(text, start=0, stop=len(text), target=5)
        assert result == 11

    def test_no_line_break_returns_none(self) -> None:
        """Returns None when no single line break exists in the window."""
        text = "Hello world no newlines"
        result = _find_line_break(text, start=0, stop=len(text), target=10)
        assert result is None

    def test_line_break_outside_window_returns_none(self) -> None:
        """Returns None when the line break is outside [start, stop)."""
        text = "Hello world\nNext line"
        # line break at 11; window is [0, 8) — break is outside
        result = _find_line_break(text, start=0, stop=8, target=5)
        assert result is None

    def test_crlf_paragraph_break_not_a_line_break(self) -> None:
        """\\r\\n\\r\\n is a paragraph break; neither \\n should be a line break."""
        text = "Hello\r\n\r\nWorld"
        result = _find_line_break(text, start=0, stop=len(text), target=10)
        assert result is None


# ---------------------------------------------------------------------------
# _find_whitespace
# ---------------------------------------------------------------------------


class TestFindWhitespace:
    """Tests for _find_whitespace — Requirement 4.6"""

    def test_space_character(self) -> None:
        """Boundary at a space character."""
        text = "Hello world"
        # space at index 5
        result = _find_whitespace(text, start=0, stop=len(text), target=8)
        assert result == 5

    def test_tab_character(self) -> None:
        """Boundary at a tab character."""
        text = "Hello\tworld"
        # tab at index 5
        result = _find_whitespace(text, start=0, stop=len(text), target=8)
        assert result == 5

    def test_newline_is_whitespace(self) -> None:
        """Newline characters qualify as whitespace boundaries."""
        text = "Hello\nworld"
        result = _find_whitespace(text, start=0, stop=len(text), target=8)
        assert result == 5

    def test_closest_from_below_preferred(self) -> None:
        """Among whitespace positions at or below target, the largest is returned."""
        text = "A B C D"
        # spaces at 1, 3, 5; target=4 → candidates below: 1, 3; largest = 3
        result = _find_whitespace(text, start=0, stop=len(text), target=4)
        assert result == 3

    def test_fallback_to_above_target(self) -> None:
        """When no whitespace is at or below target, return the lowest one above."""
        text = "Hello world"
        # space at 5; target=2 → no candidates below; fallback = 5
        result = _find_whitespace(text, start=0, stop=len(text), target=2)
        assert result == 5

    def test_no_whitespace_returns_none(self) -> None:
        """Returns None when no whitespace exists in the window."""
        text = "HelloWorld"
        result = _find_whitespace(text, start=0, stop=len(text), target=5)
        assert result is None

    def test_whitespace_outside_window_returns_none(self) -> None:
        """Returns None when whitespace is outside [start, stop)."""
        text = "Hello world"
        # space at 5; window is [6, 11) — space is outside
        result = _find_whitespace(text, start=6, stop=11, target=8)
        assert result is None

    def test_multiple_whitespace_types(self) -> None:
        """Multiple whitespace types are all candidates."""
        text = "A\tB\nC D"
        # whitespace at 1 (tab), 3 (newline), 5 (space); target=4 → candidates below: 1, 3; largest = 3
        result = _find_whitespace(text, start=0, stop=len(text), target=4)
        assert result == 3


# ---------------------------------------------------------------------------
# _find_boundary — priority ordering
# ---------------------------------------------------------------------------


class TestFindBoundaryPriority:
    """Tests for _find_boundary priority: paragraph > sentence > line > whitespace.

    Requirements: 4.1, 4.2, 4.3, 4.4, 4.6
    """

    def test_paragraph_wins_over_sentence(self) -> None:
        """Paragraph break is preferred over sentence terminator — Req 4.1"""
        # Sentence terminator at index 11, paragraph break at index 20
        text = "Hello world. More text\n\nNext paragraph"
        # Both are in window; paragraph should win
        result_offset, result_type = _find_boundary(text, start=0, stop=len(text), target=25)
        assert result_type == "paragraph"
        assert result_offset == 22

    def test_paragraph_wins_over_line_break(self) -> None:
        """Paragraph break is preferred over line break — Req 4.1"""
        text = "Hello world\nLine two\n\nParagraph two"
        # line break at 11, paragraph break at 20
        result_offset, result_type = _find_boundary(text, start=0, stop=len(text), target=25)
        assert result_type == "paragraph"
        assert result_offset == 20

    def test_paragraph_wins_over_whitespace(self) -> None:
        """Paragraph break is preferred over whitespace — Req 4.1"""
        text = "Hello world\n\nNext paragraph"
        result_offset, result_type = _find_boundary(text, start=0, stop=len(text), target=15)
        assert result_type == "paragraph"
        assert result_offset == 11

    def test_sentence_wins_over_line_break(self) -> None:
        """Sentence terminator is preferred over line break — Req 4.2"""
        text = "Hello world.\nLine two"
        # sentence boundary at 12, line break at 12 — sentence terminator is at 12
        # Actually: sentence boundary = 12 (after period), line break = 12 (the \n)
        # The sentence terminator finder returns 12 (after period at 11)
        # The line break finder returns 12 (the \n at 12)
        # Sentence wins because it's tried first
        result_offset, result_type = _find_boundary(text, start=0, stop=len(text), target=15)
        assert result_type == "sentence"

    def test_sentence_wins_over_whitespace(self) -> None:
        """Sentence terminator is preferred over whitespace — Req 4.2"""
        text = "Hello world. Next sentence"
        # sentence boundary at 12, spaces at 5, 12
        result_offset, result_type = _find_boundary(text, start=0, stop=len(text), target=15)
        assert result_type == "sentence"
        assert result_offset == 12

    def test_line_break_wins_over_whitespace(self) -> None:
        """Line break is preferred over whitespace — Req 4.3"""
        text = "Hello world\nNext line"
        # line break at 11, spaces at 5
        result_offset, result_type = _find_boundary(text, start=0, stop=len(text), target=15)
        assert result_type == "line"
        assert result_offset == 11

    def test_whitespace_fallback_when_no_other_boundary(self) -> None:
        """Whitespace is used as last resort — Req 4.6"""
        text = "HelloWorldFoo BarBaz"
        # No paragraph, sentence, or line break; space at index 13
        result_offset, result_type = _find_boundary(text, start=0, stop=len(text), target=10)
        assert result_type == "whitespace"
        assert result_offset == 13

    def test_no_boundary_returns_none_none(self) -> None:
        """Returns (None, None) when no boundary of any type exists — Req 4.7"""
        text = "HelloWorldFooBarBaz"
        result_offset, result_type = _find_boundary(text, start=0, stop=len(text), target=10)
        assert result_offset is None
        assert result_type is None

    def test_closest_from_below_preference(self) -> None:
        """Boundary closest to target from below is preferred — Req 4.4"""
        # Two sentence terminators: at index 5 and index 15; target=14
        text = "Hello. World sentence. More text"
        # boundaries at 6 and 22; target=14 → 6 is below, 22 is above; 6 wins
        result_offset, result_type = _find_boundary(text, start=0, stop=len(text), target=14)
        assert result_type == "sentence"
        assert result_offset == 6

    def test_fallback_to_above_target_when_nothing_below(self) -> None:
        """Falls back to lowest boundary above target when nothing fits below — Req 4.4"""
        text = "Hello world. Next sentence."
        # sentence boundary at 12; target=5 → nothing below; fallback = 12
        result_offset, result_type = _find_boundary(text, start=0, stop=len(text), target=5)
        assert result_type == "sentence"
        assert result_offset == 12

    def test_empty_window_returns_none_none(self) -> None:
        """Empty window [start, stop) with start >= stop returns (None, None)."""
        text = "Hello world. Next sentence."
        # Window [10, 10) is empty
        result_offset, result_type = _find_boundary(text, start=10, stop=10, target=10)
        assert result_offset is None
        assert result_type is None

    def test_window_smaller_than_min_part_length(self) -> None:
        """When start > stop (min_part_length > hard_max_length), returns (None, None)."""
        text = "Hello world. Next sentence."
        # start=20, stop=5 — inverted window (no valid candidates)
        result_offset, result_type = _find_boundary(text, start=20, stop=5, target=10)
        assert result_offset is None
        assert result_type is None


# ---------------------------------------------------------------------------
# _advance_past_whitespace
# ---------------------------------------------------------------------------


class TestAdvancePastWhitespace:
    """Tests for _advance_past_whitespace on each boundary type.

    Requirements: 4.1, 4.2, 4.3, 4.6
    """

    # --- paragraph boundary ---

    def test_paragraph_unix_advances_past_double_newline(self) -> None:
        """For paragraph boundary, advances past \\n\\n to first non-whitespace."""
        post = "Hello world\n\nNext paragraph"
        # boundary_offset=11 (first \n of \n\n); next non-whitespace is at 13
        result = _advance_past_whitespace(post, boundary_offset=11, boundary_type="paragraph")
        assert result == 13
        assert post[result] == "N"

    def test_paragraph_crlf_advances_past_crlf_crlf(self) -> None:
        """For paragraph boundary with \\r\\n\\r\\n, advances past all whitespace."""
        post = "Hello world\r\n\r\nNext paragraph"
        # boundary_offset=12 (first \n of \r\n\r\n); whitespace runs from 12 to 14
        result = _advance_past_whitespace(post, boundary_offset=12, boundary_type="paragraph")
        assert result == 15
        assert post[result] == "N"

    def test_paragraph_at_end_of_string(self) -> None:
        """For paragraph boundary at end of string, returns len(post)."""
        post = "Hello world\n\n"
        result = _advance_past_whitespace(post, boundary_offset=11, boundary_type="paragraph")
        assert result == len(post)

    # --- sentence boundary ---

    def test_sentence_advances_past_trailing_space(self) -> None:
        """For sentence boundary, advances past trailing whitespace after terminator."""
        post = "Hello world. Next sentence."
        # boundary_offset=12 (after period at 11); space at 12; next non-ws at 13
        result = _advance_past_whitespace(post, boundary_offset=12, boundary_type="sentence")
        assert result == 13
        assert post[result] == "N"

    def test_sentence_advances_past_multiple_spaces(self) -> None:
        """For sentence boundary, advances past multiple trailing spaces."""
        post = "Hello world.   Next sentence."
        # boundary_offset=12; spaces at 12, 13, 14; next non-ws at 15
        result = _advance_past_whitespace(post, boundary_offset=12, boundary_type="sentence")
        assert result == 15
        assert post[result] == "N"

    def test_sentence_at_end_of_string(self) -> None:
        """For sentence boundary at end of string, returns len(post)."""
        post = "Hello world."
        # boundary_offset=12 (= len(post)); no whitespace to skip
        result = _advance_past_whitespace(post, boundary_offset=12, boundary_type="sentence")
        assert result == len(post)

    def test_sentence_no_trailing_whitespace(self) -> None:
        """For sentence boundary with no trailing whitespace, returns boundary_offset."""
        post = "Hello world.Next"
        # boundary_offset=12; post[12]='N' (not whitespace)
        result = _advance_past_whitespace(post, boundary_offset=12, boundary_type="sentence")
        assert result == 12

    # --- line boundary ---

    def test_line_advances_past_single_newline(self) -> None:
        """For line boundary, advances past the \\n to first non-whitespace."""
        post = "Hello world\nNext line"
        # boundary_offset=11 (the \n); next non-ws at 12
        result = _advance_past_whitespace(post, boundary_offset=11, boundary_type="line")
        assert result == 12
        assert post[result] == "N"

    def test_line_advances_past_crlf(self) -> None:
        """For line boundary with \\r\\n, advances past both characters."""
        post = "Hello world\r\nNext line"
        # boundary_offset=11 (the \r); whitespace at 11, 12; next non-ws at 13
        result = _advance_past_whitespace(post, boundary_offset=11, boundary_type="line")
        assert result == 13
        assert post[result] == "N"

    def test_line_at_end_of_string(self) -> None:
        """For line boundary at end of string, returns len(post)."""
        post = "Hello world\n"
        result = _advance_past_whitespace(post, boundary_offset=11, boundary_type="line")
        assert result == len(post)

    # --- whitespace boundary ---

    def test_whitespace_advances_past_single_space(self) -> None:
        """For whitespace boundary, advances past the space character."""
        post = "Hello world"
        # boundary_offset=5 (the space); next non-ws at 6
        result = _advance_past_whitespace(post, boundary_offset=5, boundary_type="whitespace")
        assert result == 6
        assert post[result] == "w"

    def test_whitespace_advances_past_multiple_spaces(self) -> None:
        """For whitespace boundary, advances past consecutive whitespace."""
        post = "Hello   world"
        # boundary_offset=5 (first space); spaces at 5, 6, 7; next non-ws at 8
        result = _advance_past_whitespace(post, boundary_offset=5, boundary_type="whitespace")
        assert result == 8
        assert post[result] == "w"

    def test_whitespace_at_end_of_string(self) -> None:
        """For whitespace boundary at end of string, returns len(post)."""
        post = "Hello "
        result = _advance_past_whitespace(post, boundary_offset=5, boundary_type="whitespace")
        assert result == len(post)

    # --- end sentinel ---

    def test_end_sentinel_returns_offset_unchanged(self) -> None:
        """For 'end' boundary type, returns boundary_offset unchanged."""
        post = "Hello world"
        result = _advance_past_whitespace(post, boundary_offset=11, boundary_type="end")
        assert result == 11

    def test_end_sentinel_at_zero(self) -> None:
        """For 'end' boundary type at offset 0, returns 0."""
        post = "Hello world"
        result = _advance_past_whitespace(post, boundary_offset=0, boundary_type="end")
        assert result == 0


# ---------------------------------------------------------------------------
# Integration: _find_boundary + _advance_past_whitespace round-trip
# ---------------------------------------------------------------------------


class TestBoundaryRoundTrip:
    """Integration tests combining _find_boundary and _advance_past_whitespace.

    Verifies that the boundary offset + advance produces a valid next-part start.
    Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6
    """

    def test_paragraph_split_produces_clean_parts(self) -> None:
        """Splitting on a paragraph break produces clean part text."""
        post = "First paragraph text.\n\nSecond paragraph text."
        offset, kind = _find_boundary(post, start=0, stop=len(post), target=20)
        assert kind == "paragraph"
        part1 = post[:offset]
        next_start = _advance_past_whitespace(post, offset, kind)
        part2 = post[next_start:]
        assert part1 == "First paragraph text."
        assert part2 == "Second paragraph text."

    def test_sentence_split_produces_clean_parts(self) -> None:
        """Splitting on a sentence terminator produces clean part text."""
        post = "First sentence. Second sentence."
        offset, kind = _find_boundary(post, start=0, stop=len(post), target=10)
        assert kind == "sentence"
        part1 = post[:offset]
        next_start = _advance_past_whitespace(post, offset, kind)
        part2 = post[next_start:]
        assert part1 == "First sentence."
        assert part2 == "Second sentence."

    def test_line_split_produces_clean_parts(self) -> None:
        """Splitting on a line break produces clean part text."""
        post = "First line\nSecond line"
        offset, kind = _find_boundary(post, start=0, stop=len(post), target=8)
        assert kind == "line"
        part1 = post[:offset]
        next_start = _advance_past_whitespace(post, offset, kind)
        part2 = post[next_start:]
        assert part1 == "First line"
        assert part2 == "Second line"

    def test_whitespace_split_produces_clean_parts(self) -> None:
        """Splitting on whitespace produces clean part text."""
        post = "HelloWorldFoo BarBaz"
        offset, kind = _find_boundary(post, start=0, stop=len(post), target=10)
        assert kind == "whitespace"
        part1 = post[:offset]
        next_start = _advance_past_whitespace(post, offset, kind)
        part2 = post[next_start:]
        assert part1 == "HelloWorldFoo"
        assert part2 == "BarBaz"

    def test_no_mid_word_split(self) -> None:
        """The character immediately before the split offset is not mid-word — Req 4.5"""
        post = "Hello world. This is a test sentence."
        offset, kind = _find_boundary(post, start=0, stop=len(post), target=15)
        # The character at offset-1 should be a sentence terminator, whitespace, or newline
        char_before = post[offset - 1]
        assert char_before in ".!?\n\r " or char_before.isspace(), (
            f"Split at offset {offset} (kind={kind!r}) would be mid-word: "
            f"char before = {char_before!r}"
        )


# ---------------------------------------------------------------------------
# Story_Splitter edge-case example tests  (Task 5.12)
# Requirements: 4.7, 5.2, 5.3, 8.1
# ---------------------------------------------------------------------------

import math

import pytest

from utils.story_splitter.errors import StorySplitError
from utils.story_splitter.splitter import Story_Splitter, _redistribute_tail
from utils.story_splitter.types import SplittingConfig, TemplateConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(
    *,
    soft_max_length: int = 100,
    single_part_tolerance: float = 1.5,
    min_part_length: int = 30,
    max_parts: int = 5,
    mode: str = "split",
) -> SplittingConfig:
    """Build a SplittingConfig directly (no from_settings) for precise control."""
    return SplittingConfig(
        mode=mode,  # type: ignore[arg-type]
        soft_max_length=soft_max_length,
        single_part_tolerance=single_part_tolerance,
        min_part_length=min_part_length,
        max_parts=max_parts,
        templates=TemplateConfig(
            title_first_part="{title} (Part {part_number}/{total_parts})",
            title_other_part="{title} (Part {part_number}/{total_parts})",
            body_prefix_other_part="Part {part_number}: ",
            body_suffix_non_final_part="\n\nFollow for part {next_part_number}!",
        ),
        subreddit_name="test",
    )


def _make_reddit_content(post: str, thread_id: str = "test-id") -> dict:
    return {
        "thread_id": thread_id,
        "thread_title": "Test Title",
        "thread_post": post,
        "storymode": True,
    }


# ---------------------------------------------------------------------------
# _redistribute_tail — single redistribution iteration  (Req 5.2)
# ---------------------------------------------------------------------------


class TestRedistributeTailSingleIteration:
    """_redistribute_tail moves the previous boundary earlier in one step.

    Requirements: 5.2
    """

    def test_single_iteration_moves_boundary_earlier(self) -> None:
        """When the tail is too short, one earlier boundary is enough to fix it.

        Layout (hard_max=150, min_part=30):
          Part 1: chars 0..70  (sentence boundary at 70, after first '.')
          Tail:   chars 71..119  (49 chars — above min_part_length=30 after redistribution)

        We start with a split at offset 101 (second sentence boundary), leaving
        a tail of 18 chars < 30.  _redistribute_tail should find the earlier
        boundary at 70 and move the split there, giving a tail of 49 chars >= 30.
        """
        # "A"*69 + ". " + "B"*28 + ". " + "C"*19
        # Sentence boundaries (after terminator): offset 70, offset 101
        part1_body = "A" * 69 + ". "   # 71 chars; sentence boundary at offset 70
        part2_body = "B" * 28 + ". "   # 30 chars; sentence boundary at offset 101
        tail_body  = "C" * 19          # 19 chars — too short
        post = part1_body + part2_body + tail_body
        # Total = 71 + 30 + 19 = 120 chars

        config = _make_config(
            soft_max_length=100,
            single_part_tolerance=1.5,   # hard_max = 150
            min_part_length=30,
            max_parts=5,
        )

        # Initial parts: split at offset 101 (after second sentence terminator).
        # Tail entry: starts at 102 (after advancing past whitespace at 101).
        # tail length = 120 - 102 = 18 < 30 → redistribution needed.
        # _redistribute_tail expects the last entry to be the tail tuple.
        tail_start = 102  # _advance_past_whitespace(post, 101, "sentence") = 102
        initial_parts = [(0, 101, "sentence"), (tail_start, len(post), "end")]
        result = _redistribute_tail(post, initial_parts, config, "test-id")

        # After redistribution there should still be 2 parts (no merge needed)
        assert len(result) == 2, f"Expected 2 parts after redistribution, got {len(result)}"
        _start0, end0, _kind0 = result[0]
        start1, end1, _kind1 = result[1]
        tail_len = end1 - start1
        assert tail_len >= config.min_part_length, (
            f"Tail length {tail_len} is below min_part_length {config.min_part_length}"
        )


# ---------------------------------------------------------------------------
# _redistribute_tail — multi-iteration redistribution  (Req 5.2)
# ---------------------------------------------------------------------------


class TestRedistributeTailMultiIteration:
    """_redistribute_tail repeats until the tail meets min_part_length.

    Requirements: 5.2
    """

    def test_multi_iteration_keeps_moving_boundary_earlier(self) -> None:
        """Each iteration moves the boundary one step earlier until tail is long enough.

        We craft a post where the first earlier boundary still leaves a short
        tail, so a second iteration is required.

        Layout (hard_max=200, min_part=50):
          Sentence boundaries at offsets: 60, 80, 110
          Initial split at 110 → tail = post[111:] = 20 chars < 50
          After 1st iteration: split at 80 → tail = post[81:] = 50 chars == 50 ✓
        """
        # "A"*59 + ". " + "B"*19 + ". " + "C"*29 + ". " + "D"*20
        # offsets: sentence at 60, 81, 112
        seg_a = "A" * 59 + ". "   # 61 chars; sentence boundary at 60 (after '.')
        seg_b = "B" * 19 + ". "   # 21 chars; sentence boundary at 81
        seg_c = "C" * 29 + ". "   # 31 chars; sentence boundary at 113
        seg_d = "D" * 20          # 20 chars — tail too short
        post = seg_a + seg_b + seg_c + seg_d
        # Total = 61 + 21 + 31 + 20 = 133 chars

        config = _make_config(
            soft_max_length=120,
            single_part_tolerance=2.0,   # hard_max = 240
            min_part_length=50,
            max_parts=5,
        )

        # Initial split at offset 113 (after third sentence terminator).
        # Tail entry: starts at 114, length = 133 - 114 = 19 < 50.
        tail_start = 114  # _advance_past_whitespace(post, 113, "sentence") = 114
        initial_parts = [(0, 113, "sentence"), (tail_start, len(post), "end")]
        result = _redistribute_tail(post, initial_parts, config, "test-id")

        assert len(result) == 2
        _s0, _e0, _k0 = result[0]
        start1, end1, _k1 = result[1]
        tail_len = end1 - start1
        assert tail_len >= config.min_part_length, (
            f"Tail length {tail_len} is below min_part_length {config.min_part_length}"
        )


# ---------------------------------------------------------------------------
# _redistribute_tail — successful tail merge fallback  (Req 5.3)
# ---------------------------------------------------------------------------


class TestRedistributeTailMergeFallback:
    """When no earlier boundary exists, the tail is merged into the previous part.

    Requirements: 5.3
    """

    def test_tail_merge_when_no_earlier_boundary(self) -> None:
        """Tail is merged into the previous part when no earlier boundary exists.

        Layout (hard_max=200, min_part=50):
          One sentence boundary at offset 100.
          Tail = post[101:] = 20 chars < 50.
          No earlier boundary in [0+50, 100) = [50, 100).
          Merged length = len(post) - 0 = 121 <= 200 → merge succeeds.
        """
        # "A"*100 + ". " + "B"*20
        # Only one sentence boundary at offset 100 (after '.')
        # No other boundaries in the window [50, 100)
        post = "A" * 100 + ". " + "B" * 20
        # Total = 122 chars

        config = _make_config(
            soft_max_length=110,
            single_part_tolerance=2.0,   # hard_max = 220
            min_part_length=50,
            max_parts=5,
        )

        # Initial split at offset 101 (after the sentence terminator at 100).
        # Tail entry: starts at 102, length = 122 - 102 = 20 < 50.
        tail_start = 102  # _advance_past_whitespace(post, 101, "sentence") = 102
        initial_parts = [(0, 101, "sentence"), (tail_start, len(post), "end")]
        result = _redistribute_tail(post, initial_parts, config, "test-id")

        # Merge should produce a single part spanning the whole post
        assert len(result) == 1, (
            f"Expected 1 part after merge, got {len(result)}: {result}"
        )
        start, end, kind = result[0]
        assert start == 0
        assert end == len(post)
        assert kind == "end"

    def test_tail_merge_reduces_part_count_by_one(self) -> None:
        """Merging the tail into the previous part reduces total parts by 1.

        Three-part scenario: parts at [0,100], [101,200], [201,220].
        Tail [201:220] = 19 chars < min_part_length=50.
        No earlier boundary in [101+50, 200) = [151, 200).
        Merged length = 220 - 101 = 119 <= hard_max=220 → merge succeeds.
        Result: 2 parts.
        """
        # Build post with sentence boundaries at ~100 and ~200
        seg1 = "A" * 99 + ". "   # 101 chars; sentence at 99
        seg2 = "B" * 99 + ". "   # 101 chars; sentence at 200
        seg3 = "C" * 19          # 19 chars — tail too short
        post = seg1 + seg2 + seg3
        # Total = 221 chars

        config = _make_config(
            soft_max_length=110,
            single_part_tolerance=2.0,   # hard_max = 220
            min_part_length=50,
            max_parts=5,
        )

        # Initial 3-part split
        initial_parts = [
            (0, 100, "sentence"),
            (101, 201, "sentence"),
            (202, len(post), "end"),
        ]
        result = _redistribute_tail(post, initial_parts, config, "test-id")

        # Tail merged into part 2 → 2 parts total
        assert len(result) == 2, (
            f"Expected 2 parts after merge, got {len(result)}: {result}"
        )
        # Last part should span from 101 to end
        last_start, last_end, _ = result[-1]
        assert last_end == len(post)
        merged_len = last_end - last_start
        assert merged_len <= config.hard_max_length, (
            f"Merged part length {merged_len} exceeds hard_max_length {config.hard_max_length}"
        )


# ---------------------------------------------------------------------------
# pathological_text → StorySplitError(reason="no_valid_boundary")  (Req 4.7, 8.1)
# ---------------------------------------------------------------------------


class TestNoValidBoundaryError:
    """A contiguous block of non-whitespace longer than hard_max raises StorySplitError.

    Requirements: 4.7, 8.1
    """

    def test_pathological_text_raises_no_valid_boundary(self) -> None:
        """A post with no whitespace or punctuation raises StorySplitError.

        The post is longer than hard_max_length so a split is attempted, but
        no boundary of any type exists in [min_part_length, hard_max_length].
        """
        config = _make_config(
            soft_max_length=100,
            single_part_tolerance=1.5,   # hard_max = 150
            min_part_length=30,
            max_parts=5,
        )
        # 200 chars of pure non-whitespace, no punctuation
        post = "X" * 200
        reddit_content = _make_reddit_content(post)

        splitter = Story_Splitter(config)
        with pytest.raises(StorySplitError) as exc_info:
            splitter.split(reddit_content)

        assert exc_info.value.reason == "no_valid_boundary"
        assert exc_info.value.thread_id == "test-id"

    def test_pathological_text_error_has_detail(self) -> None:
        """StorySplitError for no_valid_boundary includes a non-empty detail string."""
        config = _make_config(
            soft_max_length=50,
            single_part_tolerance=2.0,   # hard_max = 100
            min_part_length=10,
            max_parts=5,
        )
        post = "Z" * 200
        reddit_content = _make_reddit_content(post)

        splitter = Story_Splitter(config)
        with pytest.raises(StorySplitError) as exc_info:
            splitter.split(reddit_content)

        assert exc_info.value.reason == "no_valid_boundary"
        assert exc_info.value.detail  # non-empty

    def test_pathological_text_error_message_format(self) -> None:
        """StorySplitError message is formatted as 'reason: detail'."""
        config = _make_config(
            soft_max_length=50,
            single_part_tolerance=2.0,
            min_part_length=10,
            max_parts=5,
        )
        post = "Z" * 200
        reddit_content = _make_reddit_content(post)

        splitter = Story_Splitter(config)
        with pytest.raises(StorySplitError) as exc_info:
            splitter.split(reddit_content)

        err = exc_info.value
        assert str(err) == f"{err.reason}: {err.detail}"


# ---------------------------------------------------------------------------
# len(thread_post) > max_parts * hard_max_length → StorySplitError("too_many_parts")
# (Req 3.4, 8.1)
# ---------------------------------------------------------------------------


class TestTooManyPartsError:
    """A post that requires more parts than max_parts raises StorySplitError.

    Requirements: 3.4, 8.1
    """

    def test_too_many_parts_raises_error(self) -> None:
        """Post requiring more than max_parts parts raises StorySplitError.

        With max_parts=2 and hard_max=150, a post of 500 chars with sentence
        boundaries every ~100 chars would need 4 parts → too_many_parts.
        """
        config = _make_config(
            soft_max_length=100,
            single_part_tolerance=1.5,   # hard_max = 150
            min_part_length=20,
            max_parts=2,
        )
        # Build a post with sentence boundaries every ~100 chars, total ~500 chars
        # Each segment: 99 "A"s + ". " = 101 chars
        segment = "A" * 99 + ". "
        post = segment * 5   # 505 chars — needs at least 4 parts
        reddit_content = _make_reddit_content(post)

        splitter = Story_Splitter(config)
        with pytest.raises(StorySplitError) as exc_info:
            splitter.split(reddit_content)

        assert exc_info.value.reason == "too_many_parts"
        assert exc_info.value.thread_id == "test-id"

    def test_too_many_parts_error_has_detail(self) -> None:
        """StorySplitError for too_many_parts includes a non-empty detail string."""
        config = _make_config(
            soft_max_length=100,
            single_part_tolerance=1.5,
            min_part_length=20,
            max_parts=1,
        )
        # Two segments → needs 2 parts but max_parts=1
        segment = "A" * 99 + ". "
        post = segment * 2 + "B" * 50
        reddit_content = _make_reddit_content(post)

        splitter = Story_Splitter(config)
        with pytest.raises(StorySplitError) as exc_info:
            splitter.split(reddit_content)

        assert exc_info.value.reason == "too_many_parts"
        assert exc_info.value.detail

    def test_exactly_max_parts_does_not_raise(self) -> None:
        """A post that fits exactly within max_parts does not raise.

        With max_parts=3 and hard_max=150, a post of ~3 * 100 chars with
        sentence boundaries should produce exactly 3 parts without error.
        """
        config = _make_config(
            soft_max_length=100,
            single_part_tolerance=1.5,   # hard_max = 150
            min_part_length=20,
            max_parts=3,
        )
        # Three segments of ~100 chars each with sentence boundaries
        segment = "A" * 99 + ". "   # 101 chars
        tail = "B" * 50             # 50 chars — above min_part_length
        post = segment * 2 + tail   # 252 chars → 2 full parts + tail
        reddit_content = _make_reddit_content(post)

        splitter = Story_Splitter(config)
        plan = splitter.split(reddit_content)
        assert len(plan) <= config.max_parts


# ---------------------------------------------------------------------------
# Tail merge exceeds hard_max_length → StorySplitError("tail_redistribution_failed")
# (Req 5.3, 8.1)
# ---------------------------------------------------------------------------


class TestTailRedistributionFailedError:
    """When the tail merge would exceed hard_max_length, StorySplitError is raised.

    Requirements: 5.3, 8.1
    """

    def test_tail_merge_exceeds_hard_max_raises_error(self) -> None:
        """Merging the tail into the previous part would exceed hard_max_length.

        Layout (hard_max=120, min_part=50):
          Part 1: chars 0..99  (100 chars — at the boundary)
          Tail:   chars 100..119  (20 chars < min_part_length=50)
          No earlier boundary in [50, 100).
          Merged length = 120 chars == hard_max → merge is allowed (<=).

        To force the failure we need merged_len > hard_max_length.
        Use hard_max=110 so merged_len=120 > 110.
        """
        config = _make_config(
            soft_max_length=100,
            single_part_tolerance=1.1,   # hard_max = floor(100 * 1.1) = 110
            min_part_length=50,
            max_parts=5,
        )
        # hard_max = 110
        # Build: 100 "A"s + ". " + 20 "B"s = 122 chars
        # Only one sentence boundary at offset 100 (after '.')
        # No earlier boundary in [50, 100)
        # Merged length = 122 - 0 = 122 > 110 → should raise
        post = "A" * 100 + ". " + "B" * 20
        # Verify our assumption
        assert math.floor(100 * 1.1) == 110
        assert len(post) == 122
        assert len(post) > config.hard_max_length

        reddit_content = _make_reddit_content(post)
        splitter = Story_Splitter(config)

        with pytest.raises(StorySplitError) as exc_info:
            splitter.split(reddit_content)

        assert exc_info.value.reason == "tail_redistribution_failed"
        assert exc_info.value.thread_id == "test-id"

    def test_tail_redistribution_failed_error_has_detail(self) -> None:
        """StorySplitError for tail_redistribution_failed includes a detail string."""
        config = _make_config(
            soft_max_length=100,
            single_part_tolerance=1.1,   # hard_max = 110
            min_part_length=50,
            max_parts=5,
        )
        post = "A" * 100 + ". " + "B" * 20
        reddit_content = _make_reddit_content(post)
        splitter = Story_Splitter(config)

        with pytest.raises(StorySplitError) as exc_info:
            splitter.split(reddit_content)

        assert exc_info.value.reason == "tail_redistribution_failed"
        assert exc_info.value.detail

    def test_tail_redistribution_failed_via_redistribute_tail_directly(self) -> None:
        """_redistribute_tail raises directly when merge would exceed hard_max_length."""
        config = _make_config(
            soft_max_length=100,
            single_part_tolerance=1.1,   # hard_max = 110
            min_part_length=50,
            max_parts=5,
        )
        # post: 100 "A"s + ". " + 20 "B"s = 122 chars
        post = "A" * 100 + ". " + "B" * 20
        # Initial split: one part ending at offset 101 (after sentence terminator).
        # Tail entry: starts at 102, length = 122 - 102 = 20 < 50.
        # No earlier boundary in [50, 101) → merge attempted.
        # Merged length = 122 - 0 = 122 > hard_max=110 → should raise.
        tail_start = 102  # _advance_past_whitespace(post, 101, "sentence") = 102
        initial_parts = [(0, 101, "sentence"), (tail_start, len(post), "end")]

        with pytest.raises(StorySplitError) as exc_info:
            _redistribute_tail(post, initial_parts, config, "test-id")

        assert exc_info.value.reason == "tail_redistribution_failed"
