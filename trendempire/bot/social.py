"""
social.py — Cross-platform social media uploader for TrendEmpire Bot.

Platforms:
  - TikTok          (Content Posting API v2)
  - Facebook Reels  (Meta Graph API)
  - Instagram Reels (Meta Graph API)
  - Twitter/X       (API v2 — text post; video requires paid tier, noted below)
  - Pinterest       (API v5 — image pin with YouTube link)
  - Spotify/Podcast (Buzzsprout API → RSS auto-syncs to Spotify)
"""

import os
import time
import json
import logging
import requests

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# TIKTOK
# ══════════════════════════════════════════════════════════════════════════════

TIKTOK_INIT_URL = "https://open.tiktokapis.com/v2/post/publish/video/init/"
TIKTOK_STATUS_URL = "https://open.tiktokapis.com/v2/post/publish/status/fetch/"


def upload_to_tiktok(video_path: str, caption: str) -> dict:
    """
    Upload a video to TikTok via the Content Posting API v2.

    Requires:
      TIKTOK_ACCESS_TOKEN in .env
      App must be approved for "video.publish" scope in TikTok Developer Portal.

    Args:
        video_path: Local path to the 9:16 MP4 (max 60s for TikTok).
        caption:    Caption text including hashtags.

    Returns:
        {"status": "success"|"failed", "publish_id": str, "url": str}
    """
    access_token = os.getenv("TIKTOK_ACCESS_TOKEN", "")
    if not access_token:
        logger.warning("TIKTOK_ACCESS_TOKEN not set — skipping TikTok upload")
        return {"status": "skipped", "reason": "no token"}

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json; charset=UTF-8",
    }

    file_size = os.path.getsize(video_path)

    # Step 1 — Initialise the upload, get chunk upload URL
    init_body = {
        "post_info": {
            "title": caption[:2200],  # TikTok caption limit
            "privacy_level": "PUBLIC_TO_EVERYONE",
            "disable_duet": False,
            "disable_comment": False,
            "disable_stitch": False,
        },
        "source_info": {
            "source": "FILE_UPLOAD",
            "video_size": file_size,
            "chunk_size": file_size,  # Single chunk for files <64MB
            "total_chunk_count": 1,
        },
    }

    try:
        resp = requests.post(TIKTOK_INIT_URL, headers=headers, json=init_body, timeout=30)
        resp.raise_for_status()
        data = resp.json().get("data", {})
        publish_id = data.get("publish_id")
        upload_url = data.get("upload_url")

        if not upload_url:
            logger.error(f"TikTok init returned no upload_url: {resp.text}")
            return {"status": "failed", "reason": "no upload_url"}

        # Step 2 — Upload the video binary
        with open(video_path, "rb") as f:
            video_bytes = f.read()

        upload_headers = {
            "Content-Type": "video/mp4",
            "Content-Range": f"bytes 0-{file_size - 1}/{file_size}",
            "Content-Length": str(file_size),
        }
        upload_resp = requests.put(upload_url, data=video_bytes, headers=upload_headers, timeout=300)
        upload_resp.raise_for_status()

        # Step 3 — Poll for publish status (up to 2 minutes)
        for _ in range(12):
            time.sleep(10)
            status_resp = requests.post(
                TIKTOK_STATUS_URL,
                headers=headers,
                json={"publish_id": publish_id},
                timeout=30,
            )
            status_data = status_resp.json().get("data", {})
            status = status_data.get("status")

            if status == "PUBLISH_COMPLETE":
                logger.info(f"TikTok upload complete — publish_id: {publish_id}")
                return {"status": "success", "publish_id": publish_id}
            elif status in ("FAILED", "PUBLISH_FAILED"):
                logger.error(f"TikTok publish failed: {status_data}")
                return {"status": "failed", "reason": status}

        logger.warning("TikTok publish timed out after 2 minutes")
        return {"status": "pending", "publish_id": publish_id}

    except requests.exceptions.HTTPError as exc:
        logger.error(f"TikTok HTTP error: {exc.response.text if exc.response else exc}")
        return {"status": "failed", "reason": str(exc)}
    except Exception as exc:
        logger.error(f"TikTok upload failed: {exc}")
        return {"status": "failed", "reason": str(exc)}


# ══════════════════════════════════════════════════════════════════════════════
# FACEBOOK REELS  (Meta Graph API)
# ══════════════════════════════════════════════════════════════════════════════

META_GRAPH = "https://graph.facebook.com/v19.0"


def upload_to_facebook_reel(video_path: str, caption: str) -> dict:
    """
    Upload a Reel to a Facebook Page via the Meta Graph API.

    Requires in .env:
      META_PAGE_ACCESS_TOKEN   — long-lived Page token (never expires if refreshed)
      META_FACEBOOK_PAGE_ID    — numeric Page ID

    Three-phase upload: initialise → upload chunks → publish.
    """
    token = os.getenv("META_PAGE_ACCESS_TOKEN", "")
    page_id = os.getenv("META_FACEBOOK_PAGE_ID", "")

    if not token or not page_id:
        logger.warning("META credentials not set — skipping Facebook Reel")
        return {"status": "skipped", "reason": "no credentials"}

    file_size = os.path.getsize(video_path)

    try:
        # Phase 1 — Initialise upload session
        init_resp = requests.post(
            f"{META_GRAPH}/{page_id}/video_reels",
            params={"access_token": token},
            json={"upload_phase": "start"},
            timeout=30,
        )
        init_resp.raise_for_status()
        video_id = init_resp.json().get("video_id")

        # Phase 2 — Upload binary
        with open(video_path, "rb") as f:
            upload_resp = requests.post(
                f"https://rupload.facebook.com/video-upload/v19.0/{video_id}",
                headers={
                    "Authorization": f"OAuth {token}",
                    "offset": "0",
                    "file_size": str(file_size),
                    "Content-Type": "application/octet-stream",
                },
                data=f,
                timeout=300,
            )
            upload_resp.raise_for_status()

        # Phase 3 — Publish the Reel
        pub_resp = requests.post(
            f"{META_GRAPH}/{page_id}/video_reels",
            params={"access_token": token},
            json={
                "upload_phase": "finish",
                "video_id": video_id,
                "title": caption[:255],
                "description": caption,
                "video_state": "PUBLISHED",
            },
            timeout=30,
        )
        pub_resp.raise_for_status()

        logger.info(f"Facebook Reel published — video_id: {video_id}")
        return {"status": "success", "video_id": video_id, "url": f"https://facebook.com/{page_id}/videos/{video_id}"}

    except requests.exceptions.HTTPError as exc:
        body = exc.response.text if exc.response else str(exc)
        logger.error(f"Facebook Reel error: {body}")
        return {"status": "failed", "reason": body}
    except Exception as exc:
        logger.error(f"Facebook Reel failed: {exc}")
        return {"status": "failed", "reason": str(exc)}


# ══════════════════════════════════════════════════════════════════════════════
# INSTAGRAM REELS  (Meta Graph API — Container model)
# ══════════════════════════════════════════════════════════════════════════════

def upload_to_instagram_reel(video_url: str, caption: str) -> dict:
    """
    Publish an Instagram Reel via the Meta Graph API container model.

    NOTE: Instagram requires a PUBLIC URL for the video — not a local file path.
    Upload the 9:16 video to your server's /output/ and pass its public URL,
    or use a temporary file host. The bot saves files to output/repurposed/reels/.

    Requires in .env:
      META_PAGE_ACCESS_TOKEN
      META_INSTAGRAM_ACCOUNT_ID   — IG Business account ID (not username)
    """
    token = os.getenv("META_PAGE_ACCESS_TOKEN", "")
    ig_id = os.getenv("META_INSTAGRAM_ACCOUNT_ID", "")

    if not token or not ig_id:
        logger.warning("Instagram credentials not set — skipping")
        return {"status": "skipped", "reason": "no credentials"}

    if not video_url.startswith("http"):
        logger.warning("Instagram Reel requires a public URL, not a local path")
        return {"status": "skipped", "reason": "local path provided, need public URL"}

    try:
        # Step 1 — Create media container
        container_resp = requests.post(
            f"{META_GRAPH}/{ig_id}/media",
            params={"access_token": token},
            json={
                "media_type": "REELS",
                "video_url": video_url,
                "caption": caption[:2200],
                "share_to_feed": True,
            },
            timeout=30,
        )
        container_resp.raise_for_status()
        creation_id = container_resp.json().get("id")

        # Step 2 — Poll until container is ready (video processing)
        for _ in range(18):  # up to 3 minutes
            time.sleep(10)
            check = requests.get(
                f"{META_GRAPH}/{creation_id}",
                params={"access_token": token, "fields": "status_code"},
                timeout=30,
            )
            status_code = check.json().get("status_code")
            if status_code == "FINISHED":
                break
            if status_code == "ERROR":
                logger.error(f"Instagram container processing error: {check.json()}")
                return {"status": "failed", "reason": "container processing error"}

        # Step 3 — Publish
        pub_resp = requests.post(
            f"{META_GRAPH}/{ig_id}/media_publish",
            params={"access_token": token},
            json={"creation_id": creation_id},
            timeout=30,
        )
        pub_resp.raise_for_status()
        media_id = pub_resp.json().get("id")

        logger.info(f"Instagram Reel published — media_id: {media_id}")
        return {"status": "success", "media_id": media_id}

    except requests.exceptions.HTTPError as exc:
        body = exc.response.text if exc.response else str(exc)
        logger.error(f"Instagram Reel error: {body}")
        return {"status": "failed", "reason": body}
    except Exception as exc:
        logger.error(f"Instagram Reel failed: {exc}")
        return {"status": "failed", "reason": str(exc)}


# ══════════════════════════════════════════════════════════════════════════════
# TWITTER / X   (API v2 — free tier = text only)
# ══════════════════════════════════════════════════════════════════════════════

def post_to_twitter(youtube_url: str, text: str) -> dict:
    """
    Post a tweet linking to the YouTube video.

    FREE tier (default): text + URL only (280 chars).
    BASIC tier ($100/month): enables media_upload for native video.

    Requires in .env:
      TWITTER_BEARER_TOKEN     — for app-only auth
      TWITTER_API_KEY
      TWITTER_API_SECRET
      TWITTER_ACCESS_TOKEN
      TWITTER_ACCESS_SECRET
    """
    api_key = os.getenv("TWITTER_API_KEY", "")
    api_secret = os.getenv("TWITTER_API_SECRET", "")
    access_token = os.getenv("TWITTER_ACCESS_TOKEN", "")
    access_secret = os.getenv("TWITTER_ACCESS_SECRET", "")

    if not all([api_key, api_secret, access_token, access_secret]):
        logger.warning("Twitter credentials not set — skipping")
        return {"status": "skipped", "reason": "no credentials"}

    # Compose tweet: caption + YouTube link (trimmed to fit 280 chars)
    link = f" {youtube_url}" if youtube_url else ""
    max_text_len = 280 - len(link) - 1
    tweet_text = text[:max_text_len].rstrip() + link

    try:
        # OAuth 1.0a user context (required for posting tweets)
        from requests_oauthlib import OAuth1
        auth = OAuth1(api_key, api_secret, access_token, access_secret)

        resp = requests.post(
            "https://api.twitter.com/2/tweets",
            auth=auth,
            json={"text": tweet_text},
            timeout=30,
        )
        resp.raise_for_status()
        tweet_id = resp.json()["data"]["id"]
        url = f"https://twitter.com/i/web/status/{tweet_id}"
        logger.info(f"Tweet posted: {url}")
        return {"status": "success", "tweet_id": tweet_id, "url": url}

    except ImportError:
        logger.error("requests_oauthlib not installed — run: pip install requests-oauthlib")
        return {"status": "failed", "reason": "missing requests_oauthlib"}
    except requests.exceptions.HTTPError as exc:
        body = exc.response.text if exc.response else str(exc)
        logger.error(f"Twitter post error: {body}")
        return {"status": "failed", "reason": body}
    except Exception as exc:
        logger.error(f"Twitter post failed: {exc}")
        return {"status": "failed", "reason": str(exc)}


# ══════════════════════════════════════════════════════════════════════════════
# PINTEREST  (API v5 — pin image + YouTube link)
# ══════════════════════════════════════════════════════════════════════════════

PINTEREST_URL = "https://api.pinterest.com/v5/pins"


def create_pinterest_pin(image_url: str, title: str, description: str, youtube_url: str) -> dict:
    """
    Create a Pinterest pin linking to the YouTube video.

    Pinterest drives SEO backlinks and evergreen traffic to YouTube.
    Use a thumbnail image or the first Pexels image as the pin image.

    Requires in .env:
      PINTEREST_ACCESS_TOKEN   — OAuth2 user token with pins:write scope
      PINTEREST_BOARD_ID       — numeric board ID (get from Pinterest API or URL)
    """
    token = os.getenv("PINTEREST_ACCESS_TOKEN", "")
    board_id = os.getenv("PINTEREST_BOARD_ID", "")

    if not token or not board_id:
        logger.warning("Pinterest credentials not set — skipping")
        return {"status": "skipped", "reason": "no credentials"}

    if not image_url.startswith("http"):
        logger.warning("Pinterest requires a public image URL")
        return {"status": "skipped", "reason": "need public image URL"}

    try:
        resp = requests.post(
            PINTEREST_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={
                "board_id": board_id,
                "title": title[:100],
                "description": description[:500],
                "link": youtube_url,
                "media_source": {
                    "source_type": "image_url",
                    "url": image_url,
                },
            },
            timeout=30,
        )
        resp.raise_for_status()
        pin_id = resp.json().get("id")
        logger.info(f"Pinterest pin created — id: {pin_id}")
        return {"status": "success", "pin_id": pin_id, "url": f"https://pinterest.com/pin/{pin_id}"}

    except requests.exceptions.HTTPError as exc:
        body = exc.response.text if exc.response else str(exc)
        logger.error(f"Pinterest error: {body}")
        return {"status": "failed", "reason": body}
    except Exception as exc:
        logger.error(f"Pinterest pin failed: {exc}")
        return {"status": "failed", "reason": str(exc)}


# ══════════════════════════════════════════════════════════════════════════════
# SPOTIFY / PODCAST  (Buzzsprout API → auto-syncs RSS to Spotify for Podcasters)
# ══════════════════════════════════════════════════════════════════════════════

def upload_podcast_episode(audio_path: str, title: str, description: str) -> dict:
    """
    Upload an audio episode to Buzzsprout, which auto-syncs to Spotify via RSS.

    Setup steps (one-time):
      1. Create account at buzzsprout.com (free: 3 hours/month)
      2. Go to buzzsprout.com → Directory → Spotify → Connect
      3. Get your Podcast ID and API Token from Profile → API

    Requires in .env:
      BUZZSPROUT_PODCAST_ID
      BUZZSPROUT_API_KEY
    """
    podcast_id = os.getenv("BUZZSPROUT_PODCAST_ID", "")
    api_key = os.getenv("BUZZSPROUT_API_KEY", "")

    if not podcast_id or not api_key:
        logger.warning("Buzzsprout credentials not set — skipping podcast upload")
        return {"status": "skipped", "reason": "no credentials"}

    try:
        with open(audio_path, "rb") as f:
            resp = requests.post(
                f"https://www.buzzsprout.com/api/{podcast_id}/episodes.json",
                headers={"Authorization": f"Token token={api_key}"},
                data={
                    "title": title,
                    "description": description,
                    "private": 0,
                    "email_after_audio_processed": 0,
                },
                files={"audio_file": (os.path.basename(audio_path), f, "audio/mpeg")},
                timeout=300,
            )
            resp.raise_for_status()

        episode = resp.json()
        ep_id = episode.get("id")
        ep_url = episode.get("audio_url", "")
        logger.info(f"Buzzsprout episode uploaded — id: {ep_id}")
        return {"status": "success", "episode_id": ep_id, "url": ep_url}

    except requests.exceptions.HTTPError as exc:
        body = exc.response.text if exc.response else str(exc)
        logger.error(f"Buzzsprout upload error: {body}")
        return {"status": "failed", "reason": body}
    except Exception as exc:
        logger.error(f"Podcast upload failed: {exc}")
        return {"status": "failed", "reason": str(exc)}


# ══════════════════════════════════════════════════════════════════════════════
# ORCHESTRATOR — post to all platforms in one call
# ══════════════════════════════════════════════════════════════════════════════

def post_to_all_platforms(
    repurposed: dict,
    captions: dict,
    script: dict,
    youtube_url: str,
    thumbnail_url: str = "",
) -> dict:
    """
    Post repurposed content to every configured platform.

    Args:
        repurposed:    Output of repurpose.repurpose_all() — platform → file list.
        captions:      Output of ai.generate_captions() — platform → caption str.
        script:        Full script dict with title, description, tags.
        youtube_url:   The published YouTube video URL.
        thumbnail_url: Optional public URL to a thumbnail image for Pinterest.

    Returns:
        Dict mapping platform → result dict.
    """
    results = {}
    title = script.get("title", "")
    description = script.get("description", "")

    # TikTok — use first clip from repurposed tiktok list
    tiktok_files = repurposed.get("tiktok", [])
    if tiktok_files:
        logger.info("Posting to TikTok...")
        results["tiktok"] = upload_to_tiktok(
            video_path=tiktok_files[0],
            caption=captions.get("tiktok", title),
        )

    # Facebook Reels
    reels_files = repurposed.get("reels", [])
    if reels_files:
        logger.info("Posting to Facebook Reels...")
        results["facebook"] = upload_to_facebook_reel(
            video_path=reels_files[0],
            caption=captions.get("reels", title),
        )

    # Instagram Reels — needs public URL, build from server base URL
    server_base = os.getenv("SERVER_BASE_URL", "")
    if reels_files and server_base:
        rel_path = os.path.relpath(reels_files[0])
        public_url = f"{server_base.rstrip('/')}/{rel_path}"
        logger.info("Posting to Instagram Reels...")
        results["instagram"] = upload_to_instagram_reel(
            video_url=public_url,
            caption=captions.get("reels", title),
        )

    # Twitter/X — text post with YouTube link
    logger.info("Posting to Twitter/X...")
    results["twitter"] = post_to_twitter(
        youtube_url=youtube_url,
        text=captions.get("tiktok", title),  # Short punchy caption
    )

    # Pinterest — pin with YouTube link
    pin_image = thumbnail_url or os.getenv("DEFAULT_THUMBNAIL_URL", "")
    if pin_image:
        logger.info("Creating Pinterest pin...")
        results["pinterest"] = create_pinterest_pin(
            image_url=pin_image,
            title=title,
            description=description[:500],
            youtube_url=youtube_url,
        )

    # Spotify / Podcast via Buzzsprout
    spotify_files = repurposed.get("spotify", [])
    if spotify_files:
        logger.info("Uploading podcast episode to Buzzsprout → Spotify...")
        results["spotify"] = upload_podcast_episode(
            audio_path=spotify_files[0],
            title=title,
            description=captions.get("spotify", description),
        )

    # Log summary
    for platform, result in results.items():
        status = result.get("status", "unknown")
        logger.info(f"  [{platform}] {status}")

    return results
