"""Temporary validation script for _strategies.py."""
from tests._strategies import (
    multi_paragraph_text,
    pathological_text,
    splitting_config,
    degenerate_config,
    template_string,
    reddit_content,
)
from hypothesis import given, settings as h_settings

@given(text=multi_paragraph_text(min_size=50, max_size=200))
@h_settings(max_examples=50)
def test_max_size(text):
    assert len(text) <= 200
    assert len(text) >= 50

test_max_size()
print("max_size constraint: OK")

@given(text=pathological_text(length=200))
@h_settings(max_examples=20)
def test_no_whitespace(text):
    assert len(text) == 200
    assert not any(c.isspace() for c in text)
    assert not any(c in ".!?," for c in text)

test_no_whitespace()
print("pathological_text no-whitespace/no-punctuation: OK")

@given(cfg=splitting_config())
@h_settings(max_examples=100)
def test_min_part_length_bound(cfg):
    s = cfg["splitting"]
    assert s["min_part_length"] <= s["soft_max_length"] // 2

test_min_part_length_bound()
print("splitting_config min_part_length bound: OK")

@given(rc=reddit_content())
@h_settings(max_examples=20)
def test_reddit_content_types(rc):
    assert isinstance(rc["thread_id"], str)
    assert isinstance(rc["thread_title"], str)
    assert isinstance(rc["thread_post"], str)
    assert isinstance(rc["comments"], list)
    assert isinstance(rc["is_nsfw"], bool)
    assert isinstance(rc["author"], str)
    assert isinstance(rc["subreddit_name"], str)

test_reddit_content_types()
print("reddit_content types: OK")

print("All validation tests passed.")
