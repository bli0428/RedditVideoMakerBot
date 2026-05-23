"""video_creation.render — public API for the card rendering pipeline.

Re-exports the three public entry points so callers can use::

    from video_creation.render import render_video, available_styles, plugin_options_schema

Satisfies: Requirements 1.3, 13.1, 13.2, 13.3
"""

from video_creation.render.api import (  # noqa: F401
    available_styles,
    plugin_options_schema,
    render_video,
)

__all__ = ["render_video", "available_styles", "plugin_options_schema"]
