"""
tts.py — Edge TTS voiceover generator (Microsoft free TTS, no API key required).
"""

import os
import asyncio
import logging

import edge_tts

logger = logging.getLogger(__name__)

DEFAULT_VOICE = "en-ZA-LeahNeural"


async def _synthesise(text: str, output_path: str, voice: str) -> None:
    """Async inner function that calls edge-tts and writes the MP3."""
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(output_path)


def generate_voiceover(text: str, output_path: str, voice: str | None = None) -> str:
    """
    Convert `text` to speech and save as MP3 at `output_path`.

    Args:
        text:        The script text to synthesise.
        output_path: Destination path (should end in .mp3).
        voice:       Edge TTS voice name; falls back to TTS_VOICE env var or default.

    Returns:
        Absolute path to the saved MP3 file.
    """
    if voice is None:
        voice = os.getenv("TTS_VOICE", DEFAULT_VOICE)

    # Ensure the output directory exists
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    try:
        logger.info(f"Generating voiceover with voice '{voice}' → {output_path}")
        asyncio.run(_synthesise(text, output_path, voice))
        logger.info(f"Voiceover saved: {output_path}")
        return os.path.abspath(output_path)

    except Exception as exc:
        logger.error(f"TTS generation failed: {exc}")
        raise
