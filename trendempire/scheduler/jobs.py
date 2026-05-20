"""
jobs.py — APScheduler daily job orchestration for TrendEmpire Bot.
Reads UPLOAD_TIME_SAST from .env and runs the full pipeline at that time.
"""

import os
import json
import logging
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler

from bot import trends, ai, tts, visuals, video, uploader, repurpose, social

logger = logging.getLogger(__name__)

# Path where the last run summary is stored for /status endpoint
LAST_RUN_PATH = os.path.join(os.path.dirname(__file__), "..", "logs", "last_run.json")

# Module-level state — updated after each pipeline run
last_run_summary: dict = {}


def run_full_pipeline() -> dict:
    """
    Execute the complete TrendEmpire video production pipeline:

    1.  Fetch SA trending topics
    2.  Pick the best monetisable topic (Groq AI)
    3.  Generate full script + SEO metadata (Groq AI)
    4.  Synthesise voiceover (Edge TTS)
    5.  Download stock images (Pexels)
    6.  Assemble 16:9 video (MoviePy)
    7.  Upload to YouTube
    8.  Generate platform captions (Groq AI)
    9.  Repurpose to 9:16 clips + Spotify audio
    10. Save run summary to logs/last_run.json

    Returns a summary dict with status and key outputs.
    """
    global last_run_summary
    run_start = datetime.now()
    timestamp = run_start.strftime("%Y%m%d_%H%M%S")

    summary = {
        "status": "running",
        "started_at": run_start.isoformat(),
        "topic": None,
        "youtube_url": None,
        "video_path": None,
        "repurposed_files": {},
        "social_results": {},
        "errors": [],
    }

    output_dir = os.path.join(os.path.dirname(__file__), "..", "output")
    os.makedirs(output_dir, exist_ok=True)

    logger.info("=" * 60)
    logger.info(f"TrendEmpire Bot — Pipeline start [{timestamp}]")

    # ── Step 1: Trending topics ────────────────────────────────────────────────
    try:
        logger.info("Step 1: Fetching trending topics...")
        topics = trends.get_trending_topics()
        logger.info(f"  Got {len(topics)} topics")
    except Exception as exc:
        logger.error(f"Step 1 failed: {exc}")
        topics = []
        summary["errors"].append(f"trends: {exc}")

    # ── Step 2: Pick best topic ────────────────────────────────────────────────
    try:
        logger.info("Step 2: Selecting best topic with AI...")
        topic_data = ai.pick_best_topic(topics)
        summary["topic"] = topic_data.get("topic")
        logger.info(f"  Selected: {summary['topic']}")
    except Exception as exc:
        logger.error(f"Step 2 failed: {exc}")
        topic_data = {"topic": topics[0] if topics else "South Africa economy", "title": "SA Finance Update", "format": "explainer"}
        summary["errors"].append(f"pick_topic: {exc}")

    # ── Step 3: Generate script ────────────────────────────────────────────────
    try:
        logger.info("Step 3: Generating script and SEO metadata...")
        script = ai.generate_script(topic_data)
        logger.info(f"  Script: {len(script.get('full_script', '').split())} words")
    except Exception as exc:
        logger.error(f"Step 3 failed: {exc}")
        summary["errors"].append(f"generate_script: {exc}")
        summary["status"] = "failed"
        _save_summary(summary)
        return summary

    # ── Step 4: Voiceover ──────────────────────────────────────────────────────
    voiceover_path = os.path.join(output_dir, f"voiceover_{timestamp}.mp3")
    try:
        logger.info("Step 4: Generating voiceover...")
        tts.generate_voiceover(
            text=script["full_script"],
            output_path=voiceover_path,
        )
    except Exception as exc:
        logger.error(f"Step 4 failed: {exc}")
        summary["errors"].append(f"tts: {exc}")
        summary["status"] = "failed"
        _save_summary(summary)
        return summary

    # ── Step 5: Stock images ───────────────────────────────────────────────────
    try:
        logger.info("Step 5: Downloading stock images...")
        image_paths = visuals.fetch_images(
            query=topic_data.get("topic", "finance"),
            count=12,
        )
        logger.info(f"  Downloaded {len(image_paths)} images")
    except Exception as exc:
        logger.error(f"Step 5 failed: {exc}")
        image_paths = []
        summary["errors"].append(f"visuals: {exc}")

    if not image_paths:
        logger.error("No images available — aborting pipeline")
        summary["status"] = "failed"
        _save_summary(summary)
        return summary

    # ── Step 6: Assemble video ─────────────────────────────────────────────────
    video_path = os.path.join(output_dir, f"video_{timestamp}.mp4")
    try:
        logger.info("Step 6: Assembling video...")
        video.assemble_video(
            image_paths=image_paths,
            audio_path=voiceover_path,
            title=script.get("title", topic_data["topic"]),
            output_path=video_path,
        )
        summary["video_path"] = video_path
    except Exception as exc:
        logger.error(f"Step 6 failed: {exc}")
        summary["errors"].append(f"video: {exc}")
        summary["status"] = "failed"
        _save_summary(summary)
        return summary

    # ── Step 7: Upload to YouTube ──────────────────────────────────────────────
    try:
        logger.info("Step 7: Uploading to YouTube...")
        yt_url = uploader.upload_to_youtube(video_path=video_path, script=script)
        summary["youtube_url"] = yt_url
        logger.info(f"  Published: {yt_url}")
    except Exception as exc:
        logger.error(f"Step 7 failed (non-fatal): {exc}")
        summary["errors"].append(f"upload: {exc}")
        # Non-fatal — continue to repurpose even if upload fails

    # ── Step 8: Platform captions ──────────────────────────────────────────────
    try:
        logger.info("Step 8: Generating platform captions...")
        captions = ai.generate_captions(
            title=script.get("title", ""),
            tags=script.get("tags", []),
        )
    except Exception as exc:
        logger.error(f"Step 8 failed (non-fatal): {exc}")
        captions = {}
        summary["errors"].append(f"captions: {exc}")

    # ── Step 9: Repurpose ──────────────────────────────────────────────────────
    try:
        logger.info("Step 9: Repurposing for TikTok, Reels, Shorts, Spotify...")
        repurposed = repurpose.repurpose_all(
            source_video=video_path,
            title=script.get("title", topic_data["topic"]),
            captions=captions,
        )
        summary["repurposed_files"] = repurposed
    except Exception as exc:
        logger.error(f"Step 9 failed (non-fatal): {exc}")
        summary["errors"].append(f"repurpose: {exc}")

    # ── Step 10: Post to all social platforms ─────────────────────────────────
    try:
        logger.info("Step 10: Posting to TikTok, Facebook, Instagram, Twitter, Pinterest, Spotify...")
        social_results = social.post_to_all_platforms(
            repurposed=repurposed if "repurposed_files" in summary else {},
            captions=captions,
            script=script,
            youtube_url=summary.get("youtube_url", ""),
        )
        summary["social_results"] = social_results
    except Exception as exc:
        logger.error(f"Step 10 failed (non-fatal): {exc}")
        summary["errors"].append(f"social: {exc}")

    # ── Cleanup temp images ────────────────────────────────────────────────────
    _cleanup_images(image_paths)

    # ── Step 11: Save summary ─────────────────────────────────────────────────
    summary["status"] = "success" if not any("failed" in e for e in summary["errors"]) else "partial"
    summary["completed_at"] = datetime.now().isoformat()
    _save_summary(summary)

    logger.info(f"Pipeline complete — status: {summary['status']}")
    logger.info("=" * 60)

    last_run_summary = summary
    return summary


def _save_summary(summary: dict) -> None:
    """Write the run summary to logs/last_run.json."""
    os.makedirs(os.path.dirname(LAST_RUN_PATH), exist_ok=True)
    try:
        with open(LAST_RUN_PATH, "w") as f:
            json.dump(summary, f, indent=2, default=str)
    except Exception as exc:
        logger.error(f"Could not save run summary: {exc}")


def _cleanup_images(paths: list) -> None:
    """Delete downloaded stock images after the video is assembled."""
    for p in paths:
        try:
            os.remove(p)
        except OSError:
            pass


def create_scheduler() -> BackgroundScheduler:
    """
    Build and return an APScheduler BackgroundScheduler configured to run
    run_full_pipeline() daily at UPLOAD_TIME_SAST (default 18:00 SAST = 16:00 UTC).
    """
    upload_time = os.getenv("UPLOAD_TIME_SAST", "18:00")
    hour_sast, minute_sast = map(int, upload_time.split(":"))

    # SAST is UTC+2 — convert to UTC for the cron trigger
    hour_utc = (hour_sast - 2) % 24

    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        func=run_full_pipeline,
        trigger="cron",
        hour=hour_utc,
        minute=minute_sast,
        id="daily_video",
        name="TrendEmpire Daily Video",
        replace_existing=True,
    )

    logger.info(
        f"Scheduler configured: daily at {upload_time} SAST "
        f"({hour_utc:02d}:{minute_sast:02d} UTC)"
    )
    return scheduler
