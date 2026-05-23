"""Snapshot tests for utils/translation/prompts.py.

Pins SYSTEM_PROMPT_DETECT and SYSTEM_PROMPT_TRANSLATE byte-for-byte against
the committed expected strings, and verifies the user-prompt builder functions
produce the expected output for concrete inputs.

Requirements: 2.5, 14.3
"""
from __future__ import annotations

from utils.translation.prompts import (
    SYSTEM_PROMPT_DETECT,
    SYSTEM_PROMPT_TRANSLATE,
    user_prompt_detect,
    user_prompt_translate,
)

# ---------------------------------------------------------------------------
# Expected strings (committed snapshots)
# ---------------------------------------------------------------------------

_EXPECTED_SYSTEM_PROMPT_DETECT = (
    "You are a language detector for short Reddit excerpts.\n"
    "\n"
    "The user will send you a single string consisting of a Reddit post title,\n"
    "followed by a snippet of the post body, followed by up to a few short\n"
    "comments, separated by ' | '. Some excerpts mix languages, contain slang,\n"
    "or contain profanity.\n"
    "\n"
    "Your job:\n"
    "- Identify the dominant language of the excerpt.\n"
    "- Reply with ONE language tag and nothing else. Use BCP-47 / ISO 639-1\n"
    "  codes (e.g. 'en', 'es', 'pt-BR', 'ja', 'zh-CN').\n"
    "- Do NOT include explanations, punctuation, quotes, or markdown.\n"
    "- Do NOT prefix your answer with 'Language:' or any other label.\n"
    "- If the excerpt is too short or ambiguous to detect, reply 'und'.\n"
)

_EXPECTED_SYSTEM_PROMPT_TRANSLATE = (
    "You translate Reddit posts and comments.\n"
    "\n"
    "Rules:\n"
    "- Translate the user's text into the target language they specify.\n"
    "- Preserve the original casual register: keep slang, profanity, internet\n"
    "  shorthand, and tone exactly as forceful or casual as the source.\n"
    "- Preserve line breaks and paragraph structure.\n"
    "- Do NOT add commentary, notes, summaries, or warnings.\n"
    "- Do NOT wrap your output in quotation marks, code fences, or markdown.\n"
    "- Do NOT translate proper nouns, usernames, or URLs.\n"
    "- Output ONLY the translated text, raw, ready to be displayed verbatim.\n"
    "- If the input is empty or whitespace-only, output the input unchanged.\n"
)

# ---------------------------------------------------------------------------
# Snapshot tests for module-level constants
# ---------------------------------------------------------------------------


def test_system_prompt_detect_snapshot() -> None:
    """SYSTEM_PROMPT_DETECT must match the committed byte-for-byte snapshot.

    Validates: Requirements 2.5, 14.3
    """
    assert SYSTEM_PROMPT_DETECT == _EXPECTED_SYSTEM_PROMPT_DETECT, (
        "SYSTEM_PROMPT_DETECT has changed from the committed snapshot.\n"
        f"Expected:\n{_EXPECTED_SYSTEM_PROMPT_DETECT!r}\n\n"
        f"Got:\n{SYSTEM_PROMPT_DETECT!r}"
    )


def test_system_prompt_translate_snapshot() -> None:
    """SYSTEM_PROMPT_TRANSLATE must match the committed byte-for-byte snapshot.

    Validates: Requirements 2.5, 14.3
    """
    assert SYSTEM_PROMPT_TRANSLATE == _EXPECTED_SYSTEM_PROMPT_TRANSLATE, (
        "SYSTEM_PROMPT_TRANSLATE has changed from the committed snapshot.\n"
        f"Expected:\n{_EXPECTED_SYSTEM_PROMPT_TRANSLATE!r}\n\n"
        f"Got:\n{SYSTEM_PROMPT_TRANSLATE!r}"
    )


# ---------------------------------------------------------------------------
# Example-based tests for user-prompt builder functions
# ---------------------------------------------------------------------------


def test_user_prompt_detect_hello() -> None:
    """user_prompt_detect('hello') must return the expected string.

    Validates: Requirements 2.5
    """
    result = user_prompt_detect("hello")
    expected = (
        "Detect the dominant language of the following Reddit excerpt:\n\nhello"
    )
    assert result == expected, (
        f"user_prompt_detect('hello') returned unexpected value.\n"
        f"Expected: {expected!r}\nGot: {result!r}"
    )


def test_user_prompt_translate_hi_es() -> None:
    """user_prompt_translate(text='hi', target_lang='es') must return the expected string.

    Validates: Requirements 2.5, 14.3
    """
    result = user_prompt_translate(text="hi", target_lang="es")
    expected = (
        "Translate the following text into the language with code "
        "'es'. Output only the translation, no quotes, no "
        "markdown, no commentary.\n\n---\nhi\n---"
    )
    assert result == expected, (
        f"user_prompt_translate(text='hi', target_lang='es') returned unexpected value.\n"
        f"Expected: {expected!r}\nGot: {result!r}"
    )
