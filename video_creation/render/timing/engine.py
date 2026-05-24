"""TimingEngine — pure-Python word-to-line/chunk timing computation.

This module MUST NOT import PIL, numpy, MoviePy, or FFmpeg — only stdlib.

Satisfies: Requirements 3.3, 6.1, 6.2, 7.4
"""

from __future__ import annotations

import math
import re
from typing import TYPE_CHECKING

from video_creation.render.timing.models import (
    LineTiming,
    LineDefinition,
    TimingResult,
    WordTimestamp,
)


_PUNCT_BREAK = re.compile(r'[,\.!?;:]$')


def _split_words_on_punctuation(words: list[str]) -> list[list[str]]:
    """Split a flat list of words into sub-groups at punctuation boundaries.

    A word that ends with ``,``, ``.``, ``!``, ``?``, ``;``, or ``:`` closes
    the current sub-group.  For example::

        ["Hi,", "my", "name"] → [["Hi,"], ["my", "name"]]

    An empty input returns an empty list.
    """
    if not words:
        return []
    groups: list[list[str]] = []
    current: list[str] = []
    for word in words:
        current.append(word)
        if _PUNCT_BREAK.search(word):
            groups.append(current)
            current = []
    if current:
        groups.append(current)
    return groups


class TimingEngine:
    """Pure-Python engine that maps word-level TTS timestamps to per-line
    and per-chunk timing entries.

    No PIL, numpy, MoviePy, or FFmpeg imports — only stdlib.
    """

    def compute(
        self,
        words: tuple[WordTimestamp, ...],
        line_definitions: tuple[LineDefinition, ...],
        chunk_size: int,
        audio_speed: float,
        title_duration: float,
    ) -> TimingResult:
        """Walk the word stream, slicing it line-by-line (and optionally
        chunk-by-chunk for karaoke). Returns a ``TimingResult`` whose
        ``entries`` are ordered by ``start`` time.

        Parameters
        ----------
        words:
            Sequence of word timestamps, already scaled by ``audio_speed``
            by the caller (AudioAssembler).  ``start`` and ``end`` are in
            seconds.
        line_definitions:
            Sequence of wrapped lines.  The sum of all ``word_count`` values
            MUST equal ``len(words)``; a ``ValueError`` is raised otherwise.
        chunk_size:
            When ``<= 0``, each ``LineDefinition`` produces exactly one
            ``LineTiming`` with ``chunk_index = 0``.  When ``> 0``, each
            ``LineDefinition`` produces ``ceil(word_count / chunk_size)``
            entries.
        audio_speed:
            Informational only at this layer — the caller is responsible for
            pre-scaling timestamps.  Accepted but not used in computation.
        title_duration:
            Duration of the title audio clip in seconds.  Passed through
            unchanged into ``TimingResult.title_duration``.

        Returns
        -------
        TimingResult
            ``entries`` ordered by ``start`` time; ``total_duration`` equals
            ``title_duration`` plus the span of all content word timestamps.

        Raises
        ------
        ValueError
            If the sum of ``line_definitions[*].word_count`` does not equal
            ``len(words)``.
        """
        # ── Input validation ──────────────────────────────────────────────
        total_word_count = sum(ld.word_count for ld in line_definitions)
        if total_word_count != len(words):
            raise ValueError(
                f"Word count mismatch: sum of line_definitions word_counts is "
                f"{total_word_count}, but {len(words)} WordTimestamp(s) were provided."
            )

        # ── Build timing entries ──────────────────────────────────────────
        entries: list[LineTiming] = []
        word_idx = 0

        for line_index, ld in enumerate(line_definitions):
            n = ld.word_count
            line_words = ld.text.split()

            if chunk_size <= 0:
                # No chunking — one LineTiming per LineDefinition.
                if n > 0:
                    start = words[word_idx].start
                    end = words[word_idx + n - 1].end
                else:
                    # Zero-word line: anchor to previous entry or 0.
                    prev_end = entries[-1].end if entries else 0.0
                    start = prev_end
                    end = prev_end

                entries.append(
                    LineTiming(
                        text=ld.text,
                        start=start,
                        end=end,
                        line_index=line_index,
                        chunk_index=0,
                        y_top=ld.y_top,
                        y_bottom=ld.y_bottom,
                        page_index=ld.page_index,
                    )
                )
                word_idx += n
            else:
                # Chunked — ceil(n / chunk_size) entries per LineDefinition,
                # then further split each chunk at punctuation boundaries so
                # that e.g. "Hi, my name" becomes ["Hi,"] and ["my", "name"].
                num_chunks = math.ceil(n / chunk_size) if n > 0 else 1
                chunk_index = 0
                for raw_chunk_idx in range(num_chunks):
                    chunk_start_word = raw_chunk_idx * chunk_size
                    chunk_end_word = min(chunk_start_word + chunk_size, n)
                    raw_chunk_words = line_words[chunk_start_word:chunk_end_word]

                    # Further split on punctuation within this raw chunk.
                    sub_groups = _split_words_on_punctuation(raw_chunk_words)
                    if not sub_groups:
                        sub_groups = [[]]  # preserve zero-word chunk behaviour

                    sub_word_idx = word_idx
                    for sub_words in sub_groups:
                        cw_n = len(sub_words)
                        chunk_text = " ".join(sub_words)

                        if cw_n > 0:
                            start = words[sub_word_idx].start
                            end = words[sub_word_idx + cw_n - 1].end
                        else:
                            prev_end = entries[-1].end if entries else 0.0
                            start = prev_end
                            end = prev_end

                        entries.append(
                            LineTiming(
                                text=chunk_text,
                                start=start,
                                end=end,
                                line_index=line_index,
                                chunk_index=chunk_index,
                                y_top=ld.y_top,
                                y_bottom=ld.y_bottom,
                                page_index=ld.page_index,
                            )
                        )
                        sub_word_idx += cw_n
                        chunk_index += 1

                    word_idx += len(raw_chunk_words)

        # ── Compute total_duration ────────────────────────────────────────
        if words:
            content_end = words[-1].end
        else:
            content_end = 0.0
        total_duration = title_duration + content_end

        return TimingResult(
            title_duration=title_duration,
            total_duration=total_duration,
            entries=tuple(entries),
        )
