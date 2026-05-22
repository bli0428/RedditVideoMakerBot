import json
import multiprocessing
import os
import re
import textwrap
from os.path import exists
from pathlib import Path
from typing import Dict, Final, Tuple

import ffmpeg
import numpy as np
import translators
from moviepy import (
    AudioFileClip,
    CompositeAudioClip,
    CompositeVideoClip,
    ImageClip,
    TextClip,
    VideoClip,
    VideoFileClip,
    concatenate_audioclips,
)
from moviepy.video.fx import CrossFadeOut, FadeIn, FadeOut
from PIL import Image, ImageDraw, ImageFont
from rich.console import Console
from rich.progress import track

from utils import settings
from utils.cleanup import cleanup
from utils.console import print_step, print_substep
from utils.id import extract_id
from utils.thumbnail import create_thumbnail
from utils.videos import save_data

console = Console()

# ── Transition settings ──────────────────────────────────────────────────────
FADE_DURATION = 0.4
ZOOM_AMOUNT = 0.10
CAPTION_FONT = os.path.join("fonts", "Montserrat-ExtraBold.ttf")
CAPTION_FONT_SIZE = 100
CAPTION_COLOR = "white"
CAPTION_STROKE_COLOR = "black"
CAPTION_STROKE_WIDTH = 12


# ── Helpers ──────────────────────────────────────────────────────────────────

def _pop_and_zoom(clip, pop_duration=0.25, zoom_amount=ZOOM_AMOUNT):
    """Quick snap 80%→100% then slow zoom."""
    def _resize_func(t):
        if t < pop_duration:
            progress = t / pop_duration
            eased = 1 - (1 - progress) ** 4
            return 0.8 + 0.2 * eased
        zoom_progress = (t - pop_duration) / (clip.duration - pop_duration)
        return 1.0 + zoom_amount * zoom_progress
    return clip.resized(_resize_func)


def _apply_zoom(clip, zoom_amount=ZOOM_AMOUNT):
    return clip.resized(lambda t: 1 + zoom_amount * (t / clip.duration))


def name_normalize(name: str) -> str:
    name = re.sub(r'[?\\"%*:|<>]', "", name)
    name = re.sub(r"( [w,W]\s?\/\s?[o,O,0])", r" without", name)
    name = re.sub(r"( [w,W]\s?\/)", r" with", name)
    name = re.sub(r"(\d+)\s?\/\s?(\d+)", r"\1 of \2", name)
    name = re.sub(r"(\w+)\s?\/\s?(\w+)", r"\1 or \2", name)
    name = re.sub(r"\/", r"", name)
    lang = settings.config["reddit"]["thread"]["post_lang"]
    if lang:
        translated_name = translators.translate_text(name, translator="google", to_language=lang)
        return translated_name
    return name


def prepare_background(reddit_id: str, W: int, H: int) -> str:
    """Scale, crop, and apply random visual tweaks to the background video.
    
    Random per-video variations (to avoid duplicate content flags):
      - Hue shift: ±15 degrees
      - Brightness: ±8%
      - Contrast: ±10%
      - Saturation: ±15%
    """
    import random

    output_path = f"assets/temp/{reddit_id}/background_noaudio.mp4"

    # Random visual tweaks
    hue_shift = random.uniform(-15, 15)
    brightness = random.uniform(-0.08, 0.08)
    contrast = random.uniform(0.9, 1.1)
    saturation = random.uniform(0.85, 1.15)

    stream = (
        ffmpeg.input(f"assets/temp/{reddit_id}/background.mp4")
        .filter("scale", W, H, force_original_aspect_ratio="increase")
        .filter("crop", W, H)
        .filter("hue", h=hue_shift, s=saturation)
        .filter("eq", brightness=brightness, contrast=contrast)
    )

    output = (
        stream.output(
            output_path, an=None,
            **{"c:v": "libx264", "b:v": "20M", "threads": multiprocessing.cpu_count()},
        )
        .overwrite_output()
    )
    try:
        output.run(quiet=True)
    except ffmpeg.Error as e:
        print(e.stderr.decode("utf8"))
        exit(1)
    return output_path


def get_text_height(draw, text, font, max_width):
    lines = textwrap.wrap(text, width=max_width)
    total_height = 0
    for line in lines:
        _, _, _, height = draw.textbbox((0, 0), line, font=font)
        total_height += height
    return total_height


def create_fancy_thumbnail(image, text, text_color, padding, wrap=35):
    font_title_size = 47
    font = ImageFont.truetype(os.path.join("fonts", "Roboto-Bold.ttf"), font_title_size)
    image_width, image_height = image.size
    draw = ImageDraw.Draw(image)
    text_height = get_text_height(draw, text, font, wrap)
    lines = textwrap.wrap(text, width=wrap)
    new_image_height = image_height + text_height + padding * (len(lines) - 1) - 50
    top_part_height = image_height // 2
    middle_part_height = 1
    bottom_part_height = image_height - top_part_height - middle_part_height
    top_part = image.crop((0, 0, image_width, top_part_height))
    middle_part = image.crop((0, top_part_height, image_width, top_part_height + middle_part_height))
    bottom_part = image.crop((0, top_part_height + middle_part_height, image_width, image_height))
    new_middle_height = max(1, new_image_height - top_part_height - bottom_part_height)
    middle_part = middle_part.resize((image_width, new_middle_height))
    new_image = Image.new("RGBA", (image_width, new_image_height))
    new_image.paste(top_part, (0, 0))
    new_image.paste(middle_part, (0, top_part_height))
    new_image.paste(bottom_part, (0, top_part_height + new_middle_height))
    draw = ImageDraw.Draw(new_image)
    y = top_part_height + padding
    for line in lines:
        draw.text((120, y), line, font=font, fill=text_color, align="left")
        y += get_text_height(draw, line, font, wrap) + padding
    username_font = ImageFont.truetype(os.path.join("fonts", "Roboto-Bold.ttf"), 30)
    draw.text(
        (205, 825), settings.config["settings"]["channel_name"],
        font=username_font, fill=text_color, align="left",
    )
    return new_image


# ── Caption rendering ────────────────────────────────────────────────────────

def _strip_emojis(text: str) -> str:
    """Remove emoji characters from text."""
    return re.sub(
        r"[\U0001F600-\U0001F64F"  # emoticons
        r"\U0001F300-\U0001F5FF"   # symbols & pictographs
        r"\U0001F680-\U0001F6FF"   # transport & map
        r"\U0001F1E0-\U0001F1FF"   # flags
        r"\U00002702-\U000027B0"   # dingbats
        r"\U000024C2-\U0001F251"   # misc
        r"\U0001F900-\U0001F9FF"   # supplemental
        r"\U0001FA00-\U0001FA6F"   # chess symbols
        r"\U0001FA70-\U0001FAFF"   # symbols extended
        r"\U00002600-\U000026FF"   # misc symbols
        r"\U0000FE00-\U0000FE0F"   # variation selectors
        r"\U0000200D"              # zero width joiner
        r"]+", "", text
    ).strip()


def _render_caption_image(text: str, max_width: int, W: int) -> str:
    """Render a caption as a PNG image with text wrapping, stroke outline,
    and return the path. Uses Pillow for full control over styling."""
    text = _strip_emojis(text)
    if not text:
        text = " "
    # Strip leading/trailing punctuation for cleaner captions
    text = re.sub(r'^[\s,.\-;:!?\'\"]+|[\s,.\-;:!?\'\"]+$', '', text)
    if not text:
        text = " "
    font = ImageFont.truetype(CAPTION_FONT, CAPTION_FONT_SIZE)

    # Wrap text to fit within max_width
    chars_per_line = max(10, int(max_width / (CAPTION_FONT_SIZE * 0.55)))
    lines = textwrap.wrap(text, width=chars_per_line)
    if not lines:
        lines = [" "]

    # Measure total size
    dummy = Image.new("RGBA", (1, 1))
    draw = ImageDraw.Draw(dummy)
    line_heights = []
    line_widths = []
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        line_widths.append(bbox[2] - bbox[0])
        line_heights.append(bbox[3] - bbox[1])

    padding = 20
    stroke = CAPTION_STROKE_WIDTH
    img_w = max(line_widths) + padding * 2 + stroke * 2
    img_h = sum(line_heights) + (len(lines) - 1) * 10 + padding * 2 + stroke * 2

    # Draw
    img = Image.new("RGBA", (int(img_w), int(img_h)), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    y = padding
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        lw = bbox[2] - bbox[0]
        x = (img_w - lw) / 2
        # Stroke
        draw.text((x, y), line, font=font, fill=CAPTION_STROKE_COLOR,
                   stroke_width=stroke, stroke_fill=CAPTION_STROKE_COLOR)
        # Fill
        draw.text((x, y), line, font=font, fill=CAPTION_COLOR)
        y += bbox[3] - bbox[1] + 10

    return img


# ── Main video assembly ──────────────────────────────────────────────────────

def make_final_video(
    number_of_clips: int,
    length: int,
    reddit_obj: dict,
    background_config: Dict[str, Tuple],
):
    """Assemble the final video:
      - Title card with pop-in + zoom
      - Post body read aloud with sentence-by-sentence captions
      - Background video with subtle zoom
    """
    W: Final[int] = int(settings.config["settings"]["resolution_w"])
    H: Final[int] = int(settings.config["settings"]["resolution_h"])
    opacity = settings.config["settings"]["opacity"]
    reddit_id = extract_id(reddit_obj)

    allow_only_tts: bool = (
        settings.config["settings"]["background"]["enable_extra_audio"]
        and settings.config["settings"]["background"]["background_audio_volume"] != 0
    )

    print_step("Creating the final video 🎥")

    # ── 1. Prepare background ─────────────────────────────────────────────
    bg_path = prepare_background(reddit_id, W=W, H=H)
    background = VideoFileClip(bg_path).resized((W, H))

    # ── 2. Collect audio ──────────────────────────────────────────────────
    title_width = int(W * 0.85)

    if settings.config["settings"]["storymode"]:
        if settings.config["settings"]["storymodemethod"] == 0:
            audio_paths = [
                f"assets/temp/{reddit_id}/mp3/title.mp3",
                f"assets/temp/{reddit_id}/mp3/postaudio.mp3",
            ]
            # For method 0, the post is one big audio file
            sentences = [reddit_obj.get("thread_post", "")]
        else:
            audio_paths = [f"assets/temp/{reddit_id}/mp3/title.mp3"] + [
                f"assets/temp/{reddit_id}/mp3/postaudio-{i}.mp3"
                for i in range(number_of_clips + 1)
            ]
            # thread_post is a list of sentences from posttextparser
            sentences = reddit_obj.get("thread_post", [])
    else:
        # Non-story mode: title + comments read aloud
        audio_paths = [f"assets/temp/{reddit_id}/mp3/title.mp3"] + [
            f"assets/temp/{reddit_id}/mp3/{i}.mp3" for i in range(number_of_clips)
        ]
        sentences = [c["comment_body"] for c in reddit_obj["comments"][:number_of_clips]]

    audio_durations = []
    for ap in audio_paths:
        info = ffmpeg.probe(ap)
        audio_durations.append(float(info["format"]["duration"]))

    # ── 3. Build audio track ──────────────────────────────────────────────
    AUDIO_SPEED = 1.15  # speed up TTS slightly for punchier delivery

    tts_clips = [AudioFileClip(ap).with_speed_scaled(AUDIO_SPEED) for ap in audio_paths]
    # Adjust durations to match the sped-up audio
    audio_durations = [d / AUDIO_SPEED for d in audio_durations]
    tts_audio = concatenate_audioclips(tts_clips)

    bg_audio_vol = settings.config["settings"]["background"]["background_audio_volume"]
    if bg_audio_vol > 0 and exists(f"assets/temp/{reddit_id}/background.mp3"):
        bg_music = AudioFileClip(f"assets/temp/{reddit_id}/background.mp3").with_volume_scaled(
            bg_audio_vol
        )
        if bg_music.duration >= tts_audio.duration:
            bg_music = bg_music.subclipped(0, tts_audio.duration)
        final_audio = CompositeAudioClip([tts_audio, bg_music])
    else:
        final_audio = tts_audio

    total_duration = sum(audio_durations)
    console.log(f"[bold green] Video will be: {int(total_duration)} seconds long")

    # ── 4. Render split post cards (header top, body bottom) ────────────
    from utils.card import render_post_card
    import random

    Path(f"assets/temp/{reddit_id}/png").mkdir(parents=True, exist_ok=True)

    post_text = ""
    if settings.config["settings"]["storymode"]:
        post_data = reddit_obj.get("thread_post", [])
        if isinstance(post_data, list):
            post_text = " ".join(post_data)
        else:
            post_text = str(post_data)
    else:
        post_text = " ".join(c["comment_body"] for c in reddit_obj.get("comments", [])[:number_of_clips])

    post_text = _strip_emojis(post_text)
    author = reddit_obj.get("author", "Anonymous")
    subreddit = settings.config["reddit"]["thread"].get("subreddit", "")

    card_path = f"assets/temp/{reddit_id}/png/card.png"
    header_path, body_pages = render_post_card(
        post_text, card_path,
        title=_strip_emojis(reddit_obj.get("thread_title", "")),
        author=author, avatar_url=reddit_obj.get("avatar_url", ""),
        source="reddit", subreddit=subreddit,
    )

    header_img = np.array(Image.open(header_path).convert("RGBA"))
    # Load all body page images
    body_page_imgs = []
    all_line_positions = []
    for bp_path, bp_positions in body_pages:
        body_page_imgs.append(np.array(Image.open(bp_path).convert("RGBA")))
        all_line_positions.extend(bp_positions)
    line_positions = all_line_positions

    # Map lines to audio timing
    content_audio_paths = audio_paths[1:]
    content_durations = audio_durations[1:]

    all_word_timestamps = []
    time_offset = 0.0
    for idx_ap, ap in enumerate(content_audio_paths):
        ts_path = Path(ap).with_suffix(".json")
        if ts_path.exists():
            with open(ts_path, "r") as f:
                words = json.load(f)
            for w in words:
                all_word_timestamps.append({
                    "word": w["word"],
                    "start": w["start"] / AUDIO_SPEED + time_offset,
                    "end": w["end"] / AUDIO_SPEED + time_offset,
                })
        time_offset += content_durations[idx_ap]

    line_timings = []
    word_idx = 0
    for lp in line_positions:
        line_words = lp["text"].split()
        n = len(line_words)
        if word_idx + n > len(all_word_timestamps):
            n = max(0, len(all_word_timestamps) - word_idx)
        if n <= 0:
            prev_end = line_timings[-1]["end"] if line_timings else 0
            line_timings.append({"y_top": lp["y_top"], "y_bottom": lp["y_bottom"], "start": prev_end, "end": prev_end + 1.0})
            continue
        start = all_word_timestamps[word_idx]["start"]
        end = all_word_timestamps[word_idx + n - 1]["end"]
        line_timings.append({"y_top": lp["y_top"], "y_bottom": lp["y_bottom"], "start": start, "end": end})
        word_idx += n

    # Display sizing
    title_len = len(reddit_obj.get("thread_title", ""))
    text_len = len(post_text)
    total_content_len = title_len + text_len
    if total_content_len < 300:
        card_width_pct = 0.90
    elif total_content_len < 600:
        card_width_pct = 0.85
    elif total_content_len < 900:
        card_width_pct = 0.78
    else:
        card_width_pct = 0.72

    DISPLAY_W = int(W * card_width_pct)
    h_scale = DISPLAY_W / header_img.shape[1]
    HEADER_DISP_H = int(header_img.shape[0] * h_scale)

    SCROLL_TIME = 0.3
    y_var = random.randint(-30, 30)
    HEADER_Y_START = int(H * 0.12) + y_var
    HEADER_Y_END = int(H * 0.08) + y_var
    BODY_Y = int(H * 0.55) + y_var
    POP_DUR = 0.25

    title_dur = audio_durations[0]
    content_total_dur = sum(content_durations)
    total_card_dur = title_dur + content_total_dur

    # Build page timing: which page is active at which time, with per-page line timings
    LINES_PER_PAGE = 6
    page_line_timings = []  # list of [(line_timing, ...), ...] per page
    page_imgs = body_page_imgs
    lt_idx = 0
    for page_idx, (bp_path, bp_positions) in enumerate(body_pages):
        page_lt = []
        for lp in bp_positions:
            if lt_idx < len(line_timings):
                page_lt.append(line_timings[lt_idx])
                lt_idx += 1
        page_line_timings.append(page_lt)

    def get_active_page_and_mask(t):
        """Return (page_index, mask_bottom_in_page_img) for time t."""
        # Find which page we're on based on which lines have started
        active_page = 0
        for pi, plt in enumerate(page_line_timings):
            if plt and t >= plt[0]["start"]:
                active_page = pi

        # Get mask bottom within the active page
        plt = page_line_timings[active_page]
        bp_positions = body_pages[active_page][1]
        mask_start = bp_positions[0]["y_top"] if bp_positions else 0
        bottom = mask_start
        for lt in plt:
            if t >= lt["start"]:
                elapsed = t - lt["start"]
                progress = min(1.0, elapsed / SCROLL_TIME)
                eased = 1 - (1 - progress) ** 3
                line_bottom = lt["y_top"] + (lt["y_bottom"] - lt["y_top"]) * eased
                bottom = max(bottom, int(line_bottom))
        page_h = page_imgs[active_page].shape[0]
        return active_page, min(bottom, page_h), mask_start

    def get_header_scale(t):
        if t < POP_DUR:
            progress = t / POP_DUR
            eased = 1 - (1 - progress) ** 4
            return 0.8 + 0.2 * eased
        zoom_progress = (t - POP_DUR) / max(0.01, total_card_dur - POP_DUR)
        return 1.0 + ZOOM_AMOUNT * zoom_progress

    # Combined frame renderer with pop-in header + mask-reveal body
    def make_combined_frame(t):
        frame = np.zeros((H, W, 3), dtype=np.uint8)

        # Header with pop-in + drift up
        scale = get_header_scale(t)
        cur_w = int(DISPLAY_W * scale)
        cur_h = int(HEADER_DISP_H * scale)
        h_pil = Image.fromarray(header_img).resize((cur_w, cur_h), Image.LANCZOS)
        h_arr = np.array(h_pil)
        x = (W - cur_w) // 2
        slide_progress = min(1.0, t / total_card_dur)
        base_y = int(HEADER_Y_START + (HEADER_Y_END - HEADER_Y_START) * slide_progress)
        base_center_y = base_y + HEADER_DISP_H // 2
        y_off = base_center_y - cur_h // 2
        a = h_arr[:, :, 3:4].astype(np.float32) / 255.0
        # Bounds
        src_y = max(0, -y_off)
        dst_y = max(0, y_off)
        src_x = max(0, -x)
        dst_x = max(0, x)
        ph = min(cur_h - src_y, H - dst_y)
        pw = min(cur_w - src_x, W - dst_x)
        if ph > 0 and pw > 0:
            bg = frame[dst_y:dst_y+ph, dst_x:dst_x+pw].astype(np.float32)
            rgb = h_arr[src_y:src_y+ph, src_x:src_x+pw, :3].astype(np.float32)
            al = a[src_y:src_y+ph, src_x:src_x+pw]
            frame[dst_y:dst_y+ph, dst_x:dst_x+pw] = (rgb * al + bg * (1 - al)).astype(np.uint8)

        # Body — invisible until text starts, swaps pages every 6 lines
        if t >= title_dur:
            page_idx, mb, mask_start = get_active_page_and_mask(t - title_dur)
            if mb > mask_start:
                cur_body = page_imgs[page_idx].copy()
                cur_body[mb:, :, 3] = 0
                cur_h, cur_w = cur_body.shape[:2]
                disp_h = int(cur_h * (DISPLAY_W / cur_w))
                b_pil = Image.fromarray(cur_body).resize((DISPLAY_W, disp_h), Image.LANCZOS)
                b_arr = np.array(b_pil)
                bx = (W - DISPLAY_W) // 2
                a2 = b_arr[:, :, 3:4].astype(np.float32) / 255.0
                ph2 = min(disp_h, H - BODY_Y)
                bg2 = frame[BODY_Y:BODY_Y+ph2, bx:bx+DISPLAY_W].astype(np.float32)
                frame[BODY_Y:BODY_Y+ph2, bx:bx+DISPLAY_W] = (b_arr[:ph2, :, :3].astype(np.float32) * a2[:ph2] + bg2 * (1 - a2[:ph2])).astype(np.uint8)

        return frame

    def make_combined_mask(t):
        mask = np.zeros((H, W), dtype=np.float64)

        # Header mask
        scale = get_header_scale(t)
        cur_w = int(DISPLAY_W * scale)
        cur_h = int(HEADER_DISP_H * scale)
        h_pil = Image.fromarray(header_img).resize((cur_w, cur_h), Image.LANCZOS)
        h_arr = np.array(h_pil)
        x = (W - cur_w) // 2
        slide_progress = min(1.0, t / total_card_dur)
        base_y = int(HEADER_Y_START + (HEADER_Y_END - HEADER_Y_START) * slide_progress)
        base_center_y = base_y + HEADER_DISP_H // 2
        y_off = base_center_y - cur_h // 2
        src_y = max(0, -y_off)
        dst_y = max(0, y_off)
        src_x = max(0, -x)
        dst_x = max(0, x)
        ph = min(cur_h - src_y, H - dst_y)
        pw = min(cur_w - src_x, W - dst_x)
        if ph > 0 and pw > 0:
            mask[dst_y:dst_y+ph, dst_x:dst_x+pw] = h_arr[src_y:src_y+ph, src_x:src_x+pw, 3] / 255.0

        # Body mask — swaps pages
        if t >= title_dur:
            page_idx, mb, mask_start = get_active_page_and_mask(t - title_dur)
            if mb > mask_start:
                cur_body = page_imgs[page_idx].copy()
                cur_body[mb:, :, 3] = 0
                cur_h, cur_w = cur_body.shape[:2]
                disp_h = int(cur_h * (DISPLAY_W / cur_w))
                b_pil = Image.fromarray(cur_body).resize((DISPLAY_W, disp_h), Image.LANCZOS)
                b_arr = np.array(b_pil)
                bx = (W - DISPLAY_W) // 2
                ph2 = min(disp_h, H - BODY_Y)
                mask[BODY_Y:BODY_Y+ph2, bx:bx+DISPLAY_W] = np.maximum(
                    mask[BODY_Y:BODY_Y+ph2, bx:bx+DISPLAY_W],
                    b_arr[:ph2, :, 3] / 255.0
                )

        return mask

    combined_clip = VideoClip(make_combined_frame, duration=total_card_dur).with_fps(30)
    combined_mask = VideoClip(make_combined_mask, duration=total_card_dur, is_mask=True).with_fps(30)
    combined_clip = combined_clip.with_mask(combined_mask).with_start(0)

    overlay_clips = [combined_clip]

    pop_sfx_path = "assets/sfx/pop.wav"
    if exists(pop_sfx_path):
        pop_sfx = AudioFileClip(pop_sfx_path).with_start(0).with_volume_scaled(0.25)
    else:
        pop_sfx = None

    current_time = title_dur + content_total_dur

    # ── 5. Composite ──────────────────────────────────────────────────────
    if background.duration < total_duration:
        from moviepy.video.fx import Loop
        loops_needed = int(total_duration / background.duration) + 1
        background = background.with_effects([Loop(n=loops_needed)])
    background = background.subclipped(0, total_duration)
    background = _apply_zoom(background, zoom_amount=ZOOM_AMOUNT * 0.3)

    # Watermark
    watermark_font = ImageFont.truetype(os.path.join("fonts", "Roboto-Regular.ttf"), 44)
    wm_dummy = Image.new("RGBA", (1, 1))
    wm_draw = ImageDraw.Draw(wm_dummy)
    wm_text = "Gameplay from Dino Duel"
    wm_bbox = wm_draw.textbbox((0, 0), wm_text, font=watermark_font)
    wm_w = wm_bbox[2] - wm_bbox[0] + 20
    wm_h = wm_bbox[3] - wm_bbox[1] + 14
    wm_img = Image.new("RGBA", (wm_w, wm_h), (0, 0, 0, 0))
    wm_d = ImageDraw.Draw(wm_img)
    wm_d.text((10, 5), wm_text, font=watermark_font, fill=(255, 255, 255, 255))
    wm_arr = np.array(wm_img)
    watermark = (
        ImageClip(wm_arr, duration=total_duration)
        .with_opacity(0.3)
        .with_position(("center", H - wm_h - 30))
    )
    overlay_clips.append(watermark)

    final_video = CompositeVideoClip(
        [background] + overlay_clips, size=(W, H),
    ).with_duration(total_duration)

    # Combine all audio: TTS + bg music + pop sfx
    audio_layers = [final_audio]
    if pop_sfx:
        audio_layers.append(pop_sfx)
    final_video = final_video.with_audio(CompositeAudioClip(audio_layers))

    # ── 7. Output ─────────────────────────────────────────────────────────
    title_for_file = extract_id(reddit_obj, "thread_title")
    idx = extract_id(reddit_obj)
    title_thumb = reddit_obj["thread_title"]
    filename = f"{name_normalize(title_for_file)[:251]}"
    subreddit = settings.config["reddit"]["thread"]["subreddit"]

    if not exists(f"./results/{subreddit}"):
        os.makedirs(f"./results/{subreddit}")
    if not exists(f"./results/{subreddit}/OnlyTTS") and allow_only_tts:
        os.makedirs(f"./results/{subreddit}/OnlyTTS")

    # Thumbnail
    settingsbackground = settings.config["settings"]["background"]
    if settingsbackground["background_thumbnail"]:
        if not exists(f"./results/{subreddit}/thumbnails"):
            os.makedirs(f"./results/{subreddit}/thumbnails")
        first_image = next(
            (f for f in os.listdir("assets/backgrounds") if f.endswith(".png")), None,
        )
        if first_image:
            thumbnail = Image.open(f"assets/backgrounds/{first_image}")
            w_t, h_t = thumbnail.size
            thumb_save = create_thumbnail(
                thumbnail,
                settingsbackground["background_thumbnail_font_family"],
                settingsbackground["background_thumbnail_font_size"],
                settingsbackground["background_thumbnail_font_color"],
                w_t, h_t, title_thumb,
            )
            thumb_save.save(f"./assets/temp/{reddit_id}/thumbnail.png")

    # ── 8. Render ─────────────────────────────────────────────────────────
    print_step("Rendering the video 🎥")
    output_path = f"results/{subreddit}/{filename}"[:251] + ".mp4"

    final_video.write_videofile(
        output_path, fps=30, codec="libx264", audio_codec="aac",
        bitrate="20M", preset="medium",
        threads=multiprocessing.cpu_count(), logger="bar",
    )

    if allow_only_tts:
        print_step("Rendering the Only TTS Video 🎥")
        tts_only_path = f"results/{subreddit}/OnlyTTS/{filename}"[:251] + ".mp4"
        final_video.with_audio(tts_audio).write_videofile(
            tts_only_path, fps=30, codec="libx264", audio_codec="aac",
            bitrate="20M", preset="medium",
            threads=multiprocessing.cpu_count(), logger="bar",
        )

    save_data(subreddit, filename + ".mp4", title_for_file, idx, background_config["video"][2])
    print_step("Removing temporary files 🗑")
    cleanups = cleanup(reddit_id)
    print_substep(f"Removed {cleanups} temporary files 🗑")
    print_step("Done! 🎉 The video is in the results folder 📁")
