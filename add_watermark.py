#!/usr/bin/env python3
"""Add a watermark to existing videos in a results folder.

Usage: python add_watermark.py results/whowouldwin/
"""

import os
import sys
from pathlib import Path

import numpy as np
from moviepy import AudioFileClip, CompositeVideoClip, ImageClip, VideoFileClip
from PIL import Image, ImageDraw, ImageFont

WATERMARK_TEXT = "Gameplay from Dino Duel"
FONT_SIZE = 44
OPACITY = 0.3


def create_watermark(W, H, duration):
    font = ImageFont.truetype(os.path.join("fonts", "Roboto-Regular.ttf"), FONT_SIZE)
    bbox = font.getbbox(WATERMARK_TEXT)
    wm_w = bbox[2] - bbox[0] + 20
    wm_h = bbox[3] - bbox[1] + 14
    img = Image.new("RGBA", (wm_w, wm_h), (0, 0, 0, 0))
    ImageDraw.Draw(img).text((10, 5), WATERMARK_TEXT, font=font, fill=(255, 255, 255, 255))
    return (
        ImageClip(np.array(img), duration=duration)
        .with_opacity(OPACITY)
        .with_position(("center", H - wm_h - 30))
    )


def add_watermark(input_path, output_path):
    print(f"  Processing: {input_path}")
    video = VideoFileClip(str(input_path))
    W, H = video.size
    wm = create_watermark(W, H, video.duration)
    final = CompositeVideoClip([video, wm], size=(W, H))
    final.write_videofile(
        str(output_path),
        fps=30,
        codec="libx264",
        audio_codec="aac",
        bitrate="20M",
        preset="medium",
        logger="bar",
    )
    video.close()
    print(f"  Saved: {output_path}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python add_watermark.py <folder>")
        print("Example: python add_watermark.py results/whowouldwin/")
        sys.exit(1)

    folder = Path(sys.argv[1])
    if not folder.is_dir():
        print(f"Not a directory: {folder}")
        sys.exit(1)

    videos = list(folder.glob("*.mp4"))
    if not videos:
        print(f"No .mp4 files found in {folder}")
        sys.exit(1)

    # Create output folder
    out_folder = folder / "watermarked"
    out_folder.mkdir(exist_ok=True)

    print(f"Adding watermark to {len(videos)} videos...")
    for vid in videos:
        output = out_folder / vid.name
        try:
            add_watermark(vid, output)
        except Exception as e:
            print(f"  FAILED: {vid.name} — {e}")

    print(f"\nDone! Watermarked videos in: {out_folder}")
