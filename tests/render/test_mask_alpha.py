"""Property test for mask-equals-frame-alpha at every timestamp.

# Feature: card-rendering-refactor, Property 4

**Validates: Requirements 4.2**

Property 4: Mask equals frame alpha at every timestamp.

For any ``make_frame: float -> ndarray(H, W, 4)`` and any timestamp ``t``,
the ``VideoClip`` produced by ``FrameCompositor.build_clip(make_frame).mask``
SHALL have ``get_frame(t)`` equal to
``make_frame(t)[:, :, 3].astype(float32) / 255.0`` element-wise.
"""

from __future__ import annotations

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from video_creation.render.compositor.frame import FrameCompositor


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Small fixed dimensions to keep tests fast while still exercising the logic.
_HEIGHTS = st.integers(min_value=1, max_value=16)
_WIDTHS = st.integers(min_value=1, max_value=16)


@st.composite
def rgba_frame_and_timestamp(draw):
    """Generate a fixed RGBA ndarray and a timestamp in [0.0, 1.0].

    Returns
    -------
    tuple[callable, float]
        ``(make_frame, t)`` where ``make_frame`` is a lambda that always
        returns the same generated RGBA array, and ``t`` is a float in
        ``[0.0, 1.0]``.
    """
    h = draw(_HEIGHTS)
    w = draw(_WIDTHS)

    # Generate a uint8 RGBA array of shape (H, W, 4).
    flat = draw(
        st.lists(
            st.integers(min_value=0, max_value=255),
            min_size=h * w * 4,
            max_size=h * w * 4,
        )
    )
    frame = np.array(flat, dtype=np.uint8).reshape(h, w, 4)

    # Wrap in a lambda so it matches the make_frame(t) -> ndarray contract.
    make_frame = lambda t, _f=frame: _f  # noqa: E731

    # Timestamp in [0.0, 1.0] — the clip duration is 1.0 second.
    t = draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False))

    return make_frame, t


# ---------------------------------------------------------------------------
# Property test
# ---------------------------------------------------------------------------


@given(inputs=rgba_frame_and_timestamp())
@settings(max_examples=30)
def test_mask_equals_frame_alpha(inputs):
    """Property 4: Mask equals frame alpha at every timestamp.

    **Validates: Requirements 4.2**

    For any make_frame and any t, the mask clip's get_frame(t) must equal
    make_frame(t)[:, :, 3].astype(float32) / 255.0 element-wise.
    """
    make_frame, t = inputs

    compositor = FrameCompositor(fps=30)
    clip = compositor.build_clip(duration=1.0, make_frame=make_frame)

    # Retrieve the mask frame at timestamp t.
    mask_frame = clip.mask.get_frame(t)

    # Compute the expected alpha channel.
    expected = make_frame(t)[:, :, 3].astype(np.float32) / 255.0

    assert np.allclose(mask_frame, expected), (
        f"Mask frame does not match expected alpha at t={t}.\n"
        f"  mask_frame shape: {mask_frame.shape}, dtype: {mask_frame.dtype}\n"
        f"  expected shape:   {expected.shape}, dtype: {expected.dtype}\n"
        f"  max abs diff: {np.max(np.abs(mask_frame - expected))}"
    )
