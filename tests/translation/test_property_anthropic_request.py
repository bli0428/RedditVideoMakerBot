"""Property-based tests for Anthropic request shape.

**Property 12: Anthropic request shape**
**Validates: Requirements 2.2, 2.4, 2.6**

Hypothesis-generate ``(model, max_output_tokens)`` configs and
``Reddit_Content`` inputs that trigger at least one translate call; capture
every ``messages.create`` kwargs invocation and assert ``model``,
``max_tokens``, and ``temperature == 0`` match.

Since ``Anthropic_Client`` lazy-imports ``anthropic`` inside its constructor,
we patch ``anthropic.Anthropic`` before constructing the client so the real
SDK is never called.
"""
from __future__ import annotations

import sys
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from utils.translation.anthropic_client import Anthropic_Client
from utils.translation.errors import TranslationConfigError

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Valid Claude model identifiers: non-empty strings without whitespace.
_model_strategy = st.text(
    alphabet=st.characters(
        whitelist_categories=("Lu", "Ll", "Nd", "Pc", "Pd"),
        whitelist_characters=".-_",
    ),
    min_size=1,
    max_size=64,
)

# max_output_tokens: positive integers in a realistic range.
_max_tokens_strategy = st.integers(min_value=1, max_value=8192)

# Non-empty text for translate/detect calls.
_nonempty_text = st.text(min_size=1, max_size=500)

# Target language codes.
_target_lang_strategy = st.sampled_from(["es", "fr", "de", "ja", "pt-BR", "zh-CN"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_anthropic_module() -> MagicMock:
    """Return a mock that stands in for the ``anthropic`` module.

    The mock's ``Anthropic()`` constructor returns a client whose
    ``messages.create`` returns a fake Message with one text block.
    """
    fake_block = MagicMock()
    fake_block.type = "text"
    fake_block.text = "translated text"

    fake_message = MagicMock()
    fake_message.content = [fake_block]

    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_message

    mock_anthropic = MagicMock()
    mock_anthropic.Anthropic.return_value = fake_client
    # Expose exception types so the except clauses in _call() resolve.
    mock_anthropic.AuthenticationError = Exception
    mock_anthropic.RateLimitError = Exception
    mock_anthropic.APITimeoutError = Exception
    mock_anthropic.APIError = Exception

    return mock_anthropic


def _build_client(
    model: str,
    max_output_tokens: int,
    mock_anthropic: MagicMock,
) -> tuple[Anthropic_Client, MagicMock]:
    """Construct an ``Anthropic_Client`` with the given config, injecting the
    mock anthropic module.  Returns ``(client, messages_create_mock)``."""
    with patch.dict(sys.modules, {"anthropic": mock_anthropic}):
        client = Anthropic_Client(
            api_key="test-key",
            model=model,
            max_output_tokens=max_output_tokens,
            temperature=0.0,
        )
    # The client now holds a reference to mock_anthropic.Anthropic()'s return
    # value as self._client.
    messages_create = client._client.messages.create
    return client, messages_create


# ---------------------------------------------------------------------------
# Property 12a: model in request matches configured model (Req 2.4)
# ---------------------------------------------------------------------------


@given(
    model=_model_strategy,
    max_output_tokens=_max_tokens_strategy,
    text=_nonempty_text,
    target_lang=_target_lang_strategy,
)
@settings(max_examples=100)
def test_request_model_matches_config(
    model: str,
    max_output_tokens: int,
    text: str,
    target_lang: str,
) -> None:
    """**Property 12: Anthropic request shape**
    **Validates: Requirements 2.4**

    The ``model`` kwarg passed to ``messages.create`` must equal the model
    identifier the client was configured with.
    """
    mock_anthropic = _make_mock_anthropic_module()
    client, messages_create = _build_client(model, max_output_tokens, mock_anthropic)

    with patch.dict(sys.modules, {"anthropic": mock_anthropic}):
        client.translate(text, target_lang)

    assert messages_create.called, "messages.create was never called"
    _, kwargs = messages_create.call_args
    assert kwargs.get("model") == model, (
        f"Expected model={model!r} in request kwargs, "
        f"got model={kwargs.get('model')!r}"
    )


# ---------------------------------------------------------------------------
# Property 12b: max_tokens in request matches configured max_output_tokens (Req 2.6)
# ---------------------------------------------------------------------------


@given(
    model=_model_strategy,
    max_output_tokens=_max_tokens_strategy,
    text=_nonempty_text,
    target_lang=_target_lang_strategy,
)
@settings(max_examples=100)
def test_request_max_tokens_matches_config(
    model: str,
    max_output_tokens: int,
    text: str,
    target_lang: str,
) -> None:
    """**Property 12: Anthropic request shape**
    **Validates: Requirements 2.6**

    The ``max_tokens`` kwarg passed to ``messages.create`` must equal the
    ``max_output_tokens`` the client was configured with.
    """
    mock_anthropic = _make_mock_anthropic_module()
    client, messages_create = _build_client(model, max_output_tokens, mock_anthropic)

    with patch.dict(sys.modules, {"anthropic": mock_anthropic}):
        client.translate(text, target_lang)

    assert messages_create.called, "messages.create was never called"
    _, kwargs = messages_create.call_args
    assert kwargs.get("max_tokens") == max_output_tokens, (
        f"Expected max_tokens={max_output_tokens!r} in request kwargs, "
        f"got max_tokens={kwargs.get('max_tokens')!r}"
    )


# ---------------------------------------------------------------------------
# Property 12c: temperature in request is exactly 0.0 (Req 2.2)
# ---------------------------------------------------------------------------


@given(
    model=_model_strategy,
    max_output_tokens=_max_tokens_strategy,
    text=_nonempty_text,
    target_lang=_target_lang_strategy,
)
@settings(max_examples=100)
def test_request_temperature_is_zero(
    model: str,
    max_output_tokens: int,
    text: str,
    target_lang: str,
) -> None:
    """**Property 12: Anthropic request shape**
    **Validates: Requirements 2.2**

    The ``temperature`` kwarg passed to ``messages.create`` must be exactly
    ``0.0`` for determinism.
    """
    mock_anthropic = _make_mock_anthropic_module()
    client, messages_create = _build_client(model, max_output_tokens, mock_anthropic)

    with patch.dict(sys.modules, {"anthropic": mock_anthropic}):
        client.translate(text, target_lang)

    assert messages_create.called, "messages.create was never called"
    _, kwargs = messages_create.call_args
    temperature = kwargs.get("temperature")
    assert temperature == 0.0, (
        f"Expected temperature=0.0 in request kwargs, got temperature={temperature!r}"
    )
    assert isinstance(temperature, float), (
        f"Expected temperature to be a float, got {type(temperature).__name__}"
    )


# ---------------------------------------------------------------------------
# Property 12d: all three invariants hold simultaneously across many calls
# ---------------------------------------------------------------------------


@given(
    model=_model_strategy,
    max_output_tokens=_max_tokens_strategy,
    texts=st.lists(_nonempty_text, min_size=1, max_size=5),
    target_lang=_target_lang_strategy,
)
@settings(max_examples=100)
def test_all_request_shape_invariants_hold_for_every_call(
    model: str,
    max_output_tokens: int,
    texts: list[str],
    target_lang: str,
) -> None:
    """**Property 12: Anthropic request shape**
    **Validates: Requirements 2.2, 2.4, 2.6**

    For every ``messages.create`` invocation across multiple translate calls,
    all three invariants (model, max_tokens, temperature) must hold.
    """
    mock_anthropic = _make_mock_anthropic_module()
    client, messages_create = _build_client(model, max_output_tokens, mock_anthropic)

    with patch.dict(sys.modules, {"anthropic": mock_anthropic}):
        for text in texts:
            client.translate(text, target_lang)

    assert messages_create.call_count == len(texts), (
        f"Expected {len(texts)} messages.create calls, "
        f"got {messages_create.call_count}"
    )

    for i, call_obj in enumerate(messages_create.call_args_list):
        _, kwargs = call_obj
        assert kwargs.get("model") == model, (
            f"Call {i}: expected model={model!r}, got {kwargs.get('model')!r}"
        )
        assert kwargs.get("max_tokens") == max_output_tokens, (
            f"Call {i}: expected max_tokens={max_output_tokens!r}, "
            f"got {kwargs.get('max_tokens')!r}"
        )
        assert kwargs.get("temperature") == 0.0, (
            f"Call {i}: expected temperature=0.0, "
            f"got {kwargs.get('temperature')!r}"
        )


# ---------------------------------------------------------------------------
# Property 12e: detect_source_language also sends correct model/max_tokens/temp
# ---------------------------------------------------------------------------


@given(
    model=_model_strategy,
    max_output_tokens=_max_tokens_strategy,
    sample=_nonempty_text,
)
@settings(max_examples=100)
def test_detect_request_shape_invariants(
    model: str,
    max_output_tokens: int,
    sample: str,
) -> None:
    """**Property 12: Anthropic request shape**
    **Validates: Requirements 2.2, 2.4, 2.6**

    ``detect_source_language`` also routes through ``_call``, so the same
    model/max_tokens/temperature invariants must hold for detection calls.
    """
    mock_anthropic = _make_mock_anthropic_module()
    client, messages_create = _build_client(model, max_output_tokens, mock_anthropic)

    with patch.dict(sys.modules, {"anthropic": mock_anthropic}):
        client.detect_source_language(sample)

    assert messages_create.called, "messages.create was never called for detect"
    _, kwargs = messages_create.call_args
    assert kwargs.get("model") == model, (
        f"detect: expected model={model!r}, got {kwargs.get('model')!r}"
    )
    assert kwargs.get("max_tokens") == max_output_tokens, (
        f"detect: expected max_tokens={max_output_tokens!r}, "
        f"got {kwargs.get('max_tokens')!r}"
    )
    assert kwargs.get("temperature") == 0.0, (
        f"detect: expected temperature=0.0, got {kwargs.get('temperature')!r}"
    )
