import base64
import json
import random
from pathlib import Path

from elevenlabs.client import ElevenLabs

from utils import settings


def _chars_to_words(alignment):
    """Convert character-level alignment to word-level timestamps.

    Args:
        alignment: CharacterAlignmentResponseModel with characters,
                   character_start_times_seconds, character_end_times_seconds

    Returns:
        list of {"word": str, "start": float, "end": float}
    """
    chars = alignment.characters
    starts = alignment.character_start_times_seconds
    ends = alignment.character_end_times_seconds

    words = []
    current_word = ""
    word_start = None

    for i, ch in enumerate(chars):
        if ch == " ":
            if current_word:
                words.append({
                    "word": current_word,
                    "start": word_start,
                    "end": ends[i - 1],
                })
                current_word = ""
                word_start = None
        else:
            if word_start is None:
                word_start = starts[i]
            current_word += ch

    # Last word
    if current_word and word_start is not None:
        words.append({
            "word": current_word,
            "start": word_start,
            "end": ends[len(chars) - 1],
        })

    return words


class elevenlabs:
    def __init__(self):
        self.max_chars = 2500
        self.client: ElevenLabs = None

    def run(self, text, filepath, random_voice: bool = False):
        if self.client is None:
            self.initialize()

        if random_voice:
            voice_name = self.randomvoice()
        else:
            voice_name = str(
                settings.config["settings"]["tts"].get("elevenlabs_voice_name", "")
            )

        # Resolve to voice_id — if it already looks like an ID, use it directly
        voice_id = self._resolve_voice(voice_name)

        # Generate audio with timestamps
        response = self.client.text_to_speech.convert_with_timestamps(
            voice_id=voice_id,
            text=text,
            model_id="eleven_multilingual_v2",
            output_format="mp3_44100_128",
        )

        # Save audio
        audio_bytes = base64.b64decode(response.audio_base_64)
        with open(filepath, "wb") as f:
            f.write(audio_bytes)

        # Save word-level timestamps alongside the audio
        if response.alignment:
            words = _chars_to_words(response.alignment)
            timestamps_path = Path(filepath).with_suffix(".json")
            with open(timestamps_path, "w") as f:
                json.dump(words, f, indent=2)

    def initialize(self):
        api_key = settings.config["settings"]["tts"].get("elevenlabs_api_key", "")
        if not api_key:
            raise ValueError(
                "You didn't set an ElevenLabs API key! "
                "Please set elevenlabs_api_key in config.toml."
            )
        self.client = ElevenLabs(api_key=api_key)

    def _resolve_voice(self, voice: str) -> str:
        """Accept a voice name or voice ID. If it looks like an ID (no spaces,
        20+ alphanumeric chars), use it directly. Otherwise look up by name."""
        # ElevenLabs voice IDs are typically 20-char alphanumeric strings
        if voice and len(voice) >= 15 and " " not in voice:
            return voice
        return self._get_voice_id(voice)

    def _get_voice_id(self, voice_name: str) -> str:
        """Look up a voice ID by name."""
        voices = self.client.voices.get_all()
        for voice in voices.voices:
            if voice.name.lower() == voice_name.lower():
                return voice.voice_id
        # Fallback: use the name as-is (might be a voice_id already)
        return voice_name

    def randomvoice(self):
        if self.client is None:
            self.initialize()
        return random.choice(self.client.voices.get_all().voices).name
