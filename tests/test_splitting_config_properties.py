"""Property-based tests for SplittingConfig.

Tests in this module cover the arithmetic and resolver properties of
SplittingConfig, as specified in the design's "Correctness Properties" section.

Requirements: 3.2, 2.1, 2.2, 2.3, 2.8, 3.6, 10.5, 10.6
"""
from __future__ import annotations

import math
from typing import Any, Dict, Optional

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from tests._strategies import degenerate_config, splitting_config
from utils.story_splitter.types import SplittingConfig

_VALID_MODES = frozenset({"cutoff", "split"})

# ---------------------------------------------------------------------------
# Property 11: Hard_Max_Length arithmetic
# ---------------------------------------------------------------------------

@given(cfg_dict=splitting_config())
@settings(max_examples=100)
def test_hard_max_length_arithmetic(cfg_dict):
    """Property 11: Hard_Max_Length arithmetic.

    For all (soft_max_length, single_part_tolerance) drawn from splitting_config(),
    SplittingConfig.hard_max_length must equal math.floor(soft_max_length * single_part_tolerance).

    **Validates: Requirements 3.2**
    """
    config = SplittingConfig.from_settings(cfg_dict)

    expected = math.floor(config.soft_max_length * config.single_part_tolerance)
    assert config.hard_max_length == expected, (
        f"hard_max_length={config.hard_max_length!r} != "
        f"math.floor({config.soft_max_length} * {config.single_part_tolerance}) "
        f"= {expected}"
    )


# ---------------------------------------------------------------------------
# Helpers for Property 14 test
# ---------------------------------------------------------------------------

def _build_settings_dict(
    default_mode: Any,
    override_subreddit: Optional[str],
    override_mode: Any,
    splitting_soft_max: Optional[int],
    storymode_max_length: Optional[int],
    single_part_tolerance: float,
) -> Dict[str, Any]:
    """Assemble a settings_config dict from the given parameters."""
    splitting: Dict[str, Any] = {
        "default_mode": default_mode,
        "single_part_tolerance": single_part_tolerance,
    }
    if splitting_soft_max is not None:
        splitting["soft_max_length"] = splitting_soft_max

    if override_subreddit is not None:
        splitting["subreddits"] = {
            override_subreddit: {"mode": override_mode}
        }

    cfg: Dict[str, Any] = {"splitting": splitting}

    if storymode_max_length is not None:
        cfg["settings"] = {"storymode_max_length": storymode_max_length}

    return cfg


# Strategy for default_mode: mix valid and invalid values
_valid_mode_st = st.sampled_from(["cutoff", "split"])
_invalid_mode_st = st.text(min_size=1, max_size=20).filter(
    lambda s: s not in _VALID_MODES
)
_any_mode_st = st.one_of(_valid_mode_st, _invalid_mode_st)

# Strategy for subreddit names (lowercase alphanumeric)
_subreddit_name_st = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789_",
    min_size=1,
    max_size=21,
)

# Strategy for soft_max_length: present (valid or invalid) or absent
_soft_max_present_st = st.one_of(
    st.integers(min_value=-100, max_value=0),   # degenerate: < 1
    st.integers(min_value=1, max_value=5000),   # valid
)

# Strategy for storymode_max_length: present (valid or invalid) or absent
_storymode_max_present_st = st.one_of(
    st.integers(min_value=-100, max_value=0),   # degenerate: < 1
    st.integers(min_value=1, max_value=5000),   # valid
)

# Strategy for single_part_tolerance: below 1.0 or valid
_tolerance_st = st.one_of(
    st.floats(min_value=-2.0, max_value=0.9999, allow_nan=False, allow_infinity=False),
    st.floats(min_value=1.0, max_value=3.0, allow_nan=False, allow_infinity=False),
)


# ---------------------------------------------------------------------------
# Property 14: Config resolver — per-subreddit override and fallback
# ---------------------------------------------------------------------------

@given(
    default_mode=_any_mode_st,
    override_subreddit=st.one_of(st.none(), _subreddit_name_st),
    override_mode=_any_mode_st,
    splitting_soft_max=st.one_of(st.none(), _soft_max_present_st),
    storymode_max_length=st.one_of(st.none(), _storymode_max_present_st),
    single_part_tolerance=_tolerance_st,
)
@settings(max_examples=100)
def test_config_resolver_override_and_fallback(
    default_mode,
    override_subreddit,
    override_mode,
    splitting_soft_max,
    storymode_max_length,
    single_part_tolerance,
):
    """Property 14: Config resolver — per-subreddit override and fallback.

    Drives SplittingConfig.from_settings with synthesized
    (default_mode, override_subreddit, override_mode, splitting_soft_max,
    storymode_max_length, single_part_tolerance) tuples and asserts:

    1. Per-subreddit mode wins when valid (Req 2.1, 2.2, 2.3).
    2. Invalid default_mode falls back to "cutoff" (Req 2.8).
    3. soft_max_length resolution order: [splitting] → [settings].storymode_max_length → 1000
       (Req 10.5).
    4. soft_max_length < 1 falls back to 1000 (Req 10.6).
    5. single_part_tolerance < 1.0 clamps to 1.0 (Req 3.6).

    **Validates: Requirements 2.1, 2.2, 2.3, 2.8, 3.6, 10.5, 10.6**
    """
    settings_dict = _build_settings_dict(
        default_mode=default_mode,
        override_subreddit=override_subreddit,
        override_mode=override_mode,
        splitting_soft_max=splitting_soft_max,
        storymode_max_length=storymode_max_length,
        single_part_tolerance=single_part_tolerance,
    )

    # Determine the subreddit_name to pass (use the override key if present)
    subreddit_name = override_subreddit if override_subreddit is not None else ""

    # from_settings must never raise (Req 2.8, 3.6, 10.6)
    config = SplittingConfig.from_settings(settings_dict, subreddit_name=subreddit_name)

    # ── Assertion 1: resolved mode is always a valid SplitMode ───────────────
    assert config.mode in _VALID_MODES, (
        f"config.mode={config.mode!r} is not a valid SplitMode"
    )

    # ── Assertion 2: per-subreddit mode wins when valid (Req 2.1, 2.2) ───────
    if override_subreddit is not None and override_mode in _VALID_MODES:
        # A valid per-subreddit override must be respected regardless of
        # default_mode validity.
        assert config.mode == override_mode, (
            f"Per-subreddit override mode={override_mode!r} was not applied; "
            f"got config.mode={config.mode!r}"
        )

    # ── Assertion 3: invalid default_mode falls back to "cutoff" (Req 2.8) ───
    # When there is no per-subreddit override at all, the resolved mode must
    # come from default_mode (if valid) or fall back to "cutoff".
    # When there IS a per-subreddit override but its mode is invalid, the
    # per-subreddit invalid mode also falls back to "cutoff" (same rule, Req 2.8).
    if override_subreddit is None:
        # No per-subreddit override: mode comes from default_mode
        if default_mode in _VALID_MODES:
            assert config.mode == default_mode, (
                f"Valid default_mode={default_mode!r} was not used; "
                f"got config.mode={config.mode!r}"
            )
        else:
            # Invalid default_mode must fall back to "cutoff"
            assert config.mode == "cutoff", (
                f"Invalid default_mode={default_mode!r} should fall back to 'cutoff'; "
                f"got config.mode={config.mode!r}"
            )
    elif override_mode not in _VALID_MODES:
        # Per-subreddit override exists but has an invalid mode: falls back to "cutoff"
        # (same "log + degrade" rule as invalid default_mode, Req 2.8)
        assert config.mode == "cutoff", (
            f"Invalid per-subreddit override_mode={override_mode!r} should fall back "
            f"to 'cutoff'; got config.mode={config.mode!r}"
        )

    # ── Assertion 4: single_part_tolerance clamped to >= 1.0 (Req 3.6) ──────
    assert config.single_part_tolerance >= 1.0, (
        f"single_part_tolerance={config.single_part_tolerance!r} is < 1.0 "
        f"(input was {single_part_tolerance!r}); should have been clamped to 1.0"
    )

    # ── Assertion 5: soft_max_length resolution order and floor (Req 10.5, 10.6) ─
    # Determine the expected soft_max_length according to the resolution rules:
    #   Tier 1: [splitting] soft_max_length (if present and >= 1)
    #   Tier 2: [settings] storymode_max_length (only when [splitting] soft_max_length
    #            is ABSENT, per Req 10.5)
    #   Tier 3: 1000 (hard-coded default)
    #
    # Note: Req 10.6 says when the resolved value is < 1, fall back to 1000.
    # Req 10.5 says tier 2 applies only when [splitting] soft_max_length is absent.
    # So an invalid (< 1) [splitting] soft_max_length falls back to 1000 directly,
    # NOT to storymode_max_length.
    expected_soft_max: int
    if splitting_soft_max is not None:
        if splitting_soft_max >= 1:
            # Tier 1: valid [splitting] soft_max_length
            expected_soft_max = splitting_soft_max
        else:
            # Tier 1 present but invalid (< 1): Req 10.6 says fall back to 1000
            # (tier 2 only applies when [splitting] soft_max_length is absent)
            expected_soft_max = 1000
    elif storymode_max_length is not None:
        # Tier 2: [splitting] soft_max_length absent, use storymode_max_length
        if storymode_max_length >= 1:
            expected_soft_max = storymode_max_length
        else:
            # storymode_max_length present but < 1: Req 10.6 falls back to 1000
            expected_soft_max = 1000
    else:
        # Tier 3: both absent
        expected_soft_max = 1000

    assert config.soft_max_length == expected_soft_max, (
        f"soft_max_length={config.soft_max_length!r} != expected {expected_soft_max!r} "
        f"(splitting_soft_max={splitting_soft_max!r}, "
        f"storymode_max_length={storymode_max_length!r})"
    )

    # ── Assertion 6: soft_max_length is always >= 1 (Req 10.6) ───────────────
    assert config.soft_max_length >= 1, (
        f"soft_max_length={config.soft_max_length!r} is < 1 after resolution"
    )
