"""
trends.py — Fetch South Africa trending topics via PyTrends.
Falls back to a curated SA finance topic list when PyTrends is unavailable.
"""

import time
import logging
from pytrends.request import TrendReq

logger = logging.getLogger(__name__)

# Fallback list used when PyTrends rate-limits or errors out
FALLBACK_TOPICS = [
    "South Africa economy 2024",
    "SARS tax return tips",
    "load shedding impact on business",
    "South Africa property market",
    "JSE stocks to watch",
    "side hustle ideas South Africa",
    "SASSA grant update",
    "rand dollar exchange rate",
    "South Africa petrol price",
    "how to save money South Africa",
]


def get_trending_topics(retries: int = 3, delay: int = 5) -> list:
    """
    Return top 10 trending search topics in South Africa.
    Retries up to `retries` times on failure with `delay` seconds between attempts.
    """
    for attempt in range(1, retries + 1):
        try:
            logger.info(f"PyTrends attempt {attempt}/{retries} — fetching ZA trends")
            pytrends = TrendReq(hl="en-ZA", tz=120)  # SAST = UTC+2

            # daily_searches returns a dict keyed by date; grab the latest
            trending_df = pytrends.trending_searches(pn="south_africa")
            topics = trending_df[0].tolist()[:10]

            if topics:
                logger.info(f"Retrieved {len(topics)} trending topics from PyTrends")
                return topics

        except Exception as exc:
            logger.warning(f"PyTrends attempt {attempt} failed: {exc}")
            if attempt < retries:
                time.sleep(delay)

    # All retries exhausted — use fallback
    logger.warning("PyTrends unavailable — using fallback SA finance topics")
    return FALLBACK_TOPICS
