"""video_creation.render.styles — StyleRegistry and CardStylePlugin implementations.

The StyleRegistry maps ``style_id`` strings to ``CardStylePlugin`` subclasses.
Plugins register themselves by decorating their class with ``@register_style``.

Public surface
--------------
register_style   -- class decorator that adds a plugin to the registry
available_styles -- returns sorted tuple of registered style identifiers
get_style        -- looks up a plugin class; raises UnknownStyleError if missing
UnknownStyleError -- re-exported from errors.py for convenience

Satisfies: Requirements 2.1, 2.2, 2.3, 2.4
"""

from __future__ import annotations

from typing import Type

from .base import CardStylePlugin
from video_creation.render.errors import UnknownStyleError

# ---------------------------------------------------------------------------
# Internal registry
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, Type[CardStylePlugin]] = {}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def register_style(cls: Type[CardStylePlugin]) -> Type[CardStylePlugin]:
    """Class decorator: register a ``CardStylePlugin`` subclass under ``cls.style_id``.

    Validates that:
    - ``cls.style_id`` is a non-empty string (Req 2.2).
    - The ``style_id`` has not already been registered (Req 2.2).

    Parameters
    ----------
    cls:
        A concrete subclass of ``CardStylePlugin`` with a non-empty
        ``style_id`` class attribute.

    Returns
    -------
    cls
        The class unchanged (decorator protocol).

    Raises
    ------
    TypeError
        If ``cls.style_id`` is missing or empty.
    ValueError
        If ``cls.style_id`` is already registered.
    """
    if not getattr(cls, "style_id", None):
        raise TypeError(f"{cls.__name__} must define a non-empty style_id")
    if cls.style_id in _REGISTRY:
        raise ValueError(f"style_id {cls.style_id!r} already registered")
    _REGISTRY[cls.style_id] = cls
    return cls


def available_styles() -> tuple[str, ...]:
    """Return registered style identifiers in sorted order (Req 2.1, 13.2).

    Returns
    -------
    tuple[str, ...]
        Sorted tuple of all currently-registered ``style_id`` strings.
        Returns an empty tuple if no plugins have been registered yet.
    """
    return tuple(sorted(_REGISTRY))


def get_style(style_id: str) -> Type[CardStylePlugin]:
    """Look up a plugin class by its ``style_id`` (Req 2.3).

    Parameters
    ----------
    style_id:
        The identifier to look up (e.g. ``"custom-card"``).

    Returns
    -------
    Type[CardStylePlugin]
        The plugin class registered under ``style_id``.

    Raises
    ------
    UnknownStyleError
        If ``style_id`` is not in the registry.  The error message includes
        the requested identifier and all currently-registered identifiers.
    """
    try:
        return _REGISTRY[style_id]
    except KeyError:
        raise UnknownStyleError(style_id, available_styles())


# ---------------------------------------------------------------------------
# Register the four built-in plugins.
# These imports trigger the @register_style decorators.
# ---------------------------------------------------------------------------

# Register the four built-in plugins.
# These imports trigger the @register_style decorators.
try:
    from . import custom_card, custom_karaoke, reddit_card, reddit_karaoke  # noqa: F401
except ImportError:
    pass  # plugins not yet implemented — will be added in Phase 3
