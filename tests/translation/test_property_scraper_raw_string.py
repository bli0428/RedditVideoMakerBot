"""Property-based tests for raw-string thread_post from the scraper.

**Property 24: Scraper returns raw string thread_post**
**Validates: Requirements 15.1, 15.4**

Hypothesis-generate mocked submission objects with arbitrary selftext strings.
For both storymodemethod values (0 and 1), assert that:
  - batch.build_reddit_object(submission)["thread_post"] is a str
  - batch.build_reddit_object(submission)["thread_post"] == submission.selftext
  - The result is NOT a list (posttextparser was not called)

Requirements 15.1 and 15.4 require that the scraper always returns raw
submission.selftext as a Python str in thread_post, regardless of
storymodemethod. Sentence segmentation (posttextparser) is the Orchestrator's
responsibility and must NOT be called inside the scraper.
"""
from __future__ import annotations

import sys
import types
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Stub out heavy / unavailable dependencies before importing the modules
# under test (batch.py and reddit/subreddit.py pull in torch, transformers,
# praw, etc. which are not installed in the test environment).
# ---------------------------------------------------------------------------


def _install_stubs() -> None:
    """Pre-populate sys.modules with stubs for modules that are not installed
    in the test environment so that importing batch.py and reddit/subreddit.py
    does not raise ModuleNotFoundError.

    Only stubs modules that are genuinely absent (importlib.util.find_spec
    returns None), so that real installed packages (rich, numpy, toml, etc.)
    are not shadowed.
    """
    import importlib.util

    def _is_available(name: str) -> bool:
        try:
            return importlib.util.find_spec(name) is not None
        except (ValueError, ModuleNotFoundError):
            return False

    # All modules (and submodules) that may not be installed in the test
    # environment. We stub the top-level package and all listed submodules.
    stub_names = [
        "torch",
        "transformers",
        "praw",
        "praw.models",
        "prawcore",
        "prawcore.exceptions",
        "spacy",
        "gtts",
        "mutagen",
        "mutagen.mp3",
        "moviepy",
        "moviepy.editor",
        "playwright",
        "playwright.sync_api",
        "translators",
        "elevenlabs",
        "elevenlabs.client",
        "openai",
        "anthropic",
        "cleantext",
        "yt_dlp",
        "cv2",
        "pyttsx3",
    ]

    for name in stub_names:
        top_level = name.split(".")[0]
        if not _is_available(top_level) and name not in sys.modules:
            stub = MagicMock()
            stub.__name__ = name
            stub.__spec__ = None
            sys.modules[name] = stub  # type: ignore[assignment]

    # video_creation.final_video was removed in Phase 4 — make_final_video now
    # lives in main.py. batch.py still has a top-level import of it, so we
    # inject a stub directly (the top-level package IS available, so the loop
    # above skips it).
    if "video_creation.final_video" not in sys.modules:
        fv_stub = MagicMock()
        fv_stub.__name__ = "video_creation.final_video"
        fv_stub.__spec__ = None
        sys.modules["video_creation.final_video"] = fv_stub  # type: ignore[assignment]

    # requests needs a real exceptions.HTTPError class (it IS installed but
    # we need the submodule to be a proper module, not a MagicMock attribute).
    if "requests" not in sys.modules:
        req_stub = MagicMock()
        req_stub.__name__ = "requests"
        sys.modules["requests"] = req_stub  # type: ignore[assignment]
    req_stub = sys.modules["requests"]
    if "requests.exceptions" not in sys.modules:
        exc_mod = types.ModuleType("requests.exceptions")
        exc_mod.HTTPError = type("HTTPError", (Exception,), {})  # type: ignore[attr-defined]
        exc_mod.JSONDecodeError = type("JSONDecodeError", (Exception,), {})  # type: ignore[attr-defined]
        req_stub.exceptions = exc_mod  # type: ignore[attr-defined]
        sys.modules["requests.exceptions"] = exc_mod


_install_stubs()

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Generate arbitrary selftext strings — any Unicode text the scraper might see.
selftext_strategy = st.text(min_size=0, max_size=5000)

# Generate storymodemethod values: 0 (raw string mode) and 1 (sentence-split mode).
storymodemethod_strategy = st.sampled_from([0, 1])


def _make_mock_submission(selftext: str) -> MagicMock:
    """Build a mock _RedditPost-like submission with the given selftext."""
    submission = MagicMock()
    submission.selftext = selftext
    submission.title = "Test Post Title"
    submission.id = "abc123"
    submission.over_18 = False
    submission.author = "testuser"
    submission.permalink = "/r/test/comments/abc123/test_post/"
    return submission


# ---------------------------------------------------------------------------
# Property 24a: batch.build_reddit_object returns str thread_post (Req 15.4)
# ---------------------------------------------------------------------------


@given(selftext=selftext_strategy, storymodemethod=storymodemethod_strategy)
@settings(max_examples=200, deadline=None)
def test_batch_build_reddit_object_thread_post_is_str(
    selftext: str, storymodemethod: int
) -> None:
    """**Property 24: Scraper returns raw string thread_post**
    **Validates: Requirements 15.4**

    batch.build_reddit_object must set thread_post to a str (submission.selftext)
    when storymode is enabled, regardless of storymodemethod.
    """
    from batch import build_reddit_object

    submission = _make_mock_submission(selftext)

    mock_config = {
        "settings": {
            "storymode": True,
            "storymodemethod": storymodemethod,
        }
    }

    with patch("batch.settings") as mock_settings, \
         patch("reddit.subreddit._fetch_avatar", return_value=""):
        mock_settings.config = mock_config
        result = build_reddit_object(submission)

    assert "thread_post" in result, (
        f"thread_post key missing from build_reddit_object result. "
        f"storymodemethod={storymodemethod}, selftext={selftext!r}"
    )
    assert isinstance(result["thread_post"], str), (
        f"Expected thread_post to be str, got {type(result['thread_post']).__name__}. "
        f"storymodemethod={storymodemethod}, selftext={selftext!r}"
    )


# ---------------------------------------------------------------------------
# Property 24b: batch.build_reddit_object thread_post equals selftext (Req 15.4)
# ---------------------------------------------------------------------------


@given(selftext=selftext_strategy, storymodemethod=storymodemethod_strategy)
@settings(max_examples=200)
def test_batch_build_reddit_object_thread_post_equals_selftext(
    selftext: str, storymodemethod: int
) -> None:
    """**Property 24: Scraper returns raw string thread_post**
    **Validates: Requirements 15.4**

    batch.build_reddit_object must set thread_post to exactly submission.selftext
    (the raw string), not a parsed list or any other transformation.
    """
    from batch import build_reddit_object

    submission = _make_mock_submission(selftext)

    mock_config = {
        "settings": {
            "storymode": True,
            "storymodemethod": storymodemethod,
        }
    }

    with patch("batch.settings") as mock_settings, \
         patch("reddit.subreddit._fetch_avatar", return_value=""):
        mock_settings.config = mock_config
        result = build_reddit_object(submission)

    assert result["thread_post"] == selftext, (
        f"Expected thread_post == submission.selftext, but got a different value. "
        f"storymodemethod={storymodemethod}, "
        f"selftext={selftext!r}, "
        f"thread_post={result['thread_post']!r}"
    )


# ---------------------------------------------------------------------------
# Property 24c: batch.build_reddit_object thread_post is NOT a list (Req 15.4)
# ---------------------------------------------------------------------------


@given(selftext=selftext_strategy, storymodemethod=storymodemethod_strategy)
@settings(max_examples=200)
def test_batch_build_reddit_object_thread_post_is_not_list(
    selftext: str, storymodemethod: int
) -> None:
    """**Property 24: Scraper returns raw string thread_post**
    **Validates: Requirements 15.4**

    batch.build_reddit_object must NOT call posttextparser on thread_post.
    The result must never be a list (which posttextparser would produce).
    """
    from batch import build_reddit_object

    submission = _make_mock_submission(selftext)

    mock_config = {
        "settings": {
            "storymode": True,
            "storymodemethod": storymodemethod,
        }
    }

    with patch("batch.settings") as mock_settings, \
         patch("reddit.subreddit._fetch_avatar", return_value=""):
        mock_settings.config = mock_config
        result = build_reddit_object(submission)

    assert not isinstance(result["thread_post"], list), (
        f"thread_post must not be a list (posttextparser must not be called "
        f"inside the scraper). "
        f"storymodemethod={storymodemethod}, selftext={selftext!r}"
    )


# ---------------------------------------------------------------------------
# Property 24d: batch.build_reddit_object does not call posttextparser (Req 15.4)
# ---------------------------------------------------------------------------


@given(selftext=selftext_strategy, storymodemethod=storymodemethod_strategy)
@settings(max_examples=100)
def test_batch_build_reddit_object_does_not_call_posttextparser(
    selftext: str, storymodemethod: int
) -> None:
    """**Property 24: Scraper returns raw string thread_post**
    **Validates: Requirements 15.4**

    batch.build_reddit_object must not call posttextparser at all.
    The posttextparser call is the Orchestrator's responsibility (Req 9.1, 16.3).
    """
    from batch import build_reddit_object

    submission = _make_mock_submission(selftext)

    mock_config = {
        "settings": {
            "storymode": True,
            "storymodemethod": storymodemethod,
        }
    }

    with patch("batch.settings") as mock_settings, \
         patch("reddit.subreddit._fetch_avatar", return_value=""), \
         patch("utils.posttextparser.posttextparser") as mock_posttextparser:
        mock_settings.config = mock_config
        result = build_reddit_object(submission)

    mock_posttextparser.assert_not_called(), (
        f"posttextparser was called inside build_reddit_object — it must not be. "
        f"storymodemethod={storymodemethod}, selftext={selftext!r}"
    )


# ---------------------------------------------------------------------------
# Property 24e: subreddit.get_subreddit_threads thread_post is raw str (Req 15.1)
#
# Since get_subreddit_threads makes network calls, we test the assignment
# logic directly by verifying the code path: when storymode is enabled,
# content["thread_post"] = submission.selftext (a str assignment, not a
# posttextparser call). We do this by patching the network calls and
# verifying the output.
# ---------------------------------------------------------------------------


@given(selftext=selftext_strategy, storymodemethod=storymodemethod_strategy)
@settings(max_examples=200)
def test_subreddit_get_subreddit_threads_thread_post_is_raw_str(
    selftext: str, storymodemethod: int
) -> None:
    """**Property 24: Scraper returns raw string thread_post**
    **Validates: Requirements 15.1**

    get_subreddit_threads must set thread_post to submission.selftext as a
    raw str when storymode is enabled, regardless of storymodemethod.
    Network calls are mocked so this is a pure logic test.
    """
    from reddit.subreddit import get_subreddit_threads

    submission = _make_mock_submission(selftext)
    submission.num_comments = 5  # avoid the "no comments" early exit

    mock_config = {
        "settings": {
            "storymode": True,
            "storymodemethod": storymodemethod,
        },
        "reddit": {
            "thread": {
                "subreddit": "test",
                "post_id": "abc123",
                "max_comment_length": 500,
                "min_comment_length": 10,
            }
        },
        "ai": {
            "ai_similarity_enabled": False,
        },
    }

    with patch("reddit.subreddit.settings") as mock_settings, \
         patch("reddit.subreddit._fetch_submission", return_value=submission), \
         patch("reddit.subreddit._fetch_avatar", return_value=""), \
         patch("reddit.subreddit.check_done", return_value=submission), \
         patch("reddit.subreddit.print_step"), \
         patch("reddit.subreddit.print_substep"):
        mock_settings.config = mock_config
        result = get_subreddit_threads("abc123")

    assert "thread_post" in result, (
        f"thread_post key missing from get_subreddit_threads result. "
        f"storymodemethod={storymodemethod}, selftext={selftext!r}"
    )
    assert isinstance(result["thread_post"], str), (
        f"Expected thread_post to be str, got {type(result['thread_post']).__name__}. "
        f"storymodemethod={storymodemethod}, selftext={selftext!r}"
    )
    assert result["thread_post"] == selftext, (
        f"Expected thread_post == submission.selftext, but got a different value. "
        f"storymodemethod={storymodemethod}, "
        f"selftext={selftext!r}, "
        f"thread_post={result['thread_post']!r}"
    )
    assert not isinstance(result["thread_post"], list), (
        f"thread_post must not be a list (posttextparser must not be called "
        f"inside get_subreddit_threads). "
        f"storymodemethod={storymodemethod}, selftext={selftext!r}"
    )


# ---------------------------------------------------------------------------
# Property 24f: subreddit.get_subreddit_threads does not call posttextparser
# ---------------------------------------------------------------------------


@given(selftext=selftext_strategy, storymodemethod=storymodemethod_strategy)
@settings(max_examples=100)
def test_subreddit_get_subreddit_threads_does_not_call_posttextparser(
    selftext: str, storymodemethod: int
) -> None:
    """**Property 24: Scraper returns raw string thread_post**
    **Validates: Requirements 15.1**

    get_subreddit_threads must not call posttextparser at all.
    The posttextparser call is the Orchestrator's responsibility (Req 9.1, 16.3).
    """
    from reddit.subreddit import get_subreddit_threads

    submission = _make_mock_submission(selftext)
    submission.num_comments = 5

    mock_config = {
        "settings": {
            "storymode": True,
            "storymodemethod": storymodemethod,
        },
        "reddit": {
            "thread": {
                "subreddit": "test",
                "post_id": "abc123",
                "max_comment_length": 500,
                "min_comment_length": 10,
            }
        },
        "ai": {
            "ai_similarity_enabled": False,
        },
    }

    with patch("reddit.subreddit.settings") as mock_settings, \
         patch("reddit.subreddit._fetch_submission", return_value=submission), \
         patch("reddit.subreddit._fetch_avatar", return_value=""), \
         patch("reddit.subreddit.check_done", return_value=submission), \
         patch("reddit.subreddit.print_step"), \
         patch("reddit.subreddit.print_substep"), \
         patch("utils.posttextparser.posttextparser") as mock_posttextparser:
        mock_settings.config = mock_config
        result = get_subreddit_threads("abc123")

    # posttextparser should not have been called from within the scraper
    mock_posttextparser.assert_not_called(), (
        f"posttextparser was called inside get_subreddit_threads — it must not be. "
        f"storymodemethod={storymodemethod}, selftext={selftext!r}"
    )
