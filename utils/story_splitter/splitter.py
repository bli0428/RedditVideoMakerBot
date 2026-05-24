"""
Core Story_Splitter algorithm.

Converts a translated Reddit_Content dict into a Split_Plan (list of
Story_Part dicts).  The splitter is a pure function of
(Reddit_Content, SplittingConfig) → Split_Plan; it performs no I/O,
makes no network calls, and never mutates its input.

Requirements: 1.3, 1.5, 1.6, 1.7, 2.4, 3.3, 3.4, 3.5, 4.1-4.7,
              5.1-5.4, 6.6, 7.1, 7.6, 8.1, 8.3, 12.1, 12.2, 12.3
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from utils.story_splitter.boundaries import _advance_past_whitespace, _find_boundary
from utils.story_splitter.errors import StorySplitError
from utils.story_splitter.templates import _decorate_body, _decorate_title
from utils.story_splitter.types import Split_Plan, SplittingConfig, Story_Part

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# Observability helper
# ---------------------------------------------------------------------------


def _log(msg: str, style: str = "bold green") -> None:
    """Emit a log line via the project console helper."""
    from utils.console import print_substep  # lazy import to avoid circular deps

    print_substep(f"[splitter] {msg}", style=style)


# ---------------------------------------------------------------------------
# Single-part helper
# ---------------------------------------------------------------------------


def _single_part(reddit_content: dict) -> Story_Part:
    """Build a single-part Story_Part that is the identity of reddit_content.

    Used for all short-circuit paths (storymode=False, cutoff mode, post
    fits within hard_max_length).  No template decoration is applied
    (Req 6.6, 7.6, 9.6).

    The returned dict is a new object; reddit_content is not mutated.
    """
    thread_post = reddit_content.get("thread_post", "")
    thread_title = reddit_content.get("thread_title", "")
    thread_id = reddit_content.get("thread_id", "")

    part: Story_Part = {
        # Copy all parent keys into the part (produces a new dict).
        **{k: v for k, v in reddit_content.items()},
        # Splitter-specific fields.
        "part_number": 1,
        "total_parts": 1,
        "part_thread_id": thread_id,
        "part_raw_post": thread_post,
        "part_thread_title": thread_title,
        "part_thread_post": thread_post,
        # Substitute per-part values for the consumer-stage keys.
        "thread_id": thread_id,
        "thread_title": thread_title,
        "thread_post": thread_post,
    }
    return part


# ---------------------------------------------------------------------------
# Iterative greedy split
# ---------------------------------------------------------------------------


def _split_iterative(
    post: str,
    config: SplittingConfig,
    thread_id: str,
) -> list[tuple[int, int, str]]:
    """Greedy split of *post* into (start, end, boundary_type) tuples.

    Each tuple names a contiguous slice of *post* for one part.  The last
    element always has boundary_type == "end".

    Raises StorySplitError when:
    - no boundary exists in the search window for the current part
      (reason="no_valid_boundary")
    - the resulting number of parts exceeds config.max_parts
      (reason="too_many_parts")
    """
    parts: list[tuple[int, int, str]] = []
    cursor = 0

    while cursor < len(post):
        remaining_len = len(post) - cursor

        # If the remaining text fits within the hard ceiling, it becomes the
        # final part without needing a boundary search.
        if remaining_len <= config.hard_max_length:
            parts.append((cursor, len(post), "end"))
            break

        # Search window: [cursor + min_part_length, cursor + hard_max_length]
        # (inclusive on both ends, so stop = cursor + hard_max_length + 1).
        search_start = cursor + config.min_part_length
        search_stop = cursor + config.hard_max_length + 1  # exclusive
        target = cursor + config.soft_max_length

        boundary_offset, boundary_type = _find_boundary(
            text=post,
            start=search_start,
            stop=search_stop,
            target=target,
        )

        if boundary_offset is None:
            raise StorySplitError(
                thread_id=thread_id,
                reason="no_valid_boundary",
                detail=(
                    f"No paragraph/sentence/line/whitespace boundary in "
                    f"[{search_start}, {cursor + config.hard_max_length}] "
                    f"(cursor={cursor})"
                ),
            )

        parts.append((cursor, boundary_offset, boundary_type))
        cursor = _advance_past_whitespace(post, boundary_offset, boundary_type)

    # Enforce max_parts ceiling (Req 3.4).
    if len(parts) > config.max_parts:
        raise StorySplitError(
            thread_id=thread_id,
            reason="too_many_parts",
            detail=(
                f"Story would require {len(parts)} parts; "
                f"max_parts = {config.max_parts}"
            ),
        )

    return parts


# ---------------------------------------------------------------------------
# Tail redistribution
# ---------------------------------------------------------------------------


def _redistribute_tail(
    post: str,
    parts: list[tuple[int, int, str]],
    config: SplittingConfig,
    thread_id: str,
) -> list[tuple[int, int, str]]:
    """Ensure the final part meets min_part_length (Req 5.2, 5.3).

    Strategy:
    1. Walk the previous part's boundary earlier through its search window
       until the tail is long enough (Req 5.2).
    2. If no earlier boundary exists, merge the tail into the previous part
       provided the merged length <= hard_max_length (Req 5.3).
    3. If the merge would exceed hard_max_length, raise StorySplitError
       (reason="tail_redistribution_failed").
    """
    # Make a mutable copy so we don't mutate the caller's list.
    parts = list(parts)

    while len(parts) >= 2 and (len(post) - parts[-1][0]) < config.min_part_length:
        prev_start, prev_end, _prev_kind = parts[-2]

        # Search for an earlier boundary strictly below prev_end.
        # Window: [prev_start + min_part_length, prev_end)
        # Target: prev_end - 1  (closest to current boundary from below)
        search_start = prev_start + config.min_part_length
        search_stop = prev_end  # exclusive — strictly below current boundary

        if search_start >= search_stop:
            # No room to move the boundary earlier.
            break

        new_boundary, new_kind = _find_boundary(
            text=post,
            start=search_start,
            stop=search_stop,
            target=prev_end - 1,
        )

        if new_boundary is None:
            # No earlier valid boundary; fall through to merge.
            break

        # Move the previous part's end earlier and update the tail's start.
        new_tail_start = _advance_past_whitespace(post, new_boundary, new_kind)
        parts[-2] = (prev_start, new_boundary, new_kind)
        parts[-1] = (new_tail_start, len(post), "end")

    # If the tail is still too short, attempt a merge (Req 5.3).
    if len(parts) >= 2 and (len(post) - parts[-1][0]) < config.min_part_length:
        prev_start, _prev_end, _prev_kind = parts[-2]
        merged_len = len(post) - prev_start

        if merged_len <= config.hard_max_length:
            # Merge: drop the last two entries and replace with one spanning both.
            parts = parts[:-2] + [(prev_start, len(post), "end")]
        else:
            raise StorySplitError(
                thread_id=thread_id,
                reason="tail_redistribution_failed",
                detail=(
                    f"Tail merge would exceed hard_max_length "
                    f"({merged_len} > {config.hard_max_length})"
                ),
            )

    return parts


# ---------------------------------------------------------------------------
# Materialise Story_Part dicts
# ---------------------------------------------------------------------------


def _materialize(
    reddit_content: dict,
    parts: list[tuple[int, int, str]],
    config: SplittingConfig,
) -> Split_Plan:
    """Build the final list of Story_Part dicts from the raw split offsets.

    Copies all parent keys from reddit_content into each part (producing a
    new dict per part), then overlays the splitter-specific fields and the
    per-part substitutions for thread_id / thread_title / thread_post.

    Template decoration is applied only when total_parts >= 2 (Req 6.6).
    """
    n = len(parts)
    thread_id = reddit_content.get("thread_id", "")
    post = reddit_content.get("thread_post", "")

    plan: Split_Plan = []

    for i, (start, end, _kind) in enumerate(parts):
        part_number = i + 1
        raw = post[start:end]

        # Derive the per-part thread_id (Req 7.1, 7.6).
        if n == 1:
            part_thread_id = thread_id
        else:
            part_thread_id = f"{thread_id}-p{part_number}"

        # Apply template decoration only for multi-part plans (Req 6.6).
        if n == 1:
            decorated_title = reddit_content.get("thread_title", "")
            decorated_body = raw
        else:
            decorated_title = _decorate_title(reddit_content, part_number, n, config)
            decorated_body = _decorate_body(raw, part_number, n, config)

        # Build the Story_Part: start with all parent keys, then overlay
        # per-part values.  We explicitly exclude thread_post and thread_title
        # from the parent copy because we set them to the per-part values below.
        part: Story_Part = {
            **{
                k: v
                for k, v in reddit_content.items()
                if k not in ("thread_post", "thread_title", "thread_id")
            },
            # Splitter-specific fields.
            "part_number": part_number,
            "total_parts": n,
            "part_thread_id": part_thread_id,
            "part_raw_post": raw,
            "part_thread_title": decorated_title,
            "part_thread_post": decorated_body,
            # Consumer-stage keys substituted with per-part values (Req 7.2).
            "thread_id": part_thread_id,
            "thread_title": decorated_title,
            "thread_post": decorated_body,
        }
        plan.append(part)

    return plan


# ---------------------------------------------------------------------------
# Public class
# ---------------------------------------------------------------------------


class Story_Splitter:
    """Converts a translated Reddit_Content into a Split_Plan.

    Usage::

        config = SplittingConfig.from_settings(settings.config, subreddit_name=...)
        splitter = Story_Splitter(config)
        split_plan = splitter.split(reddit_content)

    The splitter is stateless beyond its config; the same instance may be
    reused across multiple calls.
    """

    def __init__(self, config: SplittingConfig) -> None:
        self._config = config

    def split(self, reddit_content: dict) -> Split_Plan:
        """Split *reddit_content* into a Split_Plan of one or more Story_Parts.

        Parameters
        ----------
        reddit_content:
            The post-translation Reddit_Content dict.  Must contain at least
            ``thread_post`` (str), ``thread_title`` (str), and ``thread_id``
            (str).  This dict is never mutated.

        Returns
        -------
        Split_Plan
            An ordered list of Story_Part dicts, length >= 1.

        Raises
        ------
        StorySplitError
            When a valid Split_Plan cannot be produced (no boundary, too many
            parts, or tail redistribution failure).
        """
        config = self._config
        thread_id: str = reddit_content.get("thread_id", "")
        thread_post: str = reddit_content.get("thread_post", "")

        # ── Req 12.1: entry observability ────────────────────────────────────
        _log(
            f"split start | thread_id={thread_id!r} "
            f"mode={config.mode!r} "
            f"soft_max={config.soft_max_length} "
            f"hard_max={config.hard_max_length} "
            f"min_part={config.min_part_length} "
            f"max_parts={config.max_parts} "
            f"subreddit={config.subreddit_name!r}"
        )

        # ── Step 1: single-part short-circuits ───────────────────────────────

        # Req 1.7: storymode=False → always single-part.
        # The key is absent → treat as True (storymode assumed for splitter).
        storymode = reddit_content.get("storymode", True)
        if storymode is False or storymode == 0:
            _log(f"short-circuit: storymode=False → single part")
            return [_single_part(reddit_content)]

        # Req 2.4: cutoff mode → always single-part at splitter time.
        if config.mode == "cutoff":
            _log(f"short-circuit: mode=cutoff → single part")
            return [_single_part(reddit_content)]

        # Req 3.3, 9.6: post fits within hard ceiling → single part.
        if len(thread_post) <= config.hard_max_length:
            _log(
                f"short-circuit: len(thread_post)={len(thread_post)} "
                f"<= hard_max={config.hard_max_length} → single part"
            )
            return [_single_part(reddit_content)]

        # ── Step 2: iterative greedy split ───────────────────────────────────
        try:
            raw_parts = _split_iterative(thread_post, config, thread_id)
        except StorySplitError as exc:
            # Req 12.3: log on StorySplitError.
            _log(
                f"StorySplitError | thread_id={thread_id!r} "
                f"reason={exc.reason!r} "
                f"len(thread_post)={len(thread_post)}",
                style="red",
            )
            raise

        # ── Step 3: tail redistribution ──────────────────────────────────────
        try:
            raw_parts = _redistribute_tail(thread_post, raw_parts, config, thread_id)
        except StorySplitError as exc:
            # Req 12.3: log on StorySplitError.
            _log(
                f"StorySplitError | thread_id={thread_id!r} "
                f"reason={exc.reason!r} "
                f"len(thread_post)={len(thread_post)}",
                style="red",
            )
            raise

        # ── Step 4: materialise Story_Part dicts ─────────────────────────────
        plan = _materialize(reddit_content, raw_parts, config)

        # ── Req 12.2: post-split observability ───────────────────────────────
        part_lengths = [len(p["part_raw_post"]) for p in plan]
        boundary_types = [kind for (_s, _e, kind) in raw_parts]
        _log(
            f"split complete | parts={len(plan)} "
            f"lengths={part_lengths} "
            f"boundaries={boundary_types}"
        )

        return plan
