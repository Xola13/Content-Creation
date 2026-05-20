"""
run_pipeline.py — Standalone entry point for GitHub Actions (and local testing).

Usage:
    cd trendempire
    python run_pipeline.py

Exit codes:
    0 — pipeline completed (success or partial)
    1 — pipeline failed at a critical step
"""

import sys
import json
import logging
from dotenv import load_dotenv

# Load .env before importing any bot modules so os.getenv() calls work
load_dotenv()

# Re-apply logging config after dotenv load (main.py does this too, but we
# skip Flask here since GitHub Actions doesn't need a web server)
import os
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[
        logging.FileHandler("logs/bot.log"),
        logging.StreamHandler(sys.stdout),
    ],
)

from scheduler.jobs import run_full_pipeline

if __name__ == "__main__":
    result = run_full_pipeline()

    print("\n" + "=" * 60)
    print("PIPELINE RESULT")
    print("=" * 60)
    print(json.dumps(result, indent=2, default=str))

    if result.get("status") == "failed":
        sys.exit(1)

    sys.exit(0)
