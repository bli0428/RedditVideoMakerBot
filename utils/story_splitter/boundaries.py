"""
Boundary search helpers for the Story_Splitter.

This module is **pure**: it performs no I/O and accesses no settings.
All functions operate solely on the ``text`` string passed to them.

Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Compiled patterns
# ---------------------------------------------------------------------------

# Sentence terminator: . ! ? immediately followed by whitespace or end-of-string.
_SENTENCE_RE = re.compile(r"[.!?](?=\s|$)")

# Paragraph break: \n\n or \r\n\r\n.
# We search for the *first* \n of the sequence so that text[:offset] ends
# cleanly and _advance_past_whitespace can skip the rest.
_PARA_UNIX_RE = re.compile(r"\n\n")
_PARA_CRLF_RE = re.compile(r"\r\n\r\n")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _highest_at_or_below(offsets: list[int], target: int) -> int | None:
    """Return the largest value in *offsets* that is <= *target*, or None."""
    candidates = [o for o in offsets if o <= target]
    return max(candidates) if candidates else None


def _lowest_above(offsets: list[int], target: int) -> int | None:
    """Return the smallest value in *offsets* that is > *target*, or None."""
    candidates = [o for o in offsets if o > target]
    return min(candidates) if candidates else None


def _best_in_window(offsets: list[int], start: int, stop: int, target: int) -> int | None:
    """
    Given a list of candidate offsets, return the one that is "closest to
    *target* from below" within the half-open window ``[start, stop)``.

    Strategy (per design §Step 3):
    1. Collect all candidates in ``[start, min(stop, target + 1))``.
       Return the largest (closest to target from below).
    2. If none, collect all candidates in ``(target, stop)``.
       Return the smallest (closest to target from above, still in window).
    3. If still none, return None.
    """
    window_candidates = [o for o in offsets if start <= o < stop]
    if not window_candidates:
        return None

    below_or_at = [o for o in window_candidates if o <= target]
    if below_or_at:
        return max(below_or_at)

    above = [o for o in window_candidates if o > target]
    return min(above) if above else None


# ---------------------------------------------------------------------------
# Individual boundary finders
# ---------------------------------------------------------------------------


def _find_paragraph_break(text: str, start: int, stop: int, target: int) -> int | None:
    """
    Find a paragraph-break boundary in ``text[start:stop]``.

    A paragraph break is ``\\n\\n`` or ``\\r\\n\\r\\n``.  The boundary offset
    is the position of the **first** ``\\n`` in the sequence, so that
    ``text[:offset]`` is the part text and ``_advance_past_whitespace`` can
    consume the remaining newlines.

    Returns the offset closest to *target* from below within ``[start, stop)``,
    falling back to the lowest offset above *target* still within the window.
    Returns ``None`` if no paragraph break exists in the window.
    """
    offsets: list[int] = []

    # \r\n\r\n — boundary at the first \r (which is also the first \n - 1,
    # but we want the first \n of the sequence, i.e. index + 1).
    for m in _PARA_CRLF_RE.finditer(text):
        # m.start() points to the first \r; the first \n is at m.start() + 1.
        boundary = m.start() + 1
        offsets.append(boundary)

    # \n\n — boundary at the first \n.
    for m in _PARA_UNIX_RE.finditer(text):
        boundary = m.start()
        # Exclude if this \n is part of a \r\n\r\n sequence already captured.
        # A \n\n match at position p overlaps with \r\n\r\n at p-1 when
        # text[p-1] == '\r'.  In that case the \r\n\r\n finder already added
        # p (= m.start() + 1 of the crlf match), so we'd be adding a
        # duplicate — which is harmless because _best_in_window deduplicates
        # via max/min.  We keep it simple and just add all \n\n positions.
        offsets.append(boundary)

    return _best_in_window(offsets, start, stop, target)


def _find_sentence_terminator(text: str, start: int, stop: int, target: int) -> int | None:
    """
    Find a sentence-terminator boundary in ``text[start:stop]``.

    A sentence terminator is ``.``, ``!``, or ``?`` immediately followed by
    whitespace or end-of-string.  The boundary offset is the position
    **immediately after** the terminator character (so the terminator is the
    last character of the part, and the next part starts at or after the
    following whitespace).

    Returns the offset closest to *target* from below within ``[start, stop)``,
    falling back to the lowest offset above *target* still within the window.
    Returns ``None`` if no sentence terminator exists in the window.
    """
    offsets: list[int] = []
    for m in _SENTENCE_RE.finditer(text):
        # Boundary is immediately after the terminator character.
        boundary = m.end()
        offsets.append(boundary)

    return _best_in_window(offsets, start, stop, target)


def _find_line_break(text: str, start: int, stop: int, target: int) -> int | None:
    """
    Find a single line-break boundary in ``text[start:stop]``.

    A line break is a single ``\\n`` (or ``\\r\\n``) that is **not** part of a
    paragraph break (``\\n\\n`` or ``\\r\\n\\r\\n``).  The boundary offset is
    the position of the ``\\n`` character itself.

    Returns the offset closest to *target* from below within ``[start, stop)``,
    falling back to the lowest offset above *target* still within the window.
    Returns ``None`` if no qualifying line break exists in the window.
    """
    offsets: list[int] = []
    i = 0
    while i < len(text):
        if text[i] == "\n":
            # Check whether this \n is part of \n\n (unix paragraph break).
            prev_is_newline = i > 0 and text[i - 1] == "\n"
            next_is_newline = i + 1 < len(text) and text[i + 1] == "\n"
            # Also check for \r\n\r\n: the \n at position i is part of a
            # \r\n\r\n sequence if text[i-1] == '\r' and text[i+1:i+3] == '\r\n',
            # or if text[i-3:i] == '\r\n\r' (i.e. this is the second \n).
            is_crlf_para = (
                (i >= 3 and text[i - 3 : i] == "\r\n\r" and i + 0 < len(text))
                or (i + 2 < len(text) and text[i + 1 : i + 3] == "\r\n" and i > 0 and text[i - 1] == "\r")
            )
            if not prev_is_newline and not next_is_newline and not is_crlf_para:
                offsets.append(i)
        i += 1

    return _best_in_window(offsets, start, stop, target)


def _find_whitespace(text: str, start: int, stop: int, target: int) -> int | None:
    """
    Find a whitespace boundary in ``text[start:stop]``.

    Any position where ``text[offset]`` is a whitespace character qualifies.
    This is the last-resort fallback (Requirement 4.6).

    Returns the offset closest to *target* from below within ``[start, stop)``,
    falling back to the lowest offset above *target* still within the window.
    Returns ``None`` if no whitespace character exists in the window.
    """
    offsets: list[int] = []
    for i in range(len(text)):
        if text[i].isspace():
            offsets.append(i)

    return _best_in_window(offsets, start, stop, target)


# ---------------------------------------------------------------------------
# Public boundary search
# ---------------------------------------------------------------------------


def _find_boundary(
    text: str,
    start: int,
    stop: int,
    target: int,
) -> tuple[int | None, str | None]:
    """
    Find the best split boundary in ``text[start:stop]`` closest to *target*.

    Tries boundary types in priority order:
    paragraph → sentence → line → whitespace.

    The first type that yields a candidate wins.  Within a type, "closest to
    *target* from below" is preferred (largest offset <= target); if none
    exists, the smallest offset > target (still within the window) is used.

    Parameters
    ----------
    text:
        The full post text.
    start:
        Inclusive lower bound of the search window (absolute offset in *text*).
    stop:
        Exclusive upper bound of the search window (absolute offset in *text*).
    target:
        The ideal split point (absolute offset in *text*).  Typically
        ``cursor + soft_max_length``.

    Returns
    -------
    (offset, boundary_type) where *offset* is an absolute position in *text*
    and *boundary_type* is one of ``"paragraph"``, ``"sentence"``, ``"line"``,
    ``"whitespace"``.  Returns ``(None, None)`` when no boundary of any type
    exists in the window.
    """
    for finder, kind in (
        (_find_paragraph_break, "paragraph"),
        (_find_sentence_terminator, "sentence"),
        (_find_line_break, "line"),
        (_find_whitespace, "whitespace"),
    ):
        offset = finder(text, start, stop, target)
        if offset is not None:
            return offset, kind
    return None, None


# ---------------------------------------------------------------------------
# Whitespace advancement
# ---------------------------------------------------------------------------


def _advance_past_whitespace(
    post: str,
    boundary_offset: int,
    boundary_type: str,
) -> int:
    """
    Return the offset of the next non-whitespace character at or after
    *boundary_offset*, consuming the boundary whitespace between parts.

    For **paragraph** and **line** breaks the boundary offset points to a
    ``\\n`` character; we skip all consecutive whitespace (the newlines
    themselves) so the next part starts at the first non-whitespace character.

    For **sentence** terminators the boundary offset is immediately after the
    ``.``/``!``/``?`` character; we skip any trailing whitespace so the next
    part does not begin with a leading space.

    For the **whitespace** fallback the boundary offset points to a whitespace
    character; we skip it and any consecutive whitespace.

    For the **end** sentinel (used by the splitter to mark the final part) we
    return *boundary_offset* unchanged.

    Parameters
    ----------
    post:
        The full post text.
    boundary_offset:
        The raw boundary offset as returned by one of the ``_find_*`` helpers
        or ``_find_boundary``.
    boundary_type:
        One of ``"paragraph"``, ``"sentence"``, ``"line"``, ``"whitespace"``,
        ``"end"``.

    Returns
    -------
    The offset of the first non-whitespace character at or after
    *boundary_offset*, or ``len(post)`` if only whitespace remains.
    """
    if boundary_type == "end":
        return boundary_offset

    # For all boundary types, skip whitespace starting at boundary_offset.
    # - paragraph: boundary_offset is the first \n; skip \n\n (or \r\n\r\n).
    # - line: boundary_offset is the \n; skip it.
    # - sentence: boundary_offset is after the terminator; skip trailing ws.
    # - whitespace: boundary_offset is a whitespace char; skip it.
    i = boundary_offset
    while i < len(post) and post[i].isspace():
        i += 1
    return i
