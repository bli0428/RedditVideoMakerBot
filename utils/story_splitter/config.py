"""SplittingConfig resolver: reads [splitting] from config.toml and returns a
validated, frozen SplittingConfig.

Resolution order (Req 10.5):
  1. [splitting] soft_max_length
  2. [settings] storymode_max_length  (when [splitting] soft_max_length is absent)
  3. Hard-coded default 1000          (when both are absent)

Per-subreddit overrides are read from [splitting.subreddits.<lower(name)>]
(Req 2.1, 2.2, 2.3).

Validation follows the "log + degrade + continue" pattern from
utils/translation/config.py — this function never raises (Req 2.8, 3.6,
10.6).

Requirements: 2.1, 2.2, 2.3, 2.8, 3.1, 3.2, 3.6, 10.1, 10.2, 10.3, 10.5, 10.6
"""
from __future__ import annotations

from typing import Mapping

from utils.story_splitter.types import SplitMode, SplittingConfig, TemplateConfig

# ── Constants ────────────────────────────────────────────────────────────────

_VALID_MODES: frozenset[str] = frozenset({"cutoff", "split"})

_DEFAULT_MODE: SplitMode = "cutoff"
_DEFAULT_SOFT_MAX_LENGTH: int = 1000
_DEFAULT_SINGLE_PART_TOLERANCE: float = 1.5
_DEFAULT_MIN_PART_LENGTH: int = 300
_DEFAULT_MAX_PARTS: int = 5

# Req 6.1 template defaults
_DEFAULT_TITLE_FIRST_PART: str = "{title} (Part {part_number}/{total_parts})"
_DEFAULT_TITLE_OTHER_PART: str = "{title} (Part {part_number}/{total_parts})"
_DEFAULT_BODY_PREFIX_OTHER_PART: str = "Part {part_number}: "
_DEFAULT_BODY_SUFFIX_NON_FINAL_PART: str = "\n\nFollow for part {next_part_number}!"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _warn(msg: str) -> None:
    """Emit a yellow warning via the project console helper."""
    from utils.console import print_substep  # lazy import to avoid circular deps

    print_substep(f"[warn] {msg}", style="yellow")


def _error(msg: str) -> None:
    """Emit a red error via the project console helper."""
    from utils.console import print_substep  # lazy import to avoid circular deps

    print_substep(f"[error] {msg}", style="red")


def _resolve_mode(raw: object, context: str) -> SplitMode:
    """Validate *raw* as a SplitMode; fall back to 'cutoff' on error (Req 2.8)."""
    if raw in _VALID_MODES:
        return raw  # type: ignore[return-value]
    _error(
        f"Invalid {context} {raw!r}; supported modes: {sorted(_VALID_MODES)}. "
        f"Falling back to 'cutoff' for this run."
    )
    return "cutoff"


def _resolve_soft_max_length(
    splitting_section: Mapping,
    settings_section: Mapping,
) -> int:
    """Resolve soft_max_length with the three-tier fallback (Req 10.5, 10.6).

    Priority:
      1. [splitting] soft_max_length
      2. [settings] storymode_max_length
      3. _DEFAULT_SOFT_MAX_LENGTH (1000)
    """
    # Tier 1: explicit [splitting] soft_max_length
    if "soft_max_length" in splitting_section:
        raw = splitting_section["soft_max_length"]
        try:
            value = int(raw)
        except (TypeError, ValueError):
            _warn(
                f"[splitting] soft_max_length {raw!r} is not an integer; "
                f"falling back to default {_DEFAULT_SOFT_MAX_LENGTH}."
            )
            return _DEFAULT_SOFT_MAX_LENGTH
        if value < 1:
            _warn(
                f"[splitting] soft_max_length resolved to {value}, which is < 1; "
                f"falling back to default {_DEFAULT_SOFT_MAX_LENGTH} (Req 10.6)."
            )
            return _DEFAULT_SOFT_MAX_LENGTH
        return value

    # Tier 2: [settings] storymode_max_length
    if "storymode_max_length" in settings_section:
        raw = settings_section["storymode_max_length"]
        try:
            value = int(raw)
        except (TypeError, ValueError):
            _warn(
                f"[settings] storymode_max_length {raw!r} is not an integer; "
                f"falling back to default {_DEFAULT_SOFT_MAX_LENGTH}."
            )
            return _DEFAULT_SOFT_MAX_LENGTH
        if value < 1:
            _warn(
                f"[settings] storymode_max_length resolved to {value}, which is < 1; "
                f"falling back to default {_DEFAULT_SOFT_MAX_LENGTH} (Req 10.6)."
            )
            return _DEFAULT_SOFT_MAX_LENGTH
        return value

    # Tier 3: hard-coded default
    return _DEFAULT_SOFT_MAX_LENGTH


def _resolve_single_part_tolerance(splitting_section: Mapping) -> float:
    """Read single_part_tolerance; clamp to 1.0 if < 1.0 (Req 3.6)."""
    raw = splitting_section.get("single_part_tolerance", _DEFAULT_SINGLE_PART_TOLERANCE)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        _warn(
            f"[splitting] single_part_tolerance {raw!r} is not a float; "
            f"using default {_DEFAULT_SINGLE_PART_TOLERANCE}."
        )
        return _DEFAULT_SINGLE_PART_TOLERANCE
    if value < 1.0:
        _warn(
            f"[splitting] single_part_tolerance {value} is < 1.0; "
            f"clamping to 1.0 (Req 3.6)."
        )
        return 1.0
    return value


def _resolve_min_part_length(section: Mapping) -> int:
    """Read min_part_length; clamp to 1 if < 1."""
    raw = section.get("min_part_length", _DEFAULT_MIN_PART_LENGTH)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        _warn(
            f"[splitting] min_part_length {raw!r} is not an integer; "
            f"using default {_DEFAULT_MIN_PART_LENGTH}."
        )
        return _DEFAULT_MIN_PART_LENGTH
    if value < 1:
        _warn(
            f"[splitting] min_part_length {value} is < 1; clamping to 1."
        )
        return 1
    return value


def _resolve_max_parts(section: Mapping) -> int:
    """Read max_parts; clamp to 1 if < 1."""
    raw = section.get("max_parts", _DEFAULT_MAX_PARTS)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        _warn(
            f"[splitting] max_parts {raw!r} is not an integer; "
            f"using default {_DEFAULT_MAX_PARTS}."
        )
        return _DEFAULT_MAX_PARTS
    if value < 1:
        _warn(
            f"[splitting] max_parts {value} is < 1; clamping to 1."
        )
        return 1
    return value


def _resolve_templates(templates_section: Mapping) -> TemplateConfig:
    """Read [splitting.templates] with Req 6.1 defaults."""
    return TemplateConfig(
        title_first_part=str(
            templates_section.get("title_first_part", _DEFAULT_TITLE_FIRST_PART)
        ),
        title_other_part=str(
            templates_section.get("title_other_part", _DEFAULT_TITLE_OTHER_PART)
        ),
        body_prefix_other_part=str(
            templates_section.get("body_prefix_other_part", _DEFAULT_BODY_PREFIX_OTHER_PART)
        ),
        body_suffix_non_final_part=str(
            templates_section.get(
                "body_suffix_non_final_part", _DEFAULT_BODY_SUFFIX_NON_FINAL_PART
            )
        ),
    )


# ── Public factory ────────────────────────────────────────────────────────────

def from_settings(
    settings_config: Mapping,
    *,
    subreddit_name: str = "",
) -> SplittingConfig:
    """Build a validated, frozen SplittingConfig from the loaded config.toml.

    Parameters
    ----------
    settings_config:
        The top-level mapping returned by ``utils.settings.config`` (i.e. the
        full parsed TOML dict).
    subreddit_name:
        The lowercased subreddit name for the current post.  Used to look up
        per-subreddit overrides in ``[splitting.subreddits.<name>]``.  An
        empty string means "no subreddit known; use global defaults".

    Returns
    -------
    SplittingConfig
        A frozen dataclass with all fields validated and clamped.  Never
        raises — invalid values are logged and replaced with safe defaults.
    """
    splitting_section: Mapping = settings_config.get("splitting", {}) or {}
    settings_section: Mapping = settings_config.get("settings", {}) or {}

    # ── Step 1: global defaults ───────────────────────────────────────────────
    raw_default_mode = splitting_section.get("default_mode", _DEFAULT_MODE)
    default_mode: SplitMode = _resolve_mode(raw_default_mode, "[splitting] default_mode")

    soft_max_length = _resolve_soft_max_length(splitting_section, settings_section)
    single_part_tolerance = _resolve_single_part_tolerance(splitting_section)
    min_part_length = _resolve_min_part_length(splitting_section)
    max_parts = _resolve_max_parts(splitting_section)

    # Resolved mode starts as the global default; may be overridden below.
    resolved_mode: SplitMode = default_mode

    # ── Step 2: per-subreddit overrides (Req 2.1, 2.2, 2.3) ─────────────────
    normalized_name = subreddit_name.lower().strip() if subreddit_name else ""
    if normalized_name:
        subreddits_table: Mapping = splitting_section.get("subreddits", {}) or {}
        # Keys in the TOML table are already lowercased by convention, but we
        # normalise both sides for robustness (Req 2.1).
        override_table: Mapping | None = None
        for key, val in subreddits_table.items():
            if key.lower() == normalized_name:
                override_table = val if isinstance(val, Mapping) else {}
                break

        if override_table is not None:
            # mode override
            if "mode" in override_table:
                resolved_mode = _resolve_mode(
                    override_table["mode"],
                    f"[splitting.subreddits.{normalized_name}] mode",
                )
            # numeric overrides (each field is optional in the per-subreddit table)
            if "soft_max_length" in override_table:
                try:
                    v = int(override_table["soft_max_length"])
                    if v < 1:
                        _warn(
                            f"[splitting.subreddits.{normalized_name}] soft_max_length "
                            f"{v} is < 1; falling back to global value {soft_max_length}."
                        )
                    else:
                        soft_max_length = v
                except (TypeError, ValueError):
                    _warn(
                        f"[splitting.subreddits.{normalized_name}] soft_max_length "
                        f"{override_table['soft_max_length']!r} is not an integer; "
                        f"using global value {soft_max_length}."
                    )
            if "single_part_tolerance" in override_table:
                try:
                    v_f = float(override_table["single_part_tolerance"])
                    if v_f < 1.0:
                        _warn(
                            f"[splitting.subreddits.{normalized_name}] "
                            f"single_part_tolerance {v_f} is < 1.0; clamping to 1.0."
                        )
                        single_part_tolerance = 1.0
                    else:
                        single_part_tolerance = v_f
                except (TypeError, ValueError):
                    _warn(
                        f"[splitting.subreddits.{normalized_name}] "
                        f"single_part_tolerance "
                        f"{override_table['single_part_tolerance']!r} is not a float; "
                        f"using global value {single_part_tolerance}."
                    )
            if "min_part_length" in override_table:
                try:
                    v = int(override_table["min_part_length"])
                    if v < 1:
                        _warn(
                            f"[splitting.subreddits.{normalized_name}] min_part_length "
                            f"{v} is < 1; clamping to 1."
                        )
                        min_part_length = 1
                    else:
                        min_part_length = v
                except (TypeError, ValueError):
                    _warn(
                        f"[splitting.subreddits.{normalized_name}] min_part_length "
                        f"{override_table['min_part_length']!r} is not an integer; "
                        f"using global value {min_part_length}."
                    )
            if "max_parts" in override_table:
                try:
                    v = int(override_table["max_parts"])
                    if v < 1:
                        _warn(
                            f"[splitting.subreddits.{normalized_name}] max_parts "
                            f"{v} is < 1; clamping to 1."
                        )
                        max_parts = 1
                    else:
                        max_parts = v
                except (TypeError, ValueError):
                    _warn(
                        f"[splitting.subreddits.{normalized_name}] max_parts "
                        f"{override_table['max_parts']!r} is not an integer; "
                        f"using global value {max_parts}."
                    )

    # ── Step 3: templates (Req 6.1) ───────────────────────────────────────────
    templates_section: Mapping = splitting_section.get("templates", {}) or {}
    templates = _resolve_templates(templates_section)

    # ── Step 4: assemble and return ───────────────────────────────────────────
    return SplittingConfig(
        mode=resolved_mode,
        soft_max_length=soft_max_length,
        single_part_tolerance=single_part_tolerance,
        min_part_length=min_part_length,
        max_parts=max_parts,
        templates=templates,
        subreddit_name=normalized_name,
    )
