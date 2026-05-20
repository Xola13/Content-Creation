"""
video.py — Assemble a 1920×1080 MP4 from stock images + voiceover using MoviePy.
"""

import os
import logging

from moviepy.editor import (
    ImageClip,
    AudioFileClip,
    CompositeVideoClip,
    concatenate_videoclips,
    TextClip,
)

logger = logging.getLogger(__name__)

TARGET_W, TARGET_H = 1920, 1080
FPS = 24
CROSSFADE_DURATION = 0.5  # seconds
TITLE_OVERLAY_DURATION = 5  # seconds the title text stays on screen


def _resize_and_crop(image_path: str, duration: float) -> ImageClip:
    """Load an image, resize to fill 1920×1080, and set its duration."""
    clip = ImageClip(image_path)

    # Scale so that the shorter dimension fills the frame, then centre-crop
    scale = max(TARGET_W / clip.w, TARGET_H / clip.h)
    new_w = int(clip.w * scale)
    new_h = int(clip.h * scale)
    clip = clip.resize((new_w, new_h))

    # Crop to exact target dimensions from the centre
    x_start = (new_w - TARGET_W) // 2
    y_start = (new_h - TARGET_H) // 2
    clip = clip.crop(x1=x_start, y1=y_start, x2=x_start + TARGET_W, y2=y_start + TARGET_H)

    return clip.set_duration(duration)


def assemble_video(
    image_paths: list,
    audio_path: str,
    title: str,
    output_path: str,
) -> str:
    """
    Combine images and audio into a 1920×1080 MP4 with a title text overlay.

    Args:
        image_paths: Ordered list of local image file paths.
        audio_path:  Path to the voiceover MP3/WAV.
        title:       Video title shown as overlay for the first 5 seconds.
        output_path: Destination .mp4 path.

    Returns:
        Absolute path of the rendered video.
    """
    if not image_paths:
        raise ValueError("No images provided for video assembly")

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    # Load audio to determine per-image duration
    logger.info(f"Loading audio: {audio_path}")
    audio = AudioFileClip(audio_path)
    total_duration = audio.duration
    per_image = total_duration / len(image_paths)

    logger.info(
        f"Assembling {len(image_paths)} images × {per_image:.1f}s "
        f"= {total_duration:.1f}s total"
    )

    # Build individual image clips with crossfade
    clips = []
    for i, img_path in enumerate(image_paths):
        try:
            clip = _resize_and_crop(img_path, per_image)

            # Apply crossfade transition on all clips except the first
            if i > 0:
                clip = clip.crossfadein(CROSSFADE_DURATION)

            clips.append(clip)
        except Exception as exc:
            logger.warning(f"Skipping image {img_path}: {exc}")

    if not clips:
        raise RuntimeError("All images failed to load — cannot assemble video")

    # Concatenate with crossfade (padding ensures the fade duration is respected)
    video = concatenate_videoclips(clips, method="compose", padding=-CROSSFADE_DURATION)

    # Title text overlay — white bold text with black stroke at the bottom
    try:
        title_clip = (
            TextClip(
                title,
                fontsize=60,
                font="DejaVu-Sans-Bold",
                color="white",
                stroke_color="black",
                stroke_width=3,
                method="caption",
                size=(TARGET_W - 80, None),  # wrap with 40px margin each side
                align="center",
            )
            .set_position(("center", TARGET_H - 180))  # Near bottom
            .set_duration(min(TITLE_OVERLAY_DURATION, video.duration))
            .fadein(0.5)
            .fadeout(0.5)
        )
        video = CompositeVideoClip([video, title_clip])
    except Exception as exc:
        # Title overlay is non-critical — continue without it
        logger.warning(f"Title overlay skipped (font issue?): {exc}")

    # Attach audio and render
    video = video.set_audio(audio)

    logger.info(f"Rendering video → {output_path}")
    video.write_videofile(
        output_path,
        fps=FPS,
        codec="libx264",
        audio_codec="aac",
        temp_audiofile="output/temp_audio.m4a",
        remove_temp=True,
        logger=None,  # Suppress MoviePy's verbose progress bar in logs
    )

    # Release file handles to free memory
    video.close()
    audio.close()

    logger.info(f"Video saved: {output_path}")
    return os.path.abspath(output_path)
