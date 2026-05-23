"""Alpha-composite primitives.

``composite_rgba_onto`` replaces the inlined ``_composite`` helper that was
previously in ``test_transition.py``.
"""

from __future__ import annotations

import numpy as np


def composite_rgba_onto(
    frame: np.ndarray,
    layer: np.ndarray,
    x: int,
    y: int,
) -> None:
    """Alpha-composite an RGBA *layer* onto an RGBA *frame* at position *(x, y)*.

    The operation is performed **in-place** on *frame*.  Both arrays must be
    ``uint8`` with shape ``(H, W, 4)``.  Out-of-bounds regions are silently
    clipped.

    Args:
        frame: Destination RGBA image (modified in-place).
        layer: Source RGBA image to composite onto *frame*.
        x:     Horizontal offset (pixels from the left edge of *frame*).
        y:     Vertical offset (pixels from the top edge of *frame*).
    """
    fh, fw = frame.shape[:2]
    ih, iw = layer.shape[:2]

    # Clamp source/destination rectangles to frame bounds.
    sx = max(0, -x)
    sy = max(0, -y)
    dx = max(0, x)
    dy = max(0, y)

    pw = min(iw - sx, fw - dx)
    ph = min(ih - sy, fh - dy)

    if pw <= 0 or ph <= 0:
        return

    src_region = layer[sy:sy + ph, sx:sx + pw]
    dst_region = frame[dy:dy + ph, dx:dx + pw]

    alpha = src_region[:, :, 3:4].astype(np.float32) / 255.0
    src_rgb = src_region[:, :, :3].astype(np.float32)
    dst_rgb = dst_region[:, :, :3].astype(np.float32)
    dst_alpha = dst_region[:, :, 3:4].astype(np.float32) / 255.0

    # Standard "over" compositing for both RGB and alpha channels.
    out_alpha = alpha + dst_alpha * (1.0 - alpha)
    # Avoid division by zero for fully transparent pixels.
    safe_alpha = np.where(out_alpha > 0, out_alpha, 1.0)
    out_rgb = (src_rgb * alpha + dst_rgb * dst_alpha * (1.0 - alpha)) / safe_alpha

    frame[dy:dy + ph, dx:dx + pw, :3] = np.clip(out_rgb, 0, 255).astype(np.uint8)
    frame[dy:dy + ph, dx:dx + pw, 3] = np.clip(out_alpha[:, :, 0] * 255, 0, 255).astype(np.uint8)
