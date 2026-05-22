#!/usr/bin/env python3
"""
Preview script — tweak the settings block at the top, then run:

    python test_transition.py

and open test_transition.mp4.
"""

import os
import numpy as np
from moviepy import ColorClip, CompositeVideoClip, ImageClip, VideoClip, AudioFileClip, CompositeAudioClip
from PIL import Image, ImageDraw, ImageFont
from utils.card import render_card

# ── Settings ─────────────────────────────────────────────────────────────────
CARD_STYLE            = "reddit"   # "custom" | "reddit"
BODY_STYLE            = "karaoke"  # "card"   | "karaoke"
DISMISS_TITLE_ON_BODY = True       # fade header out when body starts
WORDS_PER_CHUNK       = 3          # karaoke only: how many words per flash (0 = full line)
# ─────────────────────────────────────────────────────────────────────────────

W, H = 1080, 1920

FONT_BOLD   = os.path.join("fonts", "Montserrat-ExtraBold.ttf")
FONT_NORMAL = os.path.join("fonts", "Roboto-Regular.ttf")

POST_TEXT = (
    "Today, I was getting sick of listening to the guy in the next "
    "cubicle talking loudly on the phone all day. I decided to send "
    "him an anonymous email telling him to shut up. I accidentally "
    "sent it to the entire office. FML"
)
TITLE = "TIFU by sending an anonymous email to my coworker"

# ── Step 1: split the full text into N-word chunks ───────────────────────────
# This is completely independent of how card.py wraps text.
all_words = POST_TEXT.split()
chunk_size = WORDS_PER_CHUNK if BODY_STYLE == "karaoke" and WORDS_PER_CHUNK > 0 else len(all_words)
chunks = [
    " ".join(all_words[i : i + chunk_size])
    for i in range(0, len(all_words), chunk_size)
]
print(f"Chunks ({len(chunks)} total, {chunk_size} words each):")
for i, c in enumerate(chunks):
    print(f"  {i}: {repr(c)}")

# ── Step 2: assign a start/end time to each chunk ────────────────────────────
# Simulate TTS at a fixed rate — no real audio needed for preview.
WORDS_PER_SEC = 3.0
word_dur = 1.0 / WORDS_PER_SEC

chunk_timings = []  # list of {"text", "start", "end"}
t = 0.0
for chunk in chunks:
    n = len(chunk.split())
    chunk_timings.append({"text": chunk, "start": t, "end": t + n * word_dur})
    t += n * word_dur

TITLE_DUR = 3.0
CONTENT_DUR = t
TOTAL_DUR = TITLE_DUR + CONTENT_DUR

print(f"\nTotal duration: {TOTAL_DUR:.1f}s  (title={TITLE_DUR}s + body={CONTENT_DUR:.1f}s)")

# ── Step 3: render the header card ───────────────────────────────────────────
os.makedirs("assets/temp/test_card", exist_ok=True)
header_path, _body_pages = render_card(
    style=CARD_STYLE,
    text=POST_TEXT,
    output_path="assets/temp/test_card/card.png",
    title=TITLE,
    author="throwaway_cubicle",
    avatar_url="https://styles.redditmedia.com/t5_3k30p/styles/profileIcon_uj015iwx9s7g1.png?width=256&height=256",
    subreddit="tifu",
    upvotes=42300,
    num_comments=1847,
)
header_img = np.array(Image.open(header_path).convert("RGBA"))

# ── Step 4: pre-render one caption image per chunk ───────────────────────────
FONT_SIZE    = 100
STROKE_W     = 12
TEXT_COLOR   = "white"
STROKE_COLOR = "black"
PAD          = 24
MAX_TEXT_W   = W - PAD * 4   # max text width before wrapping

def render_caption(text: str) -> np.ndarray:
    """Render text as a centred white-on-black-stroke caption image (RGBA)."""
    font = ImageFont.truetype(FONT_BOLD, FONT_SIZE)
    dummy_draw = ImageDraw.Draw(Image.new("RGBA", (1, 1)))

    # Word-wrap at MAX_TEXT_W
    lines, current = [], ""
    for word in text.split():
        candidate = (current + " " + word).strip()
        bb = dummy_draw.textbbox((0, 0), candidate, font=font)
        if bb[2] - bb[0] <= MAX_TEXT_W:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    if not lines:
        lines = [" "]

    LINE_GAP = 10
    bbs = [dummy_draw.textbbox((0, 0), l, font=font) for l in lines]
    widths  = [b[2] - b[0] for b in bbs]
    heights = [b[3] - b[1] for b in bbs]

    img_w = max(widths)  + PAD * 2 + STROKE_W * 2
    img_h = sum(heights) + LINE_GAP * (len(lines) - 1) + PAD * 2 + STROKE_W * 2
    img = Image.new("RGBA", (int(img_w), int(img_h)), (0, 0, 0, 0))
    d   = ImageDraw.Draw(img)

    y = PAD + STROKE_W
    for line, bb, w in zip(lines, bbs, widths):
        x = (img_w - w) / 2 - bb[0]
        d.text((x, y - bb[1]), line, font=font,
               fill=STROKE_COLOR, stroke_width=STROKE_W, stroke_fill=STROKE_COLOR)
        d.text((x, y - bb[1]), line, font=font, fill=TEXT_COLOR)
        y += bb[3] - bb[1] + LINE_GAP

    return np.array(img)

caption_imgs = [render_caption(ct["text"]) for ct in chunk_timings]

# ── Step 5: layout constants ──────────────────────────────────────────────────
DISPLAY_W     = int(W * 0.85)
h_scale       = DISPLAY_W / header_img.shape[1]
HEADER_DISP_H = int(header_img.shape[0] * h_scale)
HEADER_Y      = int(H * 0.10)   # resting position of header top edge
CAPTION_CY    = int(H * 0.60)   # vertical centre of caption text
POP_DUR       = 0.25            # header pop-in duration
DISMISS_DUR   = 0.35            # header fade-out duration
FADE_OUT_DUR  = 0.12            # caption fade-out before next chunk


def _composite(frame, img_arr, dst_x, dst_y):
    """Alpha-composite img_arr (RGBA numpy) onto frame (RGB numpy) at (dst_x, dst_y)."""
    ih, iw = img_arr.shape[:2]
    # Clamp to frame bounds
    sx = max(0, -dst_x);  dx = max(0, dst_x)
    sy = max(0, -dst_y);  dy = max(0, dst_y)
    pw = min(iw - sx, W - dx)
    ph = min(ih - sy, H - dy)
    if pw <= 0 or ph <= 0:
        return
    alpha = img_arr[sy:sy+ph, sx:sx+pw, 3:4].astype(np.float32) / 255.0
    src   = img_arr[sy:sy+ph, sx:sx+pw, :3].astype(np.float32)
    dst   = frame[dy:dy+ph, dx:dx+pw].astype(np.float32)
    frame[dy:dy+ph, dx:dx+pw] = (src * alpha + dst * (1 - alpha)).astype(np.uint8)


def make_frame(t):
    frame = np.full((H, W, 3), 40, dtype=np.uint8)

    # ── Header ────────────────────────────────────────────────────────────────
    # Pop-in: scale 80%→100% over POP_DUR
    if t < POP_DUR:
        s = 0.8 + 0.2 * (1 - (1 - t / POP_DUR) ** 4)
    else:
        s = 1.0

    # Dismiss: fade out over DISMISS_DUR once body starts
    if DISMISS_TITLE_ON_BODY and t >= TITLE_DUR:
        elapsed = t - TITLE_DUR
        h_alpha = max(0.0, 1.0 - elapsed / DISMISS_DUR)
    else:
        h_alpha = 1.0

    if h_alpha > 0:
        cw = max(1, int(DISPLAY_W * s))
        ch = max(1, int(HEADER_DISP_H * s))
        h_pil = Image.fromarray(header_img).resize((cw, ch), Image.LANCZOS)
        h_arr = np.array(h_pil)
        # Apply dismiss alpha
        if h_alpha < 1.0:
            h_arr = h_arr.copy()
            h_arr[:, :, 3] = (h_arr[:, :, 3].astype(np.float32) * h_alpha).astype(np.uint8)
        hx = (W - cw) // 2
        hy = HEADER_Y - (ch - HEADER_DISP_H) // 2   # grow from centre
        _composite(frame, h_arr, hx, hy)

    # ── Body ──────────────────────────────────────────────────────────────────
    if t >= TITLE_DUR:
        tb = t - TITLE_DUR   # time within body section

        if BODY_STYLE == "karaoke":
            # Find the active chunk
            active = None
            for i, ct in enumerate(chunk_timings):
                if tb >= ct["start"]:
                    active = i
            if active is not None:
                ct    = chunk_timings[active]
                c_arr = caption_imgs[active].copy()

                # Pop-in from chunk start
                elapsed = tb - ct["start"]
                if elapsed < POP_DUR:
                    s2 = 0.8 + 0.2 * (1 - (1 - elapsed / POP_DUR) ** 4)
                    nw = max(1, int(c_arr.shape[1] * s2))
                    nh = max(1, int(c_arr.shape[0] * s2))
                    c_arr = np.array(Image.fromarray(c_arr).resize((nw, nh), Image.LANCZOS))

                # Fade out before next chunk
                if active + 1 < len(chunk_timings):
                    time_left = chunk_timings[active + 1]["start"] - tb
                else:
                    time_left = ct["end"] - tb
                if 0 <= time_left < FADE_OUT_DUR:
                    c_arr = c_arr.copy()
                    c_arr[:, :, 3] = (c_arr[:, :, 3] * (time_left / FADE_OUT_DUR)).astype(np.uint8)

                ch2, cw2 = c_arr.shape[:2]
                cx = (W - cw2) // 2
                cy = CAPTION_CY - ch2 // 2
                _composite(frame, c_arr, cx, cy)

        else:  # "card" — use the body pages from render_card
            # Load body pages lazily (only in card mode)
            if not hasattr(make_frame, "_body_imgs"):
                make_frame._body_imgs = []
                make_frame._body_lts  = []
                wi = 0
                for bp_path, bp_positions in _body_pages:
                    make_frame._body_imgs.append(
                        np.array(Image.open(bp_path).convert("RGBA"))
                    )
                    for lp in bp_positions:
                        n = len(lp["text"].split())
                        s_t = chunk_timings[wi]["start"] if wi < len(chunk_timings) else CONTENT_DUR
                        e_t = chunk_timings[min(wi + n - 1, len(chunk_timings)-1)]["end"]
                        make_frame._body_lts.append({**lp, "start": s_t, "end": e_t, "page": len(make_frame._body_imgs)-1})
                        wi += 1

            # Find active page by which lines have started
            active_page = 0
            for lt in make_frame._body_lts:
                if tb >= lt["start"]:
                    active_page = lt["page"]

            page_lts = [lt for lt in make_frame._body_lts if lt["page"] == active_page]
            bp_img   = make_frame._body_imgs[active_page]
            ph_img   = bp_img.shape[0]

            mask_top = page_lts[0]["y_top"] if page_lts else 0
            bottom   = mask_top
            for lt in page_lts:
                if tb >= lt["start"]:
                    prog  = min(1.0, (tb - lt["start"]) / 0.3)
                    eased = 1 - (1 - prog) ** 3
                    bottom = max(bottom, int(lt["y_top"] + (lt["y_bottom"] - lt["y_top"]) * eased))

            if bottom > mask_top:
                masked = bp_img.copy()
                masked[bottom:, :, 3] = 0
                bh, bw = masked.shape[:2]
                dh = int(bh * DISPLAY_W / bw)
                b_pil = Image.fromarray(masked).resize((DISPLAY_W, dh), Image.LANCZOS)
                bx = (W - DISPLAY_W) // 2
                by = int(H * 0.55)
                _composite(frame, np.array(b_pil), bx, by)

    return frame


# ── Watermark ─────────────────────────────────────────────────────────────────
wm_font = ImageFont.truetype(FONT_NORMAL, 44)
wm_text = "Gameplay from Dino Duel"
wm_bb   = wm_font.getbbox(wm_text)
wm_w    = wm_bb[2] - wm_bb[0] + 20
wm_h    = wm_bb[3] - wm_bb[1] + 14
wm_img  = Image.new("RGBA", (wm_w, wm_h), (0, 0, 0, 0))
ImageDraw.Draw(wm_img).text((10, 5), wm_text, font=wm_font, fill=(255, 255, 255, 255))

# ── Assemble ──────────────────────────────────────────────────────────────────
bg        = ColorClip((W, H), color=(40, 40, 40), duration=TOTAL_DUR)
video     = VideoClip(make_frame, duration=TOTAL_DUR).with_fps(30)
watermark = (
    ImageClip(np.array(wm_img), duration=TOTAL_DUR)
    .with_opacity(0.3)
    .with_position(("center", H - wm_h - 30))
)
final = CompositeVideoClip([bg, video, watermark], size=(W, H)).with_duration(TOTAL_DUR)

pop_sfx_path = "assets/sfx/pop.wav"
if os.path.exists(pop_sfx_path):
    pop = AudioFileClip(pop_sfx_path).with_start(0).with_volume_scaled(0.25)
    final = final.with_audio(CompositeAudioClip([pop]))

out = "test_transition.mp4"
print(f"\nRendering → {out}")
print(f"  CARD_STYLE={CARD_STYLE!r}  BODY_STYLE={BODY_STYLE!r}")
print(f"  DISMISS_TITLE_ON_BODY={DISMISS_TITLE_ON_BODY}  WORDS_PER_CHUNK={WORDS_PER_CHUNK}")
final.write_videofile(out, fps=30, codec="libx264", audio_codec="aac", preset="ultrafast", logger="bar")
print(f"\nDone — open {out}")
