"""
visuals.py — Download royalty-free stock images from the Pexels API.
"""

import os
import logging
import requests

logger = logging.getLogger(__name__)

PEXELS_SEARCH_URL = "https://api.pexels.com/v1/search"
IMAGES_DIR = os.path.join(os.path.dirname(__file__), "..", "output", "images")


def fetch_images(query: str, count: int = 12) -> list:
    """
    Search Pexels for `query` and download up to `count` landscape images.

    Args:
        query: Search keyword derived from the video topic.
        count: Number of images to download.

    Returns:
        List of local file paths for the downloaded images.
    """
    api_key = os.getenv("PEXELS_API_KEY", "")
    if not api_key:
        logger.error("PEXELS_API_KEY is not set — cannot fetch images")
        return []

    os.makedirs(IMAGES_DIR, exist_ok=True)

    headers = {"Authorization": api_key}
    params = {
        "query": query,
        "per_page": count,
        "orientation": "landscape",  # Ensures 16:9-friendly images
    }

    try:
        logger.info(f"Fetching {count} Pexels images for query: '{query}'")
        resp = requests.get(PEXELS_SEARCH_URL, headers=headers, params=params, timeout=30)
        resp.raise_for_status()
        photos = resp.json().get("photos", [])

        if not photos:
            logger.warning(f"No Pexels results for '{query}'")
            return []

        saved_paths = []
        for i, photo in enumerate(photos[:count]):
            # Use the "large2x" size for 1920×1080 quality
            img_url = photo["src"].get("large2x") or photo["src"]["original"]
            filename = f"img_{i:02d}_{photo['id']}.jpg"
            dest = os.path.join(IMAGES_DIR, filename)

            try:
                img_resp = requests.get(img_url, timeout=30)
                img_resp.raise_for_status()
                with open(dest, "wb") as f:
                    f.write(img_resp.content)
                saved_paths.append(dest)
                logger.debug(f"  Saved image {i+1}/{len(photos)}: {filename}")

            except Exception as exc:
                logger.warning(f"  Failed to download image {i}: {exc}")

        logger.info(f"Downloaded {len(saved_paths)} images to {IMAGES_DIR}")
        return saved_paths

    except requests.exceptions.HTTPError as exc:
        logger.error(f"Pexels API HTTP error: {exc}")
        return []
    except Exception as exc:
        logger.error(f"Pexels fetch failed: {exc}")
        return []
