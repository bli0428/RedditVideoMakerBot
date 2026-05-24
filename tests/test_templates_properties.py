"""Property-based tests for template substitution and per-part decoration.

Tests in this module cover the title/body decoration properties of
``_decorate_title``, ``_decorate_body``, and ``_substitute`` as specified in
the design's "Correctness Properties" section.

Requirements: 6.2, 6.3, 6.4, 6.5, 6.7, 9.10
"""
from __future__ import annotations

import re
import warnings
from io import StringIO
from typing import Any, Dict
from unittest.mock import patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from tests._strategies import (
    reddit_content,
    splitting_config,
    template_string,
)
from utils.story_splitter.templates import _decorate_body, _decorate_title, _substitute
from utils.story_splitter.types import SplittingConfig, TemplateConfig

# ---------------------------------------------------------------------------
# Helpers: strategies for multi-part Story_Part inputs
# ---------------------------------------------------------------------------

# Known placeholder names (Requirement 6.5)
_KNOWN_PLACEHOLDERS = [
    "title",
    "part_number",
    "total_parts",
    "next_part_number",
    "prev_part_number",
]

# Unknown placeholder names used in _strategies.py
_UNKNOWN_PLACEHOLDERS = [
    "partname",
    "author",
    "subreddit",
    "date",
    "url",
    "foo",
    "bar",
    "baz",
]


@st.composite
def multi_part_inputs(draw) -> Dict[str, Any]:
    """Generate inputs for a multi-part Story_Part scenario.

    Returns a dict with:
    - ``content``: a Reddit_Content dict
    - ``part_number``: 1-indexed part number (1 <= part_number <= total_parts)
    - ``total_parts``: total number of parts (>= 2)
    - ``config``: a SplittingConfig
    - ``raw_post``: a raw post body string
    """
    cfg_dict = draw(splitting_config())
    config = SplittingConfig.from_settings(cfg_dict)

    total_parts = draw(st.integers(min_value=2, max_value=10))
    part_number = draw(st.integers(min_value=1, max_value=total_parts))

    content = draw(reddit_content())

    raw_post = draw(
        st.text(
            alphabet=st.characters(blacklist_categories=("Cs",), blacklist_characters="\x00"),
            min_size=1,
            max_size=500,
        )
    )

    return {
        "content": content,
        "part_number": part_number,
        "total_parts": total_parts,
        "config": config,
        "raw_post": raw_post,
    }


@st.composite
def template_config_with_unknown(draw) -> TemplateConfig:
    """Generate a TemplateConfig where at least one field contains an unknown placeholder."""
    # Pick a field to inject an unknown placeholder into
    unknown = draw(st.sampled_from(["{" + p + "}" for p in _UNKNOWN_PLACEHOLDERS]))
    plain = draw(
        st.text(
            alphabet=st.characters(blacklist_characters="{}", blacklist_categories=("Cs",)),
            min_size=0,
            max_size=20,
        )
    )
    # Build a template that has the unknown placeholder plus some plain text
    template_with_unknown = plain + unknown + plain

    # The other fields may be normal templates
    normal_template = draw(
        st.text(
            alphabet=st.characters(blacklist_characters="{}", blacklist_categories=("Cs",)),
            min_size=0,
            max_size=20,
        )
    )

    # Randomly pick which field gets the unknown placeholder
    field_choice = draw(st.sampled_from([
        "title_first_part",
        "title_other_part",
        "body_prefix_other_part",
        "body_suffix_non_final_part",
    ]))

    fields = {
        "title_first_part": normal_template,
        "title_other_part": normal_template,
        "body_prefix_other_part": normal_template,
        "body_suffix_non_final_part": normal_template,
    }
    fields[field_choice] = template_with_unknown

    return TemplateConfig(**fields), field_choice, unknown


# ---------------------------------------------------------------------------
# Property 15: Title decoration template selection
# ---------------------------------------------------------------------------

@given(inputs=multi_part_inputs())
@settings(max_examples=100)
def test_title_decoration_template_selection(inputs):
    """Property 15: Title decoration template selection.

    For all multi-part Story_Parts (total_parts >= 2), assert part_thread_title
    equals the substitution of title_first_part when part_number == 1 and
    title_other_part otherwise, with all five placeholders correctly substituted.

    **Validates: Requirements 6.2, 6.3, 6.5**
    """
    content = inputs["content"]
    part_number = inputs["part_number"]
    total_parts = inputs["total_parts"]
    config = inputs["config"]

    assert total_parts >= 2, "Strategy must produce total_parts >= 2"

    # Compute the actual decorated title
    actual = _decorate_title(content, part_number, total_parts, config)

    # Compute the expected value using _substitute directly
    title = content.get("thread_title", "")
    if part_number == 1:
        template = config.templates.title_first_part
        field_name = "title_first_part"
    else:
        template = config.templates.title_other_part
        field_name = "title_other_part"

    expected = _substitute(
        template,
        title=title,
        part_number=part_number,
        total_parts=total_parts,
        field_name=field_name,
    )

    assert actual == expected, (
        f"part_number={part_number}, total_parts={total_parts}: "
        f"_decorate_title returned {actual!r}, expected {expected!r} "
        f"(template={template!r})"
    )

    # Also verify the five placeholders are substituted correctly when present
    # by checking each known placeholder in the template
    for placeholder, expected_value in [
        ("title", title),
        ("part_number", str(part_number)),
        ("total_parts", str(total_parts)),
        ("next_part_number", str(part_number + 1)),
        ("prev_part_number", str(part_number - 1)),
    ]:
        if "{" + placeholder + "}" in template:
            assert str(expected_value) in actual, (
                f"Placeholder {{{placeholder}}} should have been substituted with "
                f"{expected_value!r} in result {actual!r}"
            )


# ---------------------------------------------------------------------------
# Property 16: Body decoration prefix+raw+suffix formula
# ---------------------------------------------------------------------------

@given(inputs=multi_part_inputs())
@settings(max_examples=100)
def test_body_decoration_formula(inputs):
    """Property 16: Body decoration prefix+raw+suffix formula.

    For all multi-part Story_Parts, assert part_thread_post == body_prefix +
    part_raw_post + body_suffix, with body_prefix empty for part_number == 1
    and body_suffix empty for the final part.

    **Validates: Requirements 6.4**
    """
    part_number = inputs["part_number"]
    total_parts = inputs["total_parts"]
    config = inputs["config"]
    raw_post = inputs["raw_post"]

    assert total_parts >= 2, "Strategy must produce total_parts >= 2"

    # Compute the actual decorated body
    actual = _decorate_body(raw_post, part_number, total_parts, config)

    # Compute expected prefix and suffix using _substitute directly
    title = ""  # _decorate_body uses empty title for body templates

    if part_number > 1:
        expected_prefix = _substitute(
            config.templates.body_prefix_other_part,
            title=title,
            part_number=part_number,
            total_parts=total_parts,
            field_name="body_prefix_other_part",
        )
    else:
        expected_prefix = ""

    if part_number < total_parts:
        expected_suffix = _substitute(
            config.templates.body_suffix_non_final_part,
            title=title,
            part_number=part_number,
            total_parts=total_parts,
            field_name="body_suffix_non_final_part",
        )
    else:
        expected_suffix = ""

    expected = expected_prefix + raw_post + expected_suffix

    assert actual == expected, (
        f"part_number={part_number}, total_parts={total_parts}: "
        f"_decorate_body returned {actual!r}, expected {expected!r}"
    )

    # Verify prefix is empty for part_number == 1
    if part_number == 1:
        assert actual.startswith(raw_post), (
            f"For part_number=1, body should start with raw_post. "
            f"Got {actual!r}, raw_post={raw_post!r}"
        )

    # Verify suffix is empty for the final part
    if part_number == total_parts:
        assert actual.endswith(raw_post), (
            f"For final part (part_number={part_number}=total_parts), "
            f"body should end with raw_post. Got {actual!r}, raw_post={raw_post!r}"
        )


# ---------------------------------------------------------------------------
# Property 17: Unknown placeholder passthrough
# ---------------------------------------------------------------------------

@given(
    inputs=multi_part_inputs(),
    unknown_name=st.sampled_from(_UNKNOWN_PLACEHOLDERS),
    known_name=st.sampled_from(_KNOWN_PLACEHOLDERS),
    prefix=st.text(
        alphabet=st.characters(blacklist_characters="{}", blacklist_categories=("Cs",)),
        min_size=0,
        max_size=10,
    ),
    suffix=st.text(
        alphabet=st.characters(blacklist_characters="{}", blacklist_categories=("Cs",)),
        min_size=0,
        max_size=10,
    ),
)
@settings(max_examples=100)
def test_unknown_placeholder_passthrough(inputs, unknown_name, known_name, prefix, suffix):
    """Property 17: Unknown placeholder passthrough.

    For all template strings containing one or more placeholders outside the
    known set, assert each unknown placeholder appears verbatim (with surrounding
    { and }) in the substituted output, a warning is emitted naming each unknown
    placeholder and the template field, and known placeholders in the same
    template are still substituted.

    **Validates: Requirements 6.7**
    """
    part_number = inputs["part_number"]
    total_parts = inputs["total_parts"]
    content = inputs["content"]
    title = content.get("thread_title", "")

    # Build a template that has both an unknown and a known placeholder
    unknown_placeholder = "{" + unknown_name + "}"
    known_placeholder = "{" + known_name + "}"
    template = prefix + unknown_placeholder + known_placeholder + suffix
    field_name = "test_field"

    # Capture warnings emitted by _substitute
    emitted_warnings = []

    def mock_print_substep(msg, **kwargs):
        emitted_warnings.append(msg)

    with patch("utils.story_splitter.templates.print_substep", side_effect=mock_print_substep):
        result = _substitute(
            template,
            title=title,
            part_number=part_number,
            total_parts=total_parts,
            field_name=field_name,
        )

    # 1. Unknown placeholder must appear verbatim in the output
    assert unknown_placeholder in result, (
        f"Unknown placeholder {unknown_placeholder!r} should appear verbatim in "
        f"result {result!r} (template={template!r})"
    )

    # 2. A warning must have been emitted naming the unknown placeholder and field
    assert len(emitted_warnings) >= 1, (
        f"Expected at least one warning for unknown placeholder {unknown_name!r}, "
        f"but no warnings were emitted"
    )
    warning_text = " ".join(emitted_warnings)
    assert unknown_name in warning_text, (
        f"Warning should name the unknown placeholder {unknown_name!r}. "
        f"Got warnings: {emitted_warnings!r}"
    )
    assert field_name in warning_text, (
        f"Warning should name the template field {field_name!r}. "
        f"Got warnings: {emitted_warnings!r}"
    )

    # 3. Known placeholders in the same template are still substituted
    known_values = {
        "title": title,
        "part_number": str(part_number),
        "total_parts": str(total_parts),
        "next_part_number": str(part_number + 1),
        "prev_part_number": str(part_number - 1),
    }
    expected_known_value = known_values[known_name]
    assert expected_known_value in result, (
        f"Known placeholder {known_placeholder!r} should have been substituted with "
        f"{expected_known_value!r} in result {result!r}"
    )
    # The known placeholder itself should NOT appear literally (it was substituted)
    assert known_placeholder not in result, (
        f"Known placeholder {known_placeholder!r} should have been substituted, "
        f"but still appears literally in result {result!r}"
    )


# ---------------------------------------------------------------------------
# Property 9: Decoration round-trip
# ---------------------------------------------------------------------------

@st.composite
def round_trip_inputs(draw) -> Dict[str, Any]:
    """Generate inputs for the decoration round-trip property.

    Produces a scenario where:
    - body_prefix_other_part and body_suffix_non_final_part are non-empty
    - Neither prefix nor suffix overlaps with raw_post content
    - total_parts >= 2
    """
    cfg_dict = draw(splitting_config())
    base_config = SplittingConfig.from_settings(cfg_dict)

    total_parts = draw(st.integers(min_value=2, max_value=10))
    part_number = draw(st.integers(min_value=1, max_value=total_parts))

    # Use a raw_post that contains only lowercase letters (no special chars)
    raw_post = draw(
        st.text(
            alphabet="abcdefghijklmnopqrstuvwxyz ",
            min_size=1,
            max_size=200,
        )
    )

    # Use prefix/suffix that use only uppercase letters and digits (no overlap with raw_post)
    # and are non-empty (required by the property)
    prefix_template = draw(
        st.text(
            alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
            min_size=1,
            max_size=20,
        )
    )
    suffix_template = draw(
        st.text(
            alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
            min_size=1,
            max_size=20,
        )
    )

    # Build a TemplateConfig with non-empty, non-overlapping prefix/suffix
    # (no placeholders in prefix/suffix to keep them simple and non-overlapping)
    template_config = TemplateConfig(
        title_first_part=base_config.templates.title_first_part,
        title_other_part=base_config.templates.title_other_part,
        body_prefix_other_part=prefix_template,
        body_suffix_non_final_part=suffix_template,
    )

    # Rebuild config with the new template_config
    config = SplittingConfig(
        mode=base_config.mode,
        soft_max_length=base_config.soft_max_length,
        single_part_tolerance=base_config.single_part_tolerance,
        min_part_length=base_config.min_part_length,
        max_parts=base_config.max_parts,
        templates=template_config,
        subreddit_name=base_config.subreddit_name,
    )

    return {
        "raw_post": raw_post,
        "part_number": part_number,
        "total_parts": total_parts,
        "config": config,
        "prefix_template": prefix_template,
        "suffix_template": suffix_template,
    }


@given(inputs=round_trip_inputs())
@settings(max_examples=100)
def test_decoration_round_trip(inputs):
    """Property 9: Decoration round-trip.

    For all Story_Parts where body_prefix_other_part and body_suffix_non_final_part
    are non-empty and contain no overlapping content with part_raw_post, assert that
    stripping the rendered prefix (when part_number > 1) and rendered suffix (when
    part_number < total_parts) from part_thread_post yields part_raw_post byte-for-byte.

    **Validates: Requirements 9.10, 6.4**
    """
    raw_post = inputs["raw_post"]
    part_number = inputs["part_number"]
    total_parts = inputs["total_parts"]
    config = inputs["config"]

    assert total_parts >= 2, "Strategy must produce total_parts >= 2"
    assert config.templates.body_prefix_other_part, "prefix must be non-empty"
    assert config.templates.body_suffix_non_final_part, "suffix must be non-empty"

    # Compute the decorated body
    decorated = _decorate_body(raw_post, part_number, total_parts, config)

    # Compute the rendered prefix and suffix (what was actually prepended/appended)
    title = ""  # _decorate_body uses empty title
    if part_number > 1:
        rendered_prefix = _substitute(
            config.templates.body_prefix_other_part,
            title=title,
            part_number=part_number,
            total_parts=total_parts,
            field_name="body_prefix_other_part",
        )
    else:
        rendered_prefix = ""

    if part_number < total_parts:
        rendered_suffix = _substitute(
            config.templates.body_suffix_non_final_part,
            title=title,
            part_number=part_number,
            total_parts=total_parts,
            field_name="body_suffix_non_final_part",
        )
    else:
        rendered_suffix = ""

    # Verify the round-trip: strip prefix and suffix to recover raw_post
    result = decorated

    if rendered_prefix:
        assert result.startswith(rendered_prefix), (
            f"Decorated body should start with rendered prefix {rendered_prefix!r}. "
            f"Got {result!r}"
        )
        result = result[len(rendered_prefix):]

    if rendered_suffix:
        assert result.endswith(rendered_suffix), (
            f"Decorated body (after prefix removal) should end with rendered suffix "
            f"{rendered_suffix!r}. Got {result!r}"
        )
        result = result[: len(result) - len(rendered_suffix)]

    assert result == raw_post, (
        f"After stripping prefix={rendered_prefix!r} and suffix={rendered_suffix!r}, "
        f"expected raw_post={raw_post!r} but got {result!r} "
        f"(part_number={part_number}, total_parts={total_parts})"
    )
