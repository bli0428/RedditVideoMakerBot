"""Anthropic SDK wrapper for Translation_Service.

This is the ONLY module in the project that imports the ``anthropic`` SDK
(Req 1.5, 1.6, 2.1). All SDK exception types are mapped to the
TranslationError hierarchy so callers never need to import ``anthropic``
themselves.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from utils.translation.errors import (
    TranslationAPIError,
    TranslationAuthError,
    TranslationConfigError,
    TranslationEmptyResponseError,
    TranslationRateLimitError,
    TranslationTimeoutError,
)
from utils.translation.prompts import (
    SYSTEM_PROMPT_DETECT,
    SYSTEM_PROMPT_TRANSLATE,
    user_prompt_detect,
    user_prompt_translate,
)

if TYPE_CHECKING:
    import anthropic


class Anthropic_Client:
    """Thin wrapper around the anthropic Python SDK.

    Owns:
        - SDK client construction (api_key).
        - Request building (system prompt, max_output_tokens, model, temperature=0).
        - Response parsing (extract text blocks; treat empty as failure).
        - SDK-exception-to-TranslationError mapping.

    Does NOT own:
        - failure_policy decisions (lives in Translation_Service).
        - Caching (lives in Translation_Cache).
        - Sanitization (lives in Translation_Service via utils.voice.sanitize_text).

    SDK exception mapping (Req 2.4):
        anthropic.AuthenticationError  -> TranslationAuthError
        anthropic.RateLimitError       -> TranslationRateLimitError
        anthropic.APITimeoutError      -> TranslationTimeoutError
        anthropic.APIError             -> TranslationAPIError
        empty content                  -> TranslationEmptyResponseError
    """

    def __init__(
        self,
        api_key: str,
        model: str,
        max_output_tokens: int,
        temperature: float = 0.0,
    ) -> None:
        """Construct the client.

        Args:
            api_key: Anthropic API key.
            model: Claude model identifier (e.g. "claude-3-5-sonnet-latest").
            max_output_tokens: Maximum tokens in each response.
            temperature: Must be exactly 0.0 for determinism (Req 2.3).

        Raises:
            TranslationConfigError: If temperature != 0.0.
        """
        if temperature != 0.0:
            raise TranslationConfigError(
                f"Anthropic_Client requires temperature=0 for determinism; "
                f"got temperature={temperature!r}"
            )
        # Lazy import: anthropic SDK is only imported here (Req 1.5, 1.6, 2.1)
        import anthropic  # noqa: PLC0415

        self._sdk = anthropic
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model
        self._max_output_tokens = max_output_tokens

    def detect_source_language(self, sample: str) -> str:
        """Return a BCP-47 / ISO 639-1 tag, e.g. 'en', 'es', 'pt-BR'.

        One Anthropic call. The sample is the joined detection sample from
        Translation_Service (title + body excerpt + first N comments).

        Args:
            sample: Short excerpt of the Reddit content to detect.

        Returns:
            Lowercase language tag string (e.g. "en", "es", "pt-br").
        """
        response = self._call(
            system=SYSTEM_PROMPT_DETECT,
            user=user_prompt_detect(sample),
        )
        return response.strip().lower()

    def translate(self, text: str, target_lang: str) -> str:
        """Translate text into target_lang. One Anthropic call per call.

        Args:
            text: Source text to translate.
            target_lang: BCP-47 / ISO 639-1 target language code.

        Returns:
            Translated text string.
        """
        response = self._call(
            system=SYSTEM_PROMPT_TRANSLATE,
            user=user_prompt_translate(text=text, target_lang=target_lang),
        )
        return response

    # ---- internals -------------------------------------------------------

    def _call(self, system: str, user: str) -> str:
        """Make one Anthropic messages.create call and return the text.

        Builds the request with model, max_tokens, temperature=0.0, system
        prompt, and a single user message. Maps SDK exceptions to the
        TranslationError hierarchy (Req 2.4).

        Args:
            system: System prompt string.
            user: User message string.

        Returns:
            Extracted text from the response.

        Raises:
            TranslationAuthError: On anthropic.AuthenticationError.
            TranslationRateLimitError: On anthropic.RateLimitError.
            TranslationTimeoutError: On anthropic.APITimeoutError.
            TranslationAPIError: On anthropic.APIError (catch-all).
            TranslationEmptyResponseError: When the response contains no text.
        """
        try:
            msg = self._client.messages.create(
                model=self._model,
                max_tokens=self._max_output_tokens,
                temperature=0.0,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
        except self._sdk.AuthenticationError as e:
            raise TranslationAuthError(str(e)) from e
        except self._sdk.RateLimitError as e:
            raise TranslationRateLimitError(str(e)) from e
        except self._sdk.APITimeoutError as e:
            raise TranslationTimeoutError(str(e)) from e
        except self._sdk.APIError as e:
            raise TranslationAPIError(str(e)) from e

        text = self._extract_text(msg)
        if not text or not text.strip():
            raise TranslationEmptyResponseError(
                f"Anthropic response contained no text (model={self._model})"
            )
        return text

    @staticmethod
    def _extract_text(msg) -> str:
        """Extract and concatenate all text blocks from an SDK Message.

        SDK responses have msg.content as a list of ContentBlock objects;
        each has a .type attribute ('text', 'tool_use', etc.). Only 'text'
        blocks are consumed and concatenated (Req 6.3).

        Args:
            msg: An anthropic Message object (or any object with a .content
                 attribute that is a list of blocks with .type and .text).

        Returns:
            Concatenated text from all text-type blocks. Empty string if
            there are no text blocks.
        """
        out = []
        for block in getattr(msg, "content", []) or []:
            if getattr(block, "type", None) == "text":
                out.append(getattr(block, "text", "") or "")
        return "".join(out)
