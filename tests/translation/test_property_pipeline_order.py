"""Property-based tests for Pipeline_Stage_Order in main.py::main.

**Property 23: Pipeline stage order**
**Validates: Requirements 1.1, 9.1, 9.2, 9.3, 16.1, 16.2, 16.3, 16.4**

Hypothesis-generate (storymode, storymodemethod, provider, target_lang) flag
combinations; monkey-patch get_subreddit_threads, Translation_Service.translate,
posttextparser, save_text_to_mp3, get_screenshots_of_reddit_posts, and
make_final_video with recorders and assert each call sequence is a subsequence
of the documented order with the per-flag preconditions:

  get_subreddit_threads
    → Translation_Service.translate
    → posttextparser  (only when storymode=True AND storymodemethod=1)
    → save_text_to_mp3 / get_screenshots_of_reddit_posts / make_final_video

Properties tested:
  1. Translation_Service.translate is always called after get_subreddit_threads
  2. posttextparser is called after Translation_Service.translate when
     storymode=True AND storymodemethod=1
  3. posttextparser is NOT called when storymodemethod=0
  4. Consumer stages (save_text_to_mp3, etc.) are called after posttextparser
     (when applicable)

Implementation note:
  main.py has module-level side effects (banner print, imports of modules that
  require optional heavy dependencies like torch/transformers). We stub those
  out via sys.modules before importing main, then test main.main() directly
  with all external calls mocked via unittest.mock.patch.
"""
from __future__ import annotations

import sys
import types
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Stub out heavy / unavailable dependencies before importing main
# ---------------------------------------------------------------------------


def _install_stubs() -> None:
    """Pre-populate sys.modules with stubs for modules that are not installed
    in the test environment (torch, transformers, praw, etc.) so that
    importing main.py does not raise ModuleNotFoundError.

    We use MagicMock() for each stub so that attribute access on any stub
    returns another MagicMock rather than raising AttributeError. This also
    satisfies Hypothesis's internal numpy.random import.

    Only stubs modules that are NOT already importable (i.e., not installed).
    """
    # Modules that are missing in this environment and need stubs
    _MISSING = [
        "torch",
        "numpy",
        "numpy.random",
        "numpy.core",
        "numpy.core.multiarray",
        "transformers",
        "praw",
        "praw.models",
        "prawcore",
        "prawcore.exceptions",
        "spacy",
        "gtts",
        "mutagen",
        "mutagen.mp3",
        "playwright",
        "playwright.sync_api",
        "translators",
        "elevenlabs",
        "elevenlabs.client",
        "openai",
        "anthropic",
        "cleantext",
        "cv2",
        "yt_dlp",
        "pyttsx3",
    ]
    for name in _MISSING:
        if name not in sys.modules:
            stub = MagicMock()
            stub.__name__ = name
            stub.__spec__ = None
            sys.modules[name] = stub  # type: ignore[assignment]

    # numpy.ndarray must be a real class (Hypothesis checks isinstance)
    np_stub = sys.modules["numpy"]
    np_stub.ndarray = type("ndarray", (), {})  # type: ignore[attr-defined]

    # Stub utils.version.checkversion so the module-level call in main.py
    # (checkversion(__VERSION__)) does not make a real HTTP request or attempt
    # a str < MagicMock comparison that raises TypeError in Python 3.13+.
    if "utils.version" not in sys.modules:
        version_mod = types.ModuleType("utils.version")
        version_mod.checkversion = lambda v: None  # type: ignore[attr-defined]
        sys.modules["utils.version"] = version_mod
    else:
        # Already imported — patch the function in-place so the module-level
        # call that already ran is harmless, and future imports get the stub.
        sys.modules["utils.version"].checkversion = lambda v: None  # type: ignore[attr-defined]


_install_stubs()

# Now we can safely import the modules under test.
# We import main lazily inside _run_main_with_mocks to avoid the module-level
# banner print running at collection time.

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

provider_strategy = st.sampled_from(["none", "anthropic"])
target_lang_strategy = st.one_of(
    st.just(""),
    st.sampled_from(["es", "fr", "de", "ja", "zh"]),
)
storymodemethod_strategy = st.integers(min_value=0, max_value=1)
storymode_strategy = st.booleans()

flag_strategy = st.tuples(
    storymode_strategy,
    storymodemethod_strategy,
    provider_strategy,
    target_lang_strategy,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_reddit_object(storymode: bool) -> dict[str, Any]:
    """Build a minimal Reddit_Content dict for testing."""
    obj: dict[str, Any] = {
        "thread_title": "Test title",
        "thread_id": "abc123",
        "thread_url": "https://reddit.com/r/test/abc123",
        "permalink": "/r/test/abc123",
        "author": "testuser",
        "avatar_url": "",
        "is_nsfw": False,
        "subreddit": "test",
        "comments": [
            {
                "comment_id": "c1",
                "comment_body": "A comment",
                "comment_url": "https://reddit.com/r/test/abc123/c1",
                "author": "commenter",
            }
        ],
    }
    if storymode:
        obj["thread_post"] = "Once upon a time there was a story. It was long."
    return obj


def _run_main_with_mocks(
    storymode: bool,
    storymodemethod: int,
    provider: str,
    target_lang: str,
) -> list[str]:
    """
    Run main.main() with all external calls mocked.

    Returns the ordered list of stage names that were called, in the order
    they were invoked.
    """
    call_log: list[str] = []
    reddit_obj = _make_reddit_object(storymode)
    parsed_post = ["Once upon a time there was a story.", "It was long."]

    # --- side-effect functions ---

    def scraper_side_effect(post_id):
        call_log.append("get_subreddit_threads")
        return reddit_obj

    def translate_side_effect(reddit_content):
        call_log.append("translate")
        return reddit_content

    def posttextparser_side_effect(text):
        call_log.append("posttextparser")
        return parsed_post

    def save_text_to_mp3_side_effect(reddit_content):
        call_log.append("save_text_to_mp3")
        return (10.0, 1)

    def get_screenshots_side_effect(reddit_content, number_of_comments):
        call_log.append("get_screenshots_of_reddit_posts")
        return None

    def make_final_video_side_effect(*args, **kwargs):
        call_log.append("make_final_video")
        return None

    config_patch = {
        "settings": {
            "storymode": storymode,
            "storymodemethod": storymodemethod,
            "allow_nsfw": False,
            "tts": {
                "voice_choice": "reddit",
                "tiktok_sessionid": "",
                "elevenlabs_api_key": "",
                "openai_api_key": "",
            },
        },
        "reddit": {
            "thread": {
                "subreddit": "test",
                "post_id": None,
                "post_lang": "",
            }
        },
        "translation": {
            "provider": provider,
            "target_lang": target_lang,
            "failure_policy": "skip",
            "cache_enabled": False,
            "force_translate": False,
            "anthropic": {
                "model": "claude-3-5-sonnet-latest",
                "max_output_tokens": 4096,
                "api_key": "",
            },
        },
    }

    # We need to import main inside the patch context so that the module-level
    # code (banner print, checkversion) doesn't re-run. Since main is already
    # in sys.modules after the first import, subsequent imports are no-ops.
    # We patch the already-imported names in the main module's namespace.

    # Ensure main is imported (stubs are already in sys.modules)
    import main as main_module  # noqa: PLC0415

    mock_ts_instance = MagicMock()
    mock_ts_instance.translate.side_effect = translate_side_effect

    mock_ts_class = MagicMock(return_value=mock_ts_instance)
    mock_tc_class = MagicMock()
    mock_tc_class.from_settings.return_value = MagicMock()

    with (
        patch.object(main_module, "get_subreddit_threads", side_effect=scraper_side_effect),
        patch.object(main_module, "Translation_Service", mock_ts_class),
        patch.object(main_module, "TranslationConfig", mock_tc_class),
        patch.object(main_module, "posttextparser", side_effect=posttextparser_side_effect),
        patch.object(main_module, "save_text_to_mp3", side_effect=save_text_to_mp3_side_effect),
        patch.object(main_module, "get_screenshots_of_reddit_posts", side_effect=get_screenshots_side_effect),
        patch.object(main_module, "make_final_video", side_effect=make_final_video_side_effect),
        patch.object(main_module, "download_background_video", return_value=None),
        patch.object(main_module, "download_background_audio", return_value=None),
        patch.object(main_module, "chop_background", return_value=None),
        patch.object(main_module, "get_background_config", return_value=("bg_video", "bg_audio")),
        patch.object(main_module, "extract_id", return_value="abc123"),
        patch.object(main_module, "print_substep", return_value=None),
        patch.object(main_module, "settings") as mock_settings,
    ):
        mock_settings.config = config_patch
        main_module.main(POST_ID=None)

    return call_log


# ---------------------------------------------------------------------------
# Property 23a: translate is always called after get_subreddit_threads
# (Req 1.1, 16.1, 16.2)
# ---------------------------------------------------------------------------

@given(flags=flag_strategy)
@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_translate_called_after_get_subreddit_threads(
    flags: tuple[bool, int, str, str],
) -> None:
    """**Property 23: Pipeline stage order**
    **Validates: Requirements 1.1, 16.1, 16.2**

    Translation_Service.translate must always be called after
    get_subreddit_threads, regardless of flag combinations.
    """
    storymode, storymodemethod, provider, target_lang = flags
    call_log = _run_main_with_mocks(storymode, storymodemethod, provider, target_lang)

    assert "get_subreddit_threads" in call_log, (
        f"get_subreddit_threads was not called. flags={flags!r}, log={call_log!r}"
    )
    assert "translate" in call_log, (
        f"Translation_Service.translate was not called. flags={flags!r}, log={call_log!r}"
    )

    scraper_idx = call_log.index("get_subreddit_threads")
    translate_idx = call_log.index("translate")
    assert scraper_idx < translate_idx, (
        f"translate was called before get_subreddit_threads. "
        f"flags={flags!r}, log={call_log!r}"
    )


# ---------------------------------------------------------------------------
# Property 23b: posttextparser called after translate when storymode=True
# AND storymodemethod=1 (Req 9.1, 16.3)
# ---------------------------------------------------------------------------

@given(
    provider=provider_strategy,
    target_lang=target_lang_strategy,
)
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_posttextparser_called_after_translate_when_storymode1(
    provider: str,
    target_lang: str,
) -> None:
    """**Property 23: Pipeline stage order**
    **Validates: Requirements 9.1, 16.3**

    When storymode=True AND storymodemethod=1, posttextparser must be called
    after Translation_Service.translate.
    """
    call_log = _run_main_with_mocks(
        storymode=True,
        storymodemethod=1,
        provider=provider,
        target_lang=target_lang,
    )

    assert "translate" in call_log, (
        f"translate was not called. provider={provider!r}, target_lang={target_lang!r}, "
        f"log={call_log!r}"
    )
    assert "posttextparser" in call_log, (
        f"posttextparser was not called when storymode=True AND storymodemethod=1. "
        f"provider={provider!r}, target_lang={target_lang!r}, log={call_log!r}"
    )

    translate_idx = call_log.index("translate")
    parser_idx = call_log.index("posttextparser")
    assert translate_idx < parser_idx, (
        f"posttextparser was called before translate. "
        f"provider={provider!r}, target_lang={target_lang!r}, log={call_log!r}"
    )


# ---------------------------------------------------------------------------
# Property 23c: posttextparser NOT called when storymodemethod=0
# (Req 9.3, 16.4)
# ---------------------------------------------------------------------------

@given(
    storymode=storymode_strategy,
    provider=provider_strategy,
    target_lang=target_lang_strategy,
)
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_posttextparser_not_called_when_storymodemethod_0(
    storymode: bool,
    provider: str,
    target_lang: str,
) -> None:
    """**Property 23: Pipeline stage order**
    **Validates: Requirements 9.3, 16.4**

    posttextparser must NOT be called when storymodemethod=0, regardless of
    storymode, provider, or target_lang.
    """
    call_log = _run_main_with_mocks(
        storymode=storymode,
        storymodemethod=0,
        provider=provider,
        target_lang=target_lang,
    )

    assert "posttextparser" not in call_log, (
        f"posttextparser was called when storymodemethod=0. "
        f"storymode={storymode!r}, provider={provider!r}, target_lang={target_lang!r}, "
        f"log={call_log!r}"
    )


# ---------------------------------------------------------------------------
# Property 23d: posttextparser NOT called when storymode=False
# (Req 9.3, 16.4)
# ---------------------------------------------------------------------------

@given(
    storymodemethod=storymodemethod_strategy,
    provider=provider_strategy,
    target_lang=target_lang_strategy,
)
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_posttextparser_not_called_when_storymode_false(
    storymodemethod: int,
    provider: str,
    target_lang: str,
) -> None:
    """**Property 23: Pipeline stage order**
    **Validates: Requirements 9.3, 16.4**

    posttextparser must NOT be called when storymode=False, regardless of
    storymodemethod, provider, or target_lang.
    """
    call_log = _run_main_with_mocks(
        storymode=False,
        storymodemethod=storymodemethod,
        provider=provider,
        target_lang=target_lang,
    )

    assert "posttextparser" not in call_log, (
        f"posttextparser was called when storymode=False. "
        f"storymodemethod={storymodemethod!r}, provider={provider!r}, "
        f"target_lang={target_lang!r}, log={call_log!r}"
    )


# ---------------------------------------------------------------------------
# Property 23e: Consumer stages called after posttextparser (when applicable)
# (Req 9.1, 16.1)
# ---------------------------------------------------------------------------

@given(
    provider=provider_strategy,
    target_lang=target_lang_strategy,
)
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_consumer_stages_called_after_posttextparser(
    provider: str,
    target_lang: str,
) -> None:
    """**Property 23: Pipeline stage order**
    **Validates: Requirements 9.1, 16.1**

    When storymode=True AND storymodemethod=1, consumer stages
    (save_text_to_mp3, get_screenshots_of_reddit_posts, make_final_video)
    must all be called after posttextparser.
    """
    call_log = _run_main_with_mocks(
        storymode=True,
        storymodemethod=1,
        provider=provider,
        target_lang=target_lang,
    )

    assert "posttextparser" in call_log, (
        f"posttextparser was not called. log={call_log!r}"
    )
    parser_idx = call_log.index("posttextparser")

    for consumer in ("save_text_to_mp3", "get_screenshots_of_reddit_posts", "make_final_video"):
        assert consumer in call_log, (
            f"Consumer stage '{consumer}' was not called. log={call_log!r}"
        )
        consumer_idx = call_log.index(consumer)
        assert parser_idx < consumer_idx, (
            f"Consumer stage '{consumer}' was called before posttextparser. "
            f"provider={provider!r}, target_lang={target_lang!r}, log={call_log!r}"
        )


# ---------------------------------------------------------------------------
# Property 23f: Consumer stages called after translate (all flag combos)
# (Req 1.1, 16.1, 16.2)
# ---------------------------------------------------------------------------

@given(flags=flag_strategy)
@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_consumer_stages_called_after_translate(
    flags: tuple[bool, int, str, str],
) -> None:
    """**Property 23: Pipeline stage order**
    **Validates: Requirements 1.1, 16.1, 16.2**

    Consumer stages (save_text_to_mp3, get_screenshots_of_reddit_posts,
    make_final_video) must always be called after Translation_Service.translate,
    regardless of flag combinations.
    """
    storymode, storymodemethod, provider, target_lang = flags
    call_log = _run_main_with_mocks(storymode, storymodemethod, provider, target_lang)

    assert "translate" in call_log, (
        f"translate was not called. flags={flags!r}, log={call_log!r}"
    )
    translate_idx = call_log.index("translate")

    for consumer in ("save_text_to_mp3", "get_screenshots_of_reddit_posts", "make_final_video"):
        assert consumer in call_log, (
            f"Consumer stage '{consumer}' was not called. flags={flags!r}, log={call_log!r}"
        )
        consumer_idx = call_log.index(consumer)
        assert translate_idx < consumer_idx, (
            f"Consumer stage '{consumer}' was called before translate. "
            f"flags={flags!r}, log={call_log!r}"
        )


# ---------------------------------------------------------------------------
# Property 23g: Full documented Pipeline_Stage_Order is a valid subsequence
# (Req 16.1)
# ---------------------------------------------------------------------------

@given(flags=flag_strategy)
@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_full_pipeline_stage_order_is_valid_subsequence(
    flags: tuple[bool, int, str, str],
) -> None:
    """**Property 23: Pipeline stage order**
    **Validates: Requirements 1.1, 9.1, 9.2, 9.3, 16.1, 16.2, 16.3, 16.4**

    The documented Pipeline_Stage_Order must appear as a subsequence in the
    actual call log, with per-flag preconditions applied:

      get_subreddit_threads
        → translate
        → posttextparser  (only when storymode=True AND storymodemethod=1)
        → save_text_to_mp3
        → get_screenshots_of_reddit_posts
        → make_final_video
    """
    storymode, storymodemethod, provider, target_lang = flags
    call_log = _run_main_with_mocks(storymode, storymodemethod, provider, target_lang)

    # Build the expected ordered sequence based on flags
    expected_sequence: list[str] = ["get_subreddit_threads", "translate"]
    if storymode and storymodemethod == 1:
        expected_sequence.append("posttextparser")
    expected_sequence.extend([
        "save_text_to_mp3",
        "get_screenshots_of_reddit_posts",
        "make_final_video",
    ])

    def is_subsequence(needle: list[str], haystack: list[str]) -> bool:
        it = iter(haystack)
        return all(stage in it for stage in needle)

    assert is_subsequence(expected_sequence, call_log), (
        f"Expected pipeline stage order {expected_sequence!r} is not a "
        f"subsequence of actual call log {call_log!r}. flags={flags!r}"
    )
