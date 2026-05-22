"""Detect likely gender from Reddit post text and pick an appropriate voice."""

import re
from typing import Literal

# ── Patterns ──────────────────────────────────────────────────────────────────
# Reddit age/gender tags like (25F), [30M], 25f, etc.
_AGE_GENDER_RE = re.compile(r"[\(\[]\s*\d{1,3}\s*([MmFf])\s*[\)\]]")

# Explicit self-identification phrases
_FEMALE_PHRASES = [
    r"\bi(?:'?m| am) (?:a )?(?:woman|female|girl|lady|mom|mother|wife|girlfriend|gf)\b",
    r"\bas a (?:woman|female|girl|lady|mom|mother|wife)\b",
    r"\bmy husband\b",
    r"\bmy boyfriend\b",
    r"\bmy bf\b",
    # Indirect: referring to an ex/partner with male pronouns implies female speaker
    r"\bmy ex.{0,50}\bhe\b",
    r"\bmy ex.{0,50}\bhis\b",
    r"\bmy ex.{0,50}\bhim\b",
    r"\bmy crush.{0,50}\bhe\b",
    r"\bmy crush.{0,50}\bhis\b",
    r"\bmy partner.{0,50}\bhe\b",
    r"\bmy partner.{0,50}\bhis\b",
    r"\bthis guy\b",
    r"\bthis boy\b",
    r"\bhe asked me out\b",
    r"\bhe broke up\b",
    r"\bhe cheated\b",
    r"\bhe proposed\b",
]

_MALE_PHRASES = [
    r"\bi(?:'?m| am) (?:a )?(?:man|male|guy|dude|dad|father|husband|boyfriend|bf)\b",
    r"\bas a (?:man|male|guy|dude|dad|father|husband)\b",
    r"\bmy wife\b",
    r"\bmy girlfriend\b",
    r"\bmy gf\b",
    # Indirect: referring to an ex/partner with female pronouns implies male speaker
    r"\bmy ex.{0,50}\bshe\b",
    r"\bmy ex.{0,50}\bher\b",
    r"\bmy crush.{0,50}\bshe\b",
    r"\bmy crush.{0,50}\bher\b",
    r"\bmy partner.{0,50}\bshe\b",
    r"\bmy partner.{0,50}\bher\b",
    r"\bthis girl\b",
    r"\bshe asked me out\b",
    r"\bshe broke up\b",
    r"\bshe cheated\b",
    r"\bshe proposed\b",
]

_FEMALE_RES = [re.compile(p, re.IGNORECASE) for p in _FEMALE_PHRASES]
_MALE_RES = [re.compile(p, re.IGNORECASE) for p in _MALE_PHRASES]


def detect_gender(text: str) -> Literal["male", "female", "unknown"]:
    """Scan text for gender indicators.

    Checks (in order):
      1. Reddit-style age/gender tags: (25F), [30M]
      2. Self-identification phrases: "I'm a guy", "as a woman", "my wife"

    Returns "male", "female", or "unknown".
    """
    # 1. Check for age/gender tags (most reliable)
    match = _AGE_GENDER_RE.search(text)
    if match:
        letter = match.group(1).upper()
        return "female" if letter == "F" else "male"

    # 2. Check phrase patterns
    female_score = sum(1 for r in _FEMALE_RES if r.search(text))
    male_score = sum(1 for r in _MALE_RES if r.search(text))

    if female_score > male_score:
        return "female"
    if male_score > female_score:
        return "male"

    return "unknown"


def pick_voice(text: str) -> str:
    """Pick an ElevenLabs voice ID based on detected gender.

    Uses elevenlabs_male_voice_ids / elevenlabs_female_voice_ids from config.
    These are comma-separated lists — one is picked randomly per call.
    Falls back to male voice for unknown gender.
    """
    import random
    from utils import settings

    male_raw = settings.config["settings"]["tts"].get("elevenlabs_male_voice_ids", "")
    female_raw = settings.config["settings"]["tts"].get("elevenlabs_female_voice_ids", "")

    male_ids = [v.strip() for v in male_raw.split(",") if v.strip()]
    female_ids = [v.strip() for v in female_raw.split(",") if v.strip()]

    gender = detect_gender(text)
    if gender == "male" and male_ids:
        return random.choice(male_ids)
    if gender == "female" and female_ids:
        return random.choice(female_ids)
    # Unknown or missing: pick from all available voices
    all_ids = male_ids + female_ids
    if all_ids:
        return random.choice(all_ids)
    return ""
