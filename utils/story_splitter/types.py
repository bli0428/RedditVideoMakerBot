from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Mapping, TypedDict

SplitMode = Literal["cutoff", "split"]


@dataclass(frozen=True)
class TemplateConfig:
    """Configuration for per-part title and body decoration templates.

    Each field is a format string supporting the placeholders:
    {title}, {part_number}, {total_parts}, {next_part_number}, {prev_part_number}.
    """

    title_first_part: str
    title_other_part: str
    body_prefix_other_part: str
    body_suffix_non_final_part: str


@dataclass(frozen=True)
class SplittingConfig:
    """Resolved, validated configuration for the Story_Splitter.

    All fields are immutable after construction. Validation and clamping
    are performed by ``SplittingConfig.from_settings`` in ``config.py``.
    """

    mode: SplitMode
    soft_max_length: int
    single_part_tolerance: float  # >= 1.0 (clamped by from_settings)
    min_part_length: int  # >= 1 (clamped by from_settings)
    max_parts: int  # >= 1 (clamped by from_settings)
    templates: TemplateConfig
    subreddit_name: str  # resolved name, lowercased; empty string allowed

    @property
    def hard_max_length(self) -> int:
        """Absolute character ceiling for a single part.

        Computed as ``int(soft_max_length * single_part_tolerance)``.
        Because ``single_part_tolerance >= 1.0``, this is always
        ``>= soft_max_length``.
        """
        return int(self.soft_max_length * self.single_part_tolerance)

    @classmethod
    def from_settings(
        cls,
        settings_config: Mapping,
        *,
        subreddit_name: str = "",
    ) -> "SplittingConfig":
        """Parse and validate ``settings_config``, returning a frozen
        ``SplittingConfig``.

        Delegates to ``utils.story_splitter.config.from_settings`` so that
        all resolution logic lives in one place.  The lazy import avoids a
        circular dependency between ``types.py`` and ``config.py``.

        Parameters
        ----------
        settings_config:
            The top-level mapping returned by ``utils.settings.config``.
        subreddit_name:
            Lowercased subreddit name for per-subreddit override lookup.
        """
        # Lazy import to avoid circular dependency (config.py imports types.py).
        from utils.story_splitter.config import from_settings as _from_settings

        return _from_settings(settings_config, subreddit_name=subreddit_name)


class Story_Part(TypedDict, total=False):
    """A single part of a split story, as produced by ``Story_Splitter.split``.

    All keys are optional at the type level (``total=False``) because the
    splitter builds these dicts incrementally, but in practice every
    ``Story_Part`` returned by the splitter will have all keys populated.

    Splitter-specific fields (always present in a completed Story_Part):
        part_number       -- 1-indexed position of this part in the plan.
        total_parts       -- total number of parts in the plan (>= 1).
        part_thread_id    -- "{thread_id}-p{part_number}" when total_parts >= 2,
                             else the bare thread_id (no suffix).
        part_raw_post     -- verbatim slice of the input thread_post with no
                             template decoration applied.
        part_thread_title -- decorated title (mirror of thread_title).
        part_thread_post  -- decorated body (mirror of thread_post).

    Reddit_Content keys substituted with per-part values (so consumer stages
    that read these keys work unchanged):
        thread_id    -- equals part_thread_id.
        thread_title -- equals part_thread_title.
        thread_post  -- equals part_thread_post (decorated body).
    """

    # --- Splitter-specific fields (always present) ---
    part_number: int
    total_parts: int
    part_thread_id: str
    part_raw_post: str
    part_thread_title: str
    part_thread_post: str

    # --- Reddit_Content keys substituted with per-part values ---
    thread_id: str
    thread_title: str
    thread_post: str


# A Split_Plan is an ordered list of Story_Part dicts, one per part.
# The list always has length >= 1; a single-part plan is the identity case.
Split_Plan = list[Story_Part]
