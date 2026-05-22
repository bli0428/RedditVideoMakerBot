#!/usr/bin/env python3
"""Test: split card — header top, body bottom with mask reveal."""

import os
import numpy as np
from moviepy import AudioFileClip, CompositeAudioClip, CompositeVideoClip, ColorClip, VideoClip
from PIL import Image, ImageDraw, ImageFont
from utils.card import render_post_card

W, H = 1080, 1920
POP_SFX = "assets/sfx/pop.wav"

POST_TEXT = (
    "Today, I was getting sick of listening to the guy in the next "
    "cubicle talking loudly on the phone all day. I decided to send "
    "him an anonymous email telling him to shut up. I accidentally "
    "sent it to the entire office. FML"
)
TITLE = "TIFU by sending an anonymous email to my coworker"

os.makedirs("assets/temp/test_card", exist_ok=True)
header_path, body_pages = render_post_card(
    POST_TEXT, "assets/temp/test_card/card.png",
    title=TITLE, author="throwaway_cubicle", source="reddit",
    avatar_url="https://styles.redditmedia.com/t5_3k30p/styles/profileIcon_uj015iwx9s7g1.png?width=256&height=256",
)

header_img = np.array(Image.open(header_path).convert("RGBA"))
# Use first body page for the test
body_path, line_positions = body_pages[0]
body_img = np.array(Image.open(body_path).convert("RGBA"))
body_h_px, body_w_px = body_img.shape[:2]

print(f"Header: {header_img.shape[1]}x{header_img.shape[0]}")
print(f"Body: {body_w_px}x{body_h_px}, {len(line_positions)} lines")
for i, lp in enumerate(line_positions):
    print(f"  {i}: y={lp['y_top']}-{lp['y_bottom']}  {lp['text'][:50]}")

# Simulated word timestamps
words = POST_TEXT.split()
WORDS_PER_SEC = 3.0
word_timestamps = []
t = 0.0
for w in words:
    dur = 1.0 / WORDS_PER_SEC
    word_timestamps.append({"word": w, "start": t, "end": t + dur})
    t += dur

line_timings = []
word_idx = 0
for lp in line_positions:
    lw = lp["text"].split()
    n = min(len(lw), len(word_timestamps) - word_idx)
    if n <= 0:
        break
    s = word_timestamps[word_idx]["start"]
    e = word_timestamps[word_idx + n - 1]["end"]
    line_timings.append({"y_top": lp["y_top"], "y_bottom": lp["y_bottom"], "start": s, "end": e})
    word_idx += n

TITLE_DUR = 3.0
CONTENT_DUR = word_timestamps[-1]["end"] + 1.0
TOTAL_DUR = TITLE_DUR + CONTENT_DUR

DISPLAY_W = int(W * 0.85)
h_scale = DISPLAY_W / header_img.shape[1]
b_scale = DISPLAY_W / body_w_px
HEADER_DISP_H = int(header_img.shape[0] * h_scale)
BODY_DISP_H = int(body_h_px * b_scale)

HEADER_Y_START = int(H * 0.12)
HEADER_Y_END = int(H * 0.08)
BODY_Y = int(H * 0.55)
SCROLL_TIME = 0.3
BODY_MASK_START = line_positions[0]["y_top"] if line_positions else body_h_px

# Pop-in scale for header
POP_DUR = 0.25
ZOOM_AMT = 0.10


def get_body_mask_bottom(t):
    bottom = BODY_MASK_START
    for lt in line_timings:
        if t >= lt["start"]:
            elapsed = t - lt["start"]
            progress = min(1.0, elapsed / SCROLL_TIME)
            eased = 1 - (1 - progress) ** 3
            lb = lt["y_top"] + (lt["y_bottom"] - lt["y_top"]) * eased
            bottom = max(bottom, int(lb))
    return min(bottom, body_h_px)


def get_header_scale(t):
    if t < POP_DUR:
        progress = t / POP_DUR
        eased = 1 - (1 - progress) ** 4
        return 0.8 + 0.2 * eased
    zoom_progress = (t - POP_DUR) / max(0.01, TOTAL_DUR - POP_DUR)
    return 1.0 + ZOOM_AMT * zoom_progress


def make_frame(t):
    frame = np.full((H, W, 3), 50, dtype=np.uint8)

    # Header with pop-in + slow drift up
    scale = get_header_scale(t)
    cur_w = int(DISPLAY_W * scale)
    cur_h = int(HEADER_DISP_H * scale)
    h_pil = Image.fromarray(header_img).resize((cur_w, cur_h), Image.LANCZOS)
    h_arr = np.array(h_pil)

    # Center horizontally
    x = (W - cur_w) // 2
    # Drift upward
    slide_progress = min(1.0, t / TOTAL_DUR)
    base_y = int(HEADER_Y_START + (HEADER_Y_END - HEADER_Y_START) * slide_progress)
    # Pin center so pop grows from center
    base_center_y = base_y + HEADER_DISP_H // 2
    y_off = base_center_y - cur_h // 2

    a = h_arr[:, :, 3:4].astype(np.float32) / 255.0
    ph = min(cur_h, H - max(0, y_off))
    pw = min(cur_w, W - max(0, x))
    if y_off < 0:
        src_y = -y_off
        dst_y = 0
        ph = min(cur_h - src_y, H)
    else:
        src_y = 0
        dst_y = y_off
    if x < 0:
        src_x = -x
        dst_x = 0
        pw = min(cur_w - src_x, W)
    else:
        src_x = 0
        dst_x = x

    if ph > 0 and pw > 0:
        bg = frame[dst_y:dst_y+ph, dst_x:dst_x+pw].astype(np.float32)
        rgb = h_arr[src_y:src_y+ph, src_x:src_x+pw, :3].astype(np.float32)
        al = a[src_y:src_y+ph, src_x:src_x+pw]
        frame[dst_y:dst_y+ph, dst_x:dst_x+pw] = (rgb * al + bg * (1 - al)).astype(np.uint8)

    # Body (mask reveal) — completely invisible until text starts
    if t >= TITLE_DUR:
        mb = get_body_mask_bottom(t - TITLE_DUR)
        # Only show if we've revealed past the initial mask start
        if mb > BODY_MASK_START:
            masked = body_img.copy()
            masked[mb:, :, 3] = 0
            b_pil = Image.fromarray(masked).resize((DISPLAY_W, BODY_DISP_H), Image.LANCZOS)
            b_arr = np.array(b_pil)
            bx = (W - DISPLAY_W) // 2
            a2 = b_arr[:, :, 3:4].astype(np.float32) / 255.0
            ph2 = min(BODY_DISP_H, H - BODY_Y)
            bg2 = frame[BODY_Y:BODY_Y+ph2, bx:bx+DISPLAY_W].astype(np.float32)
            frame[BODY_Y:BODY_Y+ph2, bx:bx+DISPLAY_W] = (b_arr[:ph2, :, :3].astype(np.float32) * a2[:ph2] + bg2 * (1 - a2[:ph2])).astype(np.uint8)

    return frame


video = VideoClip(make_frame, duration=TOTAL_DUR).with_fps(30)

# Watermark
from moviepy import ImageClip
watermark_font = ImageFont.truetype(os.path.join("fonts", "Roboto-Regular.ttf"), 44)
wm_text = "Gameplay from Dino Duel"
wm_bbox = watermark_font.getbbox(wm_text)
wm_w = wm_bbox[2] - wm_bbox[0] + 20
wm_h = wm_bbox[3] - wm_bbox[1] + 14
wm_img = Image.new("RGBA", (wm_w, wm_h), (0, 0, 0, 0))
ImageDraw.Draw(wm_img).text((10, 5), wm_text, font=watermark_font, fill=(255, 255, 255, 255))
wm_arr = np.array(wm_img)
watermark = (
    ImageClip(wm_arr, duration=TOTAL_DUR)
    .with_opacity(0.3)
    .with_position(("center", H - wm_h - 30))
)

bg = ColorClip(size=(W, H), color=(50, 50, 50), duration=TOTAL_DUR)
final = CompositeVideoClip([bg, video, watermark], size=(W, H)).with_duration(TOTAL_DUR)

pop_sfx = AudioFileClip(POP_SFX).with_start(0).with_volume_scaled(0.25)
final = final.with_audio(CompositeAudioClip([pop_sfx]))

print(f"\nRendering {TOTAL_DUR:.1f}s test_transition.mp4 ...")
final.write_videofile(
    "test_transition.mp4", fps=30, codec="libx264",
    audio_codec="aac", preset="ultrafast", logger="bar",
)
print("Done! Open test_transition.mp4 to preview.")
