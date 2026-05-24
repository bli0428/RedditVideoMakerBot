"""
Template substitution and per-part decoration for Story_Splitter.

Implements title and body decoration using operator-configurable template
strings with placeholder substitution.

Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.7
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from utils.console import print_substep

if TYPE_CHECKING:
    from utils.story_splitter.types import SplittingConfig

# The closed set of placeholder names supported by the template engine.
_PLACEHOLDERS = ("title", "part_number", "total_parts", "next_part_number", "prev_part_number")


def _substitute(
    template: str,
    *,
    title: str,
    part_number: int,
    total_parts: int,
    field_name: str = "<unknown>",
) -> str:
    """Substitute known placeholders in *template* and return the result.

    Known placeholders (Req 6.5):
        ``{title}``             — the original post title.
        ``{part_number}``       — 1-indexed part number.
        ``{total_parts}``       — total number of parts in the plan.
        ``{next_part_number}``  — ``part_number + 1``.
        ``{prev_part_number}``  — ``part_number - 1``.

    Unknown placeholders are left literal (the ``{name}`` text is preserved
    verbatim) and a warning is emitted naming both the placeholder and the
    template field (Req 6.7).

    Parameters
    ----------
    template:
        The raw template string, e.g. ``"{title} (Part {part_number}/{total_parts})"``.
    title:
        The original post title.
    part_number:
        1-indexed position of this part.
    total_parts:
        Total number of parts in the plan.
    field_name:
        The name of the template field being substituted (used in warning
        messages for unknown placeholders, per Req 6.7).
    """
    import utils.story_splitter.templates as _this_module  # noqa: PLC0415

    values: dict[str, str | int] = {
        "title": title,
        "part_number": part_number,
        "total_parts": total_parts,
        "next_part_number": part_number + 1,
        "prev_part_number": part_number - 1,
    }

    def repl(m: re.Match) -> str:  # type: ignore[type-arg]
        name = m.group(1)
        if name in values:
            return str(values[name])
        # Req 6.7: warn and leave the placeholder literal.
        _this_module.print_substep(
            f"[splitter] unknown placeholder {{{name}}} in template field "
            f"'{field_name}'; left literal",
            style="yellow",
        )
        return m.group(0)

    return re.sub(r"\{(\w+)\}", repl, template)


def _decorate_title(
    reddit_content: dict,
    part_number: int,
    total_parts: int,
    config: "SplittingConfig",
) -> str:
    """Return the decorated title for a given part.

    Selects ``title_first_part`` when ``part_number == 1`` and
    ``title_other_part`` otherwise (Req 6.2, 6.3).

    This function SHALL only be called when ``total_parts >= 2``; the
    single-part short-circuit in the splitter bypasses template decoration
    entirely (Req 6.6).

    Parameters
    ----------
    reddit_content:
        The translated Reddit_Content dict; ``thread_title`` is read from it.
    part_number:
        1-indexed position of this part.
    total_parts:
        Total number of parts in the plan (must be >= 2 for this to be called).
    config:
        The resolved ``SplittingConfig`` carrying the ``TemplateConfig``.
    """
    title = reddit_content.get("thread_title", "")
    if part_number == 1:
        template = config.templates.title_first_part
        field_name = "title_first_part"
    else:
        template = config.templates.title_other_part
        field_name = "title_other_part"

    return _substitute(
        template,
        title=title,
        part_number=part_number,
        total_parts=total_parts,
        field_name=field_name,
    )


def _decorate_body(
    raw_post: str,
    part_number: int,
    total_parts: int,
    config: "SplittingConfig",
) -> str:
    """Return the decorated body for a given part.

    Builds ``body_prefix + raw_post + body_suffix`` where:

    * ``body_prefix`` is the substituted ``body_prefix_other_part`` when
      ``part_number > 1``, else the empty string (Req 6.4).
    * ``body_suffix`` is the substituted ``body_suffix_non_final_part`` when
      ``part_number < total_parts``, else the empty string (Req 6.4).

    This function SHALL only be called when ``total_parts >= 2``; the
    single-part short-circuit in the splitter bypasses template decoration
    entirely (Req 6.6).

    Parameters
    ----------
    raw_post:
        The verbatim slice of ``thread_post`` for this part (no decoration).
    part_number:
        1-indexed position of this part.
    total_parts:
        Total number of parts in the plan (must be >= 2 for this to be called).
    config:
        The resolved ``SplittingConfig`` carrying the ``TemplateConfig``.
    """
    # We need a placeholder title for body templates; use empty string since
    # body templates typically don't use {title}, but we must pass something.
    # The actual title is not available here; callers that need it should
    # pass it via _substitute directly.  For body templates the title
    # placeholder is supported but callers are responsible for providing it.
    # Since _decorate_body doesn't receive the title, we pass "" and let
    # _substitute handle it (it will substitute "" for {title} if used).
    title = ""

    if part_number > 1:
        body_prefix = _substitute(
            config.templates.body_prefix_other_part,
            title=title,
            part_number=part_number,
            total_parts=total_parts,
            field_name="body_prefix_other_part",
        )
    else:
        body_prefix = ""

    if part_number < total_parts:
        body_suffix = _substitute(
            config.templates.body_suffix_non_final_part,
            title=title,
            part_number=part_number,
            total_parts=total_parts,
            field_name="body_suffix_non_final_part",
        )
    else:
        body_suffix = ""

    return body_prefix + raw_post + body_suffix
