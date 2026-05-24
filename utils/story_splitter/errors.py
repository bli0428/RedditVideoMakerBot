"""
Exceptions raised by the Story_Splitter pipeline stage.

Requirements: 8.1, 8.3
"""

from __future__ import annotations

from typing import Literal

# The closed set of reason codes that StorySplitError may carry.
SplitErrorReason = Literal[
    "no_valid_boundary",
    "too_many_parts",
    "tail_redistribution_failed",
]


class StorySplitError(Exception):
    """Raised when the Story_Splitter cannot produce a valid Split_Plan.

    Attributes
    ----------
    thread_id : str
        The ``thread_id`` of the post that could not be split.
    reason : SplitErrorReason
        A machine-readable failure category.  One of:

        * ``"no_valid_boundary"`` — no paragraph/sentence/line/whitespace
          boundary exists within ``[Min_Part_Length, Hard_Max_Length]`` for
          the current part (Requirement 4.7).
        * ``"too_many_parts"`` — splitting the post would require more parts
          than ``max_parts`` allows (Requirement 3.4).
        * ``"tail_redistribution_failed"`` — the tail redistribution in
          Requirement 5.3 could not satisfy ``Hard_Max_Length`` after
          attempting to merge the short tail into the previous part.
    detail : str
        A human-readable description of the specific failure, suitable for
        log messages.
    """

    def __init__(self, *, thread_id: str, reason: SplitErrorReason, detail: str) -> None:
        self.thread_id: str = thread_id
        self.reason: SplitErrorReason = reason
        self.detail: str = detail
        super().__init__(f"{reason}: {detail}")
