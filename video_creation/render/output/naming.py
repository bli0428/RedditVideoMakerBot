"""Output file naming utilities.

``name_normalize`` is moved here from ``video_creation/final_video.py``.
"""

from __future__ import annotations

import re


def name_normalize(name: str) -> str:
    """Sanitise a Reddit post title so it can be used as a filename.

    Removes characters that are illegal on common filesystems and expands
    common shorthand (``w/o`` → ``without``, ``w/`` → ``with``, etc.).
    Translation is handled upstream by ``Translation_Service`` before this
    function is called, so no ``translators`` call is made here (Req 10.4).
    """
    name = re.sub(r'[?\\"%*:|<>]', "", name)
    name = re.sub(r"( [w,W]\s?\/\s?[o,O,0])", r" without", name)
    name = re.sub(r"( [w,W]\s?\/)", r" with", name)
    name = re.sub(r"(\d+)\s?\/\s?(\d+)", r"\1 of \2", name)
    name = re.sub(r"(\w+)\s?\/\s?(\w+)", r"\1 or \2", name)
    name = re.sub(r"\/", r"", name)

    return name
