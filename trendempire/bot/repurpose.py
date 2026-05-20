"""
repurpose.py — Convert a 16:9 YouTube video into vertical clips (9:16) for
TikTok, Reels, and Shorts, plus an MP3 audio strip for Spotify podcasts.
Also writes platform captions as JSON alongside each output folder.
"""

import os
import json
import logging

from moviepy.editor import VideoFileClip, AudioFileClip

logger = logging.getLogger(__name__)

REPURPOSED_DIR = os.path.join(os.path.dirname(__file__), "..", "output", "repurposed")

# Maximum clip durations per platform (seconds)
PLATFORM_MAX_DURATION = {
    "tiktok": 60,
    "reels": 30,
    "shorts": 60,
}

# Output resolution: 1080×1920 (9:16 portrait)
OUT_W, OUT_H = 1080, 1920


def _make_vertical(clip: VideoFileClip) -> VideoFileClip:
    """
    Scale a 16:9 clip so its height fills 1920px, then centre-crop to 1080px wide.
    This creates the letterbox-free 9:16 portrait crop.
    """
    scale = OUT_H / clip.h
    new_w = int(clip.w * scale)
    clip = clip.resize((new_w, OUT_H))

    # Centre crop horizontally
    x_start = (new_w - OUT_W) // 2
    clip = clip.crop(x1=x_start, y1=0, x2=x_start + OUT_W, y2=OUT_H)
    return clip


def _split_clips(clip: VideoFileClip, max_duration: int) -> list:
    """
    Split `clip` into segments of at most `max_duration` seconds.
    Returns a list of sub-clips (single-item list if no split needed).
    """
    if clip.duration <= max_duration:
        return [clip]

    segments = []
    start = 0.0
    while start < clip.duration:
        end = min(start + max_duration, clip.duration)
        segments.append(clip.subclip(start, end))
        start = end

    return segments


def repurpose_all(source_video: str, title: str, captions: dict) -> dict:
    """
    Generate all repurposed assets from a single 16:9 source video.

    Args:
        source_video: Path to the original 1920×1080 MP4.
        title:        Video title used for output filenames.
        captions:     Dict with keys: tiktok, reels, shorts, spotify.

    Returns:
        Dict mapping platform name → list of output file paths.
    """
    results = {}
    safe_title = "".join(c if c.isalnum() or c in " _-" else "_" for c in title)[:40]

    try:
        source = VideoFileClip(source_video)
    except Exception as exc:
        logger.error(f"Cannot open source video '{source_video}': {exc}")
        return results

    # ── Vertical video platforms ───────────────────────────────────────────────
    for platform, max_dur in PLATFORM_MAX_DURATION.items():
        platform_dir = os.path.join(REPURPOSED_DIR, platform)
        os.makedirs(platform_dir, exist_ok=True)

        try:
            vertical = _make_vertical(source)
            segments = _split_clips(vertical, max_dur)

            platform_files = []
            for idx, seg in enumerate(segments):
                suffix = f"_pt{idx+1}" if len(segments) > 1 else ""
                filename = f"{safe_title}{suffix}_{platform}.mp4"
                dest = os.path.join(platform_dir, filename)

                seg.write_videofile(
                    dest,
                    fps=24,
                    codec="libx264",
                    audio_codec="aac",
                    logger=None,
                )
                seg.close()
                platform_files.append(dest)
                logger.info(f"  [{platform}] Saved: {dest}")

            vertical.close()
            results[platform] = platform_files

            # Write platform caption alongside the clips
            caption_path = os.path.join(platform_dir, "caption.json")
            with open(caption_path, "w") as f:
                json.dump(
                    {"title": title, "caption": captions.get(platform, "")},
                    f,
                    indent=2,
                )

        except Exception as exc:
            logger.error(f"Repurpose failed for {platform}: {exc}")
            results[platform] = []

    # ── Spotify audio strip ────────────────────────────────────────────────────
    spotify_dir = os.path.join(REPURPOSED_DIR, "spotify")
    os.makedirs(spotify_dir, exist_ok=True)

    try:
        audio_path = os.path.join(spotify_dir, f"{safe_title}_spotify.mp3")
        source.audio.write_audiofile(audio_path, logger=None)
        results["spotify"] = [audio_path]
        logger.info(f"  [spotify] Audio saved: {audio_path}")

        # Write Spotify caption/description
        caption_path = os.path.join(spotify_dir, "caption.json")
        with open(caption_path, "w") as f:
            json.dump(
                {"title": title, "description": captions.get("spotify", "")},
                f,
                indent=2,
            )

    except Exception as exc:
        logger.error(f"Spotify audio export failed: {exc}")
        results["spotify"] = []

    source.close()
    logger.info(f"Repurpose complete. Platforms: {list(results.keys())}")
    return results
