"""RenderContext and CanvasSpec — frozen dataclasses passed into every plugin call.

Plugins read from RenderContext; they never reach back into settings.config.

Satisfies: Requirements 1.1, 1.4, 11.3
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # Avoid a circular import at runtime; RenderConfig is only needed for the
    # from_reddit_obj classmethod type hint.
    from video_creation.render.config import RenderConfig


@dataclass(frozen=True)
class CanvasSpec:
    """Output canvas geometry sourced from config.toml (Req 11.3).

    All four values come from the ``[settings]`` block:
    ``resolution_w``, ``resolution_h``, ``zoom``, and ``opacity``.

    Attributes
    ----------
    width:
        Output video width in pixels (``resolution_w``).
    height:
        Output video height in pixels (``resolution_h``).
    zoom:
        Background zoom factor (``zoom``).
    opacity:
        Card overlay opacity in [0.0, 1.0] (``opacity``).
    """

    width: int
    height: int
    zoom: float
    opacity: float


@dataclass(frozen=True)
class RenderContext:
    """Immutable snapshot of post metadata and canvas settings for one render.

    Passed into every ``CardStylePlugin`` method.  Plugins read from this
    object; they never reach back into ``settings.config`` or the raw
    ``reddit_obj`` dict.

    Attributes
    ----------
    title:
        Post title text.
    body_text:
        Body text of the post (story-mode text or comment body).
    author:
        Reddit username of the post author (without the ``u/`` prefix).
    avatar_url:
        URL of the author's avatar image, or an empty string if unavailable.
    subreddit:
        Subreddit name (without the ``r/`` prefix).
    upvotes:
        Post score (upvote count).
    num_comments:
        Number of comments on the post.
    canvas:
        Output canvas geometry (width, height, zoom, opacity).
    theme:
        Active theme name (e.g. ``"light"`` or ``"dark"``).  Plugins that
        do not support themes may ignore this field (Req 7.3).
    """

    title: str
    body_text: str
    author: str
    avatar_url: str
    subreddit: str
    upvotes: int
    num_comments: int
    canvas: CanvasSpec
    theme: str

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_reddit_obj(
        cls,
        reddit_obj: dict[str, Any],
        config: "RenderConfig",
    ) -> "RenderContext":
        """Build a ``RenderContext`` from a raw Reddit post dict and config.

        Parameters
        ----------
        reddit_obj:
            The post payload dict as produced by the scraper.  Expected keys:

            * ``"thread_title"`` — post title (required)
            * ``"thread_post"`` — story-mode body text (optional; used when
              ``storymode`` is active)
            * ``"comments"`` — list of comment dicts with a ``"comment_body"``
              key (optional; used when not in story mode)
            * ``"author"`` — Reddit username (required)
            * ``"avatar_url"`` — author avatar URL (optional, defaults to
              ``""`` when absent)
            * ``"thread_score"`` — post upvote count (optional, defaults to
              ``0``)
            * ``"num_comments"`` — comment count (optional, defaults to
              ``0``)

        config:
            Parsed ``RenderConfig`` supplying canvas geometry and theme.

        Returns
        -------
        RenderContext
            Frozen context ready to be passed into plugin methods.
        """
        title: str = reddit_obj.get("thread_title", "")

        # Body text: prefer story-mode post body; fall back to first comment.
        thread_post = reddit_obj.get("thread_post", "") or ""
        # thread_post may be a list (storymodemethod=1) or a string
        if isinstance(thread_post, list):
            thread_post = " ".join(str(s) for s in thread_post)
        if thread_post.strip():
            body_text = thread_post
        else:
            comments: list[dict[str, Any]] = reddit_obj.get("comments", []) or []
            if comments:
                body_text = comments[0].get("comment_body", "")
            else:
                body_text = ""

        author: str = reddit_obj.get("author", "")
        avatar_url: str = reddit_obj.get("avatar_url", "") or ""
        upvotes: int = int(reddit_obj.get("thread_score", 0) or 0)
        num_comments: int = int(reddit_obj.get("num_comments", 0) or 0)

        canvas = CanvasSpec(
            width=config.canvas.width,
            height=config.canvas.height,
            zoom=config.canvas.zoom,
            opacity=config.canvas.opacity,
        )

        # ``subreddit`` lives on ``RenderConfig`` (sourced from
        # ``settings.config["reddit"]["thread"]["subreddit"]``).
        # Fall back to an empty string if the config object doesn't carry it
        # yet (e.g. during incremental migration).
        subreddit: str = getattr(config, "subreddit", "") or ""

        return cls(
            title=title,
            body_text=body_text,
            author=author,
            avatar_url=avatar_url,
            subreddit=subreddit,
            upvotes=upvotes,
            num_comments=num_comments,
            canvas=canvas,
            theme=config.theme,
        )
