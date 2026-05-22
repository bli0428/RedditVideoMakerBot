#!/usr/bin/env python3
"""Generate multiple videos in batch.

Fetches top posts, starting with all-time. Once upvote counts drop
below MIN_SCORE, expands to broader time filters to find more content.
"""

import json
import math
import sys
from os.path import exists
from pathlib import Path

from reddit.subreddit import _fetch_top, _fetch_submission, _RedditPost
from utils import settings
from utils.cleanup import cleanup
from utils.console import print_markdown, print_step, print_substep
from utils.ffmpeg_install import ffmpeg_install
from utils.id import extract_id
from utils.posttextparser import posttextparser
from utils.subreddit import _contains_blocked_words, already_done
from utils.voice import sanitize_text
from video_creation.background import (
    chop_background,
    download_background_audio,
    download_background_video,
    get_background_config,
)
from video_creation.final_video import make_final_video
from video_creation.voices import save_text_to_mp3

NUM_VIDEOS = 20
MIN_SCORE = 100

# Time filters in order of quality — we expand as we run out of good posts
TIME_FILTERS = ["all", "year", "month", "week"]
POSTS_PER_FETCH = 100


def load_done_ids():
    path = "video_creation/data/videos.json"
    if not exists(path):
        with open(path, "w") as f:
            json.dump([], f)
    with open(path, "r", encoding="utf-8") as f:
        return {v["id"] for v in json.load(f)}


def is_valid_post(post: _RedditPost, done_ids: set) -> bool:
    """Check if a post meets all criteria."""
    if str(post) in done_ids:
        return False
    if post.stickied:
        return False
    if post.over_18 and not settings.config["settings"]["allow_nsfw"]:
        return False
    if not post.is_self or not post.selftext:
        return False
    if len(post.selftext) < 200:
        return False
    max_len = settings.config["settings"].get("storymode_max_length", 1000)
    if len(post.selftext) > max_len:
        return False
    if _contains_blocked_words(post.title + " " + post.selftext):
        return False
    # Flair filter
    required_flair = settings.config["reddit"]["thread"].get("required_flair", "")
    if required_flair:
        flair = post.link_flair_text or ""
        if flair.lower() != required_flair.lower():
            return False
    return True


def fetch_candidates(subreddit: str) -> list:
    """Fetch posts across time filters, expanding when scores drop below MIN_SCORE."""
    candidates = []
    done_ids = load_done_ids()

    for tf in TIME_FILTERS:
        print_substep(f"Fetching top/{tf} posts...")
        posts = _fetch_top(subreddit, limit=POSTS_PER_FETCH, time_filter=tf)

        below_threshold = 0
        for post in posts:
            if not is_valid_post(post, done_ids):
                continue
            # Check if we've already added this post from a previous filter
            if any(c.id == post.id for c in candidates):
                continue
            candidates.append(post)

            if post.score < MIN_SCORE:
                below_threshold += 1

        print_substep(
            f"  Found {len(candidates)} valid candidates so far "
            f"({below_threshold} below {MIN_SCORE} score in this batch)"
        )

        # If we have enough high-quality posts, stop expanding
        high_quality = [c for c in candidates if c.score >= MIN_SCORE]
        if len(high_quality) >= NUM_VIDEOS:
            break

    # Sort by score descending — best posts first
    candidates.sort(key=lambda p: p.score, reverse=True)
    return candidates


def build_reddit_object(submission: _RedditPost) -> dict:
    """Build the reddit_object dict from a submission."""
    from reddit.subreddit import _fetch_avatar

    content = {
        "thread_url": f"https://www.reddit.com{submission.permalink}",
        "thread_title": submission.title,
        "thread_id": submission.id,
        "is_nsfw": submission.over_18,
        "author": submission.author or "Anonymous",
        "avatar_url": _fetch_avatar(submission.author),
        "comments": [],
    }

    if settings.config["settings"]["storymode"]:
        if settings.config["settings"]["storymodemethod"] == 1:
            content["thread_post"] = posttextparser(submission.selftext)
        else:
            content["thread_post"] = submission.selftext

    return content


def make_one_video(submission: _RedditPost, video_num: int) -> bool:
    """Generate one video. Returns True on success."""
    print_step(f"═══ Video {video_num}/{NUM_VIDEOS}: {submission.title[:60]}... (score: {submission.score}) ═══")

    try:
        reddit_object = build_reddit_object(submission)
        reddit_id = extract_id(reddit_object)
        print_substep(f"Post ID: {reddit_id}", style="bold blue")

        length, number_of_clips = save_text_to_mp3(reddit_object)
        length = math.ceil(length)

        bg_config = {
            "video": get_background_config("video"),
            "audio": get_background_config("audio"),
        }
        download_background_video(bg_config["video"])
        download_background_audio(bg_config["audio"])
        chop_background(bg_config, length, reddit_object)
        make_final_video(number_of_clips, length, reddit_object, bg_config)
        return True

    except Exception as e:
        print_substep(f"Failed: {e}", style="bold red")
        # Clean up temp files on failure
        try:
            reddit_id = extract_id(reddit_object)
            cleanup(reddit_id)
        except Exception:
            pass
        return False


if __name__ == "__main__":
    if sys.version_info.major != 3 or sys.version_info.minor not in [10, 11, 12]:
        print("Requires Python 3.10, 3.11, or 3.12.")
        sys.exit()

    ffmpeg_install()
    directory = Path().absolute()
    config = settings.check_toml(
        f"{directory}/utils/.config.template.toml", f"{directory}/config.toml"
    )
    if not config:
        sys.exit()

    # Force storymode
    settings.config["settings"]["storymode"] = True
    settings.config["settings"]["storymodemethod"] = 1

    subreddit = settings.config["reddit"]["thread"]["subreddit"]
    print_step(f"Batch generating {NUM_VIDEOS} videos from r/{subreddit}")

    candidates = fetch_candidates(subreddit)
    print_step(f"Found {len(candidates)} candidate posts")

    if not candidates:
        print_substep("No valid posts found!", style="bold red")
        sys.exit()

    success = 0
    failed = 0
    for i, post in enumerate(candidates):
        if success >= NUM_VIDEOS:
            break

        ok = make_one_video(post, success + 1)
        if ok:
            success += 1
        else:
            failed += 1

        print_substep(
            f"Progress: {success} done, {failed} failed, "
            f"{NUM_VIDEOS - success} remaining",
            style="bold blue",
        )

    print_step(f"Batch complete! {success}/{NUM_VIDEOS} videos generated. {failed} failures.")
