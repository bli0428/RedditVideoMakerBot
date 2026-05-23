"""Property test for temperature rejection.

**Property 13: Temperature != 0 rejection**
**Validates: Requirements 2.3**

Hypothesis-generate floats t != 0.0; assert
Anthropic_Client(api_key=..., model=..., max_output_tokens=..., temperature=t)
raises TranslationConfigError whose message contains repr(t).
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from utils.translation.errors import TranslationConfigError

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Generate finite floats that are NOT 0.0.
# We exclude NaN and infinity to keep repr() predictable, and filter out 0.0.
_nonzero_float = st.floats(
    allow_nan=False,
    allow_infinity=False,
).filter(lambda t: t != 0.0)


# ---------------------------------------------------------------------------
# Property 13: Temperature != 0 rejection
# ---------------------------------------------------------------------------


@given(t=_nonzero_float)
@settings(max_examples=200)
def test_nonzero_temperature_raises_config_error(t: float) -> None:
    """Anthropic_Client must raise TranslationConfigError for any temperature
    value other than 0.0, and the error message must contain repr(t) so the
    operator can identify the offending value (Req 2.3).
    """
    # Patch the anthropic SDK so the constructor never actually tries to
    # connect; the temperature check happens before the lazy import reaches
    # anthropic.Anthropic(), but we patch defensively to avoid ImportError
    # in environments where the SDK is not installed.
    mock_anthropic = MagicMock()
    mock_anthropic.Anthropic.return_value = MagicMock()

    with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
        with pytest.raises(TranslationConfigError) as exc_info:
            # Import inside the patch context so the lazy import inside
            # __init__ picks up the mock if it is reached.
            from utils.translation.anthropic_client import Anthropic_Client

            Anthropic_Client(
                api_key="test-key",
                model="claude-3-5-sonnet-latest",
                max_output_tokens=4096,
                temperature=t,
            )

    message = str(exc_info.value)
    assert repr(t) in message, (
        f"Error message should contain repr({t!r}) = {repr(t)!r}; "
        f"got message: {message!r}"
    )
