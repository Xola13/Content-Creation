"""
uploader.py — Upload finished videos to YouTube via the Data API v3.
Handles OAuth2 token management (pickle cache + browser refresh).
"""

import os
import pickle
import logging

from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
TOKEN_PICKLE = "token.pickle"
YOUTUBE_CATEGORY_PEOPLE_BLOGS = "22"


def _get_youtube_client():
    """Return an authenticated YouTube API client, refreshing creds as needed."""
    client_secret_path = os.getenv("YOUTUBE_CLIENT_SECRET_PATH", "client_secret.json")
    creds = None

    # Load cached token if available
    if os.path.exists(TOKEN_PICKLE):
        with open(TOKEN_PICKLE, "rb") as token_file:
            creds = pickle.load(token_file)

    # Refresh expired token or run browser OAuth flow for first-time auth
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            logger.info("Refreshing expired YouTube token...")
            creds.refresh(Request())
        else:
            logger.info("Running browser OAuth2 flow for YouTube...")
            flow = InstalledAppFlow.from_client_secrets_file(client_secret_path, SCOPES)
            creds = flow.run_local_server(port=0)

        # Persist the refreshed/new token
        with open(TOKEN_PICKLE, "wb") as token_file:
            pickle.dump(creds, token_file)

    return build("youtube", "v3", credentials=creds)


def upload_to_youtube(video_path: str, script: dict) -> str:
    """
    Upload `video_path` to YouTube using metadata from `script`.

    Args:
        video_path: Local path to the .mp4 file.
        script:     Dict with keys: title, description, tags.

    Returns:
        Public YouTube video URL (https://youtu.be/<id>).
    """
    title = script.get("title", "TrendEmpire Video")
    description = script.get("description", "")
    tags = script.get("tags", [])

    try:
        youtube = _get_youtube_client()

        body = {
            "snippet": {
                "title": title[:100],  # YouTube enforces 100-char limit
                "description": description[:5000],
                "tags": tags[:500],  # Tag list has a 500-char cumulative limit
                "categoryId": YOUTUBE_CATEGORY_PEOPLE_BLOGS,
            },
            "status": {
                "privacyStatus": "public",
                "selfDeclaredMadeForKids": False,
            },
        }

        media = MediaFileUpload(
            video_path,
            mimetype="video/mp4",
            resumable=True,  # Resumable upload handles large files and network drops
            chunksize=256 * 1024,  # 256 KB chunks
        )

        logger.info(f"Uploading '{title}' to YouTube...")
        request = youtube.videos().insert(
            part=",".join(body.keys()),
            body=body,
            media_body=media,
        )

        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                logger.debug(f"  Upload progress: {int(status.progress() * 100)}%")

        video_id = response["id"]
        url = f"https://youtu.be/{video_id}"
        logger.info(f"Upload complete: {url}")
        return url

    except HttpError as exc:
        if exc.resp.status == 403 and b"quotaExceeded" in exc.content:
            logger.error("YouTube API quota exceeded — upload skipped for today")
            return ""
        logger.error(f"YouTube upload HTTP error: {exc}")
        raise

    except Exception as exc:
        logger.error(f"YouTube upload failed: {exc}")
        raise
