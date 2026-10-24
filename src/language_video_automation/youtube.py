from __future__ import annotations

import os
import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class YouTubeError(RuntimeError):
    pass


YOUTUBE_SCOPES = [
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]


@dataclass(frozen=True)
class UploadResult:
    video_id: str
    url: str


class YouTubeUploader:
    def __init__(self) -> None:
        client_id = os.environ.get("YOUTUBE_CLIENT_ID", "")
        client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET", "")
        refresh_token = os.environ.get("YOUTUBE_REFRESH_TOKEN", "")
        missing = [
            name for name, value in (
                ("YOUTUBE_CLIENT_ID", client_id),
                ("YOUTUBE_CLIENT_SECRET", client_secret),
                ("YOUTUBE_REFRESH_TOKEN", refresh_token),
            ) if not value
        ]
        if missing:
            raise YouTubeError(f"Missing YouTube credentials: {', '.join(missing)}")
        try:
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise YouTubeError("Google API dependencies are not installed.") from exc
        credentials = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret,
            scopes=YOUTUBE_SCOPES,
        )
        self.service = build("youtube", "v3", credentials=credentials, cache_discovery=False)

    def validate_access(self, *, expected_channel_name: str, playlist_id: str) -> dict[str, str]:
        """Verify the authorized channel and configured playlist without changing YouTube."""
        try:
            channel_response = self.service.channels().list(
                part="snippet",
                mine=True,
                maxResults=1,
            ).execute()
            channels = channel_response.get("items") or []
            if len(channels) != 1:
                raise YouTubeError("The authorized account did not return exactly one YouTube channel.")
            channel = channels[0]
            channel_id = str(channel.get("id", ""))
            channel_title = str(channel.get("snippet", {}).get("title", ""))
            if not channel_id or not channel_title:
                raise YouTubeError("The authorized YouTube channel has incomplete identity data.")
            if channel_title.casefold() != expected_channel_name.casefold():
                raise YouTubeError(
                    f"Authorized channel is {channel_title!r}, expected {expected_channel_name!r}."
                )

            playlist_response = self.service.playlists().list(
                part="snippet,status",
                id=playlist_id,
                maxResults=1,
            ).execute()
            playlists = playlist_response.get("items") or []
            if len(playlists) != 1:
                raise YouTubeError(f"Configured playlist {playlist_id!r} was not found.")
            playlist = playlists[0]
            playlist_channel_id = str(playlist.get("snippet", {}).get("channelId", ""))
            if playlist_channel_id != channel_id:
                raise YouTubeError("The configured playlist does not belong to the authorized channel.")
            return {
                "channel_id": channel_id,
                "channel_title": channel_title,
                "playlist_id": str(playlist.get("id", "")),
                "playlist_title": str(playlist.get("snippet", {}).get("title", "")),
            }
        except YouTubeError:
            raise
        except Exception as exc:
            raise YouTubeError(f"YouTube access validation failed: {exc}") from exc

    def upload_private(
        self,
        *,
        video_path: Path,
        title: str,
        description: str,
        tags: list[str],
        category_id: str,
        default_language: str,
        made_for_kids: bool,
        contains_synthetic_media: bool,
    ) -> UploadResult:
        if not video_path.exists() or video_path.stat().st_size == 0:
            raise YouTubeError(f"Rendered video is missing: {video_path}")
        try:
            from googleapiclient.http import MediaFileUpload
        except ImportError as exc:
            raise YouTubeError("google-api-python-client is not installed.") from exc
        body: dict[str, Any] = {
            "snippet": {
                "title": title[:100],
                "description": description[:5000],
                "tags": [tag[:500] for tag in tags[:20]],
                "categoryId": str(category_id),
                "defaultLanguage": default_language,
            },
            "status": {
                "privacyStatus": "private",
                "selfDeclaredMadeForKids": bool(made_for_kids),
                "containsSyntheticMedia": bool(contains_synthetic_media),
            },
        }
        media = MediaFileUpload(str(video_path), chunksize=8 * 1024 * 1024, resumable=True)
        request = self.service.videos().insert(part="snippet,status", body=body, media_body=media)
        response = None
        retry = 0
        while response is None:
            try:
                _, response = request.next_chunk()
            except Exception as exc:
                retry += 1
                if retry > 5 or not _looks_retryable(exc):
                    raise YouTubeError(f"YouTube upload failed: {exc}") from exc
                time.sleep(min(60, (2**retry) + random.random()))
        video_id = str(response.get("id", ""))
        if not video_id:
            raise YouTubeError("YouTube upload returned no video ID.")
        return UploadResult(video_id=video_id, url=f"https://youtu.be/{video_id}")

    def schedule_existing(
        self,
        *,
        video_id: str,
        publish_at: datetime,
        made_for_kids: bool,
        contains_synthetic_media: bool,
    ) -> None:
        if publish_at.tzinfo is None:
            raise YouTubeError("publish_at must be timezone-aware.")
        body = {
            "id": video_id,
            "status": {
                "privacyStatus": "private",
                "publishAt": publish_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                "selfDeclaredMadeForKids": bool(made_for_kids),
                "containsSyntheticMedia": bool(contains_synthetic_media),
            },
        }
        try:
            self.service.videos().update(part="status", body=body).execute()
        except Exception as exc:
            raise YouTubeError(f"Scheduling video {video_id} failed: {exc}") from exc

    def update_description(self, *, video_id: str, description: str) -> None:
        """Replace only a video's description while preserving its other snippet metadata."""
        try:
            response = self.service.videos().list(
                part="snippet",
                id=video_id,
                maxResults=1,
            ).execute()
            items = response.get("items") or []
            if len(items) != 1:
                raise YouTubeError(f"YouTube video {video_id} was not found.")
            current = dict(items[0].get("snippet") or {})
            snippet: dict[str, Any] = {
                "title": str(current.get("title", ""))[:100],
                "description": description[:5000],
                "categoryId": str(current.get("categoryId", "27")),
            }
            for key in ("tags", "defaultLanguage", "defaultAudioLanguage"):
                if current.get(key):
                    snippet[key] = current[key]
            self.service.videos().update(
                part="snippet",
                body={"id": video_id, "snippet": snippet},
            ).execute()
        except YouTubeError:
            raise
        except Exception as exc:
            raise YouTubeError(f"Updating description for video {video_id} failed: {exc}") from exc

    def publication_statuses(self, video_ids: list[str]) -> dict[str, dict[str, str]]:
        """Return owner-visible publication state, batching the API's 50-video limit."""
        clean_ids = list(dict.fromkeys(video_id for video_id in video_ids if video_id))
        if not clean_ids:
            return {}
        try:
            result: dict[str, dict[str, str]] = {}
            for start in range(0, len(clean_ids), 50):
                batch = clean_ids[start:start + 50]
                response = self.service.videos().list(
                    part="status",
                    id=",".join(batch),
                    maxResults=50,
                ).execute()
                for item in response.get("items") or []:
                    status = item.get("status") or {}
                    result[str(item.get("id", ""))] = {
                        "privacy_status": str(status.get("privacyStatus", "unknown")),
                        "upload_status": str(status.get("uploadStatus", "unknown")),
                        "publish_at": str(status.get("publishAt", "")),
                    }
            return result
        except Exception as exc:
            raise YouTubeError(f"Reading YouTube publication status failed: {exc}") from exc

    def add_to_playlist(self, *, video_id: str, playlist_id: str) -> None:
        if not playlist_id:
            return
        body = {
            "snippet": {
                "playlistId": playlist_id,
                "resourceId": {"kind": "youtube#video", "videoId": video_id},
            }
        }
        try:
            self.service.playlistItems().insert(part="snippet", body=body).execute()
        except Exception as exc:
            raise YouTubeError(
                f"Video {video_id} uploaded, but adding it to playlist {playlist_id} failed: {exc}"
            ) from exc

    def delete_private(self, video_id: str) -> None:
        try:
            self.service.videos().delete(id=video_id).execute()
        except Exception as exc:
            raise YouTubeError(f"Deleting private preview {video_id} failed: {exc}") from exc


def _looks_retryable(exc: Exception) -> bool:
    status = getattr(getattr(exc, "resp", None), "status", None)
    return status in {429, 500, 502, 503, 504} or status is None
