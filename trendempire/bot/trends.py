"""
trends.py — Multi-source global trending topic scraper for TrendEmpire Bot.

Sources (all free, no extra API keys):
  1. PyTrends — top trending searches across 10 major countries
  2. Google News RSS — real-time global headlines (no API key needed)
  3. Reddit JSON API — hot posts from finance/news subreddits (no auth needed)

Returns a combined, deduplicated list of up to 30 globally trending topics,
ranked by how many sources mentioned them (cross-source score).
"""

import re
import time
import logging
import xml.etree.ElementTree as ET
from collections import Counter

import requests
from pytrends.request import TrendReq

logger = logging.getLogger(__name__)

# ── PyTrends: countries to query (pn= parameter values) ──────────────────────
# Spread across continents for genuine global coverage
PYTRENDS_COUNTRIES = [
    ("united_states",   "en-US"),
    ("united_kingdom",  "en-GB"),
    ("india",           "en-IN"),
    ("australia",       "en-AU"),
    ("canada",          "en-CA"),
    ("nigeria",         "en-NG"),
    ("south_africa",    "en-ZA"),
    ("brazil",          "pt-BR"),
    ("germany",         "de-DE"),
    ("south_korea",     "ko-KR"),
]

# ── Google News RSS feeds (topic categories) ──────────────────────────────────
GOOGLE_NEWS_FEEDS = [
    "https://news.google.com/rss?topic=h&hl=en-US&gl=US&ceid=US:en",   # Top headlines
    "https://news.google.com/rss?topic=b&hl=en-US&gl=US&ceid=US:en",   # Business
    "https://news.google.com/rss?topic=t&hl=en-US&gl=US&ceid=US:en",   # Technology
    "https://news.google.com/rss?topic=e&hl=en-US&gl=US&ceid=US:en",   # Entertainment
]

# ── Reddit subreddits for trending finance/world topics ───────────────────────
REDDIT_SUBREDDITS = [
    "worldnews",
    "news",
    "investing",
    "personalfinance",
    "technology",
    "economy",
]

# ── Fallback list — used only when ALL sources fail ───────────────────────────
FALLBACK_TOPICS = [
    "global inflation impact 2025",
    "US Federal Reserve interest rate decision",
    "China economy slowdown",
    "AI job market disruption",
    "oil price forecast",
    "cryptocurrency Bitcoin rally",
    "stock market crash warning signs",
    "remote work economy shift",
    "electric vehicle market growth",
    "global housing market trends",
    "South Africa rand vs dollar",
    "BRICS currency update",
]


# ══════════════════════════════════════════════════════════════════════════════
# SOURCE 1 — PyTrends (multiple countries)
# ══════════════════════════════════════════════════════════════════════════════

def _fetch_pytrends(retries: int = 2, delay: int = 4) -> list:
    """
    Query PyTrends trending searches for each country in PYTRENDS_COUNTRIES.
    Returns a flat list of topic strings (duplicates intentional — used for scoring).
    """
    all_topics = []

    for country_pn, hl in PYTRENDS_COUNTRIES:
        for attempt in range(1, retries + 1):
            try:
                pytrends = TrendReq(hl=hl, tz=0, timeout=(10, 30))
                df = pytrends.trending_searches(pn=country_pn)
                topics = df[0].tolist()[:10]
                all_topics.extend(topics)
                logger.debug(f"  PyTrends [{country_pn}]: {len(topics)} topics")
                time.sleep(1.5)  # Polite rate limiting between requests
                break

            except Exception as exc:
                logger.debug(f"  PyTrends [{country_pn}] attempt {attempt} failed: {exc}")
                if attempt < retries:
                    time.sleep(delay)

    logger.info(f"PyTrends: collected {len(all_topics)} raw topics across all countries")
    return all_topics


# ══════════════════════════════════════════════════════════════════════════════
# SOURCE 2 — Google News RSS (no API key needed)
# ══════════════════════════════════════════════════════════════════════════════

def _fetch_google_news() -> list:
    """
    Parse Google News RSS feeds and extract article titles as trend signals.
    No API key required — public RSS endpoint.
    """
    topics = []
    headers = {"User-Agent": "TrendEmpirBot/1.0 (content research bot)"}

    for feed_url in GOOGLE_NEWS_FEEDS:
        try:
            resp = requests.get(feed_url, headers=headers, timeout=15)
            resp.raise_for_status()

            root = ET.fromstring(resp.content)
            # RSS structure: rss → channel → item → title
            for item in root.findall(".//item"):
                title_el = item.find("title")
                if title_el is not None and title_el.text:
                    # Strip the " - Source Name" suffix Google appends
                    clean = re.sub(r"\s+-\s+[^-]+$", "", title_el.text).strip()
                    if len(clean) > 10:
                        topics.append(clean)

            logger.debug(f"  Google News RSS: {len(topics)} headlines so far")
            time.sleep(0.5)

        except Exception as exc:
            logger.debug(f"  Google News RSS failed [{feed_url[:50]}...]: {exc}")

    logger.info(f"Google News: collected {len(topics)} headlines")
    return topics


# ══════════════════════════════════════════════════════════════════════════════
# SOURCE 3 — Reddit JSON API (no authentication needed for public subreddits)
# ══════════════════════════════════════════════════════════════════════════════

def _fetch_reddit() -> list:
    """
    Fetch hot post titles from finance and news subreddits.
    Reddit's public JSON API requires no authentication.
    """
    topics = []
    headers = {"User-Agent": "TrendEmpireBot/1.0 (content research)"}

    for sub in REDDIT_SUBREDDITS:
        try:
            url = f"https://www.reddit.com/r/{sub}/hot.json?limit=10"
            resp = requests.get(url, headers=headers, timeout=15)
            resp.raise_for_status()

            posts = resp.json()["data"]["children"]
            for post in posts:
                title = post["data"].get("title", "")
                # Filter out memes/images — keep text-heavy titles
                if len(title) > 20 and not post["data"].get("is_video", False):
                    topics.append(title)

            logger.debug(f"  Reddit r/{sub}: {len(posts)} posts")
            time.sleep(1)  # Reddit rate limit: ~1 req/sec

        except Exception as exc:
            logger.debug(f"  Reddit r/{sub} failed: {exc}")

    logger.info(f"Reddit: collected {len(topics)} post titles")
    return topics


# ══════════════════════════════════════════════════════════════════════════════
# COMBINER — score, deduplicate, and rank
# ══════════════════════════════════════════════════════════════════════════════

def _normalise(text: str) -> str:
    """Lowercase and strip punctuation for deduplication comparison."""
    return re.sub(r"[^\w\s]", "", text.lower()).strip()


def _score_and_rank(all_topics: list, top_n: int = 30) -> list:
    """
    Score topics by frequency across sources, deduplicate near-duplicates,
    and return the top_n unique trending topics.
    """
    # Count normalised occurrences for cross-source scoring
    norm_counter = Counter(_normalise(t) for t in all_topics)

    # Map normalised form back to the cleanest original string
    best_form: dict[str, str] = {}
    for topic in all_topics:
        norm = _normalise(topic)
        # Prefer shorter, cleaner strings as the canonical form
        if norm not in best_form or len(topic) < len(best_form[norm]):
            best_form[norm] = topic

    # Sort by cross-source score (most-mentioned = highest ranked)
    ranked = sorted(norm_counter.items(), key=lambda x: x[1], reverse=True)

    # Rebuild original-form list, skip very short or noisy entries
    seen_words: set[str] = set()
    result = []
    for norm, _count in ranked:
        original = best_form.get(norm, norm)
        words = set(norm.split())

        # Skip if this topic shares >60% words with an already-added topic
        overlap = words & seen_words
        if len(words) > 0 and len(overlap) / len(words) > 0.6:
            continue

        seen_words.update(words)
        result.append(original)

        if len(result) >= top_n:
            break

    return result


# ══════════════════════════════════════════════════════════════════════════════
# PUBLIC INTERFACE
# ══════════════════════════════════════════════════════════════════════════════

def get_trending_topics(top_n: int = 30) -> list:
    """
    Fetch globally trending topics from all three sources and return the
    top `top_n` ranked by cross-source mention frequency.

    Falls back to FALLBACK_TOPICS only when every source fails.

    Args:
        top_n: Maximum number of topics to return (default 30).

    Returns:
        List of trending topic strings, most viral first.
    """
    logger.info("Fetching global trending topics from all sources...")
    all_raw: list[str] = []

    # Source 1: PyTrends (10 countries)
    try:
        pytrends_topics = _fetch_pytrends()
        all_raw.extend(pytrends_topics)
    except Exception as exc:
        logger.warning(f"PyTrends source failed entirely: {exc}")

    # Source 2: Google News RSS
    try:
        news_topics = _fetch_google_news()
        all_raw.extend(news_topics)
    except Exception as exc:
        logger.warning(f"Google News source failed: {exc}")

    # Source 3: Reddit
    try:
        reddit_topics = _fetch_reddit()
        all_raw.extend(reddit_topics)
    except Exception as exc:
        logger.warning(f"Reddit source failed: {exc}")

    if not all_raw:
        logger.warning("All trend sources failed — using fallback topics")
        return FALLBACK_TOPICS

    ranked = _score_and_rank(all_raw, top_n=top_n)
    logger.info(f"Global trends ready: {len(ranked)} unique topics from {len(all_raw)} raw signals")
    return ranked
