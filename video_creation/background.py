import json
import random
import re
from pathlib import Path
from random import randrange
from typing import Any, Dict, Tuple

import yt_dlp
from moviepy import AudioFileClip, VideoFileClip
from moviepy.video.io.ffmpeg_tools import ffmpeg_extract_subclip

from utils import settings
from utils.console import print_step, print_substep


def load_background_options():
    _background_options = {}
    # Load background videos
    with open("./utils/background_videos.json") as json_file:
        _background_options["video"] = json.load(json_file)

    # Load background audios
    with open("./utils/background_audios.json") as json_file:
        _background_options["audio"] = json.load(json_file)

    # Remove "__comment" from backgrounds
    del _background_options["video"]["__comment"]
    del _background_options["audio"]["__comment"]

    for name in list(_background_options["video"].keys()):
        pos = _background_options["video"][name][3]

        if pos != "center":
            _background_options["video"][name][3] = lambda t: ("center", pos + t)

    return _background_options


def get_start_and_end_times(video_length: int, length_of_clip: int) -> Tuple[int, int]:
    """Generates a random interval of time to be used as the background of the video.

    Args:
        video_length (int): Length of the video
        length_of_clip (int): Length of the video to be used as the background

    Returns:
        tuple[int,int]: Start and end time of the randomized interval
    """
    initialValue = 180
    # Issue #1649 - Ensures that will be a valid interval in the video
    while int(length_of_clip) <= int(video_length + initialValue):
        if initialValue == initialValue // 2:
            raise Exception("Your background is too short for this video length")
        else:
            initialValue //= 2  # Divides the initial value by 2 until reach 0
    # Leave a 60-second buffer at the end to avoid frozen frames
    max_start = int(length_of_clip) - int(video_length) - 60
    if max_start <= initialValue:
        max_start = int(length_of_clip) - int(video_length)
    random_time = randrange(initialValue, max(initialValue + 1, max_start))
    return random_time, random_time + video_length


def get_background_config(mode: str):
    """Fetch the background/s configuration"""
    try:
        choice = str(settings.config["settings"]["background"][f"background_{mode}"]).casefold()
    except AttributeError:
        print_substep("No background selected. Picking random background'")
        choice = None

    # Handle default / not supported background using default option.
    # Default : pick random from supported background.
    if not choice or choice not in background_options[mode]:
        choice = random.choice(list(background_options[mode].keys()))

    return background_options[mode][choice]


def download_background_video(background_config: Tuple[str, str, str, Any]):
    """Downloads the background/s video from YouTube, or skips if the file already exists (e.g. custom local clip)."""
    Path("./assets/backgrounds/video/").mkdir(parents=True, exist_ok=True)
    uri, filename, credit, _ = background_config
    filepath = Path(f"assets/backgrounds/video/{credit}-{filename}")
    if filepath.is_file():
        return
    if not uri:
        print_substep(
            f"No URL for background video and file not found at {filepath}.\n"
            f"Please place your own video clip at: {filepath}",
            style="bold red",
        )
        exit()
    print_step(
        "We need to download the backgrounds videos. they are fairly large but it's only done once. 😎"
    )
    print_substep("Downloading the backgrounds videos... please be patient 🙏 ")
    print_substep(f"Downloading {filename} from {uri}")
    ydl_opts = {
        "format": "bestvideo[height<=1080][ext=mp4]",
        "outtmpl": f"assets/backgrounds/video/{credit}-{filename}",
        "retries": 10,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download(uri)
    print_substep("Background video downloaded successfully! 🎉", style="bold green")


def download_background_audio(background_config: Tuple[str, str, str]):
    """Downloads the background/s audio from YouTube, or skips if the file already exists."""
    Path("./assets/backgrounds/audio/").mkdir(parents=True, exist_ok=True)
    uri, filename, credit = background_config
    filepath = Path(f"assets/backgrounds/audio/{credit}-{filename}")
    if filepath.is_file():
        return
    if not uri:
        print_substep(
            f"No URL for background audio and file not found at {filepath}.\n"
            f"Please place your own audio file at: {filepath}",
            style="bold red",
        )
        exit()
    print_step(
        "We need to download the backgrounds audio. they are fairly large but it's only done once. 😎"
    )
    print_substep("Downloading the backgrounds audio... please be patient 🙏 ")
    print_substep(f"Downloading {filename} from {uri}")
    ydl_opts = {
        "outtmpl": f"./assets/backgrounds/audio/{credit}-{filename}",
        "format": "bestaudio/best",
        "extract_audio": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([uri])

    print_substep("Background audio downloaded successfully! 🎉", style="bold green")


def chop_background(background_config: Dict[str, Tuple], video_length: int, reddit_object: dict):
    """Generates the background audio and footage to be used in the video.

    If a custom-clips/ directory exists with video files, picks a random clip
    weighted by duration (longer clips are more likely to be chosen) and
    extracts a random segment. Otherwise falls back to the configured background.
    """
    thread_id = re.sub(r"[^\w\s-]", "", reddit_object["thread_id"])

    if settings.config["settings"]["background"]["background_audio_volume"] == 0:
        print_step("Volume was set to 0. Skipping background audio creation . . .")
    else:
        print_step("Finding a spot in the backgrounds audio to chop...✂️")
        audio_choice = f"{background_config['audio'][2]}-{background_config['audio'][1]}"
        background_audio = AudioFileClip(f"assets/backgrounds/audio/{audio_choice}")
        start_time_audio, end_time_audio = get_start_and_end_times(
            video_length, background_audio.duration
        )
        background_audio = background_audio.subclipped(start_time_audio, end_time_audio)
        background_audio.write_audiofile(f"assets/temp/{thread_id}/background.mp3")

    # Check for custom clips directory
    custom_clips_dir = Path("assets/backgrounds/video/custom-clips")
    custom_clips = []
    if custom_clips_dir.is_dir():
        for ext in ("*.mp4", "*.mov", "*.mkv", "*.avi", "*.webm"):
            custom_clips.extend(custom_clips_dir.glob(ext))

    if custom_clips:
        print_step("Picking from custom clips (weighted by duration)...✂️")
        # Get durations for weighting
        clip_durations = []
        valid_clips = []
        for clip_path in custom_clips:
            try:
                with VideoFileClip(str(clip_path)) as vc:
                    dur = vc.duration
                if dur >= video_length:
                    clip_durations.append(dur)
                    valid_clips.append(clip_path)
                else:
                    print_substep(f"  Skipping {clip_path.name} ({dur:.0f}s < {video_length}s needed)")
            except Exception as e:
                print_substep(f"  Skipping {clip_path.name}: {e}")

        if valid_clips:
            # Weight by duration — longer clips get proportionally more picks
            total_dur = sum(clip_durations)
            weights = [d / total_dur for d in clip_durations]
            chosen_idx = random.choices(range(len(valid_clips)), weights=weights, k=1)[0]
            chosen_clip = valid_clips[chosen_idx]
            chosen_dur = clip_durations[chosen_idx]

            print_substep(f"  Selected: {chosen_clip.name} ({chosen_dur:.0f}s)")

            start_time, end_time = get_start_and_end_times(video_length, chosen_dur)
            try:
                with VideoFileClip(str(chosen_clip)) as video:
                    segment = video.subclipped(start_time, end_time)
                    segment.write_videofile(f"assets/temp/{thread_id}/background.mp4")
            except (OSError, IOError):
                ffmpeg_extract_subclip(
                    str(chosen_clip), start_time, end_time,
                    outputfile=f"assets/temp/{thread_id}/background.mp4",
                )
            print_substep("Custom clip chopped successfully!", style="bold green")
            return chosen_clip.stem
        else:
            print_substep("No custom clips long enough, falling back to configured background.")

    # Fallback: use configured background
    print_step("Finding a spot in the backgrounds video to chop...✂️")
    video_choice = f"{background_config['video'][2]}-{background_config['video'][1]}"
    background_video = VideoFileClip(f"assets/backgrounds/video/{video_choice}")
    start_time_video, end_time_video = get_start_and_end_times(
        video_length, background_video.duration
    )
    try:
        with VideoFileClip(f"assets/backgrounds/video/{video_choice}") as video:
            new = video.subclipped(start_time_video, end_time_video)
            new.write_videofile(f"assets/temp/{thread_id}/background.mp4")
    except (OSError, IOError):
        print_substep("FFMPEG issue. Trying again...")
        ffmpeg_extract_subclip(
            f"assets/backgrounds/video/{video_choice}",
            start_time_video,
            end_time_video,
            outputfile=f"assets/temp/{thread_id}/background.mp4",
        )
    print_substep("Background video chopped successfully!", style="bold green")
    return background_config["video"][2]


# Create a tuple for downloads background (background_audio_options, background_video_options)
background_options = load_background_options()
