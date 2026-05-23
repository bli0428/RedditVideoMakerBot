import random

from gtts import gTTS

from utils import settings
from utils.console import print_substep


class GTTS:
    def __init__(self):
        self.max_chars = 5000
        self.voices = []

    def run(self, text, filepath, random_voice: bool = False):
        # Locale precedence (Req 10.5, 10.6):
        # 1. [translation] target_lang if non-empty
        # 2. [reddit.thread] post_lang if non-empty
        # 3. "en" with a warning
        lang = settings.config.get("translation", {}).get("target_lang", "")
        if not lang:
            lang = settings.config["reddit"]["thread"]["post_lang"]
        if not lang:
            print_substep(
                "[warn] No translation locale available (neither [translation].target_lang "
                "nor [reddit.thread].post_lang is set); falling back to 'en'.",
                style="yellow",
            )
            lang = "en"
        tts = gTTS(
            text=text,
            lang=lang,
            slow=False,
        )
        tts.save(filepath)

    def randomvoice(self):
        return random.choice(self.voices)
