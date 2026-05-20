"""
main.py — TrendEmpire Bot Flask server.
Exposes health, status, and webhook endpoints.
Starts the APScheduler daily job on startup.
"""

import os
import json
import logging
import threading
from datetime import datetime

from flask import Flask, request, jsonify
from dotenv import load_dotenv

# Load environment variables before importing bot modules
load_dotenv()

from scheduler.jobs import create_scheduler, run_full_pipeline, last_run_summary, LAST_RUN_PATH
from bot import repurpose as repurpose_module

# ── Logging setup ──────────────────────────────────────────────────────────────
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[
        logging.FileHandler("logs/bot.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

# ── Flask app ──────────────────────────────────────────────────────────────────
app = Flask(__name__)

# ── Scheduler (started once at import time) ────────────────────────────────────
_scheduler = create_scheduler()
_scheduler.start()
logger.info("APScheduler started")


def _verify_webhook_secret(req) -> bool:
    """Check the X-Webhook-Secret header matches the configured secret."""
    secret = os.getenv("WEBHOOK_SECRET", "")
    if not secret:
        # No secret configured — allow all requests (dev mode)
        return True
    return req.headers.get("X-Webhook-Secret") == secret


def _get_next_run_time() -> str:
    """Return ISO timestamp of the next scheduled pipeline run."""
    job = _scheduler.get_job("daily_video")
    if job and job.next_run_time:
        return job.next_run_time.isoformat()
    return "unknown"


def _load_last_run() -> dict:
    """Load the last run summary from disk (falls back to in-memory state)."""
    if os.path.exists(LAST_RUN_PATH):
        try:
            with open(LAST_RUN_PATH) as f:
                return json.load(f)
        except Exception:
            pass
    return last_run_summary


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.route("/health", methods=["GET"])
def health():
    """Simple liveness probe."""
    return jsonify({"status": "ok", "time": datetime.utcnow().isoformat() + "Z"})


@app.route("/status", methods=["GET"])
def status():
    """Return last run summary and next scheduled run time."""
    run_data = _load_last_run()
    return jsonify({
        "last_run": run_data,
        "last_video_url": run_data.get("youtube_url"),
        "next_scheduled_run": _get_next_run_time(),
        "scheduler_running": _scheduler.running,
    })


@app.route("/webhook/run", methods=["POST"])
def webhook_run():
    """
    Trigger the full pipeline immediately.
    Validates X-Webhook-Secret header.
    Runs the pipeline in a background thread so the request returns instantly.
    """
    if not _verify_webhook_secret(request):
        logger.warning("Webhook /run rejected — invalid secret")
        return jsonify({"error": "Unauthorized"}), 401

    logger.info("Webhook /run triggered")

    def _bg_run():
        try:
            run_full_pipeline()
        except Exception as exc:
            logger.error(f"Webhook pipeline error: {exc}")

    thread = threading.Thread(target=_bg_run, daemon=True)
    thread.start()

    return jsonify({
        "status": "accepted",
        "message": "Pipeline started in background. Check /status for progress.",
        "triggered_at": datetime.utcnow().isoformat() + "Z",
    })


@app.route("/webhook/repurpose", methods=["POST"])
def webhook_repurpose():
    """
    Re-run the repurpose step on the last assembled video without re-uploading.
    Validates X-Webhook-Secret header.
    """
    if not _verify_webhook_secret(request):
        logger.warning("Webhook /repurpose rejected — invalid secret")
        return jsonify({"error": "Unauthorized"}), 401

    run_data = _load_last_run()
    source_video = run_data.get("video_path")

    if not source_video or not os.path.exists(source_video):
        return jsonify({"error": "No video available to repurpose"}), 404

    title = run_data.get("topic", "TrendEmpire Video")

    def _bg_repurpose():
        try:
            repurpose_module.repurpose_all(
                source_video=source_video,
                title=title,
                captions={},
            )
        except Exception as exc:
            logger.error(f"Webhook repurpose error: {exc}")

    thread = threading.Thread(target=_bg_repurpose, daemon=True)
    thread.start()

    return jsonify({
        "status": "accepted",
        "message": f"Repurposing '{title}' in background.",
        "source_video": source_video,
    })


# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.getenv("FLASK_PORT", 5000))
    logger.info(f"TrendEmpire Bot starting on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
