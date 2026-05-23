"""Translation error hierarchy for the Translation_Service.

All errors raised by Anthropic_Client and Translation_Service inherit from
TranslationError, allowing failure_policy logic to operate on a single
hierarchy without importing SDK exception types.
"""


class TranslationError(Exception):
    """Base class for translation-layer errors. All errors raised by
    Anthropic_Client and Translation_Service inherit from this."""


class TranslationConfigError(TranslationError):
    """Raised for misconfiguration: invalid temperature, missing API key,
    invalid failure_policy. Always propagates regardless of failure_policy
    because misconfiguration cannot be 'skipped past' meaningfully."""


class TranslationAPIError(TranslationError):
    """Generic Anthropic API error (non-auth, non-rate-limit, non-timeout,
    non-empty-response). Maps anthropic.APIError."""


class TranslationAuthError(TranslationError):
    """Anthropic authentication failure. Maps anthropic.AuthenticationError."""


class TranslationRateLimitError(TranslationError):
    """Anthropic rate limit hit. Maps anthropic.RateLimitError."""


class TranslationTimeoutError(TranslationError):
    """Anthropic request timed out. Maps anthropic.APITimeoutError."""


class TranslationEmptyResponseError(TranslationError):
    """Anthropic returned a Message with no text content (Req 6.3)."""
