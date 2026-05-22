import re

import requests

from utils import settings
from utils.ai_methods import sort_by_similarity
from utils.console import print_step, print_substep
from utils.posttextparser import posttextparser
from utils.subreddit import _contains_blocked_words, get_subreddit_undone
from utils.videos import check_done
from utils.voice import sanitize_text

# Reddit's public JSON API — no API key or OAuth required.
_HEADERS = {
    "User-Agent": "RedditVideoMakerBot/4.0 (public JSON; no auth)",
    "Accept": "application/json",
}


class _RedditPost:
    """Lightweight stand-in for praw.models.Submission so the rest of the
    codebase can keep using attribute access (submission.title, etc.)."""

    def __init__(self, data: dict):
        self._data = data
        self.id: str = data["id"]
        self.title: str = data.get("title", "")
        self.selftext: str = data.get("selftext", "")
        self.score: int = data.get("score", 0)
        self.upvote_ratio: float = data.get("upvote_ratio", 0.0)
        self.num_comments: int = data.get("num_comments", 0)
        self.permalink: str = data.get("permalink", "")
        self.over_18: bool = data.get("over_18", False)
        self.stickied: bool = data.get("stickied", False)
        self.is_self: bool = data.get("is_self", True)
        self.author: str | None = data.get("author")
        self.link_flair_text: str | None = data.get("link_flair_text")

    def __str__(self) -> str:
        """Return the post ID — matches praw.models.Submission.__str__."""
        return self.id


class _RedditComment:
    """Lightweight stand-in for praw.models.Comment."""

    def __init__(self, data: dict):
        self.id: str = data["id"]
        self.body: str = data.get("body", "")
        self.permalink: str = data.get("permalink", "")
        self.stickied: bool = data.get("stickied", False)
        self.author: str | None = data.get("author")


def _fetch_json(url: str, params: dict | None = None) -> dict:
    """GET a Reddit .json URL and return the parsed response."""
    resp = requests.get(url, headers=_HEADERS, params=params, timeout=20)
    resp.raise_for_status()
    return resp.json()


def _fetch_top(subreddit: str, limit: int = 25, time_filter: str = "all") -> list[_RedditPost]:
    """Return top posts for a subreddit via the public JSON endpoint."""
    data = _fetch_json(f"https://www.reddit.com/r/{subreddit}/top.json", {"limit": limit, "t": time_filter, "raw_json": 1})
    posts = []
    for child in data["data"]["children"]:
        posts.append(_RedditPost(child["data"]))
    return posts


def _fetch_submission(post_id: str) -> _RedditPost:
    """Fetch a single submission by ID."""
    data = _fetch_json(f"https://www.reddit.com/comments/{post_id}.json", {"raw_json": 1})
    # Reddit returns a two-element list: [post listing, comments listing]
    return _RedditPost(data[0]["data"]["children"][0]["data"])


def _fetch_avatar(username: str | None) -> str:
    """Fetch a Reddit user's profile picture URL. Returns empty string on failure."""
    if not username:
        return ""
    try:
        import html
        data = _fetch_json(f"https://www.reddit.com/user/{username}/about.json", {"raw_json": 1})
        icon = data.get("data", {}).get("icon_img", "")
        # Clean up HTML entities and strip query params after the image extension
        icon = html.unescape(icon)
        return icon
    except Exception:
        return ""


def _fetch_comments(post_id: str) -> list[_RedditComment]:
    """Fetch top-level comments for a submission."""
    data = _fetch_json(f"https://www.reddit.com/comments/{post_id}.json", {"limit": 200, "raw_json": 1})
    comments = []
    for child in data[1]["data"]["children"]:
        if child["kind"] != "t1":  # skip "more" stubs
            continue
        comments.append(_RedditComment(child["data"]))
    return comments


def get_subreddit_threads(POST_ID: str):
    """
    Returns a list of threads from the chosen subreddit using Reddit's
    public JSON endpoints (no API key / OAuth required).
    """

    print_substep("Fetching from Reddit (public JSON, no login required).")

    content = {}

    # Ask user for subreddit input
    print_step("Getting subreddit threads...")
    similarity_score = 0
    if not settings.config["reddit"]["thread"]["subreddit"]:
        try:
            subreddit_name = re.sub(r"r/", "", input("What subreddit would you like to pull from? "))
        except ValueError:
            subreddit_name = "askreddit"
            print_substep("Subreddit not defined. Using AskReddit.")
    else:
        sub = settings.config["reddit"]["thread"]["subreddit"]
        print_substep(f"Using subreddit: r/{sub} from TOML config")
        subreddit_name = sub
        if str(subreddit_name).casefold().startswith("r/"):
            subreddit_name = subreddit_name[2:]

    if POST_ID:
        submission = _fetch_submission(POST_ID)

    elif (
        settings.config["reddit"]["thread"]["post_id"]
        and len(str(settings.config["reddit"]["thread"]["post_id"]).split("+")) == 1
    ):
        submission = _fetch_submission(settings.config["reddit"]["thread"]["post_id"])
    elif settings.config["ai"]["ai_similarity_enabled"]:
        threads = _fetch_top(subreddit_name, limit=50)
        keywords = settings.config["ai"]["ai_similarity_keywords"].split(",")
        keywords = [keyword.strip() for keyword in keywords]
        keywords_print = ", ".join(keywords)
        print(f"Sorting threads by similarity to the given keywords: {keywords_print}")
        threads, similarity_scores = sort_by_similarity(threads, keywords)
        submission, similarity_score = get_subreddit_undone(
            threads, subreddit_name, similarity_scores=similarity_scores
        )
    else:
        threads = _fetch_top(subreddit_name, limit=25)
        submission = get_subreddit_undone(threads, subreddit_name)

    if submission is None:
        return get_subreddit_threads(POST_ID)  # submission already done — rerun

    elif not submission.num_comments and settings.config["settings"]["storymode"] == "false":
        print_substep("No comments found. Skipping.")
        exit()

    submission = check_done(submission)  # double-checking

    upvotes = submission.score
    ratio = submission.upvote_ratio * 100
    num_comments = submission.num_comments
    threadurl = f"https://www.reddit.com{submission.permalink}"

    print_substep(f"Video will be: {submission.title} :thumbsup:", style="bold green")
    print_substep(f"Thread url is: {threadurl} :thumbsup:", style="bold green")
    print_substep(f"Thread has {upvotes} upvotes", style="bold blue")
    print_substep(f"Thread has a upvote ratio of {ratio}%", style="bold blue")
    print_substep(f"Thread has {num_comments} comments", style="bold blue")
    if similarity_score:
        print_substep(
            f"Thread has a similarity score up to {round(similarity_score * 100)}%",
            style="bold blue",
        )

    content["thread_url"] = threadurl
    content["thread_title"] = submission.title
    content["thread_id"] = submission.id
    content["is_nsfw"] = submission.over_18
    content["author"] = submission.author or "Anonymous"
    content["avatar_url"] = _fetch_avatar(submission.author)
    content["comments"] = []
    if settings.config["settings"]["storymode"]:
        if settings.config["settings"]["storymodemethod"] == 1:
            content["thread_post"] = posttextparser(submission.selftext)
        else:
            content["thread_post"] = submission.selftext
    else:
        comments = _fetch_comments(submission.id)
        for comment in comments:
            if comment.body in ["[removed]", "[deleted]"]:
                continue
            if _contains_blocked_words(comment.body):
                continue
            if not comment.stickied:
                sanitised = sanitize_text(comment.body)
                if not sanitised or sanitised == " ":
                    continue
                if len(comment.body) <= int(
                    settings.config["reddit"]["thread"]["max_comment_length"]
                ):
                    if len(comment.body) >= int(
                        settings.config["reddit"]["thread"]["min_comment_length"]
                    ):
                        if comment.author is not None and sanitize_text(comment.body) is not None:
                            content["comments"].append(
                                {
                                    "comment_body": comment.body,
                                    "comment_url": comment.permalink,
                                    "comment_id": comment.id,
                                }
                            )

    print_substep("Received subreddit threads Successfully.", style="bold green")
    return content
