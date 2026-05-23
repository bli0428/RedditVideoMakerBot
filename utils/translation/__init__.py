"""utils.translation — public API for the Translation_Service.

Re-exports the service, config, and error hierarchy so callers only need to
import from this package:

    from utils.translation import Translation_Service, TranslationConfig
    from utils.translation import TranslationError, TranslationConfigError
"""

from utils.translation.config import TranslationConfig
from utils.translation.errors import (
    TranslationAPIError,
    TranslationAuthError,
    TranslationConfigError,
    TranslationEmptyResponseError,
    TranslationError,
    TranslationRateLimitError,
    TranslationTimeoutError,
)
from utils.translation.service import Translation_Service

__all__ = [
    "Translation_Service",
    "TranslationConfig",
    "TranslationError",
    "TranslationConfigError",
    "TranslationAPIError",
    "TranslationAuthError",
    "TranslationRateLimitError",
    "TranslationTimeoutError",
    "TranslationEmptyResponseError",
]
